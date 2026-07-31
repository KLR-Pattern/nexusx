"""Federation pagination end-to-end (US1 / T012): catalog mounts reviews;
Product.reviews enables pagination and selects a member order profile. A single query paginates
reviews across the service boundary.

- SC-001: limit/offset returns the correct page + has_more + total_count.
- SC-002: reviews receives exactly ONE gql query (the paginated batch root).
- R6: total_count is optional (only returned when selected).
"""

import os
import tempfile

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, Relationship, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.applications import Starlette
from starlette.routing import Mount

from nexusx import (
    AutoQueryConfig,
    BatchPageConfig,
    GraphQLHandler,
    OrderTerm,
    PageOrder,
)
from nexusx.federation import RemoteRelationship, RemoteService
from nexusx.federation.http import GraphQLTransport
from nexusx.federation.introspect import build_federable_app

reviews = RemoteService("reviews", url="http://test/reviews")


class EPCatalogBase(SQLModel):
    pass


class EPReviewsBase(SQLModel):
    pass


class EPReview(EPReviewsBase, table=True):
    __tablename__ = "fed_pag_e2e_review"
    id: int | None = Field(default=None, primary_key=True)
    product_id: int
    title: str
    rating: int
    comments: list["EPComment"] = Relationship(back_populates="review")


class EPComment(EPReviewsBase, table=True):
    __tablename__ = "fed_pag_e2e_comment"
    id: int | None = Field(default=None, primary_key=True)
    review_id: int = Field(foreign_key="fed_pag_e2e_review.id")
    text: str
    review: "EPReview" = Relationship(back_populates="comments")


class EPProduct(EPCatalogBase, table=True):
    __tablename__ = "fed_pag_e2e_product"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[reviews.EPReview],
            name="reviews", join_remote="product_id",
            pagination=True,
            order="HIGHEST_RATING",
        ),
    ]


def _engine():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return create_async_engine(f"sqlite+aiosqlite:///{path}")


_cat_engine = _engine()
_rev_engine = _engine()
_cat_sf = async_sessionmaker(_cat_engine, class_=AsyncSession, expire_on_commit=False)
_rev_sf = async_sessionmaker(_rev_engine, class_=AsyncSession, expire_on_commit=False)
_seeded = False


async def _ensure_seed():
    global _seeded
    if _seeded:
        return
    async with _cat_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with _rev_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with _cat_sf() as s:
        s.add(EPProduct(id=1, name="P1"))
        s.add(EPProduct(id=2, name="P2"))
        s.add(EPProduct(id=3, name="P3"))  # no reviews — for empty-children edge case
        await s.commit()
    async with _rev_sf() as s:
        # Product 1: 7 reviews, ratings 1..7 (deterministic asc order)
        for i in range(1, 8):
            s.add(EPReview(id=i, product_id=1, title=f"R{i}", rating=i))
        # Product 2: 2 reviews
        s.add(EPReview(id=10, product_id=2, title="RA", rating=5))
        s.add(EPReview(id=11, product_id=2, title="RB", rating=3))
        # comments on the first two rows in HIGHEST_RATING order.
        s.add(EPComment(id=1, review_id=7, text="C7"))
        s.add(EPComment(id=2, review_id=6, text="C6"))
        await s.commit()
    _seeded = True


class CountingTransport(GraphQLTransport):
    def __init__(self, client):
        super().__init__(client=client)
        self.gql_calls = 0

    async def post_json(self, url, body):
        if "/graphql" in url:
            self.gql_calls += 1
        return await super().post_json(url, body)


