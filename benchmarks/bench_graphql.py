"""GraphQL QueryExecutor performance benchmark.

Measures the time spent in QueryExecutor._resolve_result + _serialize,
comparing DFS (current) vs BFS (optimized) relationship resolution.

Scenarios:
  Q1: 1-level — tasks → owner (scalar)
  Q2: 2-level — sprints → tasks → owner
  Q3: wide — users → posts + comments (parallel siblings) ← BFS main win

Data scales: Small (15 tasks), Medium (200 tasks)

Usage:
    uv run python benchmarks/bench_graphql.py                  # SQLite in-memory
    uv run python benchmarks/bench_graphql.py --mysql          # MySQL (localhost:3306)
"""

import asyncio
import sys
import time
from statistics import mean, quantiles
from typing import Optional

USE_MYSQL = "--mysql" in sys.argv

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, Relationship, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from graphql import parse

from nexusx.execution.query_executor import QueryExecutor
from nexusx.loader.registry import ErManager
from nexusx.query_parser import QueryParser

# ──────────────────────────────────────────────────────────
# Models — blog-style with User → posts + comments
# ──────────────────────────────────────────────────────────


class User(SQLModel, table=True):
    __tablename__ = "gql_bench_user"

    id: int | None = Field(default=None, primary_key=True)
    name: str

    posts: list["Post"] = Relationship(
        back_populates="author",
        sa_relationship_kwargs={"lazy": "noload", "order_by": "Post.id"},
    )
    comments: list["Comment"] = Relationship(
        back_populates="author",
        sa_relationship_kwargs={"lazy": "noload", "order_by": "Comment.id"},
    )
    tasks: list["Task"] = Relationship(
        back_populates="owner",
        sa_relationship_kwargs={"lazy": "noload", "order_by": "Task.id"},
    )


class Post(SQLModel, table=True):
    __tablename__ = "gql_bench_post"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="gql_bench_user.id")

    author: Optional["User"] = Relationship(back_populates="posts")
    comments: list["Comment"] = Relationship(
        back_populates="post",
        sa_relationship_kwargs={"lazy": "noload", "order_by": "Comment.id"},
    )


class Comment(SQLModel, table=True):
    __tablename__ = "gql_bench_comment"

    id: int | None = Field(default=None, primary_key=True)
    content: str
    post_id: int = Field(foreign_key="gql_bench_post.id")
    author_id: int = Field(foreign_key="gql_bench_user.id")

    post: Optional["Post"] = Relationship(back_populates="comments")
    author: Optional["User"] = Relationship(back_populates="comments")


class Sprint(SQLModel, table=True):
    __tablename__ = "gql_bench_sprint"

    id: int | None = Field(default=None, primary_key=True)
    name: str

    tasks: list["Task"] = Relationship(
        back_populates="sprint",
        sa_relationship_kwargs={"lazy": "noload", "order_by": "Task.id"},
    )


class Task(SQLModel, table=True):
    __tablename__ = "gql_bench_task"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    sprint_id: int = Field(foreign_key="gql_bench_sprint.id")
    owner_id: int | None = Field(default=None, foreign_key="gql_bench_user.id")

    sprint: Optional["Sprint"] = Relationship(back_populates="tasks")
    owner: Optional["User"] = Relationship(back_populates="tasks")


# ──────────────────────────────────────────────────────────
# Database
# ──────────────────────────────────────────────────────────

_engine = None
_session_factory = None

SQLITE_URL = "sqlite+aiosqlite:///:memory:"
MYSQL_URL = "mysql+asyncmy://root:root@localhost:3306/nexusx_bench"


def _ensure_engine():
    global _engine, _session_factory
    if _engine is None:
        url = MYSQL_URL if USE_MYSQL else SQLITE_URL
        _engine = create_async_engine(url, echo=False, pool_recycle=3600)
        _session_factory = async_sessionmaker(
            _engine, class_=AsyncSession, expire_on_commit=False
        )
    return _engine, _session_factory


async def setup_db():
    engine, _ = _ensure_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)


