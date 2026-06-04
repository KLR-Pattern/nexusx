"""Tests for fixes: caching, desc/asc, ambiguity, FK lookup, closures."""

from __future__ import annotations

import logging

import pytest
from pydantic import BaseModel
from sqlmodel import Field, SQLModel

from nexusx.context import (
    _expose_cache,
    _send_to_cache,
    scan_expose_fields,
    scan_send_to_fields,
)
from nexusx.loader.registry import ErManager, _extract_sort_field
from nexusx.relationship import Relationship
from nexusx.resolver import Loader, Resolver, _class_meta_cache, _get_class_meta

# ──────────────────────────────────────────────────────────
# Issue 1+2: Resolver metadata caching
# ──────────────────────────────────────────────────────────


class TestClassMetaCache:
    """Verify class metadata is computed once and reused."""

    def test_cache_populated_on_first_access(self):
        """_get_class_meta should populate cache on first call."""

        class SomeModel(BaseModel):
            name: str
            greeting: str = ""

            def resolve_greeting(self):
                return f"Hello, {self.name}!"

            def post_upper_name(self):
                return self.name.upper()

        # Clear cache to isolate test
        _class_meta_cache.pop(SomeModel, None)

        meta = _get_class_meta(SomeModel)

        assert SomeModel in _class_meta_cache
        assert len(meta.resolve_methods) == 1
        assert meta.resolve_methods[0] == ("greeting", "resolve_greeting")
        assert len(meta.post_methods) == 1
        assert meta.post_methods[0] == ("upper_name", "post_upper_name")

    def test_cache_reused_on_second_access(self):
        """_get_class_meta should return the same object on subsequent calls."""

        class AnotherModel(BaseModel):
            x: int = 0

        _class_meta_cache.pop(AnotherModel, None)

        meta1 = _get_class_meta(AnotherModel)
        meta2 = _get_class_meta(AnotherModel)
        assert meta1 is meta2

    def test_resolve_param_info_cached(self):
        """Method parameter info should be pre-computed."""

        async def test_batch_fn(keys):
            return keys

        class ParamModel(BaseModel):
            value: str = ""

            def resolve_value(self, context, loader=Loader(test_batch_fn)):
                return "ok"

        _class_meta_cache.pop(ParamModel, None)
        meta = _get_class_meta(ParamModel)

        param_info = meta.resolve_params["resolve_value"]
        assert param_info.has_context is True
        assert param_info.has_parent is False
        assert param_info.has_ancestor_context is False
        assert len(param_info.loader_deps) == 1
        assert param_info.loader_deps[0][0] == "loader"

    async def test_resolver_uses_cached_meta(self):
        """Resolver should use cached metadata during traversal."""

        class CachedModel(BaseModel):
            name: str
            greeting: str = ""

            def resolve_greeting(self):
                return f"Hi, {self.name}"

        _class_meta_cache.pop(CachedModel, None)

        items = [CachedModel(name="A"), CachedModel(name="B"), CachedModel(name="C")]
        result = await Resolver().resolve(items)

        assert result[0].greeting == "Hi, A"
        assert result[1].greeting == "Hi, B"
        assert result[2].greeting == "Hi, C"
        # Meta should have been computed only once
        assert CachedModel in _class_meta_cache


# ──────────────────────────────────────────────────────────
# Issue 4: scan_expose/send_to caching
# ──────────────────────────────────────────────────────────


class TestContextScanCaching:
    def test_expose_cache_populated(self):
        """scan_expose_fields should cache results per class."""
        from typing import Annotated

        from nexusx.context import ExposeAs

        class ExposedModel(BaseModel):
            name: Annotated[str, ExposeAs("user_name")]

        _expose_cache.pop(ExposedModel, None)

        result1 = scan_expose_fields(ExposedModel)
        result2 = scan_expose_fields(ExposedModel)

        assert result1 == {"name": "user_name"}
        assert result1 is result2  # Same object from cache

    def test_send_to_cache_populated(self):
        """scan_send_to_fields should cache results per class."""
        from typing import Annotated

        from nexusx.context import SendTo

        class CollectedModel(BaseModel):
            owner: Annotated[str | None, SendTo("contributors")] = None

        _send_to_cache.pop(CollectedModel, None)

        result1 = scan_send_to_fields(CollectedModel)
        result2 = scan_send_to_fields(CollectedModel)

        assert result1 == {"owner": "contributors"}
        assert result1 is result2  # Same object from cache


# ──────────────────────────────────────────────────────────
# Issue 6: _extract_sort_field desc/asc
# ──────────────────────────────────────────────────────────


class TestExtractSortFieldDescAsc:
    def test_plain_column(self):
        """Plain column reference with .key attribute."""

        class FakeCol:
            key = "created_at"

        assert _extract_sort_field(FakeCol()) == "created_at"

    def test_desc_column(self):
        """desc(Column) should extract inner column key."""

        class FakeCol:
            key = "created_at"

        class FakeDesc:
            element = FakeCol()

        assert _extract_sort_field(FakeDesc()) == "created_at"

    def test_asc_column(self):
        """asc(Column) should extract inner column key."""

        class FakeCol:
            key = "updated_at"

        class FakeAsc:
            element = FakeCol()

        assert _extract_sort_field(FakeAsc()) == "updated_at"

    def test_desc_in_list(self):
        """desc(Column) wrapped in a list should work."""

        class FakeCol:
            key = "id"

        class FakeDesc:
            element = FakeCol()

        assert _extract_sort_field([FakeDesc()]) == "id"

    def test_invalid_order_by(self):
        """Non-column object should raise ValueError."""
        with pytest.raises(ValueError, match="Unable to extract sort field"):
            _extract_sort_field("not_a_column")


# ──────────────────────────────────────────────────────────
# Issue 7: get_loader_by_name ambiguity warning
# ──────────────────────────────────────────────────────────


async def _noop_loader(keys):
    return [None] * len(keys)


class AmbigEntity1(SQLModel, table=True):
    __tablename__ = "ambig_entity_1"
    id: int | None = Field(default=None, primary_key=True)
    name: str = ""

    __relationships__ = [
        Relationship(
            fk="id", target=list["AmbigTarget"], name="items",
            loader=_noop_loader,
        )
    ]


class AmbigEntity2(SQLModel, table=True):
    __tablename__ = "ambig_entity_2"
    id: int | None = Field(default=None, primary_key=True)
    title: str = ""

    __relationships__ = [
        Relationship(
            fk="id", target=list["AmbigTarget"], name="items",
            loader=_noop_loader,
        )
    ]


class AmbigTarget(SQLModel, table=True):
    __tablename__ = "ambig_target"
    id: int | None = Field(default=None, primary_key=True)


class TestGetLoaderByNameAmbiguity:
    async def test_ambiguous_name_logs_warning(self, caplog):
        """get_loader_by_name should log a warning when name is ambiguous."""

        async def session_factory():
            pass  # Won't be called

        registry = ErManager(
            entities=[AmbigEntity1, AmbigEntity2, AmbigTarget],
            session_factory=session_factory,
        )

        with caplog.at_level(logging.WARNING, logger="nexusx.loader.registry"):
            loader = registry.get_loader_by_name("items")

        assert loader is not None
        assert "Ambiguous loader lookup" in caplog.text
        assert "items" in caplog.text

    async def test_unique_name_no_warning(self, caplog):
        """get_loader_by_name should not warn when name is unique."""

        async def session_factory():
            pass

        class UniqueEntity(SQLModel, table=True):
            __tablename__ = "unique_entity_test"
            id: int | None = Field(default=None, primary_key=True)
            __relationships__ = [
                Relationship(fk="id", target=list[AmbigTarget], name="unique_rel",
                             loader=_noop_loader)
            ]

        registry = ErManager(
            entities=[UniqueEntity, AmbigTarget],
            session_factory=session_factory,
        )

        with caplog.at_level(logging.WARNING, logger="nexusx.loader.registry"):
            loader = registry.get_loader_by_name("unique_rel")

        assert loader is not None
        assert "Ambiguous" not in caplog.text


# ──────────────────────────────────────────────────────────
# Issue 8: query_meta FK field lookup
# ──────────────────────────────────────────────────────────


