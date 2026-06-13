"""Tests for Loader refactor (Depends) and implicit auto-loading."""

from __future__ import annotations

import pytest
from aiodataloader import DataLoader
from pydantic import BaseModel
from sqlmodel import select

from nexusx.loader.registry import ErManager
from nexusx.resolver import Depends, Loader, Resolver
from nexusx.subset import DefineSubset
from tests.conftest import (
    FixtureSprint,
    FixtureTask,
    FixtureUser,
    get_test_session_factory,
)

# ──────────────────────────────────────────────────────────
# Test: Loader(Depends) refactored to support multiple types
# ──────────────────────────────────────────────────────────

class TestLoaderDepends:
    def test_loader_with_none(self):
        """Loader(None) should return Depends with None dependency."""
        dep = Loader(None)
        assert isinstance(dep, Depends)
        assert dep.dependency is None

    def test_loader_with_class(self):
        """Loader(DataLoaderClass) should return Depends with class."""

        class MyLoader(DataLoader):
            async def batch_load_fn(self, keys):
                return [k * 2 for k in keys]

        dep = Loader(MyLoader)
        assert isinstance(dep, Depends)
        assert dep.dependency is MyLoader

    def test_loader_with_function(self):
        """Loader(fn) should return Depends with function."""

        async def my_batch_fn(keys):
            return keys

        dep = Loader(my_batch_fn)
        assert isinstance(dep, Depends)
        assert dep.dependency is my_batch_fn


class TestLoaderWithFunction:
    @pytest.mark.usefixtures("test_db")
    async def test_loader_with_async_batch_fn(self):
        """Loader(async_fn) should wrap function in DataLoader."""

        async def greeting_loader(names):
            return [f"Hello, {name}!" for name in names]

        class Model(BaseModel):
            name: str
            greeting: str = ""

            def resolve_greeting(self, loader=Loader(greeting_loader)):
                return loader.load(self.name)

        model = Model(name="Alice")
        result = await Resolver().resolve(model)

        assert result.greeting == "Hello, Alice!"

    @pytest.mark.usefixtures("test_db")
    async def test_loader_with_dataclass_caching(self):
        """Same function should return same DataLoader instance."""

        call_count = 0

        async def count_loader(keys):
            nonlocal call_count
            call_count += 1
            return [k * 2 for k in keys]

        class Model(BaseModel):
            val: int
            doubled: int = 0

            def resolve_doubled(self, loader=Loader(count_loader)):
                return loader.load(self.val)

        models = [Model(val=1), Model(val=2), Model(val=3)]
        await Resolver().resolve(models)

        # Should batch all 3 into a single call
        assert call_count == 1


class TestLoaderWithDataLoaderClass:
    @pytest.mark.usefixtures("test_db")
    async def test_loader_with_dataloader_subclass(self):
        """Loader(DataLoaderClass) should instantiate and use the class."""

        class ReverseLoader(DataLoader):
            async def batch_load_fn(self, keys):
                return [k[::-1] for k in keys]

        class Model(BaseModel):
            word: str
            reversed: str = ""

            def resolve_reversed(self, loader=Loader(ReverseLoader)):
                return loader.load(self.word)

        model = Model(word="hello")
        result = await Resolver().resolve(model)

        assert result.reversed == "olleh"

    @pytest.mark.usefixtures("test_db")
    async def test_loader_with_dataloader_class_batching(self):
        """DataLoader subclass should batch multiple requests."""

        call_count = 0

        class CountingLoader(DataLoader):
            async def batch_load_fn(self, keys):
                nonlocal call_count
                call_count += 1
                return [k + 10 for k in keys]

        class Model(BaseModel):
            val: int
            result: int = 0

            def resolve_result(self, loader=Loader(CountingLoader)):
                return loader.load(self.val)

        models = [Model(val=1), Model(val=2), Model(val=3)]
        await Resolver().resolve(models)

        assert call_count == 1
        assert models[0].result == 11
        assert models[1].result == 12
        assert models[2].result == 13