async def seed_data(n_users: int, n_sprints: int, n_tasks_per_sprint: int):
    _, sf = _ensure_engine()
    async with sf() as session:
        existing = (await session.exec(select(User))).first()
        if existing:
            return

        users = [User(name=f"User_{i}") for i in range(n_users)]
        for u in users:
            session.add(u)
        await session.commit()
        for u in users:
            await session.refresh(u)

        # Posts: 3-5 per user
        posts = []
        for u in users:
            n_posts = 3 + (hash(u.name) % 3)
            for j in range(n_posts):
                p = Post(title=f"Post_{u.name}_{j}", author_id=u.id)
                session.add(p)
                posts.append(p)
        await session.commit()
        for p in posts:
            await session.refresh(p)

        # Comments: 2-3 per post, by other users
        comments = []
        for i, p in enumerate(posts):
            n_c = 2 + (i % 2)
            for j in range(n_c):
                author = users[(i + j + 1) % n_users]
                c = Comment(content=f"Comment_{i}_{j}", post_id=p.id, author_id=author.id)
                session.add(c)
                comments.append(c)
        await session.commit()

        sprints = [Sprint(name=f"Sprint_{i}") for i in range(n_sprints)]
        for s in sprints:
            session.add(s)
        await session.commit()
        for s in sprints:
            await session.refresh(s)

        task_id = 0
        for sprint in sprints:
            for _j in range(n_tasks_per_sprint):
                owner = users[task_id % n_users]
                task = Task(
                    title=f"Task_{task_id}",
                    sprint_id=sprint.id,
                    owner_id=owner.id,
                )
                session.add(task)
                task_id += 1
        await session.commit()


# ──────────────────────────────────────────────────────────
# Query helpers
# ──────────────────────────────────────────────────────────

ALL_ENTITIES_BLOG = [User, Post, Comment]
ALL_ENTITIES_SPRINT = [User, Sprint, Task]


def _make_query_method(entity_cls, session_factory):
    """Create a simple get_all query method (no cls parameter)."""
    async def get_all():
        async with session_factory() as session:
            return list((await session.exec(select(entity_cls))).all())
    return get_all


def _make_executor(entities, session_factory) -> QueryExecutor:
    registry = ErManager(entities=entities, session_factory=session_factory)
    return QueryExecutor(registry)


def _run_query(executor, gql, parsed, query_methods, entities):
    """Run a single query through the executor.

    Parse happens here (inside the timed region) so timings reflect the full
    request path: parse + execute. Master bench did 2 parses (one here via
    QueryParser, one inside executor); this branch does 1 (executor takes
    document directly).
    """
    document = parse(gql)
    return executor.execute_query(
        document, None, None, parsed, query_methods, {}, entities,
    )


# ──────────────────────────────────────────────────────────
# Benchmark scenarios
# ──────────────────────────────────────────────────────────

async def bench_q1(executor, session_factory, entities):
    """Q1: 1-level — tasks → owner (scalar relationship)."""
    method = _make_query_method(Task, session_factory)
    query_methods = {"tasks": (Task, method)}
    gql = "{ tasks { id title owner { id name } } }"
    parsed = QueryParser().parse(gql)
    return await _run_query(executor, gql, parsed, query_methods, entities)


async def bench_q2(executor, session_factory, entities):
    """Q2: 2-level — sprints → tasks → owner."""
    method = _make_query_method(Sprint, session_factory)
    query_methods = {"sprints": (Sprint, method)}
    gql = "{ sprints { id name tasks { id title owner { id name } } } }"
    parsed = QueryParser().parse(gql)
    return await _run_query(executor, gql, parsed, query_methods, entities)


async def bench_q3(executor, session_factory, entities):
    """Q3: wide — users → posts + comments (parallel siblings)."""
    method = _make_query_method(User, session_factory)
    query_methods = {"users": (User, method)}
    gql = "{ users { id name posts { id title } comments { id content } } }"
    parsed = QueryParser().parse(gql)
    return await _run_query(executor, gql, parsed, query_methods, entities)


