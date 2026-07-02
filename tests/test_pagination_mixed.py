"""End-to-end tests for the warn-skip behavior (issue #83).

Mixed scenario: one parent with two list relationships — one paginated
(``sorted_kids`` has ``order_by``) and one not (``raw_kids`` lacks it).
These tests prove that SDL, introspection, and execution all honor the
per-relationship ``page_loader is None`` signal rather than assuming
``enable_pagination=True`` means "every list is paginated".
"""

from typing import Optional

import pytest
from sqlmodel import Field, Relationship, SQLModel

from nexusx.introspection import IntrospectionGenerator
from nexusx.loader.pagination import PageArgs, PageLoadCommand
from nexusx.loader.registry import ErManager
from nexusx.sdl_generator import SDLGenerator
from tests.conftest import get_test_session_factory


# ──────────────────────────────────────────────────────────
# Shared mixed-pagination fixtures
# ──────────────────────────────────────────────────────────


class MixedBase(SQLModel):
    pass


class SortedKid(MixedBase, table=True):
    __tablename__ = "mix_sorted_kid"

    id: int | None = Field(default=None, primary_key=True)
    label: str
    parent_id: int = Field(foreign_key="mix_parent.id")
    parent: Optional["MixedParent"] = Relationship(back_populates="sorted_kids")


class RawKid(MixedBase, table=True):
    __tablename__ = "mix_raw_kid"

    id: int | None = Field(default=None, primary_key=True)
    label: str
    parent_id: int = Field(foreign_key="mix_parent.id")
    parent: Optional["MixedParent"] = Relationship(back_populates="raw_kids")


class MixedParent(MixedBase, table=True):
    __tablename__ = "mix_parent"

    id: int | None = Field(default=None, primary_key=True)
    name: str

    sorted_kids: list["SortedKid"] = Relationship(
        back_populates="parent",
        sa_relationship_kwargs={"order_by": "SortedKid.id"},
    )
    raw_kids: list["RawKid"] = Relationship(back_populates="parent")


MIXED_ENTITIES = [MixedParent, SortedKid, RawKid]


def _make_registry() -> ErManager:
    return ErManager(
        entities=MIXED_ENTITIES,
        session_factory=get_test_session_factory(),
        enable_pagination=True,
    )


# ──────────────────────────────────────────────────────────
# 1. SDL: per-relationship rendering
# ──────────────────────────────────────────────────────────


class TestSDLMixedPagination:
    def test_paginated_list_renders_as_result_type(self):
        """sorted_kids (has order_by) → SortedKidResult! with limit/offset args."""
        registry = _make_registry()
        sdl = SDLGenerator(MIXED_ENTITIES).generate(
            enable_pagination=True, loader_registry=registry
        )

        assert "type SortedKidResult {" in sdl
        assert "items: [SortedKid!]!" in sdl

        parent_block = sdl.split("type MixedParent {", 1)[1].split("}", 1)[0]
        # Field type is SortedKidResult! (non-null). Field may declare args
        # — that's covered by test_paginated_field_exposes_limit_offset_args.
        assert ": SortedKidResult!" in parent_block

    def test_paginated_field_exposes_limit_offset_args(self):
        """Issue #85: paginated list field must declare limit/offset args in SDL.

        SDL and introspection must agree — without args in SDL, any client
        that reads the schema via SDL (codegen tools, AI agents, GraphiQL
        alternatives) cannot tell the field is paginated.
        """
        registry = _make_registry()
        sdl = SDLGenerator(MIXED_ENTITIES).generate(
            enable_pagination=True, loader_registry=registry
        )

        parent_block = sdl.split("type MixedParent {", 1)[1].split("}", 1)[0]
        assert "sorted_kids(limit: Int, offset: Int = 0): SortedKidResult!" in parent_block

    def test_non_paginated_list_renders_as_plain_list(self):
        """raw_kids (no order_by) → [RawKid!]! with no pagination args."""
        registry = _make_registry()
        sdl = SDLGenerator(MIXED_ENTITIES).generate(
            enable_pagination=True, loader_registry=registry
        )

        assert "RawKidResult" not in sdl

        parent_block = sdl.split("type MixedParent {", 1)[1].split("}", 1)[0]
        assert "raw_kids: [RawKid!]!" in parent_block
        assert "raw_kids(" not in parent_block

    def test_pagination_warning_does_not_block_sdl_generation(self, caplog):
        """Startup warns about raw_kids but SDL still generates successfully."""
        import logging

        with caplog.at_level(logging.WARNING, logger="nexusx.loader.registry"):
            registry = _make_registry()

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "MixedParent.raw_kids" in warnings[0].getMessage()
        assert registry.get_relationship(MixedParent, "sorted_kids").page_loader is not None
        assert registry.get_relationship(MixedParent, "raw_kids").page_loader is None
        assert registry.get_relationship(MixedParent, "raw_kids").loader is not None


