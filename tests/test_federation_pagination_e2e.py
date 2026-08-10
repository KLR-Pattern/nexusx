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
    __federation_keys__ = ["product_id"]
    __pagination_orders__ = BatchPageConfig(
        default_order="HIGHEST_RATING",
        orders={
            "LOWEST_RATING": PageOrder([OrderTerm("rating", "asc")]),
            "HIGHEST_RATING": PageOrder([OrderTerm("rating", "desc")]),
        },
    )
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
        s.add(EPProduct(id=4, name="P4"))  # 3 reviews all rating=5 — PK tie-breaker case
        await s.commit()
    async with _rev_sf() as s:
        # Product 1: 7 reviews, ratings 1..7 (deterministic asc order)
        for i in range(1, 8):
            s.add(EPReview(id=i, product_id=1, title=f"R{i}", rating=i))
        # Product 2: 2 reviews
        s.add(EPReview(id=10, product_id=2, title="RA", rating=5))
        s.add(EPReview(id=11, product_id=2, title="RB", rating=3))
        # Product 4: 3 reviews, all rating=5 → rating ties, so PK tie-breaker (desc) decides order.
        s.add(EPReview(id=100, product_id=4, title="T100", rating=5))
        s.add(EPReview(id=101, product_id=4, title="T101", rating=5))
        s.add(EPReview(id=102, product_id=4, title="T102", rating=5))
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
        auto_query_config=AutoQueryConfig(),
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


@pytest.mark.asyncio
async def test_multiple_parents_each_get_own_page(federation):
    """跨服务 batch 内多 parent：每个 parent 只拿到自己的那页，整批仍只发一条 GQL。

    by_filter 一次取回 P1..P4 四个 parent；分页必须按 join key 对齐到各自父，
    而不是把某一个 parent 的页错配给所有 parent。per-key 对齐此前只在 loader
    单元里用 FakeTransport 测过——这里在真实 GraphQL 序列化链路上端到端复核。
    """
    catalog_handler, transport = federation
    res = await catalog_handler.execute(
        "{ EPProduct { by_filter { id reviews(limit: 5) { "
        "items { title } pagination { has_more total_count } } } } }"
    )
    assert not res.get("errors"), res
    assert transport.gql_calls == 1  # 整个 batch 仍只有一条 GQL
    by_id = {p["id"]: p for p in res["data"]["EPProduct"]["by_filter"]}
    assert set(by_id) == {1, 2, 3, 4}

    # P1: 7 条，rating desc → R7..R3，limit 5 有下一页
    p1 = by_id[1]["reviews"]
    assert [it["title"] for it in p1["items"]] == ["R7", "R6", "R5", "R4", "R3"]
    assert p1["pagination"] == {"has_more": True, "total_count": 7}

    # P2: 2 条，rating desc → RA(5) RB(3)，不足一页
    p2 = by_id[2]["reviews"]
    assert [it["title"] for it in p2["items"]] == ["RA", "RB"]
    assert p2["pagination"] == {"has_more": False, "total_count": 2}

    # P3: 无 children
    p3 = by_id[3]["reviews"]
    assert p3["items"] == []
    assert p3["pagination"] == {"has_more": False, "total_count": 0}

    # P4: 3 条 rating 全 5 → 顺序由 PK tie-breaker 决定（见下一条测试）
    p4 = by_id[4]["reviews"]
    assert len(p4["items"]) == 3
    assert p4["pagination"] == {"has_more": False, "total_count": 3}


@pytest.mark.asyncio
async def test_pk_tie_breaker_for_equal_rating(federation):
    """排序语义跨服务端到端：rating 相同时，缺省 PK tie-breaker 按 order 方向（desc）定序。

    HIGHEST_RATING = [rating desc]，member 自动追加 PK；末位 term 是 desc，故 PK 亦 desc。
    P4 的三条 review rating 全为 5（id=100/101/102）→ 期望 102, 101, 100。这条链路覆盖
    order profile → wire enum → member 解析 → SQL → package → mounter 对齐 的完整排序语义。
    """
    catalog_handler, _ = federation
    res = await catalog_handler.execute(
        "{ EPProduct { by_id(id: 4) { reviews(limit: 5) { "
        "items { title } pagination { has_more total_count } } } } }"
    )
    assert not res.get("errors"), res
    pkg = res["data"]["EPProduct"]["by_id"]["reviews"]
    assert [it["title"] for it in pkg["items"]] == ["T102", "T101", "T100"]
    assert pkg["pagination"]["has_more"] is False
    assert pkg["pagination"]["total_count"] == 3


