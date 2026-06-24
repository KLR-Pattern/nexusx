"""Tests for ErManager — relationship discovery and DataLoader management."""

from typing import Optional

import pytest
from sqlmodel import Field, Relationship, SQLModel

from nexusx.loader.registry import ErManager
from nexusx.relationship import Relationship as NxRelationship
from tests.conftest import FixtureSprint, FixtureTask, FixtureUser, get_test_session_factory

# ──────────────────────────────────────────────────────────
# Test entities for custom relationships
# ──────────────────────────────────────────────────────────


async def _dummy_loader(keys):
    return keys


class RegTag(SQLModel, table=True):
    __tablename__ = "reg_test_tag"

    id: int | None = Field(default=None, primary_key=True)
    name: str


class RegPost(SQLModel, table=True):
    __tablename__ = "reg_test_post"

    id: int | None = Field(default=None, primary_key=True)
    title: str

    __relationships__ = [
        NxRelationship(
            fk="id",
            target=list[RegTag],
            name="tags",
            loader=_dummy_loader,
        )
    ]


class ConflictPost(SQLModel, table=True):
    __tablename__ = "reg_test_conflict_post"

    id: int | None = Field(default=None, primary_key=True)
    title: str

    __relationships__ = [
        NxRelationship(fk="id", target=list[RegTag], name="tags", loader=_dummy_loader),
        NxRelationship(fk="id", target=list[RegTag], name="tags", loader=_dummy_loader),
    ]


# ──────────────────────────────────────────────────────────
# Entities for pagination warn-skip (no order_by on the list side)
# ──────────────────────────────────────────────────────────


class _PagBase(SQLModel):
    pass


class _PagChild(_PagBase, table=True):
    __tablename__ = "reg_test_pag_child"

    id: int | None = Field(default=None, primary_key=True)
    parent_id: int = Field(foreign_key="reg_test_pag_parent.id")
    parent: Optional["_PagParent"] = Relationship(back_populates="children")


class _PagParent(_PagBase, table=True):
    __tablename__ = "reg_test_pag_parent"

    id: int | None = Field(default=None, primary_key=True)
    # Deliberately no order_by — stands in for audit logs / append-only /
    # config tables that have no natural sort key.
    children: list["_PagChild"] = Relationship(back_populates="parent")


# ──────────────────────────────────────────────────────────
# Tests: relationship discovery
# ──────────────────────────────────────────────────────────


class TestErManagerDiscovery:
    def test_discovers_many_to_one_relationship(self):
        """Registry should discover M2O relationships (FixtureTask.owner)."""
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=get_test_session_factory(),
        )

        task_rels = registry.get_relationships(FixtureTask)
        assert "owner" in task_rels
        owner_rel = task_rels["owner"]
        assert owner_rel.direction == "MANYTOONE"
        assert owner_rel.is_list is False
        assert owner_rel.target_entity is FixtureUser

    def test_discovers_one_to_many_relationship(self):
        """Registry should discover O2M relationships (FixtureSprint.tasks)."""
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=get_test_session_factory(),
        )

        sprint_rels = registry.get_relationships(FixtureSprint)
        assert "tasks" in sprint_rels
        tasks_rel = sprint_rels["tasks"]
        assert tasks_rel.direction == "ONETOMANY"
        assert tasks_rel.is_list is True
        assert tasks_rel.target_entity is FixtureTask

    def test_get_relationship_returns_none_for_unknown(self):
        """Registry should return None for unknown relationship name."""
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=get_test_session_factory(),
        )

        assert registry.get_relationship(FixtureTask, "nonexistent") is None

    def test_get_relationships_for_unknown_entity(self):
        """Registry should return empty dict for unregistered entity."""

        class UnknownEntity(SQLModel, table=False):
            id: int

        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=get_test_session_factory(),
        )

        assert registry.get_relationships(UnknownEntity) == {}


class TestErManagerCache:
    async def test_get_loader_caches_instance(self):
        """get_loader should return same instance for same loader class."""
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=get_test_session_factory(),
        )

        task_rels = registry.get_relationships(FixtureTask)
        owner_rel = task_rels["owner"]

        loader1 = registry.get_loader(owner_rel.loader)
        loader2 = registry.get_loader(owner_rel.loader)

        assert loader1 is loader2

    async def test_clear_cache_resets_instances(self):
        """clear_cache should remove all cached loader instances."""
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=get_test_session_factory(),
        )

        task_rels = registry.get_relationships(FixtureTask)
        owner_rel = task_rels["owner"]

        loader1 = registry.get_loader(owner_rel.loader)
        registry.clear_cache()
        loader2 = registry.get_loader(owner_rel.loader)

        assert loader1 is not loader2


