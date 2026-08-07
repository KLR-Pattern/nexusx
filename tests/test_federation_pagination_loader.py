"""paginated RemoteLoader — gql construction + per-key alignment + order/direction passthrough.

Validates the mounter-side core of federation pagination without going through
graphql schema validation (the FakeTransport answers with a fixed per-key
package). This isolates build_paginated_gql_query + create_paginated_remote_loader
alignment, and (specs/014) that ``order``/``direction`` are read from the
selection arguments rather than baked at federate time.
"""

import pytest
from pydantic import create_model

from nexusx.federation.remote_loader import (
    RemoteQueryError,
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


def _selection(
    limit=5,
    offset=0,
    want_total_count=True,
    order=None,
    direction=None,
):
    pag_sub = {"has_more": FieldSelection(name="has_more")}
    if want_total_count:
        pag_sub["total_count"] = FieldSelection(name="total_count")
    arguments: dict = {"limit": limit, "offset": offset}
    if order is not None:
        arguments["order"] = order
    if direction is not None:
        arguments["direction"] = direction
    return FieldSelection(
        name="reviews",
        arguments=arguments,
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
        typename="PagReview", entry="page_by_product_id_in",
        arg_name="product_id_list", join_remote="product_id",
        keys=[1, 2], items_sel=items_sel,
        order="HIGHEST_RATING", direction="DESC",
        limit=5, offset=0, want_total_count=True,
    )
    # entry + batch-level args
    assert "page_by_product_id_in(" in q
    assert "product_id_list: [1, 2]" in q
    assert "limit: 5" in q and "offset: 0" in q
    # order/direction render as bare (unquoted) enum literals.
    assert "order: HIGHEST_RATING" in q
    assert "direction: DESC" in q
    assert '"HIGHEST_RATING"' not in q  # never a quoted string
    # fk field for alignment + items/pagination wrappers
    assert "product_id" in q
    assert "items {" in q and "pagination {" in q
    assert "has_more" in q and "total_count" in q


@pytest.mark.asyncio
async def test_build_paginated_gql_query_omits_direction_when_none():
    items_sel = FieldSelection(name="PagReview", sub_fields={"title": FieldSelection(name="title")})
    q = build_paginated_gql_query(
        typename="PagReview", entry="page_by_product_id_in",
        arg_name="product_id_list", join_remote="product_id",
        keys=[1], items_sel=items_sel, order="HIGHEST_RATING",
        limit=3, offset=0, want_total_count=False,
    )
    assert "direction" not in q  # member applies its profile default
    assert "order: HIGHEST_RATING" in q
    assert "total_count" not in q
    assert "has_more" in q


@pytest.mark.asyncio
async def test_paginated_loader_aligns_per_key_by_join_key():
    fake = FakeTransport({"data": {"PagReview": {"page_by_product_id_in": [
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
        default_order="HIGHEST_RATING",
    )
    loader = loader_cls()
    set_remote_selection(loader, _selection(limit=5, offset=0))
    # Out-of-order keys prove alignment is by join key, not position.
    results = await loader.load_many([2, 1, 99])

    assert len(results) == 3
    # key=2
    assert [it.title for it in results[0].items] == ["R3"]
    assert results[0].pagination["has_more"] is False
    assert results[0].pagination["total_count"] == 1
    # key=1
    assert [it.title for it in results[1].items] == ["R1", "R2"]
    assert results[1].pagination["has_more"] is True
    assert results[1].pagination["total_count"] == 7
    # key=99 missing → empty page (not an error)
    assert results[2].items == []
    assert results[2].pagination["has_more"] is False
    assert results[2].pagination["total_count"] == 0
    # exactly one gql sent (SC-006)
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_paginated_loader_passes_order_direction_from_selection():
    """specs/014: order/direction come from the query's selection.arguments,
    not baked at federate time. The loader falls back to default_order only
    when the caller omits ``order``.
    """
    fake = FakeTransport({"data": {"PagReview": {"page_by_product_id_in": []}}})
    loader_cls = create_paginated_remote_loader(
        typename="PagReview", join_remote="product_id", endpoint="http://test",
        target_cls=PagReview, transport=fake, arg_name="product_id_list",
        default_order="HIGHEST_RATING",
    )
    loader = loader_cls()
    set_remote_selection(
        loader, _selection(limit=3, offset=10, order="NEWEST", direction="ASC")
    )
    await loader.load_many([1])
    sent = fake.calls[0]["query"]
    assert "limit: 3" in sent
    assert "offset: 10" in sent
    assert "order: NEWEST" in sent
    assert "direction: ASC" in sent


@pytest.mark.asyncio
async def test_paginated_loader_falls_back_to_default_order_when_omitted():
    """Caller omits ``order`` → loader sends the member default_order."""
    fake = FakeTransport({"data": {"PagReview": {"page_by_product_id_in": []}}})
    loader_cls = create_paginated_remote_loader(
        typename="PagReview", join_remote="product_id", endpoint="http://test",
        target_cls=PagReview, transport=fake, arg_name="product_id_list",
        default_order="HIGHEST_RATING",
    )
    loader = loader_cls()
    set_remote_selection(loader, _selection(limit=3, offset=0))  # no order/direction
    await loader.load_many([1])
    sent = fake.calls[0]["query"]
    assert "order: HIGHEST_RATING" in sent  # default fallback
    assert "direction" not in sent


@pytest.mark.asyncio
async def test_paginated_loader_aligns_uuid_join_key():
    """UUID join key aligns despite JSON string-ification.

    The member returns the fk as a string over JSON; the mounter holds UUID
    objects. ``_normalize_join_key`` bridges them so per-key packages map back
    to the right parent (mirrors the non-paginated RemoteLoader's UUID fix).
    """
    import uuid as _uuid

    UuidReview = create_model(
        "UuidReview",
        product_id=(_uuid.UUID | None, None),
        title=(str | None, None),
    )
    pk1 = _uuid.UUID("00000000-0000-0000-0000-000000000001")
    pk2 = _uuid.UUID("00000000-0000-0000-0000-000000000002")
    fake = FakeTransport({
        "data": {"UuidReview": {"page_by_product_id_in": [
            {
                "product_id": str(pk1),
                "items": [{"product_id": str(pk1), "title": "U1"}],
                "pagination": {"has_more": False, "total_count": 1},
            },
            {
                "product_id": str(pk2),
                "items": [{"product_id": str(pk2), "title": "U2"}],
                "pagination": {"has_more": False, "total_count": 1},
            },
        ]}}
    })
    loader_cls = create_paginated_remote_loader(
        typename="UuidReview", join_remote="product_id", endpoint="http://test",
        target_cls=UuidReview, transport=fake, arg_name="product_id_list",
        default_order="TITLE",
    )
    loader = loader_cls()
    set_remote_selection(loader, _selection(limit=5, offset=0))
    # UUID objects, out of order — alignment must bridge UUID ↔ string.
    results = await loader.load_many([pk2, pk1])
    assert results[0].items[0].title == "U2"
    assert results[1].items[0].title == "U1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        None,
        {},
        {"data": {}},
        {"data": {"PagReview": {}}},
        {"data": {"PagReview": {"page_by_product_id_in": {}}}},
        {
            "data": {
                "PagReview": {
                    "page_by_product_id_in": [
                        {"product_id": 1, "items": [], "pagination": {}}
                    ]
                }
            }
        },
    ],
)
async def test_paginated_loader_rejects_malformed_response(response):
    fake = FakeTransport(response)
    loader_cls = create_paginated_remote_loader(
        typename="PagReview",
        join_remote="product_id",
        endpoint="http://test",
        target_cls=PagReview,
        transport=fake,
        arg_name="product_id_list",
        default_order="HIGHEST_RATING",
    )
    loader = loader_cls()
    set_remote_selection(loader, _selection())
    with pytest.raises(RemoteQueryError):
        await loader.load_many([1])