@pytest.fixture
async def federation():
    await _ensure_seed()
    reviews_handler = GraphQLHandler(
        base=EPReviewsBase, session_factory=_rev_sf,
        auto_query_config=AutoQueryConfig(
            batch_keys={"EPReview": ["product_id"]},
            batch_pages={
                "EPReview": {
                    "product_id": BatchPageConfig(
                        default_order="LOWEST_RATING",
                        orders={
                            "LOWEST_RATING": PageOrder(
                                [OrderTerm("rating", "asc")]
                            ),
                            "HIGHEST_RATING": PageOrder(
                                [OrderTerm("rating", "desc")]
                            ),
                        },
                    )
                }
            },
        ),
        service_name="reviews",
    )
    reviews_app = build_federable_app(reviews_handler)
    catalog_handler = GraphQLHandler(
        base=EPCatalogBase, session_factory=_cat_sf,
        auto_query_config=AutoQueryConfig(), service_name="catalog",
    )
    composite = Starlette(routes=[Mount("/reviews", app=reviews_app)])
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=composite), base_url="http://test",
    )
    transport = CountingTransport(client=client)
    await catalog_handler.er.initialize(transport=transport)
    yield catalog_handler, transport
    await client.aclose()


@pytest.mark.asyncio
async def test_first_page_correct(federation):
    """SC-001: limit/offset returns the correct page + has_more + total_count."""
    catalog_handler, _ = federation
    res = await catalog_handler.execute(
        "{ EPProduct { by_id(id: 1) { reviews(limit: 5, offset: 0) { "
        "items { title rating } pagination { has_more total_count } } } } }"
    )
    assert not res.get("errors"), res
    pkg = res["data"]["EPProduct"]["by_id"]["reviews"]
    assert [it["title"] for it in pkg["items"]] == ["R7", "R6", "R5", "R4", "R3"]
    assert pkg["pagination"]["has_more"] is True
    assert pkg["pagination"]["total_count"] == 7


@pytest.mark.asyncio
async def test_last_page_correct(federation):
    catalog_handler, _ = federation
    res = await catalog_handler.execute(
        "{ EPProduct { by_id(id: 1) { reviews(limit: 5, offset: 5) { "
        "items { title } pagination { has_more total_count } } } } }"
    )
    assert not res.get("errors"), res
    pkg = res["data"]["EPProduct"]["by_id"]["reviews"]
    assert [it["title"] for it in pkg["items"]] == ["R2", "R1"]
    assert pkg["pagination"]["has_more"] is False
    assert pkg["pagination"]["total_count"] == 7


@pytest.mark.asyncio
async def test_one_gql_query_to_reviews(federation):
    """SC-002: paginated fetch sends exactly ONE gql query to reviews."""
    catalog_handler, transport = federation
    assert transport.gql_calls == 0  # federate() only did a GET (introspection)
    await catalog_handler.execute(
        "{ EPProduct { by_filter { reviews(limit: 3) { items { title } "
        "pagination { has_more } } } } }"
    )
    assert transport.gql_calls == 1


@pytest.mark.asyncio
async def test_total_count_optional(federation):
    """R6: not selecting total_count → not returned."""
    catalog_handler, _ = federation
    res = await catalog_handler.execute(
        "{ EPProduct { by_id(id: 1) { reviews(limit: 2) { items { title } "
        "pagination { has_more } } } } }"
    )
    assert not res.get("errors"), res
    pagination = res["data"]["EPProduct"]["by_id"]["reviews"]["pagination"]
    assert "total_count" not in pagination
    assert pagination["has_more"] is True