class TestErManagerPagination:
    def test_warn_skip_when_list_relationship_lacks_order_by(self, caplog):
        """enable_pagination with a no-order_by list should warn, not raise.

        Regression for issue #83: all-or-nothing startup check blocked apps
        whose audit-log / append-only / config list relationships have no
        natural sort key. The relationship must still register a regular
        loader so it resolves as ``[T]!``; only the page_loader is omitted.
        """
        import logging

        with caplog.at_level(logging.WARNING, logger="nexusx.loader.registry"):
            registry = ErManager(
                entities=[_PagParent, _PagChild],
                session_factory=get_test_session_factory(),
                enable_pagination=True,
            )

        # Did not raise, and the no-order_by list falls back to regular loader.
        children_rel = registry.get_relationship(_PagParent, "children")
        assert children_rel is not None
        assert children_rel.page_loader is None
        assert children_rel.loader is not None

        # A single WARNING was emitted naming the skipped relationship.
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "_PagParent.children" in warnings[0].getMessage()
        assert "order_by" in warnings[0].getMessage()

    def test_no_warning_when_all_list_relationships_have_order_by(self, caplog):
        """Sanity: when every list relationship has order_by, no WARNING."""
        import logging

        with caplog.at_level(logging.WARNING, logger="nexusx.loader.registry"):
            ErManager(
                entities=[FixtureUser, FixtureSprint, FixtureTask],
                session_factory=get_test_session_factory(),
                enable_pagination=True,
            )

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings == []


class TestErManagerCustomRelationships:
    def test_custom_relationship_registered(self):
        """Custom __relationships__ should be registered."""
        registry = ErManager(
            entities=[RegPost, RegTag],
            session_factory=lambda: None,
        )

        post_rels = registry.get_relationships(RegPost)
        assert "tags" in post_rels
        tags_rel = post_rels["tags"]
        assert tags_rel.direction == "CUSTOM"
        assert tags_rel.is_list is True

    def test_name_conflict_raises(self):
        """Duplicate relationship name should raise ValueError."""
        with pytest.raises(ValueError, match="conflicts"):
            ErManager(
                entities=[ConflictPost, RegTag],
                session_factory=lambda: None,
            )

    async def test_get_loader_by_name(self):
        """get_loader_by_name should find loader across all entities."""
        registry = ErManager(
            entities=[RegPost, RegTag],
            session_factory=lambda: None,
        )

        loader = registry.get_loader_by_name("tags")
        assert loader is not None

    def test_get_loader_by_name_not_found(self):
        """get_loader_by_name should return None for unknown name."""
        registry = ErManager(
            entities=[RegPost, RegTag],
            session_factory=lambda: None,
        )

        loader = registry.get_loader_by_name("nonexistent")
        assert loader is None

    async def test_get_loader_for_entity(self):
        """get_loader_for_entity should return loader for specific entity."""
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=get_test_session_factory(),
        )

        loader = registry.get_loader_for_entity(FixtureTask, "owner")
        assert loader is not None

    def test_get_loader_for_entity_not_found(self):
        """get_loader_for_entity should return None for unknown entity/rel."""
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=get_test_session_factory(),
        )

        assert registry.get_loader_for_entity(FixtureTask, "nonexistent") is None


# ──────────────────────────────────────────────────────────
# P0/P1: ErManager init validation, create_resolver, pagination edges
# ──────────────────────────────────────────────────────────


class TestErManagerInitValidation:
    def test_base_and_entities_mutually_exclusive(self):
        """Passing both base and entities should raise ValueError."""
        with pytest.raises(ValueError, match="mutually exclusive"):
            ErManager(
                base=SQLModel,
                entities=[FixtureUser],
                session_factory=get_test_session_factory(),
            )

    def test_neither_base_nor_entities_raises(self):
        """Passing neither base nor entities should raise ValueError."""
        with pytest.raises(ValueError, match="Either base or entities"):
            ErManager(
                session_factory=get_test_session_factory(),
            )

    def test_base_mode_creates_registry(self):
        """base mode should create a working registry via EntityDiscovery."""
        from nexusx.discovery import EntityDiscovery

        # Verify EntityDiscovery works (which base mode uses internally)
        discovery = EntityDiscovery(SQLModel)
        entities = discovery.discover(include_all=True)
        # Should find at least the FixtureBase entities
        assert len(entities) > 0


