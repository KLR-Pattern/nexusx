"""Tests for Loader refactor (Depends) and implicit auto-loading."""

from __future__ import annotations

from typing import Annotated

import pytest
from aiodataloader import DataLoader
from pydantic import BaseModel
from sqlmodel import Field, SQLModel, select

from nexusx import AutoLoad
from nexusx.loader.registry import ErManager
from nexusx.relationship import Relationship
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
    async def test_implicit_with_derived_scalar_post_field(self):
        """An auto-loaded relationship can feed a scalar post_* field.

        Mirrors cases like ``agent`` auto-loaded first, then ``agent_name``
        computed by ``post_agent_name()``.
        """

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
            owner_name: str | None = None

            def post_owner_name(self):
                return self.owner.name if self.owner else None

        async with session_factory() as session:
            tasks = (await session.exec(select(FixtureTask))).all()

        dtos = [TaskDTO(id=t.id, title=t.title, owner_id=t.owner_id) for t in tasks]
        result = await Resolver(registry).resolve(dtos)

        assert all(dto.owner is not None for dto in result)
        assert all(dto.owner_name == dto.owner.name for dto in result)

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


# ──────────────────────────────────────────────────────────
# Scalar-list custom relationship fields are auto-loaded
# ──────────────────────────────────────────────────────────


class TestAutoLoadScalarListField:
    """Scalar-list custom relationship fields auto-load like DTO-typed ones.

    A DTO field whose type is a primitive (e.g. ``list[int]``) and whose name
    matches a registered CUSTOM ``Relationship`` with the same primitive
    ``target`` is auto-loaded — no explicit ``resolve_*`` required. The
    explicit-resolve form in the second test documents the manual fallback.
    """

    async def test_custom_relationship_targeting_scalar_list_autoloads(self):
        """DTO ``ids: list[int]`` matching ``Relationship(target=list[int])`` should populate."""

        async def ids_loader(keys: list[int]) -> list[list[int]]:
            table = {1: [10, 20], 2: [30]}
            return [table.get(k, []) for k in keys]

        class ScalarEntity(SQLModel, table=True):
            __tablename__ = "scalar_list_autoload_entity"

            id: int | None = Field(default=None, primary_key=True)

            __relationships__ = [
                Relationship(
                    fk="id",
                    target=list[int],
                    name="ids",
                    loader=ids_loader,
                )
            ]

        registry = ErManager(
            entities=[ScalarEntity],
            session_factory=lambda: None,
        )

        class ScalarDTO(DefineSubset):
            __subset__ = (ScalarEntity, ("id",))
            ids: list[int] = []
            id_summaries: Annotated[list[int], AutoLoad("ids")] = []

        result = await Resolver(registry).resolve(
            [ScalarDTO(id=1), ScalarDTO(id=2)]
        )

        assert result[0].ids == [10, 20]
        assert result[1].ids == [30]
        assert result[0].id_summaries == [10, 20]
        assert result[1].id_summaries == [30]

    async def test_scalar_list_field_works_with_explicit_resolve(self):
        """Documented workaround: explicit ``resolve_*`` with ``Loader(callable)``."""

        async def ids_loader(keys: list[int]) -> list[list[int]]:
            table = {1: [10, 20], 2: [30]}
            return [table.get(k, []) for k in keys]

        class WorkaroundEntity(SQLModel, table=True):
            __tablename__ = "scalar_list_workaround_entity"

            id: int | None = Field(default=None, primary_key=True)

            __relationships__ = [
                Relationship(
                    fk="id",
                    target=list[int],
                    name="ids",
                    loader=ids_loader,
                )
            ]

        registry = ErManager(
            entities=[WorkaroundEntity],
            session_factory=lambda: None,
        )

        class WorkaroundDTO(DefineSubset):
            __subset__ = (WorkaroundEntity, ("id",))
            ids: list[int] = []

            def resolve_ids(self, loader=Loader(ids_loader)):
                return loader.load(self.id)

        result = await Resolver(registry).resolve(
            [WorkaroundDTO(id=1), WorkaroundDTO(id=2)]
        )

        assert result[0].ids == [10, 20]
        assert result[1].ids == [30]


# ──────────────────────────────────────────────────────────
# AutoLoad(origin=...) relationship override
# ──────────────────────────────────────────────────────────

