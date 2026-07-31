"""US1 (T005): paginated RemoteLoader — gql construction + per-key alignment.

Validates the mounter-side core of federation pagination without going through
graphql schema validation (the FakeTransport answers with a fixed per-key
package). This isolates build_paginated_gql_query + create_paginated_remote_loader
alignment (T009). End-to-end (T012) is covered separately once schema rendering
of the {items, pagination} shape lands.
"""

import pytest
from pydantic import create_model

from nexusx.federation.remote_loader import (
    build_paginated_gql_query,
    create_paginated_remote_loader,
    set_remote_selection,
)
from nexusx.query_parser import FieldSelection

# A materialized-style target class (mirrors what FederatedTypeRegistry produces).
PagReview = create_model(
    "PagReview",
    product_id=(int | None, None),
    title=(str | None, None),
    rating=(int | None, None),
)


class FakeTransport:
    """Stand-in for FederationTransport — returns a canned per-key package list."""

    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []

    async def post_json(self, url, body):
        self.calls.append(body)
        return self.response

    async def get_json(self, url):
        return {}

    async def close(self):
        pass


def _selection(limit=5, offset=0, want_total_count=True):
    pag_sub = {"has_more": FieldSelection(name="has_more")}
    if want_total_count:
        pag_sub["total_count"] = FieldSelection(name="total_count")
    return FieldSelection(
        name="reviews",
        arguments={"limit": limit, "offset": offset},
        sub_fields={
            "items": FieldSelection(
                name="items",
                sub_fields={
                    "title": FieldSelection(name="title"),
                    "rating": FieldSelection(name="rating"),
                },
            ),
            "pagination": FieldSelection(name="pagination", sub_fields=pag_sub),
        },
    )


@pytest.mark.asyncio
async def test_build_paginated_gql_query_shape():
    items_sel = FieldSelection(
        name="PagReview",
        sub_fields={
            "title": FieldSelection(name="title"),
            "rating": FieldSelection(name="rating"),
        },
    )
    q = build_paginated_gql_query(
        typename="PagReview", entry="by_product_id_in_page",
        arg_name="product_id_list", join_remote="product_id",
        keys=[1, 2], items_sel=items_sel,
        sort_field="rating", sort_direction="asc",
        limit=5, offset=0, want_total_count=True,
    )
    # entry + batch-level args
    assert "by_product_id_in_page(" in q
    assert "product_id_list: [1, 2]" in q
    assert "limit: 5" in q and "offset: 0" in q
    assert 'sort_field: "rating"' in q and 'sort_direction: "asc"' in q
    # fk field for alignment + items/pagination wrappers
    assert "product_id" in q
    assert "items {" in q and "pagination {" in q
    assert "has_more" in q and "total_count" in q


@pytest.mark.asyncio
async def test_build_paginated_gql_query_omits_total_count_when_not_selected():
    items_sel = FieldSelection(name="PagReview", sub_fields={"title": FieldSelection(name="title")})
    q = build_paginated_gql_query(
        typename="PagReview", entry="by_product_id_in_page",
        arg_name="product_id_list", join_remote="product_id",
        keys=[1], items_sel=items_sel, sort_field="rating",
        limit=3, offset=0, want_total_count=False,
    )
    assert "total_count" not in q
    assert "has_more" in q


@pytest.mark.asyncio
async def test_paginated_loader_aligns_per_key_by_join_key():
    fake = FakeTransport({"data": {"PagReview": {"by_product_id_in_page": [
        {
            "product_id": 1,
            "items": [
                {"product_id": 1, "title": "R1", "rating": 5},
                {"product_id": 1, "title": "R2", "rating": 3},
            ],
            "pagination": {"has_more": True, "total_count": 7},
        },
        {
            "product_id": 2,
            "items": [{"product_id": 2, "title": "R3", "rating": 4}],
            "pagination": {"has_more": False, "total_count": 1},
        },
    ]}}})
    loader_cls = create_paginated_remote_loader(
        typename="PagReview", join_remote="product_id", endpoint="http://test",
        target_cls=PagReview, transport=fake, arg_name="product_id_list",
        sort_field="rating",
    )
    loader = loader_cls()
    set_remote_selection(loader, _selection(limit=5, offset=0))
    # Out-of-order keys prove alignment is by join key, not position.
    results = await loader.load_many([2, 1, 99])

    assert len(results) == 3
    # key=2
    assert [it.title for it in results[0]["items"]] == ["R3"]
    assert results[0]["pagination"]["has_more"] is False
    assert results[0]["pagination"]["total_count"] == 1
    # key=1
    assert [it.title for it in results[1]["items"]] == ["R1", "R2"]
    assert results[1]["pagination"]["has_more"] is True
    assert results[1]["pagination"]["total_count"] == 7
    # key=99 missing → empty page (not an error)
    assert results[2]["items"] == []
    assert results[2]["pagination"]["has_more"] is False
    assert results[2]["pagination"]["total_count"] == 0
    # exactly one gql sent (SC-002)
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_paginated_loader_passes_page_args_from_selection():
    fake = FakeTransport({"data": {"PagReview": {"by_product_id_in_page": []}}})
    loader_cls = create_paginated_remote_loader(
        typename="PagReview", join_remote="product_id", endpoint="http://test",
        target_cls=PagReview, transport=fake, arg_name="product_id_list",
        sort_field="rating", sort_direction="desc",
    )
    loader = loader_cls()
    set_remote_selection(loader, _selection(limit=3, offset=10))
    await loader.load_many([1])
    sent = fake.calls[0]["query"]
    assert "limit: 3" in sent
    assert "offset: 10" in sent
    assert 'sort_direction: "desc"' in sent
