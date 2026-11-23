"""Regression tests for issue #160 milestone M0 (7.0.0 review hotfixes).

Each test pins a behaviour the review found broken, exercised through the
public surface only (``GraphQLHandler.execute`` / ``ErManager.create_resolver``).
"""

from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Relationship, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx import GraphQLHandler, query


# ──────────────────────────────────────────────────────────
# BUG_1 fixtures — one O2M and one M2M paginated relationship
# ──────────────────────────────────────────────────────────


class R160Base(SQLModel):
    pass


class R160AuthorTag(R160Base, table=True):
    __tablename__ = "r160_author_tag"

    author_id: int = Field(foreign_key="r160_author.id", primary_key=True)
    tag_id: int = Field(foreign_key="r160_tag.id", primary_key=True)


class R160Post(R160Base, table=True):
    __tablename__ = "r160_post"

    id: int | None = Field(default=None, primary_key=True)
    author_id: int = Field(foreign_key="r160_author.id")
    author: Optional["R160Author"] = Relationship(back_populates="posts")


class R160Tag(R160Base, table=True):
    __tablename__ = "r160_tag"

    id: int | None = Field(default=None, primary_key=True)
    authors: list["R160Author"] = Relationship(
        back_populates="tags", link_model=R160AuthorTag
    )


class R160Author(R160Base, table=True):
    __tablename__ = "r160_author"

    id: int | None = Field(default=None, primary_key=True)
    name: str = ""

    posts: list[R160Post] = Relationship(
        back_populates="author",
        sa_relationship_kwargs={"order_by": "R160Post.id"},
    )
    tags: list[R160Tag] = Relationship(
        back_populates="authors",
        link_model=R160AuthorTag,
        sa_relationship_kwargs={"order_by": "R160Tag.id"},
    )

    @query
    async def get_all(cls) -> list["R160Author"]:
        async with SESSION_FACTORY() as session:
            return list((await session.exec(select(cls))).all())


R160Base.model_rebuild()

engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
)
SESSION_FACTORY = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
handler = GraphQLHandler(base=R160Base, session_factory=SESSION_FACTORY)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _seed():
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    async with SESSION_FACTORY() as session:
        session.add(
            R160Author(
                id=1,
                name="a",
                posts=[R160Post(id=i, author_id=1) for i in (1, 2, 3)],
                tags=[R160Tag(id=i) for i in (1, 2, 3)],
            )
        )
        await session.commit()
    yield
    await engine.dispose()


def _page(result: dict, field: str) -> dict:
    return result["data"]["R160Author"]["get_all"][0][field]


# ──────────────────────────────────────────────────────────
# BUG_1 — limit=0 on a local paginated relationship
# ──────────────────────────────────────────────────────────


class TestLimitZeroHasMore:
    @pytest.mark.parametrize("field", ["posts", "tags"])
    async def test_limit_zero_is_an_empty_page_without_a_next_page(self, field: str):
        result = await handler.execute(
            "{ R160Author { get_all { id %s(limit: 0) { items { id } "
            "pagination { has_more total_count } } } } }" % field
        )
        page = _page(result, field)
        assert page["items"] == []
        assert page["pagination"]["total_count"] == 3
        assert page["pagination"]["has_more"] is False
