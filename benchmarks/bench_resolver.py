"""DefineSubset + Resolver vs SQLAlchemy selectinload performance benchmark.

Compares two approaches for building nested API responses:
  A) nexusx: DefineSubset DTO + Resolver (auto relationship loading + derived fields)
  B) Raw SQLAlchemy: selectinload + manual dict construction + manual derived fields

Scenarios (progressive complexity):
  L1: Pure field selection — no relationships
  L2: Single-level relationship — task → owner
  L3: Two-level relationships + derived fields — sprint → tasks → owner + post_*
  L4: Cross-layer data flow — ExposeAs + SendTo + Collector

Data scales: Small (15 tasks), Medium (200 tasks), Large (1000 tasks)

Usage:
    uv run python benchmarks/bench_resolver.py                  # SQLite in-memory
    uv run python benchmarks/bench_resolver.py --mysql          # MySQL (localhost:3306)
"""

import asyncio
import sys
import time
from statistics import mean, quantiles
from typing import Optional

USE_MYSQL = "--mysql" in sys.argv

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlmodel import Field, Relationship, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx import (
    Collector,
    DefineSubset,
    ErManager,
    SubsetConfig,
    build_dto_select,
)

# ──────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────


class User(SQLModel, table=True):
    __tablename__ = "bench_user"

    id: int | None = Field(default=None, primary_key=True)
    name: str

    tasks: list["Task"] = Relationship(
        back_populates="owner",
        sa_relationship_kwargs={"lazy": "noload", "order_by": "Task.id"},
    )


class Sprint(SQLModel, table=True):
    __tablename__ = "bench_sprint"

    id: int | None = Field(default=None, primary_key=True)
    name: str

    tasks: list["Task"] = Relationship(
        back_populates="sprint",
        sa_relationship_kwargs={"lazy": "noload", "order_by": "Task.id"},
    )


class Task(SQLModel, table=True):
    __tablename__ = "bench_task"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    done: bool = False
    sprint_id: int = Field(foreign_key="bench_sprint.id")
    owner_id: int | None = Field(default=None, foreign_key="bench_user.id")

    sprint: Optional["Sprint"] = Relationship(back_populates="tasks")
    owner: Optional["User"] = Relationship(back_populates="tasks")


# ──────────────────────────────────────────────────────────
# DTOs (mirror demo/core_api/dtos.py patterns)
# ──────────────────────────────────────────────────────────


class UserSummary(DefineSubset):
    __subset__ = SubsetConfig(kls=User, fields=["id", "name"])


class TaskSummary(DefineSubset):
    __subset__ = SubsetConfig(kls=Task, fields=["id", "title", "sprint_id", "owner_id", "done"])
    owner: UserSummary | None = None


class SprintSummary(DefineSubset):
    __subset__ = SubsetConfig(kls=Sprint, fields=["id", "name"])
    tasks: list[TaskSummary] = []
    task_count: int = 0
    contributor_names: list[str] = []

    def post_task_count(self):
        return len(self.tasks)

    def post_contributor_names(self):
        names = {t.owner.name for t in self.tasks if t.owner}
        return sorted(names)


class TaskDetail(DefineSubset):
    __subset__ = SubsetConfig(
        kls=Task,
        fields=["id", "title", "sprint_id", "owner_id", "done"],
        send_to=[("owner", "contributors")],
    )
    owner: UserSummary | None = None
    full_title: str = ""

    def post_full_title(self, ancestor_context=None):
        if ancestor_context is None:
            ancestor_context = {}
        sprint_name = ancestor_context.get("sprint_name", "unknown")
        return f"{sprint_name} / {self.title}"


class SprintDetail(DefineSubset):
    __subset__ = SubsetConfig(
        kls=Sprint,
        fields=["id", "name"],
        expose_as=[("name", "sprint_name")],
    )
    tasks: list[TaskDetail] = []
    contributors: list[UserSummary] = []

    def post_contributors(self, collector=Collector("contributors")):
        return collector.values()


