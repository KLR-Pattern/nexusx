"""Federation pagination e2e — 跨服务边界场景补充。

现有 ``test_federation_pagination_e2e.py`` 覆盖 happy path；这里补两条此前只在
单元层（FakeTransport / member 本地 SQL）验过的链路，放到真实 GraphQL 序列化链路上
端到端复核一遍：

- default_order：catalog 声明 ``pagination=True`` 但省略 ``order`` → mounter 静态解析
  member 的 ``default_order``，wire 发送默认 enum，member 按默认 profile 排序。
- UUID join key：catalog 持有 UUID 对象 → wire 序列化为字符串 → member 的 UUID 列
  ``page_by_<key>_in`` 匹配 → 响应里的字符串 join key 对齐回 UUID parent。
  这是 spec Acceptance 明确点名的「UUID join key」，此前只有 loader 单元覆盖。

两个场景共享一个 member app（挂 EdgeReview + EdgeSession）和一个 catalog app。

注：Decimal join key 不受支持——已在 ``federate()`` 声明校验阶段拒绝
（``_SUPPORTED_JOIN_TYPES`` 不含 Decimal）。根因：member page_by 按 SQL 列值分桶，
对 wire 字符串 key 存在类型不匹配；UUID 之所以能过是因为 UUID 列在 SQLite 也存为 string。
"""

import os
import tempfile
import uuid as _uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel
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

member = RemoteService("member", url="http://test/member")


class EdgeCatalogBase(SQLModel):
    pass


class EdgeMemberBase(SQLModel):
    pass


# ── member 侧 ────────────────────────────────────────────────────────────

# 复用于 default_order 场景（int join key）。
class EdgeReview(EdgeMemberBase, table=True):
    __tablename__ = "fed_pag_edge_review"
    __federation_keys__ = ["product_id"]
    __pagination_orders__ = BatchPageConfig(
        default_order="LOWEST_RATING",
        orders={
            "LOWEST_RATING": PageOrder([OrderTerm("rating", "asc")]),
            "HIGHEST_RATING": PageOrder([OrderTerm("rating", "desc")]),
        },
    )
    id: int | None = Field(default=None, primary_key=True)
    product_id: int
    title: str
    rating: int


# UUID join key 场景：account_id 是 UUID 列，作为 page key。
class EdgeSession(EdgeMemberBase, table=True):
    __tablename__ = "fed_pag_edge_session"
    __federation_keys__ = ["account_id"]
    __pagination_orders__ = BatchPageConfig(
        default_order="NEWEST",
        orders={"NEWEST": PageOrder([OrderTerm("started_at", "desc")])},
    )
    id: int | None = Field(default=None, primary_key=True)
    account_id: _uuid.UUID
    title: str
    started_at: int


# ── catalog 侧 ───────────────────────────────────────────────────────────

# pagination=True 但省略 order → 走 member default_order (LOWEST_RATING)。
class EdgeDefaultProduct(EdgeCatalogBase, table=True):
    __tablename__ = "fed_pag_edge_default_product"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[member.EdgeReview],
            name="reviews", join_remote="product_id",
            pagination=True,
        ),
    ]


# UUID join key：fk=account_uuid (UUID 对象) → member EdgeSession.account_id。
class EdgeAccount(EdgeCatalogBase, table=True):
    __tablename__ = "fed_pag_edge_account"
    id: int | None = Field(default=None, primary_key=True)
    account_uuid: _uuid.UUID
    name: str
    __relationships__ = [
        RemoteRelationship(
            fk="account_uuid", target=list[member.EdgeSession],
            name="sessions", join_remote="account_id",
            pagination=True,
        ),
    ]


def _engine():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return create_async_engine(f"sqlite+aiosqlite:///{path}")


_cat_engine = _engine()
_mem_engine = _engine()
_cat_sf = async_sessionmaker(_cat_engine, class_=AsyncSession, expire_on_commit=False)
_mem_sf = async_sessionmaker(_mem_engine, class_=AsyncSession, expire_on_commit=False)
_seeded = False

# 固定 UUID（确定性，避免每次跑测试值不同）。
_U1 = _uuid.UUID("11111111-1111-1111-1111-111111111111")
_U2 = _uuid.UUID("22222222-2222-2222-2222-222222222222")


