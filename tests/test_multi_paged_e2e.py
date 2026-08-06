"""specs/019 多 paged 同层 e2e。

验证同层多个 paged 字段(posts + comments)各自 limit 独立、不串。覆盖
``_build_entity_field_jobs`` 遍历多 paged 字段 → 每个 paged 字段各调一次
``paged_provider`` → 各自 ``page_loader`` 的完整链路。

Alice 有 3 posts / 4 comments:
- ``posts(limit:2)`` → 2 items, has_more True
- ``comments(limit:3)`` → 3 items, has_more True

posts 不拿 comments 的 limit(3),comments 不拿 posts 的(2)。
"""

from typing import Optional

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, Relationship, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx import AutoQueryConfig, GraphQLHandler


class MPBase(SQLModel):
    pass


class MPPost(MPBase, table=True):
    __tablename__ = "mp_post"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="mp_user.id")

    author: Optional["MPUser"] = Relationship(back_populates="posts")
    reviews: list["MPReview"] = Relationship(  # type: ignore[type-arg]
        back_populates="post",
        sa_relationship_kwargs={"order_by": "MPReview.id"},
    )


class MPReview(MPBase, table=True):
    __tablename__ = "mp_review"

    id: int | None = Field(default=None, primary_key=True)
    content: str
    post_id: int = Field(foreign_key="mp_post.id")

    post: Optional["MPPost"] = Relationship(back_populates="reviews")


class MPComment(MPBase, table=True):
    __tablename__ = "mp_comment"

    id: int | None = Field(default=None, primary_key=True)
    content: str
    author_id: int = Field(foreign_key="mp_user.id")

    author: Optional["MPUser"] = Relationship(back_populates="comments")


class MPUser(MPBase, table=True):
    __tablename__ = "mp_user"

    id: int | None = Field(default=None, primary_key=True)
    name: str

    posts: list[MPPost] = Relationship(  # type: ignore[type-arg]
        back_populates="author",
        sa_relationship_kwargs={"order_by": "MPPost.id"},
    )
    comments: list[MPComment] = Relationship(  # type: ignore[type-arg]
        back_populates="author",
        sa_relationship_kwargs={"order_by": "MPComment.id"},
    )


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
        s.add(MPUser(id=1, name="Alice"))
        s.add(MPUser(id=2, name="Bob"))
        # Alice: 3 posts (A1-A3), Bob: 1 post (B1)
        for i, (title, aid) in enumerate(
            [("A1", 1), ("A2", 1), ("A3", 1), ("B1", 2)], start=1
        ):
            s.add(MPPost(id=i, title=title, author_id=aid))
        # Alice: 4 comments (C1-C4), Bob: 1 comment (C5)
        for i, (content, aid) in enumerate(
            [("C1", 1), ("C2", 1), ("C3", 1), ("C4", 1), ("C5", 2)], start=1
        ):
            s.add(MPComment(id=i, content=content, author_id=aid))
        # reviews: A1 post 3 reviews (R1-R3), A2 post 2 reviews (R4-R5)
        for i, (content, pid) in enumerate(
            [("R1", 1), ("R2", 1), ("R3", 1), ("R4", 2), ("R5", 2)], start=1
        ):
            s.add(MPReview(id=i, content=content, post_id=pid))
        await s.commit()
    _seeded = True


@pytest.fixture
async def seeded():
    await _seed()