# ──────────────────────────────────────────────────────────
# Plain Pydantic DTOs (for fair comparison — same fields, no DefineSubset)
# ──────────────────────────────────────────────────────────

from pydantic import BaseModel as PydanticBaseModel


class PUserSummary(PydanticBaseModel):
    id: int
    name: str


class PTaskSummary(PydanticBaseModel):
    id: int
    title: str
    sprint_id: int
    owner_id: int | None
    done: bool
    owner: PUserSummary | None = None


class PSprintSummary(PydanticBaseModel):
    id: int
    name: str
    tasks: list[PTaskSummary] = []
    task_count: int = 0
    contributor_names: list[str] = []


class PTaskDetail(PydanticBaseModel):
    id: int
    title: str
    sprint_id: int
    owner_id: int | None
    done: bool
    owner: PUserSummary | None = None
    full_title: str = ""


class PSprintDetail(PydanticBaseModel):
    id: int
    name: str
    tasks: list[PTaskDetail] = []
    contributors: list[PUserSummary] = []


# ──────────────────────────────────────────────────────────
# Database setup
# ──────────────────────────────────────────────────────────

_engine = None
_session_factory = None

SQLITE_URL = "sqlite+aiosqlite:///:memory:"
MYSQL_URL = "mysql+asyncmy://root:bench@localhost:3306/nexusx_bench"


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
        # Check if already seeded
        existing = (await session.exec(select(User))).first()
        if existing:
            return

        users = [User(name=f"User_{i}") for i in range(n_users)]
        for u in users:
            session.add(u)
        await session.commit()
        for u in users:
            await session.refresh(u)

        sprints = [Sprint(name=f"Sprint_{i}") for i in range(n_sprints)]
        for s in sprints:
            session.add(s)
        await session.commit()
        for s in sprints:
            await session.refresh(s)

        task_id = 0
        for sprint in sprints:
            for j in range(n_tasks_per_sprint):
                owner = users[task_id % n_users]
                task = Task(
                    title=f"Task_{task_id}",
                    sprint_id=sprint.id,
                    owner_id=owner.id,
                    done=task_id % 3 == 0,
                )
                session.add(task)
                task_id += 1
        await session.commit()


# ──────────────────────────────────────────────────────────
# Benchmark: nexusx DefineSubset
# ──────────────────────────────────────────────────────────

er = None
Resolver = None


def _ensure_resolver():
    global er, Resolver
    if er is None:
        _, sf = _ensure_engine()
        er = ErManager(entities=[User, Sprint, Task], session_factory=sf)
        Resolver = er.create_resolver()


async def bench_nexusx_l1():
    """L1: Pure field selection — UserSummary."""
    _ensure_resolver()
    _, sf = _ensure_engine()
    stmt = build_dto_select(UserSummary)
    async with sf() as session:
        rows = (await session.exec(stmt)).all()
    dtos = [UserSummary(**dict(row._mapping)) for row in rows]
    return dtos


async def bench_nexusx_l2():
    """L2: TaskSummary with auto-loaded owner."""
    _ensure_resolver()
    _, sf = _ensure_engine()
    stmt = build_dto_select(TaskSummary)
    async with sf() as session:
        rows = (await session.exec(stmt)).all()
    dtos = [TaskSummary(**dict(row._mapping)) for row in rows]
    return await Resolver().resolve(dtos)


async def bench_nexusx_l3():
    """L3: SprintSummary with tasks → owner + derived fields."""
    _ensure_resolver()
    _, sf = _ensure_engine()
    stmt = build_dto_select(SprintSummary)
    async with sf() as session:
        rows = (await session.exec(stmt)).all()
    dtos = [SprintSummary(**dict(row._mapping)) for row in rows]
    return await Resolver().resolve(dtos)


