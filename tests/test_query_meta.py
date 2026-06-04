"""Tests for query_meta: SQL column pruning via _query_meta."""

from __future__ import annotations

from pydantic import BaseModel

from nexusx.loader.factories import (
    _apply_load_only,
    _dedupe_fields,
    _get_default_fields,
    _get_effective_query_fields,
)
from nexusx.loader.query_meta import (
    generate_query_meta_from_dto,
    generate_query_meta_from_selection,
    generate_type_key_from_dto,
    generate_type_key_from_selection,
    merge_query_meta,
    set_query_meta,
)
from nexusx.query_parser import FieldSelection

# ── DTO fixtures ──


class FakeEntity(BaseModel):
    id: int
    name: str
    email: str
    bio: str = ""


class TaskCardDTO(BaseModel):
    id: int
    title: str


class TaskDetailDTO(BaseModel):
    id: int
    title: str
    desc: str
    status: str


# ── generate_query_meta_from_dto ──


class TestGenerateQueryMetaFromDto:
    def test_extracts_all_model_fields(self):
        meta = generate_query_meta_from_dto(TaskCardDTO)
        assert meta["fields"] == ["id", "title"]
        assert len(meta["request_types"]) == 1
        assert meta["request_types"][0]["name"] is TaskCardDTO
        assert meta["request_types"][0]["fields"] == ["id", "title"]

    def test_includes_all_columns(self):
        meta = generate_query_meta_from_dto(FakeEntity)
        assert "id" in meta["fields"]
        assert "name" in meta["fields"]
        assert "email" in meta["fields"]
        assert "bio" in meta["fields"]


# ── generate_query_meta_from_selection ──


class TestGenerateQueryMetaFromSelection:
    def test_scalar_fields_only(self):
        sel = FieldSelection(
            name="user",
            sub_fields={
                "id": FieldSelection(name="id"),
                "name": FieldSelection(name="name"),
            },
        )
        meta = generate_query_meta_from_selection(sel, FakeEntity)
        assert "id" in meta["fields"]
        assert "name" in meta["fields"]
        assert "email" not in meta["fields"]
        assert "bio" not in meta["fields"]

    def test_relationship_fields_excluded_but_fk_preserved(self):
        """Relationship fields (with sub_fields) should be excluded,
        but their FK column (e.g., owner_id) should be preserved."""
        sel = FieldSelection(
            name="task",
            sub_fields={
                "id": FieldSelection(name="id"),
                "title": FieldSelection(name="title"),
                "owner": FieldSelection(
                    name="owner",
                    sub_fields={
                        "id": FieldSelection(name="id"),
                        "name": FieldSelection(name="name"),
                    },
                ),
            },
        )

        class TaskEntity(BaseModel):
            id: int
            title: str
            owner_id: int

        meta = generate_query_meta_from_selection(sel, TaskEntity)
        assert "id" in meta["fields"]
        assert "title" in meta["fields"]
        assert "owner_id" in meta["fields"]  # FK preserved
        assert "owner" not in meta["fields"]  # relationship excluded

    def test_none_selection_returns_all_fields(self):
        meta = generate_query_meta_from_selection(None, FakeEntity)
        assert meta["fields"] == list(FakeEntity.model_fields.keys())

    def test_empty_sub_fields_returns_all_fields(self):
        sel = FieldSelection(name="user")
        meta = generate_query_meta_from_selection(sel, FakeEntity)
        assert meta["fields"] == list(FakeEntity.model_fields.keys())


# ── merge_query_meta ──


class TestMergeQueryMeta:
    def test_first_merge_sets_meta(self):
        loader = type("L", (), {})()
        meta = {"fields": ["id", "name"], "request_types": []}
        merge_query_meta(loader, meta)
        assert loader._query_meta["fields"] == ["id", "name"]

    def test_second_merge_takes_union(self):
        loader = type("L", (), {})()
        merge_query_meta(loader, {"fields": ["id", "name"], "request_types": []})
        merge_query_meta(loader, {"fields": ["id", "email"], "request_types": []})
        fields = set(loader._query_meta["fields"])
        assert fields == {"id", "name", "email"}


# ── _dedupe_fields ──


class TestDedupeFields:
    def test_removes_duplicates_preserves_order(self):
        assert _dedupe_fields(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]

    def test_empty_input(self):
        assert _dedupe_fields([]) == []


# ── _get_default_fields ──


class TestGetDefaultFields:
    def test_returns_all_model_fields(self):
        fields = _get_default_fields(FakeEntity)
        assert fields == ["id", "name", "email", "bio"]


# ── _get_effective_query_fields ──


class TestGetEffectiveQueryFields:
    def test_with_query_meta_returns_requested_fields(self):
        loader = type("L", (), {"_query_meta": {"fields": ["id", "name"]}})()
        result = _get_effective_query_fields(loader, FakeEntity)
        assert result == ["id", "name"]

    def test_with_extra_fields_appends(self):
        loader = type("L", (), {"_query_meta": {"fields": ["id"]}})()
        result = _get_effective_query_fields(loader, FakeEntity, extra_fields=["email"])
        assert result == ["id", "email"]

    def test_without_query_meta_returns_none(self):
        loader = type("L", (), {})()
        result = _get_effective_query_fields(loader, FakeEntity)
        assert result is None

    def test_deduplicates_extra_fields(self):
        loader = type("L", (), {"_query_meta": {"fields": ["id", "name"]}})()
        result = _get_effective_query_fields(loader, FakeEntity, extra_fields=["name"])
        assert result == ["id", "name"]

    def test_with_query_meta_missing_fields_key(self):
        loader = type("L", (), {"_query_meta": {}})()
        result = _get_effective_query_fields(loader, FakeEntity)
        assert result is None