class TestAutoLoadOriginOverride:
    """``AutoLoad(origin=...)`` must load the named relationship.

    ``AutoLoad`` accepts an ``origin`` argument documented as: "Override
    relationship name. Defaults to the field name." These tests pin that
    contract so a field whose name differs from the relationship can still
    auto-load.
    """

    @pytest.mark.usefixtures("test_db")
    async def test_origin_override_loads_when_field_name_differs(self):
        """A field named ``owner_summary`` with ``AutoLoad("owner")`` loads."""
        session_factory = get_test_session_factory()
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=session_factory,
        )

        class UserDTO(DefineSubset):
            __subset__ = (FixtureUser, ("id", "name"))

        class TaskDTO(DefineSubset):
            __subset__ = (FixtureTask, ("id", "title", "owner_id"))
            # Field name differs from the relationship name; origin overrides it.
            owner_summary: Annotated[UserDTO | None, AutoLoad("owner")] = None

        async with session_factory() as session:
            tasks = (await session.exec(select(FixtureTask))).all()

        dtos = [
            TaskDTO(id=t.id, title=t.title, owner_id=t.owner_id) for t in tasks
        ]
        result = await Resolver(registry).resolve(dtos)

        assert len(result) == 4
        assert all(dto.owner_summary is not None for dto in result)
        assert [dto.owner_summary.id for dto in result] == [task.owner_id for task in tasks]
        assert {dto.owner_summary.name for dto in result} == {"Alice", "Bob"}

    @pytest.mark.usefixtures("test_db")
    async def test_origin_defaults_to_field_name(self):
        """AutoLoad() uses the field name when origin is absent."""
        session_factory = get_test_session_factory()
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=session_factory,
        )

        class UserDTO(DefineSubset):
            __subset__ = (FixtureUser, ("id", "name"))

        class TaskDTO(DefineSubset):
            __subset__ = (FixtureTask, ("id", "title", "owner_id"))
            owner: Annotated[UserDTO | None, AutoLoad()] = None

        async with session_factory() as session:
            tasks = (await session.exec(select(FixtureTask))).all()

        dtos = [
            TaskDTO(id=t.id, title=t.title, owner_id=t.owner_id) for t in tasks
        ]
        result = await Resolver(registry).resolve(dtos)

        assert all(dto.owner is not None for dto in result)

    @pytest.mark.usefixtures("test_db")
    async def test_origin_override_loads_list_and_nested_relationships(self):
        """An aliased list loads its items and their nested relationships."""
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
            task_summaries: Annotated[list[TaskDTO], AutoLoad(origin="tasks")] = []

        async with session_factory() as session:
            sprints = (await session.exec(select(FixtureSprint))).all()
            tasks = (await session.exec(select(FixtureTask))).all()

        result = await Resolver(registry).resolve(
            [SprintDTO(id=sprint.id, name=sprint.name) for sprint in sprints]
        )

        assert len(result) == 2
        for sprint in result:
            expected_ids = {task.id for task in tasks if task.sprint_id == sprint.id}
            assert {task.id for task in sprint.task_summaries} == expected_ids
            assert all(task.owner.id == task.owner_id for task in sprint.task_summaries)

    @pytest.mark.usefixtures("test_db")
    @pytest.mark.parametrize("split_loader_by_type", [False, True])
    async def test_origin_override_keeps_distinct_dto_projections(self, split_loader_by_type):
        """Fields using one relationship can request different SQL columns."""
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=get_test_session_factory(),
            split_loader_by_type=split_loader_by_type,
        )

        class UserDTO(DefineSubset):
            __subset__ = (FixtureUser, ("id", "name"))

        class UserContactDTO(DefineSubset):
            __subset__ = (FixtureUser, ("id", "email"))

        class TaskDTO(DefineSubset):
            __subset__ = (FixtureTask, ("id", "title", "owner_id"))
            owner: UserDTO | None = None
            owner_contact: Annotated[UserContactDTO | None, AutoLoad("owner")] = None

        result = await Resolver(registry).resolve(TaskDTO(id=1, title="Test", owner_id=1))

        assert result.owner.name == "Alice"
        assert result.owner_contact.email == "alice@test.com"
        assert result.owner.id == result.owner_contact.id == result.owner_id

    @pytest.mark.usefixtures("test_db")
    async def test_manual_resolve_takes_priority_over_origin(self):
        """A resolve method still overrides an explicit AutoLoad marker."""
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=get_test_session_factory(),
        )

        class UserDTO(DefineSubset):
            __subset__ = (FixtureUser, ("id", "name"))

        class TaskDTO(DefineSubset):
            __subset__ = (FixtureTask, ("id", "title", "owner_id"))
            owner_summary: Annotated[UserDTO | None, AutoLoad("owner")] = None

            def resolve_owner_summary(self):
                return UserDTO(id=999, name="Manual Override")

        result = await Resolver(registry).resolve(TaskDTO(id=1, title="Test", owner_id=1))

        assert result.owner_summary.id == 999
        assert result.owner_summary.name == "Manual Override"

    @pytest.mark.usefixtures("test_db")
    @pytest.mark.parametrize("origin", ["missing", "sprint"])
    async def test_invalid_origin_does_not_fall_back_to_field_name(self, origin):
        """An unknown or incompatible origin does not use the implicit relationship."""
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=get_test_session_factory(),
        )

        class UserDTO(DefineSubset):
            __subset__ = (FixtureUser, ("id", "name"))

        class TaskDTO(DefineSubset):
            __subset__ = (FixtureTask, ("id", "title", "owner_id", "sprint_id"))
            owner: Annotated[UserDTO | None, AutoLoad(origin=origin)] = None

        result = await Resolver(registry).resolve(
            TaskDTO(id=1, title="Test", owner_id=1, sprint_id=1)
        )

        assert result.owner is None