async def _ensure_seed():
    global _seeded
    if _seeded:
        return
    async with _cat_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with _mem_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with _cat_sf() as s:
        s.add(EdgeDefaultProduct(id=1, name="P1"))
        s.add(EdgeAccount(id=1, account_uuid=_U1, name="A1"))
        s.add(EdgeAccount(id=2, account_uuid=_U2, name="A2"))
        await s.commit()
    async with _mem_sf() as s:
        # product_id=1 的 5 条 review，rating 1..5（default LOWEST_RATING=asc → R1..R5）
        for i in range(1, 6):
            s.add(EdgeReview(id=i, product_id=1, title=f"R{i}", rating=i))
        # account U1: 3 sessions；NEWEST = started_at desc → S2(30) S3(20) S1(10)
        s.add(EdgeSession(id=1, account_id=_U1, title="S1", started_at=10))
        s.add(EdgeSession(id=2, account_id=_U1, title="S2", started_at=30))
        s.add(EdgeSession(id=3, account_id=_U1, title="S3", started_at=20))
        # account U2: 2 sessions → S4(99) S5(88)
        s.add(EdgeSession(id=4, account_id=_U2, title="S4", started_at=99))
        s.add(EdgeSession(id=5, account_id=_U2, title="S5", started_at=88))
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
    member_handler = GraphQLHandler(
        base=EdgeMemberBase, session_factory=_mem_sf,
        auto_query_config=AutoQueryConfig(),
        service_name="member",
    )
    member_app = build_federable_app(member_handler)
    catalog_handler = GraphQLHandler(
        base=EdgeCatalogBase, session_factory=_cat_sf,
        auto_query_config=AutoQueryConfig(), service_name="catalog",
    )
    composite = Starlette(routes=[Mount("/member", app=member_app)])
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=composite), base_url="http://test",
    )
    transport = CountingTransport(client=client)
    await catalog_handler.er.initialize(transport=transport)
    yield catalog_handler, transport
    await client.aclose()


@pytest.mark.asyncio
async def test_default_order_used_when_catalog_omits_order(federation):
    """pagination=True 但省略 order → mounter 解析 member default_order 并在 wire 上发送。

    member 的 default_order=LOWEST_RATING (rating asc)。catalog 未传 order，故结果必须按
    asc 排（R1..R5）——若 default 解析失败/回退到其它 profile，顺序会错。这条覆盖
    catalog 声明 → mounter 静态解析 → wire enum → member 解析 → SQL 的完整默认 order 链路。
    """
    catalog_handler, _ = federation
    res = await catalog_handler.execute(
        "{ EdgeDefaultProduct { by_id(id: 1) { reviews(limit: 5) { "
        "items { title } pagination { has_more total_count } } } } }"
    )
    assert not res.get("errors"), res
    pkg = res["data"]["EdgeDefaultProduct"]["by_id"]["reviews"]
    assert [it["title"] for it in pkg["items"]] == ["R1", "R2", "R3", "R4", "R5"]
    assert pkg["pagination"]["has_more"] is False
    assert pkg["pagination"]["total_count"] == 5


@pytest.mark.asyncio
async def test_uuid_join_key_paginates_across_service(federation):
    """UUID join key 跨服务端到端（spec Acceptance）。

    catalog 持 UUID 对象（EdgeAccount.account_uuid）→ outbound _render_value 序列化为
    字符串 → member 的 UUID 列 page_by_account_id_in 匹配 → 响应里 account_id 为字符串
    → _normalize_join_key 对齐回 UUID parent。两个 account 一批，仍只发一条 GQL。
    """
    catalog_handler, transport = federation
    res = await catalog_handler.execute(
        "{ EdgeAccount { by_filter { id sessions(limit: 5) { "
        "items { title } pagination { has_more total_count } } } } }"
    )
    assert not res.get("errors"), res
    assert transport.gql_calls == 1  # 两个 UUID parent 一批，仍只一条 GQL
    by_id = {a["id"]: a for a in res["data"]["EdgeAccount"]["by_filter"]}
    assert set(by_id) == {1, 2}

    # A1: 3 sessions，NEWEST = started_at desc → S2(30) S3(20) S1(10)
    a1 = by_id[1]["sessions"]
    assert [it["title"] for it in a1["items"]] == ["S2", "S3", "S1"]
    assert a1["pagination"] == {"has_more": False, "total_count": 3}

    # A2: 2 sessions → S4(99) S5(88)
    a2 = by_id[2]["sessions"]
    assert [it["title"] for it in a2["items"]] == ["S4", "S5"]
    assert a2["pagination"] == {"has_more": False, "total_count": 2}
