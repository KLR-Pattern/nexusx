"""specs/019 回归：名为 ``items`` 的普通 list 关系 + GraphQL 二级钻取。

旧的 ``is_paginated_package`` 靠「tree 含 items」猜分页包，把任何名为 items
的普通关系（Order ── items ── OrderItem，业务里极常见）误判成分页包，导致
**父关系整个字段被丢弃**（静默 continue）。修复后判定改用明确意图——构建期
读 RelationshipInfo，运行时 isinstance(PaginatedPackage)——关系命名自由。
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Relationship, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx import ErManager, GraphQLHandler, query

_sf: dict = {}


class PitParent(SQLModel, table=True):
    __tablename__ = "pit_parent"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    # 关系名故意叫 items —— 旧逻辑会误判成分页包。
    items: list["PitLine"] = Relationship(back_populates="parent")

    @query
    async def get_parents(cls):
        async with _sf["sf"]() as s:
            return list((await s.exec(select(cls))).all())


class PitLine(SQLModel, table=True):
    __tablename__ = "pit_line"

    id: int | None = Field(default=None, primary_key=True)
    parent_id: int = Field(foreign_key="pit_parent.id")
    qty: int
    parent: PitParent = Relationship(back_populates="items")


@pytest_asyncio.fixture
async def pit_handler():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sf = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    _sf["sf"] = sf
    async with eng.begin() as c:
        await c.run_sync(SQLModel.metadata.create_all)
    async with sf() as s:
        s.add(PitParent(id=1, name="P1"))
        await s.commit()
        s.add(PitLine(parent_id=1, qty=1))
        s.add(PitLine(parent_id=1, qty=2))
        await s.commit()
    er = ErManager(session_factory=sf, entities=[PitParent, PitLine])
    handler = GraphQLHandler(er_manager=er, entities=[PitParent, PitLine])
    yield handler
    await eng.dispose()


async def test_items_drilldown_not_misclassified(pit_handler):
    """名为 items 的 list 关系 + 二级钻取正常返回（旧逻辑会丢父字段）。"""
    r = await pit_handler.execute(
        "{ PitParent { get_parents { name items { qty } } } }"
    )
    assert r.get("errors") is None, r.get("errors")
    parent = r["data"]["PitParent"]["get_parents"][0]
    assert parent["name"] == "P1"
    assert [i["qty"] for i in parent["items"]] == [1, 2]


async def test_items_plus_pagination_field_coexist(pit_handler):
    """同 query 里既有 items 关系又有别的标量 —— items 不再被吞。"""
    r = await pit_handler.execute(
        "{ PitParent { get_parents { id name items { id qty } } } }"
    )
    assert r.get("errors") is None, r.get("errors")
    parent = r["data"]["PitParent"]["get_parents"][0]
    assert parent["name"] == "P1"
    assert len(parent["items"]) == 2