# ──────────────────────────────────────────────────────────
# Test: Implicit auto-loading
# ──────────────────────────────────────────────────────────

class TestImplicitAutoLoad:
    @pytest.mark.usefixtures("test_db")
    async def test_implicit_many_to_one(self):
        """Fields matching a relationship name should auto-load."""

        session_factory = get_test_session_factory()
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=session_factory,
        )

        class UserDTO(DefineSubset):
            __subset__ = (FixtureUser, ("id", "name"))

        class TaskDTO(DefineSubset):
            __subset__ = (FixtureTask, ("id", "title", "owner_id"))
            # Field name 'owner' matches Task.owner relationship → auto-loaded
            owner: UserDTO | None = None

        async with session_factory() as session:
            tasks = (await session.exec(select(FixtureTask))).all()

        dtos = [
            TaskDTO(id=t.id, title=t.title, owner_id=t.owner_id) for t in tasks
        ]
        result = await Resolver(registry).resolve(dtos)

        assert all(dto.owner is not None for dto in result)
        owner_names = {dto.owner.name for dto in result}
        assert "Alice" in owner_names
        assert "Bob" in owner_names

    @pytest.mark.usefixtures("test_db")
    async def test_implicit_one_to_many(self):
        """One-to-many fields matching relationship name should auto-load."""

        session_factory = get_test_session_factory()
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=session_factory,
        )

        class UserDTO(DefineSubset):
            __subset__ = (FixtureUser, ("id", "name"))

        class TaskDTO(DefineSubset):
            __subset__ = (FixtureTask, ("id", "title", "owner_id"))
            owner: UserDTO | None = None

        class SprintDTO(DefineSubset):
            __subset__ = (FixtureSprint, ("id", "name"))
            tasks: list[TaskDTO] = []

        async with session_factory() as session:
            sprints = (await session.exec(select(FixtureSprint))).all()

        dtos = [SprintDTO(id=s.id, name=s.name) for s in sprints]
        result = await Resolver(registry).resolve(dtos)

        assert len(result[0].tasks) == 2
        assert len(result[1].tasks) == 2

        # Nested implicit loading: task owners should also be loaded
        assert all(t.owner is not None for t in result[0].tasks)

    @pytest.mark.usefixtures("test_db")
    async def test_implicit_with_post_methods(self):
        """Implicit auto-load + post_* should work together."""

        session_factory = get_test_session_factory()
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=session_factory,
        )

        class UserDTO(DefineSubset):
            __subset__ = (FixtureUser, ("id", "name"))

        class TaskDTO(DefineSubset):
            __subset__ = (FixtureTask, ("id", "title", "owner_id"))
            owner: UserDTO | None = None

        class SprintDTO(DefineSubset):
            __subset__ = (FixtureSprint, ("id", "name"))
            tasks: list[TaskDTO] = []
            task_count: int = 0

            def post_task_count(self):
                return len(self.tasks)

        async with session_factory() as session:
            sprints = (await session.exec(select(FixtureSprint))).all()

        dtos = [SprintDTO(id=s.id, name=s.name) for s in sprints]
        result = await Resolver(registry).resolve(dtos)

        assert result[0].task_count == 2
        assert result[1].task_count == 2

    @pytest.mark.usefixtures("test_db")
    async def test_implicit_does_not_trigger_for_non_relationship_fields(self):
        """Fields that don't match a relationship should NOT auto-load."""

        session_factory = get_test_session_factory()
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=session_factory,
        )

        class UserDTO(DefineSubset):
            __subset__ = (FixtureUser, ("id", "name"))

        class TaskDTO(DefineSubset):
            __subset__ = (FixtureTask, ("id", "title", "owner_id"))
            # 'assignee' does NOT match any relationship on FixtureTask
            assignee: UserDTO | None = None

        async with session_factory() as session:
            tasks = (await session.exec(select(FixtureTask))).all()

        dtos = [
            TaskDTO(id=t.id, title=t.title, owner_id=t.owner_id) for t in tasks
        ]
        result = await Resolver(registry).resolve(dtos)

        assert all(dto.assignee is None for dto in result)

    @pytest.mark.usefixtures("test_db")
    async def test_manual_resolve_takes_priority(self):
        """Manual resolve_* method should take priority over implicit auto-load."""

        session_factory = get_test_session_factory()
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=session_factory,
        )

        class UserDTO(DefineSubset):
            __subset__ = (FixtureUser, ("id", "name"))

        class TaskDTO(DefineSubset):
            __subset__ = (FixtureTask, ("id", "title", "owner_id"))
            owner: UserDTO | None = None

            # Manual resolve overrides implicit auto-load
            def resolve_owner(self):
                return UserDTO(id=999, name="Manual Override")

        async with session_factory() as session:
            tasks = (await session.exec(select(FixtureTask))).all()

        dtos = [
            TaskDTO(id=t.id, title=t.title, owner_id=t.owner_id) for t in tasks
        ]
        result = await Resolver(registry).resolve(dtos)

        assert all(dto.owner.name == "Manual Override" for dto in result)

    @pytest.mark.usefixtures("test_db")
    async def test_implicit_with_nonexistent_fk(self):
        """Implicit auto-load should handle non-existent FK value gracefully."""

        session_factory = get_test_session_factory()
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=session_factory,
        )

        class UserDTO(DefineSubset):
            __subset__ = (FixtureUser, ("id", "name"))

        class TaskDTO(DefineSubset):
            __subset__ = (FixtureTask, ("id", "title", "owner_id"))
            owner: UserDTO | None = None

        dto = TaskDTO(id=99, title="Orphan", owner_id=9999)
        result = await Resolver(registry).resolve(dto)

        assert result.owner is None

    @pytest.mark.usefixtures("test_db")
    async def test_incompatible_type_not_auto_loaded(self):
        """Fields with incompatible DTO types should NOT be auto-loaded."""

        session_factory = get_test_session_factory()
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=session_factory,
        )

        class SprintDTO(DefineSubset):
            __subset__ = (FixtureSprint, ("id", "name"))

        class TaskDTO(DefineSubset):
            __subset__ = (FixtureTask, ("id", "title", "owner_id"))
            # 'owner' matches Task.owner relationship (target=FixtureUser),
            # but SprintDTO is a subset of FixtureSprint, NOT FixtureUser.
            # Should NOT be auto-loaded.
            owner: SprintDTO | None = None

        async with session_factory() as session:
            tasks = (await session.exec(select(FixtureTask))).all()

        dtos = [
            TaskDTO(id=t.id, title=t.title, owner_id=t.owner_id) for t in tasks
        ]
        result = await Resolver(registry).resolve(dtos)

        # owner should remain None — incompatible type skipped
        assert all(dto.owner is None for dto in result)


class TestAutoLoadSubsetFields:
    def test_subset_fields_stored(self):
        """DefineSubset should store __subset_fields__."""

        class UserDTO(DefineSubset):
            __subset__ = (FixtureUser, ("id", "name"))

        assert hasattr(UserDTO, "__subset_fields__")
        assert UserDTO.__subset_fields__ == ["id", "name"]

    def test_subset_fields_includes_fk(self):
        """__subset_fields__ should include FK fields."""

        class TaskDTO(DefineSubset):
            __subset__ = (FixtureTask, ("id", "title", "owner_id"))

        assert "owner_id" in TaskDTO.__subset_fields__

    def test_subset_fields_includes_auto_fks(self):
        """__subset_fields__ should include auto-included PK and FK fields."""

        class TaskDTO(DefineSubset):
            __subset__ = (FixtureTask, ("id", "title"))

        assert "owner_id" in TaskDTO.__subset_fields__
        assert "sprint_id" in TaskDTO.__subset_fields__
        # Auto-included FK fields are tracked in __subset_auto_excluded__
        assert "owner_id" in TaskDTO.__subset_auto_excluded__