class TestCreateResolver:
    def test_create_resolver_returns_class(self):
        """create_resolver should return a Resolver class, not instance."""
        from nexusx.resolver import Resolver

        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=get_test_session_factory(),
        )
        ResolverCls = registry.create_resolver()
        assert isinstance(ResolverCls, type)
        assert issubclass(ResolverCls, Resolver)
        assert ResolverCls.__name__ == "Resolver"

    def test_create_resolver_instance_has_registry(self):
        """BoundResolver instances should have the ErManager as registry."""
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=get_test_session_factory(),
        )
        ResolverCls = registry.create_resolver()
        instance = ResolverCls()
        assert instance._registry is registry

    async def test_create_resolver_forwards_loader_instances(self):
        """``loader_instances`` must flow through ``create_resolver()`` to the underlying Resolver."""
        from aiodataloader import DataLoader

        class StubLoader(DataLoader):
            async def batch_load_fn(self, keys):
                return keys

        supplied = StubLoader()
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=get_test_session_factory(),
        )
        ResolverCls = registry.create_resolver()
        instance = ResolverCls(loader_instances={StubLoader: supplied})

        # Supplied instance is forwarded by reference.
        assert instance._loader_instances[StubLoader] is supplied


class TestPaginationValidation:
    def test_empty_order_by_raises(self):
        """Empty order_by list should raise ValueError."""
        from nexusx.loader.registry import _extract_sort_field

        with pytest.raises(ValueError, match="order_by cannot be empty"):
            _extract_sort_field([])

    def test_multi_column_order_by_raises(self):
        """Multi-column order_by should raise ValueError."""
        from nexusx.loader.registry import _extract_sort_field

        with pytest.raises(ValueError, match="Only single-column"):
            _extract_sort_field([FixtureUser.id, FixtureUser.name])

    def test_pagination_without_order_by_on_relationship(self, caplog):
        """enable_pagination warns (does not raise) when a list rel lacks order_by.

        Issue #83: warn-skip replaces the all-or-nothing startup check so apps
        with audit-log / append-only list relationships aren't blocked.
        """
        import logging
        from unittest.mock import MagicMock

        from nexusx.loader.registry import RelationshipInfo

        registry = ErManager.__new__(ErManager)
        registry._session_factory = get_test_session_factory()
        registry._enable_pagination = True
        registry._split_mode = False
        registry._loader_instances = {}

        # Create a fake list relationship without page_loader
        rel_info = MagicMock(spec=RelationshipInfo)
        rel_info.is_list = True
        rel_info.page_loader = None
        rel_info.direction = "ONETOMANY"
        rel_info.name = "items"

        mock_entity = MagicMock()
        mock_entity.__name__ = "TestEntity"
        registry._registry = {mock_entity: {"items": rel_info}}

        with caplog.at_level(logging.WARNING, logger="nexusx.loader.registry"):
            registry._validate_pagination()  # must not raise

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        msg = warnings[0].getMessage()
        assert "TestEntity.items" in msg
        assert "order_by" in msg

    def test_pagination_skips_custom_relationships(self, caplog):
        """CUSTOM relationships neither raise nor emit a warning."""
        import logging
        from unittest.mock import MagicMock

        from nexusx.loader.registry import RelationshipInfo

        registry = ErManager.__new__(ErManager)
        registry._session_factory = get_test_session_factory()
        registry._enable_pagination = True
        registry._split_mode = False
        registry._loader_instances = {}

        rel_info = MagicMock(spec=RelationshipInfo)
        rel_info.is_list = True
        rel_info.page_loader = None
        rel_info.direction = "CUSTOM"
        rel_info.name = "custom_items"

        mock_entity = MagicMock()
        mock_entity.__name__ = "TestEntity"
        registry._registry = {mock_entity: {"custom_items": rel_info}}

        with caplog.at_level(logging.WARNING, logger="nexusx.loader.registry"):
            registry._validate_pagination()  # must not raise

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings == []
