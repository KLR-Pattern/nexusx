"""US1 — RemoteLoader: gql nested-query construction + response alignment."""

from __future__ import annotations

import pytest
from pydantic import create_model

from nexusx.federation.remote_loader import (
    create_remote_loader,
    set_remote_selection,
)
from nexusx.query_parser import FieldSelection


class FakeTransport:
    """Records posted gql bodies; returns a canned {data} response."""

    def __init__(self, data):
        self.data = data
        self.posts: list[tuple[str, dict]] = []

    async def post_json(self, url, body):
        self.posts.append((url, body))
        return {"data": self.data}


def _selection(*scalars):
    return FieldSelection(
        name="reviews",
        sub_fields={s: FieldSelection(name=s) for s in scalars},
    )


@pytest.mark.asyncio
async def test_remote_loader_builds_gql_and_aligns_to_many():
    target_cls = create_model(
        "Review",
        id=(int | None, None),
        product_id=(int | None, None),
        title=(str | None, None),
        rating=(int | None, None),
    )
    data = {
        "Review": {
            "by_product_id_in": [
                {"id": 1, "product_id": 1, "title": "R1", "rating": 5},
                {"id": 2, "product_id": 1, "title": "R2", "rating": 3},
                {"id": 3, "product_id": 2, "title": "R3", "rating": 4},
            ]
        }
    }
    transport = FakeTransport(data)
    loader_cls = create_remote_loader(
        typename="Review",
        join_remote="product_id",
        endpoint="http://reviews",
        target_cls=target_cls,
        transport=transport,
        is_list=True,
    )
    loader = loader_cls()
    set_remote_selection(loader, _selection("title", "rating"))

    results = await loader.load_many([1, 2])

    # Alignment: key 1 -> [R1, R2], key 2 -> [R3].
    assert [r.title for r in results[0]] == ["R1", "R2"]
    assert [r.title for r in results[1]] == ["R3"]

    # Exactly one gql POST, to /graphql, with the right entry + keys.
    assert len(transport.posts) == 1
    url, body = transport.posts[0]
    assert url == "http://reviews/graphql"
    q = body["query"]
    assert "Review" in q
    assert "by_product_id_in(product_id_list: [1, 2])" in q
    # join key is always requested (for alignment) even if client didn't select it.
    assert "product_id" in q


@pytest.mark.asyncio
async def test_remote_loader_to_one_missing_key_maps_none():
    target_cls = create_model("User", id=(int | None, None), name=(str | None, None))
    data = {"User": {"by_id_in": [{"id": 7, "name": "Bob"}]}}
    transport = FakeTransport(data)
    loader_cls = create_remote_loader(
        typename="User",
        join_remote="id",
        endpoint="http://users",
        target_cls=target_cls,
        transport=transport,
        is_list=False,
    )
    loader = loader_cls()
    set_remote_selection(
        loader, FieldSelection(name="author", sub_fields={"name": FieldSelection(name="name")})
    )

    results = await loader.load_many([7, 999])
    assert results[0].name == "Bob"
    assert results[1] is None  # missing key -> None (to-one)


@pytest.mark.asyncio
async def test_remote_loader_batches_multiple_loads_into_one_query():
    """DataLoader coalesces concurrent loads into a single batch_load_fn call."""
    target_cls = create_model(
        "Review",
        id=(int | None, None), product_id=(int | None, None), title=(str | None, None),
    )
    data = {"Review": {"by_product_id_in": [
        {"id": 1, "product_id": p, "title": f"R{p}"} for p in (1, 2, 3, 4, 5)
    ]}}
    transport = FakeTransport(data)
    loader_cls = create_remote_loader(
        typename="Review", join_remote="product_id", endpoint="http://reviews",
        target_cls=target_cls, transport=transport, is_list=False,
    )
    loader = loader_cls()
    set_remote_selection(
        loader, FieldSelection(name="reviews", sub_fields={"title": FieldSelection(name="title")})
    )

    # Five separate .load() calls in the same frame → one batched gql query.
    import asyncio
    vals = await asyncio.gather(*(loader.load(p) for p in (1, 2, 3, 4, 5)))
    assert [v.title for v in vals] == ["R1", "R2", "R3", "R4", "R5"]
    assert len(transport.posts) == 1  # SC-003: one query for N keys