async def bench_nexusx_l4():
    """L4: SprintDetail with ExposeAs + SendTo + Collector."""
    _ensure_resolver()
    _, sf = _ensure_engine()
    stmt = build_dto_select(SprintDetail)
    async with sf() as session:
        rows = (await session.exec(stmt)).all()
    dtos = [SprintDetail(**dict(row._mapping)) for row in rows]
    return await Resolver().resolve(dtos)


# ──────────────────────────────────────────────────────────
# Benchmark: Raw SQLAlchemy selectinload
# ──────────────────────────────────────────────────────────


async def bench_raw_l1():
    """L1: Pure field selection — manual dict."""
    _, sf = _ensure_engine()
    stmt = select(User)
    async with sf() as session:
        users = (await session.exec(stmt)).all()
    return [{"id": u.id, "name": u.name} for u in users]


async def bench_raw_l2():
    """L2: Task with selectinload owner."""
    _, sf = _ensure_engine()
    stmt = select(Task).options(selectinload(Task.owner))
    async with sf() as session:
        tasks = (await session.exec(stmt)).all()
    return [
        {
            "id": t.id,
            "title": t.title,
            "sprint_id": t.sprint_id,
            "owner_id": t.owner_id,
            "done": t.done,
            "owner": {"id": t.owner.id, "name": t.owner.name} if t.owner else None,
        }
        for t in tasks
    ]


async def bench_raw_l3():
    """L3: Sprint with tasks → owner + derived fields."""
    _, sf = _ensure_engine()
    stmt = select(Sprint).options(
        selectinload(Sprint.tasks).selectinload(Task.owner)
    )
    async with sf() as session:
        sprints = (await session.exec(stmt)).all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "sprint_id": t.sprint_id,
                    "owner_id": t.owner_id,
                    "done": t.done,
                    "owner": (
                        {"id": t.owner.id, "name": t.owner.name} if t.owner else None
                    ),
                }
                for t in s.tasks
            ],
            "task_count": len(s.tasks),
            "contributor_names": sorted(
                {t.owner.name for t in s.tasks if t.owner}
            ),
        }
        for s in sprints
    ]


async def bench_raw_l4():
    """L4: Sprint with tasks → owner + full_title + contributors aggregation."""
    _, sf = _ensure_engine()
    stmt = select(Sprint).options(
        selectinload(Sprint.tasks).selectinload(Task.owner)
    )
    async with sf() as session:
        sprints = (await session.exec(stmt)).all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "sprint_id": t.sprint_id,
                    "owner_id": t.owner_id,
                    "done": t.done,
                    "owner": (
                        {"id": t.owner.id, "name": t.owner.name} if t.owner else None
                    ),
                    "full_title": f"{s.name} / {t.title}",
                }
                for t in s.tasks
            ],
            "contributors": [
                {"id": t.owner.id, "name": t.owner.name}
                for t in s.tasks
                if t.owner
            ],
        }
        for s in sprints
    ]


# ──────────────────────────────────────────────────────────
# Benchmark: Raw SQLAlchemy selectinload + Pydantic DTO
# ──────────────────────────────────────────────────────────


async def bench_pydantic_l1():
    """L1: Pure field selection — Pydantic model."""
    _, sf = _ensure_engine()
    stmt = select(User)
    async with sf() as session:
        users = (await session.exec(stmt)).all()
    return [PUserSummary(id=u.id, name=u.name) for u in users]


async def bench_pydantic_l2():
    """L2: Task with selectinload owner — Pydantic model."""
    _, sf = _ensure_engine()
    stmt = select(Task).options(selectinload(Task.owner))
    async with sf() as session:
        tasks = (await session.exec(stmt)).all()
    return [
        PTaskSummary(
            id=t.id,
            title=t.title,
            sprint_id=t.sprint_id,
            owner_id=t.owner_id,
            done=t.done,
            owner=PUserSummary(id=t.owner.id, name=t.owner.name) if t.owner else None,
        )
        for t in tasks
    ]


