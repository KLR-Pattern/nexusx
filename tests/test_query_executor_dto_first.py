"""specs/018 T002 — US1 等价性 fixture。

同一个 gql query 在 ``use_response_builder=True`` 和 ``=False`` 两个值下跑，
响应 dict 必须完全一致。这是 US1 的硬 gate（spec.md US1 Acceptance Scenario 1-3）。

覆盖：
  (a) scalar + nested 关系
  (b) paginated package（``{ items, pagination }``）
  (c) federation materialized remote type —— TODO，等 T003-T007 实现后补

当前阶段（T001 之后、T003 之前）：flag 还未被 ``_serialize`` 真正读取，
所以 flag-on / flag-off 跑同一段代码，本 fixture 必然全绿——这建立等价性
baseline。T003-T007 实现 ``_serialize_via_response_builder`` 后，本 fixture
若失败即说明 ``build_response_model`` 路径行为偏移。
"""

from typing import Optional

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, Relationship, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx import AutoQueryConfig, GraphQLHandler

# ──────────────────────────────────────────────────────────
# Test entities
# ──────────────────────────────────────────────────────────


class US1Base(SQLModel):
    pass


class US1Post(US1Base, table=True):
    __tablename__ = "us1_post"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="us1_user.id")
    author: Optional["US1User"] = Relationship(back_populates="posts")


class US1User(US1Base, table=True):
    __tablename__ = "us1_user"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    posts: list[US1Post] = Relationship(  # type: ignore[type-arg]
        back_populates="author",
        sa_relationship_kwargs={"order_by": "US1Post.id"},
    )


# ──────────────────────────────────────────────────────────
# Shared session + seed
# ──────────────────────────────────────────────────────────

_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
_sf = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
_seeded = False


async def _seed() -> None:
    global _seeded
    if _seeded:
        return
    async with _engine.begin() as c:
        await c.run_sync(SQLModel.metadata.create_all)
    async with _sf() as s:
        s.add(US1User(id=1, name="Alice"))
        s.add(US1User(id=2, name="Bob"))
        s.add(US1Post(id=1, author_id=1, title="A1"))
        s.add(US1Post(id=2, author_id=1, title="A2"))
        s.add(US1Post(id=3, author_id=2, title="B1"))
        await s.commit()
    _seeded = True


def _make_handler(*, use_response_builder: bool) -> GraphQLHandler:
    """Two handler instances that differ ONLY in the flag value."""
    return GraphQLHandler(
        base=US1Base,
        session_factory=_sf,
        auto_query_config=AutoQueryConfig(),
        enable_pagination=True,
        use_response_builder=use_response_builder,
    )


@pytest.fixture
async def seeded() -> None:
    await _seed()


# ──────────────────────────────────────────────────────────
# (a) scalar + nested
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scalar_fields_equivalence(seeded):
    """(a) scalar-only query: flag-on == flag-off."""
    h_old = _make_handler(use_response_builder=False)
    h_new = _make_handler(use_response_builder=True)
    q = "{ US1User { by_filter { id name } } }"
    r_old = await h_old.execute(q)
    r_new = await h_new.execute(q)
    assert r_old == r_new


@pytest.mark.asyncio
async def test_nested_to_many_equivalence(seeded):
    """(a) nested to-many (non-paginated): flag-on == flag-off."""
    h_old = _make_handler(use_response_builder=False)
    h_new = _make_handler(use_response_builder=True)
    q = "{ US1User { by_filter { id name posts { id title } } } }"
    r_old = await h_old.execute(q)
    r_new = await h_new.execute(q)
    assert r_old == r_new


@pytest.mark.asyncio
async def test_nested_to_one_equivalence(seeded):
    """(a) nested to-one: flag-on == flag-off."""
    h_old = _make_handler(use_response_builder=False)
    h_new = _make_handler(use_response_builder=True)
    q = "{ US1Post { by_filter { id title author { id name } } } }"
    r_old = await h_old.execute(q)
    r_new = await h_new.execute(q)
    assert r_old == r_new


# ──────────────────────────────────────────────────────────
# (b) paginated package
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_paginated_relationship_equivalence(seeded):
    """(b) paginated package {items, pagination}: flag-on == flag-off."""
    h_old = _make_handler(use_response_builder=False)
    h_new = _make_handler(use_response_builder=True)
    q = (
        "{ US1User { by_filter { id "
        "posts(limit: 2) { items { title } pagination { has_more } } "
        "} } }"
    )
    r_old = await h_old.execute(q)
    r_new = await h_new.execute(q)
    assert r_old == r_new


# ──────────────────────────────────────────────────────────
# (c) federation materialized remote type — covered by federation suite
# ──────────────────────────────────────────────────────────
#
# T002b 完成：(c) 的 flag-on/off parity 不在这里复刻 federation fixture
# （复杂度不划算），而是依赖 tests/test_federation_*.py 的 24 个 federation
# e2e 测试在 ``NEXUSX_USE_RESPONSE_BUILDER=1`` 下全部跑通——它们基于 flag-off
# 行为写的 assertion，flag-on 也成立即等价于 parity。conftest.py 的
# ``_force_use_response_builder`` autouse fixture 让 flag-on 跑同一段代码。
