"""三层联邦分页穿透：A→B→C，B/C enable_pagination=False（默认），验证联邦分页仍工作。

验证 specs/020 核心：联邦分页（page_by_）由 __federation_keys__ + __pagination_orders__
驱动，与 enable_pagination（本地关系分页开关）正交。即使 B/C 没开 enable_pagination，
A 的分页查询穿透到 C 仍正常 —— 因为联邦分页根独立于本地分页开关。
"""
import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.applications import Starlette
from starlette.routing import Mount

from nexusx import AutoQueryConfig, BatchPageConfig, GraphQLHandler, OrderTerm, PageOrder
from nexusx.federation import RemoteRelationship, RemoteService
from nexusx.federation.http import GraphQLTransport
from nexusx.federation.introspect import build_federable_app

users = RemoteService("users", url="http://test/users")
reviews = RemoteService("reviews", url="http://test/reviews")


class _UsersBase(SQLModel):
    pass


class _ReviewsBase(SQLModel):
    pass


class _CatalogBase(SQLModel):
    pass


# C member（叶子）—— enable_pagination 不开，但有联邦分页能力
class CEntity(_UsersBase, table=True):
    __tablename__ = "trans_pag_c"
    __federation_keys__ = ["b_id"]
    __pagination_orders__ = BatchPageConfig(
        default_order="TOP",
        orders={"TOP": PageOrder([OrderTerm("score", "desc")])},
    )
    id: int | None = Field(default=None, primary_key=True)
    b_id: int
    name: str
    score: int


# B member + mounter —— enable_pagination 不开，联邦 A + 挂 C（分页）
class BEntity(_ReviewsBase, table=True):
    __tablename__ = "trans_pag_b"
    __federation_keys__ = ["a_id"]
    __pagination_orders__ = BatchPageConfig(
        default_order="TOP",
        orders={"TOP": PageOrder([OrderTerm("score", "desc")])},
    )
    id: int | None = Field(default=None, primary_key=True)
    a_id: int
    name: str
    score: int
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[users.CEntity],
            name="cs", join_remote="b_id",
        ),
    ]


# A mounter —— 联邦 B（分页）
class AEntity(_CatalogBase, table=True):
    __tablename__ = "trans_pag_a"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[reviews.BEntity],
            name="bs", join_remote="a_id",
        ),
    ]


@pytest.fixture(scope="module")
async def _engines():
    eng = {
        "users": create_async_engine("sqlite+aiosqlite:///:memory:"),
        "reviews": create_async_engine("sqlite+aiosqlite:///:memory:"),
        "catalog": create_async_engine("sqlite+aiosqlite:///:memory:"),
    }
    for e in eng.values():
        async with e.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
    yield eng
    for e in eng.values():
        await e.dispose()


@pytest.mark.asyncio
async def test_transitive_pagination_without_enable_pagination(_engines):
    # seed: A1 → [B1(5), B2(3)]；B1 → [C1(9), C2(7)]；B2 → [C3(5)]
    users_sf = async_sessionmaker(_engines["users"], class_=AsyncSession, expire_on_commit=False)
    async with users_sf() as s:
        s.add(CEntity(id=1, b_id=1, name="C1", score=9))
        s.add(CEntity(id=2, b_id=1, name="C2", score=7))
        s.add(CEntity(id=3, b_id=2, name="C3", score=5))
        await s.commit()

    reviews_sf = async_sessionmaker(_engines["reviews"], class_=AsyncSession, expire_on_commit=False)
    async with reviews_sf() as s:
        s.add(BEntity(id=1, a_id=1, name="B1", score=5))
        s.add(BEntity(id=2, a_id=1, name="B2", score=3))
        await s.commit()

    catalog_sf = async_sessionmaker(_engines["catalog"], class_=AsyncSession, expire_on_commit=False)
    async with catalog_sf() as s:
        s.add(AEntity(id=1, name="A1"))
        await s.commit()

    # handlers —— 注意：都不传 enable_pagination（默认 False）
    users_h = GraphQLHandler(
        base=_UsersBase, session_factory=users_sf,
        auto_query_config=AutoQueryConfig(), service_name="users",
    )
    reviews_h = GraphQLHandler(
        base=_ReviewsBase, session_factory=reviews_sf,
        auto_query_config=AutoQueryConfig(), service_name="reviews",
        expose_mounted_endpoints=True,  # 让 catalog transitive 发现 users
    )
    catalog_h = GraphQLHandler(
        base=_CatalogBase, session_factory=catalog_sf,
        auto_query_config=AutoQueryConfig(), service_name="catalog",
    )

    composite = Starlette(routes=[
        Mount("/users", app=build_federable_app(users_h)),
        Mount("/reviews", app=build_federable_app(reviews_h)),
    ])
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=composite), base_url="http://test")
    transport = GraphQLTransport(client=client)

    # reviews mounts users; catalog mounts reviews (transitive → users)
    await reviews_h.er.initialize(transport=transport)
    await catalog_h.er.initialize(transport=transport)

    try:
        res = await catalog_h.execute(
            "{ AEntity { by_id(id: 1) { "
            "bs(limit: 1, order: TOP) { items { name score "
            "cs(limit: 1, order: TOP) { items { name score } } } } } } }"
        )
        # 即使 B/C enable_pagination=False，联邦分页穿透应正常
        assert not res.get("errors"), res
        a = res["data"]["AEntity"]["by_id"]
        bs = a["bs"]["items"]
        assert len(bs) == 1
        assert bs[0]["name"] == "B1"  # score=5 > B2 score=3 → top
        cs = bs[0]["cs"]["items"]
        assert len(cs) == 1
        assert cs[0]["name"] == "C1"  # score=9 > C2 score=7 → top
    finally:
        await client.aclose()