class TestQueryMetaFKLookup:
    def test_fk_lookup_overrides_convention(self):
        """fk_lookup should use actual FK name instead of {rel}_id."""
        from nexusx.loader.query_meta import generate_query_meta_from_selection
        from nexusx.query_parser import FieldSelection

        class MyEntity(SQLModel, table=True):
            __tablename__ = "fk_lookup_entity"
            id: int | None = Field(default=None, primary_key=True)
            title: str = ""
            author_user_id: int = Field(foreign_key="user.id")
            # Note: FK is "author_user_id", NOT "author_id"

        sel = FieldSelection(
            name="root",
            sub_fields={
                "title": FieldSelection(name="title"),
                "author": FieldSelection(
                    name="author",
                    sub_fields={"id": FieldSelection(name="id")},
                ),
            },
        )

        # Without fk_lookup: would try "author_id" (wrong)
        meta_without = generate_query_meta_from_selection(sel, MyEntity)
        assert "author_user_id" not in meta_without["fields"]

        # With fk_lookup: uses actual FK name
        fk_lookup = {"author": "author_user_id"}
        meta_with = generate_query_meta_from_selection(sel, MyEntity, fk_lookup=fk_lookup)
        assert "author_user_id" in meta_with["fields"]
        assert "title" in meta_with["fields"]

    def test_fk_lookup_none_falls_back(self):
        """When fk_lookup is None, should fall back to {rel}_id convention."""
        from nexusx.loader.query_meta import generate_query_meta_from_selection
        from nexusx.query_parser import FieldSelection

        class ConventionEntity(SQLModel, table=True):
            __tablename__ = "convention_entity"
            id: int | None = Field(default=None, primary_key=True)
            name: str = ""
            owner_id: int = Field(foreign_key="user.id")

        sel = FieldSelection(
            name="root",
            sub_fields={
                "name": FieldSelection(name="name"),
                "owner": FieldSelection(
                    name="owner",
                    sub_fields={"id": FieldSelection(name="id")},
                ),
            },
        )

        meta = generate_query_meta_from_selection(sel, ConventionEntity, fk_lookup=None)
        assert "owner_id" in meta["fields"]

    def test_type_key_with_fk_lookup(self):
        """generate_type_key_from_selection should also use fk_lookup."""
        from nexusx.loader.query_meta import generate_type_key_from_selection
        from nexusx.query_parser import FieldSelection

        class TypeKeyEntity(SQLModel, table=True):
            __tablename__ = "type_key_entity"
            id: int | None = Field(default=None, primary_key=True)
            name: str = ""
            creator_ref: int = Field(foreign_key="user.id")

        sel = FieldSelection(
            name="root",
            sub_fields={
                "name": FieldSelection(name="name"),
                "creator": FieldSelection(
                    name="creator",
                    sub_fields={"id": FieldSelection(name="id")},
                ),
            },
        )

        # Without lookup: "creator_id" not in model_fields, so FK not included
        key_without = generate_type_key_from_selection(sel, TypeKeyEntity)
        assert key_without == frozenset({"name"})

        # With lookup: "creator_ref" IS in model_fields
        fk_lookup = {"creator": "creator_ref"}
        key_with = generate_type_key_from_selection(sel, TypeKeyEntity, fk_lookup=fk_lookup)
        assert "creator_ref" in key_with
        assert "name" in key_with


# ──────────────────────────────────────────────────────────
# Issue 9: DataLoader factory closures
# ──────────────────────────────────────────────────────────


class TestLoaderFactoryClosures:
    def test_closure_captures_correct_values(self):
        """Factory-created loaders should capture closure variables correctly."""
        from nexusx.loader.factories import create_many_to_one_loader

        class FakeTarget(SQLModel, table=True):
            __tablename__ = "closure_target"
            id: int | None = Field(default=None, primary_key=True)

        async def fake_session():
            pass

        loader_cls = create_many_to_one_loader(
            source_kls=FakeTarget,
            rel_name="test",
            target_kls=FakeTarget,
            target_remote_col_name="id",
            session_factory=fake_session,
        )

        # Loader class should not have leaked class attributes
        assert not hasattr(loader_cls, "target_kls")
        assert not hasattr(loader_cls, "target_remote_col_name")
        assert not hasattr(loader_cls, "session_factory")

    def test_multiple_loaders_independent(self):
        """Multiple loaders created by same factory should be independent."""
        from nexusx.loader.factories import create_one_to_many_loader

        class Target1(SQLModel, table=True):
            __tablename__ = "closure_target_1"
            id: int | None = Field(default=None, primary_key=True)

        class Target2(SQLModel, table=True):
            __tablename__ = "closure_target_2"
            id: int | None = Field(default=None, primary_key=True)

        async def session1():
            pass

        async def session2():
            pass

        loader1 = create_one_to_many_loader(
            source_kls=Target1, rel_name="a",
            target_kls=Target1, target_fk_col_name="id",
            session_factory=session1,
        )
        loader2 = create_one_to_many_loader(
            source_kls=Target2, rel_name="b",
            target_kls=Target2, target_fk_col_name="id",
            session_factory=session2,
        )

        # Should be different classes
        assert loader1 is not loader2
        assert loader1.__name__ != loader2.__name__
