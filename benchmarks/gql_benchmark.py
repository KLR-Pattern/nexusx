"""gql benchmark — response_builder serialize latency (specs/018 T025 / Phase 7).

Measures entity-first gql end-to-end latency under the response_builder path
(``build_response_model`` + ``model_validate``), which is the **only** serialize
path since Phase 7 T028 removed the legacy dict-based loop + the
``use_response_builder`` flag.

History: T025 originally compared flag-on vs flag-off to gate the default flip.
That comparison (and the create_model cache that closed the gap) is captured in
``specs/018-dto-first-gql-execution/benchmark-baseline.md``. With the flag gone,
this script now monitors the response_builder path's absolute latency + cProfile
so regressions (e.g. cache miss, new per-item overhead) show up.

Scenarios (representative shapes). Federation needs a live member service and is
out of scope — β serialize goes through the same response_builder path:

  Q1 scalar+nested — tasks → owner
  Q2 deep          — sprints → tasks → owner
  Q3 wide          — users → posts + comments
  Q4 paginated     — sprints → tasks(limit) { items pagination }

Usage::

    uv run python benchmarks/gql_benchmark.py            # latency table
    uv run python benchmarks/gql_benchmark.py --profile  # + cProfile (Q2)

Reuses the entity models + seed from ``benchmarks/bench_graphql.py``.
"""

from __future__ import annotations

import argparse
import asyncio
import cProfile
import os
import pstats
import sys
import time
from io import StringIO
from statistics import mean, quantiles

from graphql import parse
from sqlmodel import select

from nexusx.execution.query_executor import QueryExecutor
from nexusx.loader.registry import ErManager
from nexusx.query_parser import QueryParser

# Make the repo root importable when this script is run directly
# (``python benchmarks/gql_benchmark.py`` → sys.path[0] is benchmarks/, not root).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from benchmarks.bench_graphql import (  # noqa: E402
    ALL_ENTITIES_BLOG,
    ALL_ENTITIES_SPRINT,
    Sprint,
    Task,
    User,
    _ensure_engine,
    fmt_ms,
    seed_data,
    setup_db,
)

N_WARMUP = 5
N_RUNS = 50


def _make_executor(entities, session_factory) -> QueryExecutor:
    """Build an executor with ``enable_pagination`` on (Q4's page_loader wired)."""
    registry = ErManager(
        entities=entities, session_factory=session_factory, enable_pagination=True,
    )
    return QueryExecutor(registry, enable_pagination=True)


def _query_method(entity_cls, session_factory):
    """A plain get-all query method (no args) — execute_query calls it as-is."""

    async def get_all():
        async with session_factory() as session:
            return list((await session.exec(select(entity_cls))).all())

    return get_all


async def _execute(executor, gql, entity_name, method_name, entity_cls, method, entities):
    """Run one grouped-dispatch query (``{ Entity { method {...} } }``)."""
    document = parse(gql)
    parsed = QueryParser().parse(gql)
    query_methods = {entity_name: {method_name: (entity_cls, method)}}
    return await executor.execute_query(
        document, None, None, parsed, query_methods, {}, entities,
    )


async def bench_q1(executor, session_factory, entities):
    """Q1: scalar+nested — tasks → owner."""
    gql = "{ Task { all { id title owner { id name } } } }"
    return await _execute(
        executor, gql, "Task", "all", Task, _query_method(Task, session_factory), entities
    )


async def bench_q2(executor, session_factory, entities):
    """Q2: deep — sprints → tasks → owner."""
    gql = "{ Sprint { all { id name tasks { id title owner { id name } } } } }"
    return await _execute(
        executor, gql, "Sprint", "all", Sprint, _query_method(Sprint, session_factory), entities
    )


async def bench_q3(executor, session_factory, entities):
    """Q3: wide — users → posts + comments."""
    gql = "{ User { all { id name posts { id title } comments { id content } } } }"
    return await _execute(
        executor, gql, "User", "all", User, _query_method(User, session_factory), entities
    )


async def bench_q4_paginated(executor, session_factory, entities):
    """Q4: paginated — sprints → tasks(limit) { items pagination }."""
    gql = (
        "{ Sprint { all { id name tasks(limit: 5) { items { id title owner { id name } } "
        "pagination { has_more total_count } } } } }"
    )
    return await _execute(
        executor, gql, "Sprint", "all", Sprint, _query_method(Sprint, session_factory), entities
    )


async def _run_bench(fn, n_runs: int) -> list[float]:
    times: list[float] = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        await fn()
        times.append(time.perf_counter() - t0)
    return times


def _stats(times: list[float]) -> tuple[float, float, float]:
    avg = mean(times)
    p50 = quantiles(times, n=4)[0]
    p95 = quantiles(times, n=20)[18]
    return avg, p50, p95


async def _correctness_check(session_factory) -> None:
    """Sanity: Q2 returns sprint→tasks→owner data before timing."""
    entities = ALL_ENTITIES_SPRINT
    ex = _make_executor(entities, session_factory)
    r = await bench_q2(ex, session_factory, entities)
    assert "errors" not in r, f"Q2 errors: {r.get('errors')}"
    sprints = r["data"]["Sprint"]["all"]
    assert sprints, "Q2 returned no sprints"
    print(f"  correctness (Q2 returned {len(sprints)} sprints): PASSED\n")


async def main(profile: bool) -> None:
    print("=" * 70)
    print("  gql benchmark — response_builder serialize latency (specs/018)")
    print("=" * 70)
    print()

    _, sf = _ensure_engine()
    await setup_db()
    await seed_data(n_users=20, n_sprints=10, n_tasks_per_sprint=20)  # Medium

    print("  Verifying correctness...")
    await _correctness_check(sf)

    scenarios = [
        ("Q1 scalar+nested (task→owner)", bench_q1, ALL_ENTITIES_SPRINT),
        ("Q2 deep (sprint→tasks→owner)", bench_q2, ALL_ENTITIES_SPRINT),
        ("Q3 wide (user→posts+comments)", bench_q3, ALL_ENTITIES_BLOG),
        ("Q4 paginated (sprint→tasks limit)", bench_q4_paginated, ALL_ENTITIES_SPRINT),
    ]

    print(f"  {'Scenario':<40s} {'Avg':>9s} {'P50':>9s} {'P95':>9s}")
    print(f"  {'─' * 70}")

    for label, bench_fn, scenario_entities in scenarios:
        ex = _make_executor(scenario_entities, sf)

        async def run(_fn=bench_fn, _ex=ex, _sf=sf, _en=scenario_entities):
            await _fn(_ex, _sf, _en)

        await _run_bench(run, N_WARMUP)
        times = await _run_bench(run, N_RUNS)
        avg, p50, p95 = _stats(times)
        print(f"  {label:<40s} {fmt_ms(avg):>9s} {fmt_ms(p50):>9s} {fmt_ms(p95):>9s}")

    print()

    if profile:
        print("  cProfile (Q2 deep) — top 15 by cumulative time:")
        print(f"  {'─' * 70}")
        ex = _make_executor(ALL_ENTITIES_SPRINT, sf)
        profiler = cProfile.Profile()
        profiler.enable()
        for _ in range(20):
            await bench_q2(ex, sf, ALL_ENTITIES_SPRINT)
        profiler.disable()
        buf = StringIO()
        pstats.Stats(profiler, stream=buf).sort_stats("cumulative").print_stats(15)
        for line in buf.getvalue().splitlines():
            print(f"  {line}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--profile", action="store_true", help="dump cProfile for Q2")
    args = p.parse_args()
    sys.exit(asyncio.run(main(args.profile)))
