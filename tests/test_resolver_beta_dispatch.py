"""T015 — Resolver entity-field dispatch (specs/018 US3).

The level-by-level BFS + β ``fetch_remote_subtree`` dispatch moved from
``QueryExecutor`` into ``Resolver._bfs_dispatch_entity_fields`` (US3 / T016).
This file covers:

  (a) local relationship → registry loader (NOT fetch_remote_subtree)
  (b) β remote (REMOTE_PLAIN / REMOTE_PAGED) → fetch_remote_subtree
  (c) REMOTE_COALESCED → skipped (no job produced)

Plus migrated tests for ``_extract_entity_page_args`` /
``_build_entity_field_jobs`` — these methods moved house (executor →
resolver), so their tests moved with them verbatim.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nexusx.loader import query_meta as qm
from nexusx.loader.registry import ErManager, RelationshipKind
from nexusx.query_parser import FieldSelection
from nexusx.resolver import Resolver, _EntityFieldJob
from tests.conftest import (
    FixtureSprint,
    FixtureTask,
    FixtureUser,
    get_test_session_factory,
)


def _make_resolver(entities=None, session_factory=None, enable_pagination=False):
    """Build a real ErManager-backed Resolver (for migrated edge-case tests)."""
    if entities is None:
        entities = [FixtureUser, FixtureSprint, FixtureTask]
    if session_factory is None:
        session_factory = get_test_session_factory()
    registry = ErManager(
        entities=entities,
        session_factory=session_factory,
        enable_pagination=enable_pagination,
    )
    return registry.create_resolver()()


def _fake_rel(kind, **over):
    """A RelationshipInfo-shaped SimpleNamespace for routing tests (duck typed)."""
    base = dict(
        kind=kind,
        is_list=False,
        page_loader=None,
        fk_field="x_id",
        target_entity=type("Target", (), {}),
        name="rel",
        loader=object(),
        default_page_size=None,
        max_page_size=None,
        page_capability=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


# ── Migrated from test_query_executor.py (methods moved into Resolver) ──


class TestExtractEntityPageArgs:
    def test_rejects_negative_values(self):
        """Negative pagination arguments should fail fast (PageArgs validator)."""
        resolver = _make_resolver(enable_pagination=True)

        class Rel:
            default_page_size = 20
            max_page_size = 100

        with pytest.raises(ValueError, match="limit must be greater than or equal to 0"):
            resolver._extract_entity_page_args(
                FieldSelection(arguments={"limit": -1}), Rel(),
            )
        with pytest.raises(ValueError, match="offset must be greater than or equal to 0"):
            resolver._extract_entity_page_args(
                FieldSelection(arguments={"offset": -1}), Rel(),
            )


class TestBuildEntityFieldJobsEdgeCases:
    def test_empty_sub_fields_returns_no_jobs(self):
        """child_sel with empty sub_fields should produce no jobs."""
        resolver = _make_resolver()
        rel_info = resolver._registry.get_relationship(FixtureTask, "owner")
        assert rel_info is not None

        child_sel = FieldSelection(name="owner")
        jobs = resolver._build_entity_field_jobs(
            [FixtureTask(id=1, title="T", sprint_id=1, owner_id=1)],
            FixtureTask,
            FieldSelection(name="root", sub_fields={"owner": child_sel}),
            enable_pagination=False,
        )
        assert jobs == []

    def test_all_none_fk_values_returns_no_jobs(self):
        """Parents with all-None FK values should produce no jobs."""
        resolver = _make_resolver()
        task = FixtureTask(id=99, title="orphan", sprint_id=1, owner_id=None)
        jobs = resolver._build_entity_field_jobs(
            [task],
            FixtureTask,
            FieldSelection(
                name="root",
                sub_fields={
                    "owner": FieldSelection(
                        name="owner", sub_fields={"id": FieldSelection(name="id")}
                    )
                },
            ),
            enable_pagination=False,
        )
        assert jobs == []

    def test_pagination_items_without_sub_fields_produces_job(self):
        """Paginated field with only pagination selected still produces a job
        because child_sel.sub_fields is non-empty (has 'pagination')."""
        resolver = _make_resolver(enable_pagination=True)
        child_sel = FieldSelection(
            name="tasks", sub_fields={"pagination": FieldSelection(name="pagination")},
        )
        jobs = resolver._build_entity_field_jobs(
            [FixtureSprint(id=1, name="S1")],
            FixtureSprint,
            FieldSelection(name="root", sub_fields={"tasks": child_sel}),
            enable_pagination=True,
        )
        assert len(jobs) == 1

    def test_coalesced_remote_is_skipped(self):
        """(c) REMOTE_COALESCED produces no job — data already on the instance,
        resolved by the owning service within the parent fetch."""
        coalesced = _fake_rel(RelationshipKind.REMOTE_COALESCED, name="coalesced_rel")
        registry = SimpleNamespace(get_relationship=lambda e, f: coalesced)
        resolver = Resolver(loader_registry=registry)
        sel = FieldSelection(
            name="root",
            sub_fields={
                "coalesced_rel": FieldSelection(
                    name="coalesced_rel",
                    sub_fields={"id": FieldSelection(name="id")},
                )
            },
        )
        jobs = resolver._build_entity_field_jobs(
            [SimpleNamespace(x_id=1)], type("P", (), {}), sel, enable_pagination=False,
        )
        assert jobs == []


# ── T015 route-branch coverage: (a) local / (b) β remote ────────────────


class TestEntityFieldBatchRouting:
    """``_load_entity_field_batch`` routing — the US3 invariant that β
    ``fetch_remote_subtree`` lives inside the Resolver, not the executor."""

    @pytest.mark.asyncio
    async def test_local_rel_does_not_call_fetch_remote_subtree(self, monkeypatch):
        """(a) A LOCAL relationship routes through the registry loader and
        never reaches ``fetch_remote_subtree``."""
        import nexusx.federation.remote_loader as rl

        fetch_calls: list = []

        async def spy_fetch(**kwargs):
            fetch_calls.append(kwargs)
            return []

        monkeypatch.setattr(rl, "fetch_remote_subtree", spy_fetch)
        # Neutralize the query_meta helpers so the local branch needs no real
        # entity shape — this test asserts routing, not SQL column pruning.
        monkeypatch.setattr(qm, "generate_type_key_from_selection", lambda *a, **k: None)
        monkeypatch.setattr(qm, "generate_query_meta_from_selection", lambda *a, **k: None)
        monkeypatch.setattr(qm, "set_query_meta", lambda *a, **k: None)
        monkeypatch.setattr(qm, "merge_query_meta", lambda *a, **k: None)

        loader = SimpleNamespace(load_many=AsyncMock(return_value=[{"id": 1}]))
        rel = _fake_rel(RelationshipKind.LOCAL, name="local_rel")
        registry = SimpleNamespace(
            get_relationship=lambda e, f: rel,
            get_relationships=lambda e: {},
            get_loader=lambda *a, **k: loader,
            _split_mode=False,
        )
        resolver = Resolver(loader_registry=registry)

        job = _EntityFieldJob(
            parents=[SimpleNamespace(x_id=1)],
            parent_entity=type("P", (), {}),
            rel_info=rel,
            child_sel=FieldSelection(
                name="local_rel", sub_fields={"id": FieldSelection(name="id")}
            ),
        )
        store: list = []
        await resolver._load_entity_field_batch(
            job, lambda p, n, v: store.append((n, v))
        )

        assert fetch_calls == []  # (a) local never fetches remotely
        assert loader.load_many.await_count == 1  # it goes through the registry loader

    @pytest.mark.asyncio
    async def test_remote_plain_routes_to_fetch_remote_subtree(self, monkeypatch):
        """(b) A REMOTE_PLAIN β relationship routes to fetch_remote_subtree
        with paged=False."""
        import nexusx.federation.remote_loader as rl

        captured: dict = {}

        async def spy_fetch(*, registry, rel_info, parents, selection, paged=False):
            captured["kind"] = rel_info.kind
            captured["paged"] = paged
            return [[SimpleNamespace(id=1)]]

        monkeypatch.setattr(rl, "fetch_remote_subtree", spy_fetch)

        rel = _fake_rel(RelationshipKind.REMOTE_PLAIN, name="beta_rel", is_list=True)
        registry = SimpleNamespace(get_relationship=lambda e, f: rel)
        resolver = Resolver(loader_registry=registry)

        job = _EntityFieldJob(
            parents=[SimpleNamespace(x_id=7)],
            parent_entity=type("P", (), {}),
            rel_info=rel,
            child_sel=FieldSelection(
                name="beta_rel", sub_fields={"id": FieldSelection(name="id")}
            ),
        )
        store: list = []
        await resolver._load_entity_field_batch(
            job, lambda p, n, v: store.append((n, v))
        )

        assert captured["kind"] == RelationshipKind.REMOTE_PLAIN
        assert captured["paged"] is False

    @pytest.mark.asyncio
    async def test_remote_paged_routes_to_fetch_remote_subtree_paged(self, monkeypatch):
        """(b) A REMOTE_PAGED β relationship routes to fetch_remote_subtree
        with paged=True (member's page_by_<key>_in root)."""
        import nexusx.federation.remote_loader as rl

        captured: dict = {}

        async def spy_fetch(*, registry, rel_info, parents, selection, paged=False):
            captured["paged"] = paged
            return [{"items": [SimpleNamespace(id=1)], "pagination": {}}]

        monkeypatch.setattr(rl, "fetch_remote_subtree", spy_fetch)

        rel = _fake_rel(RelationshipKind.REMOTE_PAGED, name="beta_paged_rel", is_list=True)
        registry = SimpleNamespace(get_relationship=lambda e, f: rel)
        resolver = Resolver(loader_registry=registry)

        job = _EntityFieldJob(
            parents=[SimpleNamespace(x_id=7)],
            parent_entity=type("P", (), {}),
            rel_info=rel,
            child_sel=FieldSelection(
                name="beta_paged_rel", sub_fields={"id": FieldSelection(name="id")}
            ),
        )
        store: list = []
        await resolver._load_entity_field_batch(
            job, lambda p, n, v: store.append((n, v))
        )

        assert captured["paged"] is True