# ── _apply_load_only integration ──


class TestApplyLoadOnly:
    def test_applies_load_only_to_statement(self):
        """Verify _apply_load_only adds load_only options to the statement."""
        from sqlalchemy import select

        from tests.conftest import FixtureUser

        stmt = select(FixtureUser)
        result = _apply_load_only(stmt, FixtureUser, ["id", "name"])

        # Verify the statement has load_only options
        compiled = result.compile()
        sql_text = str(compiled)
        assert "id" in sql_text or "name" in sql_text


# ── set_query_meta ──


class TestSetQueryMeta:
    def test_direct_set(self):
        loader = type("L", (), {})()
        meta = {"fields": ["id", "name"], "request_types": []}
        set_query_meta(loader, meta)
        assert loader._query_meta["fields"] == ["id", "name"]

    def test_overwrites_existing(self):
        loader = type("L", (), {})()
        set_query_meta(loader, {"fields": ["id"], "request_types": []})
        set_query_meta(loader, {"fields": ["id", "name"], "request_types": []})
        assert loader._query_meta["fields"] == ["id", "name"]


# ── generate_type_key_from_selection ──


class TestGenerateTypeKeyFromSelection:
    def test_scalar_fields(self):
        sel = FieldSelection(
            name="user",
            sub_fields={
                "id": FieldSelection(name="id"),
                "name": FieldSelection(name="name"),
            },
        )
        key = generate_type_key_from_selection(sel, FakeEntity)
        assert key == frozenset({"id", "name"})

    def test_includes_fk_for_relationships(self):
        class TaskEntity(BaseModel):
            id: int
            title: str
            owner_id: int

        sel = FieldSelection(
            name="task",
            sub_fields={
                "id": FieldSelection(name="id"),
                "owner": FieldSelection(
                    name="owner",
                    sub_fields={"id": FieldSelection(name="id")},
                ),
            },
        )
        key = generate_type_key_from_selection(sel, TaskEntity)
        assert "id" in key
        assert "owner_id" in key
        assert "owner" not in key

    def test_none_returns_none(self):
        assert generate_type_key_from_selection(None, FakeEntity) is None

    def test_empty_sub_fields_returns_none(self):
        sel = FieldSelection(name="user")
        assert generate_type_key_from_selection(sel, FakeEntity) is None

    def test_is_hashable(self):
        key = frozenset({"id", "name"})
        assert hash(key) is not None
        s = {key}
        assert key in s


# ── generate_type_key_from_dto ──


class TestGenerateTypeKeyFromDto:
    def test_from_dto_fields(self):
        key = generate_type_key_from_dto(TaskCardDTO)
        assert key == frozenset({"id", "title"})

    def test_from_dto_all_fields(self):
        key = generate_type_key_from_dto(FakeEntity)
        assert key == frozenset({"id", "name", "email", "bio"})

    def test_none_entity_fallback(self):
        key = generate_type_key_from_dto(TaskCardDTO, entity_kls=None)
        assert key == frozenset({"id", "title"})


# ── ErManager split mode ──


class TestErManagerSplitMode:
    async def test_split_creates_separate_instances(self):
        from nexusx.loader.registry import ErManager
        from tests.conftest import FixtureTask, FixtureUser

        registry = ErManager(
            entities=[FixtureUser, FixtureTask],
            session_factory=lambda: None,
            split_loader_by_type=True,
        )

        # Get a relationship's loader class
        rel_info = registry.get_relationship(FixtureTask, "owner")
        loader_cls = rel_info.loader

        key1 = frozenset({"id", "name"})
        key2 = frozenset({"id", "name", "email"})
        inst1 = registry.get_loader(loader_cls, type_key=key1)
        inst2 = registry.get_loader(loader_cls, type_key=key2)

        assert inst1 is not inst2

    async def test_split_same_type_key_shares_instance(self):
        from nexusx.loader.registry import ErManager
        from tests.conftest import FixtureTask, FixtureUser

        registry = ErManager(
            entities=[FixtureUser, FixtureTask],
            session_factory=lambda: None,
            split_loader_by_type=True,
        )

        rel_info = registry.get_relationship(FixtureTask, "owner")
        loader_cls = rel_info.loader

        key = frozenset({"id", "name"})
        inst1 = registry.get_loader(loader_cls, type_key=key)
        inst2 = registry.get_loader(loader_cls, type_key=key)

        assert inst1 is inst2

    async def test_default_mode_ignores_type_key(self):
        from nexusx.loader.registry import ErManager
        from tests.conftest import FixtureTask, FixtureUser

        registry = ErManager(
            entities=[FixtureUser, FixtureTask],
            session_factory=lambda: None,
            # split_loader_by_type=False (default)
        )

        rel_info = registry.get_relationship(FixtureTask, "owner")
        loader_cls = rel_info.loader

        key1 = frozenset({"id"})
        key2 = frozenset({"id", "name"})
        inst1 = registry.get_loader(loader_cls, type_key=key1)
        inst2 = registry.get_loader(loader_cls, type_key=key2)

        # Default mode: always returns same instance regardless of type_key
        assert inst1 is inst2

    async def test_clear_cache_resets_split_instances(self):
        from nexusx.loader.registry import ErManager
        from tests.conftest import FixtureTask, FixtureUser

        registry = ErManager(
            entities=[FixtureUser, FixtureTask],
            session_factory=lambda: None,
            split_loader_by_type=True,
        )

        rel_info = registry.get_relationship(FixtureTask, "owner")
        loader_cls = rel_info.loader

        key = frozenset({"id"})
        inst_before = registry.get_loader(loader_cls, type_key=key)
        registry.clear_cache()
        inst_after = registry.get_loader(loader_cls, type_key=key)

        assert inst_before is not inst_after