@pytest.mark.asyncio
async def test_multi_paged_fields_distinct_limits(seeded):
    """同层 posts(limit:2) + comments(limit:3),各自 limit 独立,不串。"""
    h = GraphQLHandler(
        base=MPBase,
        session_factory=_sf,
        auto_query_config=AutoQueryConfig(),
        enable_pagination=True,
    )
    q = (
        "{ MPUser { by_filter { id "
        "posts(limit: 2) { items { title } pagination { has_more total_count } } "
        "comments(limit: 3) { items { content } pagination { has_more total_count } } "
        "} } }"
    )
    r = await h.execute(q)
    assert "errors" not in r, f"errors: {r.get('errors')}"
    users = {u["id"]: u for u in r["data"]["MPUser"]["by_filter"]}
    alice = users[1]

    # posts(limit:2): Alice 3 posts → 2 items (A1, A2), has_more True, total 3
    assert [it["title"] for it in alice["posts"]["items"]] == ["A1", "A2"]
    assert alice["posts"]["pagination"]["has_more"] is True
    assert alice["posts"]["pagination"]["total_count"] == 3

    # comments(limit:3): Alice 4 comments → 3 items (C1, C2, C3), has_more True, total 4
    assert [it["content"] for it in alice["comments"]["items"]] == ["C1", "C2", "C3"]
    assert alice["comments"]["pagination"]["has_more"] is True
    assert alice["comments"]["pagination"]["total_count"] == 4

    # 不串:posts 不拿 comments 的 limit (3),comments 不拿 posts 的 (2)
    assert len(alice["posts"]["items"]) == 2
    assert len(alice["comments"]["items"]) == 3


@pytest.mark.asyncio
async def test_multi_paged_fields_one_silent(seeded):
    """一个 paged 字段带 limit、另一个不带(走 rel default),互不影响。

    posts(limit:1) 显式;comments 不带 limit(走 default_page_size)。验证多 paged
    字段各自独立解析 args,不因一个带 args 影响另一个。
    """
    h = GraphQLHandler(
        base=MPBase,
        session_factory=_sf,
        auto_query_config=AutoQueryConfig(),
        enable_pagination=True,
    )
    q = (
        "{ MPUser { by_filter { id "
        "posts(limit: 1) { items { title } pagination { has_more total_count } } "
        "comments { items { content } pagination { has_more total_count } } "
        "} } }"
    )
    r = await h.execute(q)
    assert "errors" not in r, f"errors: {r.get('errors')}"
    alice = next(u for u in r["data"]["MPUser"]["by_filter"] if u["id"] == 1)

    # posts(limit:1): 显式 → 1 item (A1), has_more True
    assert [it["title"] for it in alice["posts"]["items"]] == ["A1"]
    assert alice["posts"]["pagination"]["has_more"] is True
    assert alice["posts"]["pagination"]["total_count"] == 3

    # comments(无 limit): 走 default_page_size, 返 Alice 全部 4 comments(默认足够大)
    assert len(alice["comments"]["items"]) == 4
    assert alice["comments"]["pagination"]["total_count"] == 4


@pytest.mark.asyncio
async def test_nested_paged_fields_provider_handoff(seeded):
    """嵌套 paged:posts(limit) → items(Post) → Post.reviews(limit)。

    BFS 两层 paged,provider 每层接当前 field_sel(跨层接力):
    - 层 1(User):provider(User field_sel, 'posts') → Paged(limit:5)
    - 层 2(Post items):provider(items child_sel, 'reviews') → Paged(limit:2)
    验证 provider 跨层 field_sel 正确(不拿成 User 层的 posts args)。
    """
    h = GraphQLHandler(
        base=MPBase,
        session_factory=_sf,
        auto_query_config=AutoQueryConfig(),
        enable_pagination=True,
    )
    q = (
        "{ MPUser { by_filter { id "
        "posts(limit: 5) { items { title "
        "reviews(limit: 2) { items { content } pagination { has_more total_count } } "
        "} pagination { has_more total_count } } "
        "} } }"
    )
    r = await h.execute(q)
    assert "errors" not in r, f"errors: {r.get('errors')}"
    alice = next(u for u in r["data"]["MPUser"]["by_filter"] if u["id"] == 1)

    # posts(limit:5): Alice 3 posts → 3 items (A1, A2, A3)
    posts = alice["posts"]["items"]
    assert [p["title"] for p in posts] == ["A1", "A2", "A3"]

    # A1 post 有 3 reviews,reviews(limit:2) → 2 items (R1, R2), has_more True, total 3
    a1 = next(p for p in posts if p["title"] == "A1")
    assert [it["content"] for it in a1["reviews"]["items"]] == ["R1", "R2"]
    assert a1["reviews"]["pagination"]["has_more"] is True
    assert a1["reviews"]["pagination"]["total_count"] == 3