# ──────────────────────────────────────────────────────────
# 2. Introspection: per-relationship field shape
# ──────────────────────────────────────────────────────────


def _make_introspection() -> dict:
    """Build introspection dict directly (bypass GraphQLHandler discovery)."""
    registry = _make_registry()
    gen = IntrospectionGenerator(
        entities=MIXED_ENTITIES,
        query_methods={},
        mutation_methods={},
        enable_pagination=True,
        loader_registry=registry,
    )
    return gen.generate()


class TestIntrospectionMixedPagination:
    @pytest.fixture
    def schema(self):
        return _make_introspection()

    def _field(self, schema, type_name, field_name):
        t = next((t for t in schema["types"] if t["name"] == type_name), None)
        assert t is not None, f"type {type_name} missing"
        f = next((f for f in t["fields"] if f["name"] == field_name), None)
        assert f is not None, f"field {type_name}.{field_name} missing"
        return f

    def _unwrap(self, type_ref):
        while type_ref.get("ofType") is not None:
            type_ref = type_ref["ofType"]
        return type_ref

    def test_paginated_field_uses_result_type_with_args(self, schema):
        f = self._field(schema, "MixedParent", "sorted_kids")
        inner = self._unwrap(f["type"])
        assert inner["kind"] == "OBJECT"
        assert inner["name"] == "SortedKidResult"
        arg_names = [a["name"] for a in f["args"]]
        assert "limit" in arg_names
        assert "offset" in arg_names

    def test_non_paginated_field_uses_plain_list_no_args(self, schema):
        f = self._field(schema, "MixedParent", "raw_kids")
        outer = f["type"]
        assert outer["kind"] == "NON_NULL"
        list_node = outer["ofType"]
        assert list_node["kind"] == "LIST"
        inner_non_null = list_node["ofType"]
        assert inner_non_null["kind"] == "NON_NULL"
        leaf = inner_non_null["ofType"]
        assert leaf["kind"] == "OBJECT"
        assert leaf["name"] == "RawKid"
        assert f["args"] == []

    def test_result_type_emitted_only_for_paginated_target(self, schema):
        names = {t["name"] for t in schema["types"]}
        assert "SortedKidResult" in names
        assert "RawKidResult" not in names


# ──────────────────────────────────────────────────────────
# 3. Execution: paginated vs non-paginated loader shapes
# ──────────────────────────────────────────────────────────


class TestExecutionMixedPagination:
    @pytest.mark.usefixtures("test_db")
    async def test_paginated_and_regular_loaders_dispatch_correctly(self):
        """sorted_kids returns a Result dict; raw_kids returns a plain list.

        Issue #83: when ``enable_pagination=True`` but a list lacks
        ``order_by``, that list must still resolve via the regular loader
        rather than 404'ing or being silently dropped.
        """
        from tests.conftest import init_test_db

        await init_test_db()
        session_factory = get_test_session_factory()
        async with session_factory() as session:
            parent = MixedParent(name="P1")
            session.add(parent)
            await session.commit()
            await session.refresh(parent)
            for label in ("s1", "s2", "s3"):
                session.add(SortedKid(label=label, parent_id=parent.id))
            for label in ("r1", "r2"):
                session.add(RawKid(label=label, parent_id=parent.id))
            await session.commit()

        registry = _make_registry()
        sorted_rel = registry.get_relationship(MixedParent, "sorted_kids")
        raw_rel = registry.get_relationship(MixedParent, "raw_kids")

        assert sorted_rel.page_loader is not None
        assert raw_rel.page_loader is None
        assert raw_rel.loader is not None

        # Paginated loader returns Result-shaped dicts. Cover both the
        # easy case (limit << total) and the boundary case (limit leaves
        # exactly one row beyond the current page) — the boundary is the
        # regression guard for the has_more off-by-one fix (#86).
        page_loader = registry.get_loader(sorted_rel.page_loader)
        for limit, expected_has_more in [(1, True), (2, True), (3, False)]:
            cmd = PageLoadCommand(fk_value=parent.id, page_args=PageArgs(limit=limit))
            results = await page_loader.load_many([cmd])
            assert len(results) == 1
            assert {"items", "pagination"} <= set(results[0].keys())
            assert len(results[0]["items"]) == limit
            assert results[0]["pagination"].total_count == 3
            assert (
                results[0]["pagination"].has_more is expected_has_more
            ), f"limit={limit} expected has_more={expected_has_more}"

        # Regular loader returns a plain list of RawKid instances.
        regular_loader = registry.get_loader(raw_rel.loader)
        raw_rows = await regular_loader.load_many([parent.id])
        assert len(raw_rows) == 1
        assert isinstance(raw_rows[0], list)
        assert all(isinstance(r, RawKid) for r in raw_rows[0])
        assert {r.label for r in raw_rows[0]} == {"r1", "r2"}
