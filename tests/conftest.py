"""Test infrastructure: database setup and shared fixtures."""

from typing import Optional

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, Relationship, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

# ──────────────────────────────────────────────────────────
# Test models (Sprint / Task / User for resolve/post/context testing)
# ──────────────────────────────────────────────────────────

class FixtureBase(SQLModel):
    """Base class for test entities."""
    pass


class FixtureUser(FixtureBase, table=True):
    __tablename__ = "test_user"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str

    tasks: list["FixtureTask"] = Relationship(
        back_populates="owner",
        sa_relationship_kwargs={"order_by": "FixtureTask.id"},
    )


class FixtureSprint(FixtureBase, table=True):
    __tablename__ = "test_sprint"

    id: int | None = Field(default=None, primary_key=True)
    name: str

    tasks: list["FixtureTask"] = Relationship(
        back_populates="sprint",
        sa_relationship_kwargs={"order_by": "FixtureTask.id"},
    )


class FixtureTask(FixtureBase, table=True):
    __tablename__ = "test_task"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    sprint_id: int = Field(foreign_key="test_sprint.id")
    owner_id: int = Field(foreign_key="test_user.id")

    sprint: Optional["FixtureSprint"] = Relationship(back_populates="tasks")
    owner: Optional["FixtureUser"] = Relationship(back_populates="tasks")


# ──────────────────────────────────────────────────────────
# M2M test models (Article / Reader / ArticleReader)
# ──────────────────────────────────────────────────────────


class FixtureArticleReader(FixtureBase, table=True):
    """Link table for Article <-> Reader many-to-many."""

    __tablename__ = "test_article_reader"

    article_id: int = Field(foreign_key="test_article.id", primary_key=True)
    reader_id: int = Field(foreign_key="test_reader.id", primary_key=True)


class FixtureReader(FixtureBase, table=True):
    __tablename__ = "test_reader"

    id: int | None = Field(default=None, primary_key=True)
    name: str

    articles: list["FixtureArticle"] = Relationship(
        back_populates="readers",
        link_model=FixtureArticleReader,
        sa_relationship_kwargs={"order_by": "FixtureArticle.id"},
    )


class FixtureArticle(FixtureBase, table=True):
    __tablename__ = "test_article"

    id: int | None = Field(default=None, primary_key=True)
    title: str

    readers: list["FixtureReader"] = Relationship(
        back_populates="articles",
        link_model=FixtureArticleReader,
        sa_relationship_kwargs={"order_by": "FixtureReader.id"},
    )


# ──────────────────────────────────────────────────────────
# Database engine and session factory
# ──────────────────────────────────────────────────────────

_engine = None
_session_factory = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False,
        )
    return _engine


def get_test_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            _get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def init_test_db():
    """Create all tables."""
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def seed_test_data():
    """Insert seed data for testing."""
    session_factory = get_test_session_factory()
    async with session_factory() as session:
        # Check existing
        result = await session.exec(select(FixtureUser))
        if result.first():
            return

        # Users
        users = [
            FixtureUser(name="Alice", email="alice@test.com"),
            FixtureUser(name="Bob", email="bob@test.com"),
        ]
        for u in users:
            session.add(u)
        await session.commit()
        for u in users:
            await session.refresh(u)

        # Sprints
        sprints = [
            FixtureSprint(name="Sprint 1"),
            FixtureSprint(name="Sprint 2"),
        ]
        for s in sprints:
            session.add(s)
        await session.commit()
        for s in sprints:
            await session.refresh(s)

        # Tasks
        tasks = [
            FixtureTask(title="Task A", sprint_id=sprints[0].id, owner_id=users[0].id),
            FixtureTask(title="Task B", sprint_id=sprints[0].id, owner_id=users[1].id),
            FixtureTask(title="Task C", sprint_id=sprints[1].id, owner_id=users[0].id),
            FixtureTask(title="Task D", sprint_id=sprints[1].id, owner_id=users[1].id),
        ]
        for t in tasks:
            session.add(t)
        await session.commit()
        for t in tasks:
            await session.refresh(t)


@pytest_asyncio.fixture
async def test_db():
    """Create tables and seed data for resolve/post/context tests.

    Not autouse — only used by tests that need the test models.
    """
    await init_test_db()
    await seed_test_data()
    yield
    # Cleanup: drop tables to ensure isolation between tests
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)


async def seed_m2m_data():
    """Insert M2M seed data: readers, articles, and link rows."""
    session_factory = get_test_session_factory()
    async with session_factory() as session:
        # Check existing
        result = await session.exec(select(FixtureReader))
        if result.first():
            return

        readers = [
            FixtureReader(name="Reader A"),
            FixtureReader(name="Reader B"),
            FixtureReader(name="Reader C"),
        ]
        for r in readers:
            session.add(r)
        await session.commit()
        for r in readers:
            await session.refresh(r)

        articles = [
            FixtureArticle(title="Article 1"),
            FixtureArticle(title="Article 2"),
        ]
        for a in articles:
            session.add(a)
        await session.commit()
        for a in articles:
            await session.refresh(a)

        # Link: Article 1 has Reader A and Reader B
        #       Article 2 has Reader B and Reader C
        links = [
            FixtureArticleReader(article_id=articles[0].id, reader_id=readers[0].id),
            FixtureArticleReader(article_id=articles[0].id, reader_id=readers[1].id),
            FixtureArticleReader(article_id=articles[1].id, reader_id=readers[1].id),
            FixtureArticleReader(article_id=articles[1].id, reader_id=readers[2].id),
        ]
        for link in links:
            session.add(link)
        await session.commit()


@pytest_asyncio.fixture
async def test_db_m2m():
    """Create tables and seed M2M data (Article/Reader)."""
    await init_test_db()
    await seed_m2m_data()
    yield
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