async def bench_pydantic_l3():
    """L3: Sprint with tasks → owner + derived fields — Pydantic model."""
    _, sf = _ensure_engine()
    stmt = select(Sprint).options(
        selectinload(Sprint.tasks).selectinload(Task.owner)
    )
    async with sf() as session:
        sprints = (await session.exec(stmt)).all()
    return [
        PSprintSummary(
            id=s.id,
            name=s.name,
            tasks=[
                PTaskSummary(
                    id=t.id,
                    title=t.title,
                    sprint_id=t.sprint_id,
                    owner_id=t.owner_id,
                    done=t.done,
                    owner=(
                        PUserSummary(id=t.owner.id, name=t.owner.name)
                        if t.owner
                        else None
                    ),
                )
                for t in s.tasks
            ],
            task_count=len(s.tasks),
            contributor_names=sorted({t.owner.name for t in s.tasks if t.owner}),
        )
        for s in sprints
    ]


async def bench_pydantic_l4():
    """L4: Sprint with tasks → owner + full_title + contributors — Pydantic model."""
    _, sf = _ensure_engine()
    stmt = select(Sprint).options(
        selectinload(Sprint.tasks).selectinload(Task.owner)
    )
    async with sf() as session:
        sprints = (await session.exec(stmt)).all()
    return [
        PSprintDetail(
            id=s.id,
            name=s.name,
            tasks=[
                PTaskDetail(
                    id=t.id,
                    title=t.title,
                    sprint_id=t.sprint_id,
                    owner_id=t.owner_id,
                    done=t.done,
                    owner=(
                        PUserSummary(id=t.owner.id, name=t.owner.name)
                        if t.owner
                        else None
                    ),
                    full_title=f"{s.name} / {t.title}",
                )
                for t in s.tasks
            ],
            contributors=[
                PUserSummary(id=t.owner.id, name=t.owner.name)
                for t in s.tasks
                if t.owner
            ],
        )
        for s in sprints
    ]


# ──────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────

N_WARMUP = 5
N_RUNS = 50

SCENARIOS = [
    ("L1: Field selection", bench_nexusx_l1, bench_pydantic_l1, bench_raw_l1),
    ("L2: 1-level relationship", bench_nexusx_l2, bench_pydantic_l2, bench_raw_l2),
    ("L3: 2-level + derived fields", bench_nexusx_l3, bench_pydantic_l3, bench_raw_l3),
    ("L4: Cross-layer data flow", bench_nexusx_l4, bench_pydantic_l4, bench_raw_l4),
]

SCALES = [
    ("Small", 5, 3, 5),     # 15 tasks
    ("Medium", 20, 10, 20),  # 200 tasks
    ("Large", 50, 20, 50),   # 1000 tasks
]


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


def print_comparison(
    label: str,
    nexusx_times: list[float],
    pydantic_times: list[float],
    raw_times: list[float],
):
    def _stats(times):
        return mean(times), quantiles(times, n=4)[0], quantiles(times, n=20)[18]

    nx_avg, nx_p50, nx_p95 = _stats(nexusx_times)
    pd_avg, pd_p50, pd_p95 = _stats(pydantic_times)
    raw_avg, raw_p50, raw_p95 = _stats(raw_times)

    pd_overhead = ((pd_avg - raw_avg) / raw_avg) * 100 if raw_avg > 0 else 0
    nx_overhead = ((nx_avg - raw_avg) / raw_avg) * 100 if raw_avg > 0 else 0
    nx_vs_pd = ((nx_avg - pd_avg) / pd_avg) * 100 if pd_avg > 0 else 0
    sign_pd = "+" if pd_overhead >= 0 else ""
    sign_nx = "+" if nx_overhead >= 0 else ""
    sign_vs = "+" if nx_vs_pd >= 0 else ""

    print(f"  {label}")
    print(f"  {'Method':<25s} {'Avg':>10s} {'P50':>10s} {'P95':>10s}")
    print(f"  {'─' * 58}")
    print(f"  {'Raw dict (baseline)':<25s} {fmt_ms(raw_avg):>10s} {fmt_ms(raw_p50):>10s} {fmt_ms(raw_p95):>10s}")
    print(f"  {'Raw + Pydantic DTO':<25s} {fmt_ms(pd_avg):>10s} {fmt_ms(pd_p50):>10s} {fmt_ms(pd_p95):>10s}")
    print(f"  {'  vs dict':<25s} {sign_pd}{pd_overhead:.1f}%")
    print(f"  {'nexusx DefineSubset':<25s} {fmt_ms(nx_avg):>10s} {fmt_ms(nx_p50):>10s} {fmt_ms(nx_p95):>10s}")
    print(f"  {'  vs dict':<25s} {sign_nx}{nx_overhead:.1f}%")
    print(f"  {'  vs Pydantic':<25s} {sign_vs}{nx_vs_pd:.1f}%")
    print()