@pytest.fixture
async def federation_paginated():
    """Same topology, but the catalog enables local pagination
    (``enable_pagination=True``). The β REMOTE_PAGED path must still route
    through ``fetch_remote_subtree`` with the merged Paged side-channelled —
    specs/021 GAP A regression: this combination used to send
    ``PageLoadCommand`` objects to the remote loader (illegal gql) and never
    set the remote selection, crashing the whole query.
    """
    await _ensure_seed()
    reviews_handler = GraphQLHandler(
        base=EPReviewsBase, session_factory=_rev_sf,
        auto_query_config=AutoQueryConfig(),
        service_name="reviews",
    )
    reviews_app = build_federable_app(reviews_handler)
    catalog_handler = GraphQLHandler(
        base=EPCatalogBase, session_factory=_cat_sf,
        auto_query_config=AutoQueryConfig(), service_name="catalog",
        enable_pagination=True,
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
async def test_beta_remote_paged_under_enable_pagination(federation_paginated):
    """GAP A: enable_pagination=True + β 远程分页字段 → 正常分页(修复前必崩)。"""
    catalog_handler, _ = federation_paginated
    res = await catalog_handler.execute(
        "{ EPProduct { by_id(id: 1) { reviews(limit: 2, order: HIGHEST_RATING) "
        "{ items { title rating } pagination { has_more total_count } } } } }"
    )
    assert not res.get("errors"), res
    pkg = res["data"]["EPProduct"]["by_id"]["reviews"]
    assert [it["title"] for it in pkg["items"]] == ["R7", "R6"]  # top-2
    assert pkg["pagination"]["has_more"] is True
    assert pkg["pagination"]["total_count"] == 7


@pytest.mark.asyncio
async def test_beta_variable_paged_args_never_leak_undefined(federation):
    """GAP B: β 远程分页的 selection.arguments 变量参数必须清洗 —
    未提供变量的 $lim → Undefined 不得上 wire(修复前渲染 limit: Undefined
    非法字面量 → member 报错); 提供变量时真值生效。"""
    catalog_handler, _ = federation
    q = ("query Q($lim: Int) { EPProduct { by_id(id: 1) "
         "{ reviews(limit: $lim) { items { title } pagination { has_more } } } } }")
    # 未提供变量 → 干净降级为 member 默认页(7 条全量)
    r = await catalog_handler.execute(q, variables={})
    assert not r.get("errors"), r
    pkg = r["data"]["EPProduct"]["by_id"]["reviews"]
    assert len(pkg["items"]) == 7
    # 提供变量 → limit 生效
    r2 = await catalog_handler.execute(q, variables={"lim": 3})
    assert not r2.get("errors"), r2
    pkg2 = r2["data"]["EPProduct"]["by_id"]["reviews"]
    assert len(pkg2["items"]) == 3


@pytest.mark.asyncio
async def test_limit_zero_returns_empty_with_no_has_more(federation):
    """GAP E: limit=0 → 空 items + has_more=False(修复前窗口 peek 到 1 行,
    has_more 误报 True + items=[] 矛盾)。"""
    catalog_handler, _ = federation
    res = await catalog_handler.execute(
        "{ EPProduct { by_id(id: 1) { reviews(limit: 0) { "
        "items { title } pagination { has_more total_count } } } } }"
    )
    assert not res.get("errors"), res
    pkg = res["data"]["EPProduct"]["by_id"]["reviews"]
    assert pkg["items"] == []
    assert pkg["pagination"]["has_more"] is False
    assert pkg["pagination"]["total_count"] == 7