async def bench_q4(executor, session_factory, entities):
    """Q4: deep+wide — users → posts → comments + comments → post."""
    method = _make_query_method(User, session_factory)
    query_methods = {"users": (User, method)}
    gql = (
        "{ users { id name posts { id title comments { id content } } "
        "comments { id content post { id title } } } }"
    )
    parsed = QueryParser().parse(gql)
    return await _run_query(executor, gql, parsed, query_methods, entities)


# ──────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────

N_WARMUP = 5
N_RUNS = 50


async def run_bench(fn, n_runs: int) -> list[float]:
    times = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        await fn()
        times.append(time.perf_counter() - t0)
    return times


def fmt_ms(seconds: float) -> str:
    if seconds < 0.001:
        return f"{seconds * 1_000_000:.0f}us"
    return f"{seconds * 1000:.2f}ms"


def print_result(label: str, times: list[float]):
    avg = mean(times)
    p50 = quantiles(times, n=4)[0]
    p95 = quantiles(times, n=20)[18]
    print(f"  {label:<45s} {fmt_ms(avg):>10s} {fmt_ms(p50):>10s} {fmt_ms(p95):>10s}")


async def verify_correctness(session_factory):
    """Verify Q3 produces reasonable results."""
    entities = ALL_ENTITIES_BLOG
    executor = _make_executor(entities, session_factory)
    result = await bench_q3(executor, session_factory, entities)
    if "errors" in result:
        print(f"  WARNING: errors in Q3: {result['errors']}")
    assert "data" in result, f"No data in result: {result}"
    users = result["data"]["users"]
    for u in users:
        assert "posts" in u, f"User {u.get('id')} missing posts"
        assert "comments" in u, f"User {u.get('id')} missing comments"
    print("  Correctness verification: PASSED\n")


async def main():
    db_label = "MySQL 8.0 (localhost)" if USE_MYSQL else "SQLite in-memory"
    print("=" * 70)
    print("  GraphQL QueryExecutor Benchmark")
    print(f"  Database: {db_label}")
    print("=" * 70)
    print()

    _, sf = _ensure_engine()

    scenarios = [
        ("Q1: 1-level (task→owner)", bench_q1, ALL_ENTITIES_SPRINT),
        ("Q2: 2-level (sprint→tasks→owner)", bench_q2, ALL_ENTITIES_SPRINT),
        ("Q3: wide (user→posts+comments)", bench_q3, ALL_ENTITIES_BLOG),
        ("Q4: deep+wide (user→posts→comments + comments→post)", bench_q4, ALL_ENTITIES_BLOG),
    ]

    scales = [
        ("Small", 5, 3, 5),       # 15 tasks, ~20 posts, ~50 comments
        ("Medium", 20, 10, 20),    # 200 tasks, ~80 posts, ~200 comments
        ("Large", 50, 20, 50),     # 1000 tasks, ~200 posts, ~500 comments
    ]

    for scale_name, n_users, n_sprints, n_tasks in scales:
        total_tasks = n_sprints * n_tasks
        print(f"  ── {scale_name} ({n_users} users, {n_sprints} sprints, {total_tasks} tasks) ──")
        print()

        global _engine, _session_factory
        _engine = None
        _session_factory = None
        _, sf = _ensure_engine()

        await setup_db()
        await seed_data(n_users, n_sprints, n_tasks)

        if scale_name == "Medium":
            print("  Verifying correctness...")
            await verify_correctness(sf)

        print(f"  {'Scenario':<45s} {'Avg':>10s} {'P50':>10s} {'P95':>10s}")
        print(f"  {'─' * 78}")

        for label, bench_fn, scenario_entities in scenarios:
            executor = _make_executor(scenario_entities, sf)

            async def run(_fn=bench_fn, _ex=executor, _sf=sf, _en=scenario_entities):
                await _fn(_ex, _sf, _en)

            await run_bench(run, N_WARMUP)
            times = await run_bench(run, N_RUNS)
            print_result(label, times)

        print()


if __name__ == "__main__":
    asyncio.run(main())