async def verify_correctness():
    """Verify both approaches produce equivalent results."""
    _ensure_resolver()
    _, sf = _ensure_engine()

    # L3: SprintSummary
    stmt = build_dto_select(SprintSummary)
    async with sf() as session:
        rows = (await session.exec(stmt)).all()
    dtos = [SprintSummary(**dict(row._mapping)) for row in rows]
    nx_result = await Resolver().resolve(dtos)

    stmt_raw = select(Sprint).options(
        selectinload(Sprint.tasks).selectinload(Task.owner)
    )
    async with sf() as session:
        sprints = (await session.exec(stmt_raw)).all()
    raw_result = [
        {
            "id": s.id,
            "task_count": len(s.tasks),
            "contributor_names": sorted(
                {t.owner.name for t in s.tasks if t.owner}
            ),
        }
        for s in sprints
    ]

    nx_map = {r.id: r for r in nx_result}
    raw_map = {r["id"]: r for r in raw_result}

    assert set(nx_map.keys()) == set(raw_map.keys()), "ID mismatch"
    for sid in nx_map:
        nx = nx_map[sid]
        raw = raw_map[sid]
        assert nx.task_count == raw["task_count"], (
            f"Sprint {sid}: task_count mismatch: {nx.task_count} vs {raw['task_count']}"
        )
        assert nx.contributor_names == raw["contributor_names"], (
            f"Sprint {sid}: contributor_names mismatch"
        )

    print("  Correctness verification: PASSED\n")


async def main():
    db_label = "MySQL 8.0 (localhost)" if USE_MYSQL else "SQLite in-memory"
    print("=" * 60)
    print("  DefineSubset + Resolver vs SQLAlchemy selectinload")
    print(f"  Database: {db_label}")
    print("=" * 60)
    print()

    await setup_db()

    for scale_name, n_users, n_sprints, n_tasks_per_sprint in SCALES:
        total_tasks = n_sprints * n_tasks_per_sprint
        print(f"  ── {scale_name} scale ({n_users} users, {n_sprints} sprints, {total_tasks} tasks) ──")
        print()

        # Reset globals for clean slate
        global _engine, _session_factory, er, Resolver
        _engine = None
        _session_factory = None
        er = None
        Resolver = None

        await setup_db()
        await seed_data(n_users, n_sprints, n_tasks_per_sprint)

        _ensure_resolver()

        # Verify correctness on medium scale
        if scale_name == "Medium":
            print("  Verifying result equivalence...")
            await verify_correctness()

        for scenario_name, nexusx_fn, pydantic_fn, raw_fn in SCENARIOS:
            # Warmup
            await run_bench(nexusx_fn, N_WARMUP)
            await run_bench(pydantic_fn, N_WARMUP)
            await run_bench(raw_fn, N_WARMUP)

            # Measure
            nx_times = await run_bench(nexusx_fn, N_RUNS)
            pd_times = await run_bench(pydantic_fn, N_RUNS)
            raw_times = await run_bench(raw_fn, N_RUNS)

            print_comparison(scenario_name, nx_times, pd_times, raw_times)

        print()


if __name__ == "__main__":
    asyncio.run(main())
