"""specs/018 T002 — response_builder serialize 正确性（Phase 7 后 legacy 移除）。

entity-first gql 的 serialize 现在唯一走 ``response_builder``（specs/018 US1 +
Phase 7 T028 删除 legacy dict-based loop）。这些 fixture 验证 response_builder
路径在 scalar / nested / paginated 各形状下产出正确结构。

历史：T002 原为 flag-on/off 等价性 gate（证明 response_builder 可替换 legacy）；
Phase 7 T028 删除 legacy 后等价性不再需要（legacy 不存在），改为直接断言
response_builder 输出的正确性。

覆盖：
  (a) scalar + nested 关系（to-one / to-many）
  (b) paginated package（``{ items, pagination }``）
  (c) federation materialized remote type —— 由 tests/test_federation_*.py 覆盖
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


class US1NullableParent(US1Base, table=True):
    __tablename__ = "us1_nullable_parent"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    children: list["US1NullableChild"] = Relationship(back_populates="parent")


class US1NullableChild(US1Base, table=True):
    __tablename__ = "us1_nullable_child"

    id: int | None = Field(default=None, primary_key=True)
    parent_id: int | None = Field(
        default=None, foreign_key="us1_nullable_parent.id",
    )
    parent: US1NullableParent | None = Relationship(back_populates="children")


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
        s.add(US1NullableChild(id=1, parent_id=None))
        await s.commit()
    _seeded = True


def _make_handler(*, enable_pagination: bool = False) -> GraphQLHandler:
    return GraphQLHandler(
        base=US1Base,
        session_factory=_sf,
        auto_query_config=AutoQueryConfig(),
        enable_pagination=enable_pagination,
    )


@pytest.fixture
async def seeded() -> None:
    await _seed()


# ──────────────────────────────────────────────────────────
# (a) scalar + nested
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scalar_fields(seeded):
    """(a) scalar-only query via response_builder."""
    h = _make_handler()
    q = "{ US1User { by_filter { id name } } }"
    r = await h.execute(q)
    users = {u["id"]: u for u in r["data"]["US1User"]["by_filter"]}
    assert users[1] == {"id": 1, "name": "Alice"}
    assert users[2] == {"id": 2, "name": "Bob"}


@pytest.mark.asyncio
async def test_nested_to_many(seeded):
    """(a) nested to-many (non-paginated) via response_builder."""
    h = _make_handler()
    q = "{ US1User { by_filter { id name posts { id title } } } }"
    r = await h.execute(q)
    users = {u["id"]: u for u in r["data"]["US1User"]["by_filter"]}
    assert [p["title"] for p in users[1]["posts"]] == ["A1", "A2"]
    assert [p["title"] for p in users[2]["posts"]] == ["B1"]


@pytest.mark.asyncio
async def test_nested_to_one(seeded):
    """(a) nested to-one via response_builder."""
    h = _make_handler()
    q = "{ US1Post { by_filter { id title author { id name } } } }"
    r = await h.execute(q)
    posts = {p["id"]: p for p in r["data"]["US1Post"]["by_filter"]}
    assert posts[1]["author"]["name"] == "Alice"
    assert posts[3]["author"]["name"] == "Bob"


@pytest.mark.asyncio
async def test_nullable_to_one_serializes_none_without_lazy_loading(seeded):
    """A null FK must not access a detached SQLAlchemy relationship attribute."""
    h = _make_handler()
    q = "{ US1NullableChild { by_filter { id parent { id name } } } }"

    r = await h.execute(q)

    assert "errors" not in r
    assert r["data"]["US1NullableChild"]["by_filter"] == [
        {"id": 1, "parent": None},
    ]


# ──────────────────────────────────────────────────────────
# (b) paginated package
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_paginated_relationship(seeded):
    """(b) paginated package {items, pagination} via response_builder."""
    h = _make_handler(enable_pagination=True)
    q = (
        "{ US1User { by_filter { id "
        "posts(limit: 2) { items { title } pagination { has_more } } "
        "} } }"
    )
    r = await h.execute(q)
    users = {u["id"]: u for u in r["data"]["US1User"]["by_filter"]}
    # Alice has 2 posts (A1, A2); limit=2 → both, has_more False.
    assert [it["title"] for it in users[1]["posts"]["items"]] == ["A1", "A2"]
    assert users[1]["posts"]["pagination"]["has_more"] is False
    # Bob has 1 post (B1); limit=2 → 1 item, has_more False.
    assert [it["title"] for it in users[2]["posts"]["items"]] == ["B1"]


# ──────────────────────────────────────────────────────────
# (c) federation materialized remote type — covered by federation suite
# ──────────────────────────────────────────────────────────
#
# Phase 7 后 flag 移除：tests/test_federation_*.py 的 24 个 federation e2e 默认走
# response_builder（handler 唯一路径），覆盖 materialized remote type parity。