@pytest.mark.asyncio
async def test_total_count_only_computed_when_selected(federation):
    """R6: member SQL only includes COUNT when total_count is selected."""
    catalog_handler, _ = federation
    statements: list[str] = []

    def capture_sql(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(statement)

    event.listen(_rev_engine.sync_engine, "before_cursor_execute", capture_sql)
    try:
        without_total = await catalog_handler.execute(
            "{ EPProduct { by_id(id: 1) { reviews(limit: 2, offset: 100) { "
            "items { title } pagination { has_more } } } } }"
        )
        page = without_total["data"]["EPProduct"]["by_id"]["reviews"]
        assert page == {"items": [], "pagination": {"has_more": False}}
        review_statements = [
            statement
            for statement in statements
            if "fed_pag_e2e_review" in statement.lower()
        ]
        assert review_statements
        assert not any("count(" in statement.lower() for statement in review_statements)

        statements.clear()
        with_total = await catalog_handler.execute(
            "{ EPProduct { by_id(id: 1) { reviews(limit: 2, offset: 100) { "
            "items { title } pagination { has_more total_count } } } } }"
        )
        page = with_total["data"]["EPProduct"]["by_id"]["reviews"]
        assert page["items"] == []
        assert page["pagination"] == {"has_more": False, "total_count": 7}
        review_statements = [
            statement
            for statement in statements
            if "fed_pag_e2e_review" in statement.lower()
        ]
        assert any(
            "count(" in statement.lower() and "over" in statement.lower()
            for statement in review_statements
        )
    finally:
        event.remove(_rev_engine.sync_engine, "before_cursor_execute", capture_sql)


@pytest.mark.asyncio
async def test_items_subtree_resolved(federation):
    """US2 (SC-005): paginated items' nested relationship (comments) is resolved.

    The member resolves comments inside its page_by_<key>_in response (items
    subtree recursion on the root path); catalog reads them off the instance.
    """
    catalog_handler, _ = federation
    res = await catalog_handler.execute(
        "{ EPProduct { by_id(id: 1) { reviews(limit: 2, offset: 0) { "
        "items { title comments { text } } pagination { has_more } } } } }"
    )
    assert not res.get("errors"), res
    pkg = res["data"]["EPProduct"]["by_id"]["reviews"]
    # descending by rating → R7 (has C7), R6 (has C6)
    by_title = {it["title"]: it for it in pkg["items"]}
    assert [c["text"] for c in by_title["R7"]["comments"]] == ["C7"]
    assert [c["text"] for c in by_title["R6"]["comments"]] == ["C6"]
    assert pkg["pagination"]["has_more"] is True  # 7 total, took 2


@pytest.mark.asyncio
async def test_offset_beyond_total(federation):
    """Edge: offset > total → empty items, has_more false, total_count still real."""
    catalog_handler, _ = federation
    res = await catalog_handler.execute(
        "{ EPProduct { by_id(id: 1) { reviews(limit: 5, offset: 100) { "
        "items { title } pagination { has_more total_count } } } } }"
    )
    assert not res.get("errors"), res
    pkg = res["data"]["EPProduct"]["by_id"]["reviews"]
    assert pkg["items"] == []
    assert pkg["pagination"]["has_more"] is False
    assert pkg["pagination"]["total_count"] == 7


@pytest.mark.asyncio
async def test_parent_with_no_children(federation):
    """Edge: parent with zero children → items=[], total_count=0, has_more=false."""
    catalog_handler, _ = federation
    res = await catalog_handler.execute(
        "{ EPProduct { by_id(id: 3) { reviews(limit: 5) { "
        "items { title } pagination { has_more total_count } } } } }"
    )
    assert not res.get("errors"), res
    pkg = res["data"]["EPProduct"]["by_id"]["reviews"]
    assert pkg["items"] == []
    assert pkg["pagination"]["has_more"] is False
    assert pkg["pagination"]["total_count"] == 0


@pytest.mark.asyncio
async def test_default_page_size_when_no_limit(federation):
    """Edge: client omits limit → default_page_size (20); product1's 7 all returned."""
    catalog_handler, _ = federation
    res = await catalog_handler.execute(
        "{ EPProduct { by_id(id: 1) { reviews { "
        "items { title } pagination { has_more total_count } } } } }"
    )
    assert not res.get("errors"), res
    pkg = res["data"]["EPProduct"]["by_id"]["reviews"]
    assert len(pkg["items"]) == 7  # 7 total < default 20 → whole relation returned
    assert pkg["pagination"]["has_more"] is False
    assert pkg["pagination"]["total_count"] == 7
