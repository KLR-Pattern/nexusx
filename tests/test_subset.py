"""Tests for DefineSubset — independent DTO layer from SQLModel entities."""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import BaseModel
from sqlmodel import Field, SQLModel

from nexusx.context import scan_expose_fields
from nexusx.subset import (
    SUBSET_REFERENCE,
    DefineSubset,
    SubsetConfig,
    get_subset_source,
)
from tests.conftest import FixtureSprint, FixtureTask, FixtureUser, get_test_session_factory

# ──────────────────────────────────────────────────────────
# Test entities
# ──────────────────────────────────────────────────────────

class SampleUser(SQLModel, table=False):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str


class SamplePost(SQLModel, table=False):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    content: str
    author_id: int = Field(foreign_key="sample_user.id")


# ──────────────────────────────────────────────────────────
# Test: basic field selection
# ──────────────────────────────────────────────────────────


class TestDefineSubsetBasic:
    def test_subset_creates_pydantic_model(self):
        """DefineSubset should create a pure Pydantic BaseModel, not SQLModel."""

        class UserSummary(DefineSubset):
            __subset__ = (SampleUser, ("id", "name"))

        assert issubclass(UserSummary, BaseModel)
        # Should NOT be a SQLModel with table=True
        assert not issubclass(UserSummary, SQLModel) or not getattr(
            UserSummary, "__tablename__", None
        )

    def test_subset_only_includes_selected_fields(self):
        """Only selected fields should appear in the DTO."""

        class UserSummary(DefineSubset):
            __subset__ = (SampleUser, ("id", "name"))

        assert "id" in UserSummary.model_fields
        assert "name" in UserSummary.model_fields
        assert "email" not in UserSummary.model_fields

    def test_subset_model_validate(self):
        """DTO should be creatable from source entity via model_validate."""

        class UserSummary(DefineSubset):
            __subset__ = (SampleUser, ("id", "name"))

        user = SampleUser(id=1, name="Alice", email="alice@test.com")
        dto = UserSummary.model_validate(user)

        assert dto.id == 1
        assert dto.name == "Alice"
        # email should not be present (or None)
        assert not hasattr(dto, "email") or dto.email is None

    def test_subset_source_registration(self):
        """Source entity should be registered in the subset registry."""

        class UserSummary(DefineSubset):
            __subset__ = (SampleUser, ("id", "name"))

        assert get_subset_source(UserSummary) is SampleUser
        assert getattr(UserSummary, SUBSET_REFERENCE, None) is SampleUser

    def test_subset_preserves_field_types(self):
        """Field types should be preserved from the source entity."""

        class UserSummary(DefineSubset):
            __subset__ = (SampleUser, ("id", "name"))

        assert UserSummary.model_fields["id"].annotation == int | None
        assert UserSummary.model_fields["name"].annotation == str  # noqa: E721


# ──────────────────────────────────────────────────────────
# Test: FK field handling
# ──────────────────────────────────────────────────────────

class TestDefineSubsetFK:
    def test_fk_field_visible_when_explicitly_declared(self):
        """FK fields explicitly declared in fields should be visible in serialization."""

        class PostSummary(DefineSubset):
            __subset__ = (SamplePost, ("id", "title", "author_id"))

        assert "author_id" in PostSummary.model_fields
        # Explicitly declared FK should NOT be excluded
        assert PostSummary.model_fields["author_id"].exclude is not True

    def test_fk_field_available_and_visible(self):
        """FK fields explicitly declared should be accessible and appear in serialization."""

        class PostSummary(DefineSubset):
            __subset__ = (SamplePost, ("id", "title", "author_id"))

        post = SamplePost(id=1, title="Hello", content="World", author_id=42)
        dto = PostSummary.model_validate(post)

        # Internal access works
        assert dto.author_id == 42
        # Explicitly declared FK is also visible in serialization
        data = dto.model_dump()
        assert "author_id" in data
        assert data["author_id"] == 42

    def test_fk_auto_included_when_not_in_fields(self):
        """FK fields NOT in fields list are auto-included (with exclude=True)
        so Resolver can use them as DataLoader keys for relationship loading.
        """

        class PostSummary(DefineSubset):
            __subset__ = (SamplePost, ("id", "title"))

        # FK is auto-included but excluded from serialization
        assert "author_id" in PostSummary.model_fields
        dto = PostSummary(id=1, title="Hello")
        assert dto.author_id is None
        dumped = dto.model_dump()
        assert "author_id" not in dumped


# ──────────────────────────────────────────────────────────
# Test: extra fields
# ──────────────────────────────────────────────────────────

class TestDefineSubsetExtraFields:
    def test_extra_field_declaration(self):
        """Extra fields can be declared in the DefineSubset class body."""

        class UserSummary(DefineSubset):
            __subset__ = (SampleUser, ("id", "name"))
            display_name: str = ""

        assert "display_name" in UserSummary.model_fields
        dto = UserSummary(id=1, name="Alice", display_name="Alice (Admin)")
        assert dto.display_name == "Alice (Admin)"

    def test_extra_field_with_none_default(self):
        """Extra fields with Optional type and None default."""

        class UserSummary(DefineSubset):
            __subset__ = (SampleUser, ("id", "name"))
            nickname: str | None = None

        dto = UserSummary(id=1, name="Alice")
        assert dto.nickname is None

    def test_subset_field_reannotation_allowed(self):
        """Subset fields can be re-annotated with metadata (e.g., ExposeAs)."""


        from nexusx.context import ExposeAs

        class ReAnnotatedSubset(DefineSubset):
            __subset__ = (SampleUser, ("id", "name"))
            name: Annotated[str, ExposeAs("user_name")]

        # ExposeAs metadata should be present on the 'name' field
        expose = scan_expose_fields(ReAnnotatedSubset)
        assert expose == {"name": "user_name"}

        # Field should still work normally
        instance = ReAnnotatedSubset(id=1, name="test")
        assert instance.name == "test"


# ──────────────────────────────────────────────────────────
# Test: validation errors
# ──────────────────────────────────────────────────────────

class TestDefineSubsetValidation:
    def test_missing_subset_definition(self):
        """Class without __subset__ should raise ValueError."""

        with pytest.raises(ValueError, match="must define"):

            class BadSubset(DefineSubset):
                pass

    def test_invalid_field_name(self):
        """Non-existent field should raise AttributeError."""

        with pytest.raises(AttributeError, match="does not exist"):

            class BadSubset(DefineSubset):
                __subset__ = (SampleUser, ("id", "nonexistent"))

    def test_non_string_field_name(self):
        """Non-string field name should raise TypeError."""

        with pytest.raises(TypeError, match="must be a string"):

            class BadSubset(DefineSubset):
                __subset__ = (SampleUser, ("id", 123))  # type: ignore

    def test_duplicate_field_name(self):
        """Duplicate field name should raise ValueError."""

        with pytest.raises(ValueError, match="duplicate"):

            class BadSubset(DefineSubset):
                __subset__ = (SampleUser, ("id", "id"))

    def test_non_sqlmodel_entity(self):
        """Non-SQLModel entity should raise TypeError."""

        with pytest.raises(TypeError, match="SQLModel"):

            class BadSubset(DefineSubset):
                __subset__ = (str, ("upper",))  # type: ignore


# ──────────────────────────────────────────────────────────
# Test: methods
# ──────────────────────────────────────────────────────────

class TestDefineSubsetMethods:
    def test_post_method_attached(self):
        """post_* methods should be attached to the generated class."""

        class UserSummary(DefineSubset):
            __subset__ = (SampleUser, ("id", "name"))
            greeting: str = ""

            def post_greeting(self):
                return f"Hello, {self.name}!"

        assert hasattr(UserSummary, "post_greeting")
        dto = UserSummary(id=1, name="Alice")
        assert dto.post_greeting() == "Hello, Alice!"

    def test_resolve_method_attached(self):
        """resolve_* methods should be attached to the generated class."""

        class UserSummary(DefineSubset):
            __subset__ = (SampleUser, ("id", "name"))
            extra: str = ""

            def resolve_extra(self):
                return "resolved"

        assert hasattr(UserSummary, "resolve_extra")
        dto = UserSummary(id=1, name="Alice")
        assert dto.resolve_extra() == "resolved"


# ──────────────────────────────────────────────────────────
# Test: nested subsets
# ──────────────────────────────────────────────────────────

class TestDefineSubsetNested:
    def test_nested_subset_reference(self):
        """One DefineSubset can reference another as a field type."""

        class UserBrief(DefineSubset):
            __subset__ = (SampleUser, ("id", "name"))

        class PostBrief(DefineSubset):
            __subset__ = (SamplePost, ("id", "title"))
            author: UserBrief | None = None

        assert "author" in PostBrief.model_fields
        dto = PostBrief(id=1, title="Hello", author=UserBrief(id=42, name="Alice"))
        assert dto.author.name == "Alice"


# ──────────────────────────────────────────────────────────
# Test: SQLModel type validation for relationship fields
# ──────────────────────────────────────────────────────────


class TestSQLModelRelationshipTypeValidation:
    def test_raw_sqlmodel_type_on_relationship_raises(self):
        """Using a raw SQLModel entity as relationship field type should raise TypeError."""

        with pytest.raises(TypeError, match="must use a DTO type"):

            class TaskBad(DefineSubset):
                __subset__ = (FixtureTask, ("id", "title", "owner_id"))
                owner: FixtureUser | None = None  # raw SQLModel → error

    def test_sqlmodel_in_list_raises(self):
        """Using raw SQLModel in list[Entity] should raise TypeError."""

        with pytest.raises(TypeError, match="must use a DTO type"):

            class SprintBad(DefineSubset):
                __subset__ = (FixtureSprint, ("id", "name"))
                tasks: list[FixtureTask] = []  # raw SQLModel in list → error

    def test_sqlmodel_in_annotated_raises(self):
        """Using Annotated[Entity, ...] should raise TypeError."""

        from nexusx import SendTo

        with pytest.raises(TypeError, match="must use a DTO type"):

            class TaskBadAnnotated(DefineSubset):
                __subset__ = (FixtureTask, ("id", "title", "owner_id"))
                owner: Annotated[FixtureUser | None, SendTo("owners")] = None

    def test_dto_type_on_relationship_works(self):
        """Using a DefineSubset DTO type for relationship field should work fine."""

        class UserDTO(DefineSubset):
            __subset__ = (FixtureUser, ("id", "name"))

        class TaskDTO(DefineSubset):
            __subset__ = (FixtureTask, ("id", "title", "owner_id"))
            owner: UserDTO | None = None

        assert "owner" in TaskDTO.model_fields

    def test_dto_in_list_works(self):
        """Using list[DTO] for one-to-many relationship should work fine."""

        class TaskDTO(DefineSubset):
            __subset__ = (FixtureTask, ("id", "title", "owner_id"))

        class SprintDTO(DefineSubset):
            __subset__ = (FixtureSprint, ("id", "name"))
            tasks: list[TaskDTO] = []

        assert "tasks" in SprintDTO.model_fields

    def test_non_relationship_field_allows_any_type(self):
        """Fields that don't match a relationship name should accept any type."""

        class TaskDTO(DefineSubset):
            __subset__ = (FixtureTask, ("id", "title", "owner_id"))
            # 'assignee' does NOT match any relationship on FixtureTask
            # (relationships are 'owner' and 'sprint')
            assignee: FixtureUser | None = None

        # Should not raise — 'assignee' is not a relationship name
        assert "assignee" in TaskDTO.model_fields


# ──────────────────────────────────────────────────────────
# Test: SubsetConfig
# ──────────────────────────────────────────────────────────


class TestSubsetConfig:
    def test_config_with_fields(self):
        """SubsetConfig(fields=[...]) basic usage."""
        from nexusx.subset import SubsetConfig

        class UserSub(DefineSubset):
            __subset__ = SubsetConfig(
                kls=SampleUser,
                fields=["id", "name"],
            )

        assert "id" in UserSub.model_fields
        assert "name" in UserSub.model_fields
        assert "email" not in UserSub.model_fields
        dto = UserSub(id=1, name="Alice")
        assert dto.id == 1

    def test_config_with_omit_fields(self):
        """SubsetConfig(omit_fields=[...]) inverse selection."""

        from nexusx.subset import SubsetConfig

        class UserSub(DefineSubset):
            __subset__ = SubsetConfig(
                kls=SampleUser,
                omit_fields=["email"],
            )

        assert "id" in UserSub.model_fields
        assert "name" in UserSub.model_fields
        assert "email" not in UserSub.model_fields

    def test_config_with_fields_all(self):
        """SubsetConfig(fields='all') includes all fields."""

        from nexusx.subset import SubsetConfig

        class UserSub(DefineSubset):
            __subset__ = SubsetConfig(
                kls=SampleUser,
                fields="all",
            )

        assert set(UserSub.model_fields.keys()) == set(SampleUser.model_fields.keys())

    def test_config_with_omit_empty(self):
        """SubsetConfig(omit_fields=[]) is equivalent to fields='all'."""

        from nexusx.subset import SubsetConfig

        class UserSub(DefineSubset):
            __subset__ = SubsetConfig(
                kls=SampleUser,
                omit_fields=[],
            )

        assert set(UserSub.model_fields.keys()) == set(SampleUser.model_fields.keys())

    def test_config_with_excluded_fields(self):
        """excluded_fields should set exclude=True and hide from serialization."""

        from nexusx.subset import SubsetConfig

        class UserSub(DefineSubset):
            __subset__ = SubsetConfig(
                kls=SampleUser,
                fields=["id", "name", "email"],
                excluded_fields=["email"],
            )

        dto = UserSub(id=1, name="Alice", email="alice@test.com")
        assert dto.email == "alice@test.com"
        assert UserSub.model_fields["email"].exclude is True
        assert "email" not in dto.model_dump()

    def test_config_with_expose_as(self):
        """expose_as should add ExposeInfo metadata to fields."""

        from nexusx.subset import SubsetConfig

        class UserSub(DefineSubset):
            __subset__ = SubsetConfig(
                kls=SampleUser,
                fields=["id", "name"],
                expose_as=[("name", "user_name")],
            )

        expose = scan_expose_fields(UserSub)
        assert expose == {"name": "user_name"}

    def test_config_with_send_to(self):
        """send_to should add SendToInfo metadata to fields."""

        from nexusx.context import scan_send_to_fields
        from nexusx.subset import SubsetConfig

        class UserSub(DefineSubset):
            __subset__ = SubsetConfig(
                kls=SampleUser,
                fields=["id", "name", "email"],
                send_to=[("email", "email_collector")],
            )

        send_to = scan_send_to_fields(UserSub)
        assert "email" in send_to
        assert send_to["email"] == "email_collector"

    def test_config_with_send_to_tuple(self):
        """send_to with tuple of collector names."""

        from nexusx.context import scan_send_to_fields
        from nexusx.subset import SubsetConfig

        class UserSub(DefineSubset):
            __subset__ = SubsetConfig(
                kls=SampleUser,
                fields=["id", "name", "email"],
                send_to=[("email", ("col_a", "col_b"))],
            )

        send_to = scan_send_to_fields(UserSub)
        assert send_to["email"] == ("col_a", "col_b")

    def test_config_fields_and_omit_exclusive(self):
        """fields + omit_fields both specified should raise ValueError."""

        from nexusx.subset import SubsetConfig

        with pytest.raises(ValueError, match="exclusive"):
            SubsetConfig(
                kls=SampleUser,
                fields=["id"],
                omit_fields=["email"],
            )

    def test_config_missing_both(self):
        """Neither fields nor omit_fields should raise ValueError."""

        from nexusx.subset import SubsetConfig

        with pytest.raises(ValueError, match="must be provided"):
            SubsetConfig(kls=SampleUser)

    def test_config_with_extra_fields(self):
        """SubsetConfig + class body extra fields should coexist."""

        from nexusx.subset import SubsetConfig

        class UserSub(DefineSubset):
            __subset__ = SubsetConfig(
                kls=SampleUser,
                fields=["id", "name"],
            )
            display_name: str = ""

        assert "id" in UserSub.model_fields
        assert "display_name" in UserSub.model_fields

    def test_config_source_registration(self):
        """SubsetConfig-based DTO should register source entity."""

        from nexusx.subset import SubsetConfig

        class UserSub(DefineSubset):
            __subset__ = SubsetConfig(
                kls=SampleUser,
                fields=["id", "name"],
            )

        assert get_subset_source(UserSub) is SampleUser

    def test_config_with_sqlmodel_table_true(self):
        """SubsetConfig with table=True entity (with relationships)."""

        from nexusx.subset import SubsetConfig

        class TaskDTO(DefineSubset):
            __subset__ = SubsetConfig(
                kls=FixtureTask,
                fields=["id", "title", "owner_id"],
            )

        assert "id" in TaskDTO.model_fields
        assert "title" in TaskDTO.model_fields
        # FK field should be present but excluded
        assert "owner_id" in TaskDTO.model_fields


# ──────────────────────────────────────────────────────────
# Test: SubsetConfig end-to-end integration with Resolver
# ──────────────────────────────────────────────────────────


class TestSubsetConfigIntegration:
    """End-to-end tests: SubsetConfig metadata flows through Resolver correctly."""

    @pytest.mark.usefixtures("test_db")
    async def test_expose_as_with_resolver(self):
        """SubsetConfig expose_as should work through Resolver end-to-end."""
        from sqlmodel import select

        from nexusx.resolver import Resolver
        from nexusx.subset import SubsetConfig

        class ChildDTO(DefineSubset):
            __subset__ = SubsetConfig(
                kls=FixtureTask,
                fields=["id", "title"],
            )
            parent_name: str = ""

            def post_parent_name(self, ancestor_context=None):
                if ancestor_context is None:
                    ancestor_context = {}
                return ancestor_context.get("sprint_name", "unknown")

        class ParentDTO(DefineSubset):
            __subset__ = SubsetConfig(
                kls=FixtureSprint,
                fields=["id", "name"],
                expose_as=[("name", "sprint_name")],
            )
            tasks: list[ChildDTO] = []

        session_factory = get_test_session_factory()
        async with session_factory() as session:
            sprints = (await session.exec(select(FixtureSprint))).all()

        dtos = [ParentDTO(id=s.id, name=s.name) for s in sprints]
        result = await Resolver().resolve(dtos)

        # ExposeAs('sprint_name') should propagate to children
        for sprint_dto in result:
            for task_dto in sprint_dto.tasks:
                assert task_dto.parent_name == sprint_dto.name

    async def test_send_to_on_extra_field_with_resolver(self):
        """SubsetConfig send_to on an extra field should collect through Resolver."""
        from sqlmodel import select

        from nexusx.context import Collector
        from nexusx.loader.registry import ErManager
        from nexusx.resolver import Resolver
        from nexusx.subset import SubsetConfig
        from tests.conftest import init_test_db, seed_test_data
        await init_test_db()
        await seed_test_data()

        session_factory = get_test_session_factory()
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=session_factory,
        )

        class UserDTO(DefineSubset):
            __subset__ = SubsetConfig(kls=FixtureUser, fields=["id", "name"])

        class TaskDTO(DefineSubset):
            __subset__ = SubsetConfig(
                kls=FixtureTask,
                fields=["id", "title", "owner_id"],
                send_to=[("owner", "contributors")],
            )
            owner: UserDTO | None = None

        class SprintDTO(DefineSubset):
            __subset__ = SubsetConfig(kls=FixtureSprint, fields=["id", "name"])
            tasks: list[TaskDTO] = []
            contributors: list[UserDTO] = []

            def post_contributors(self, collector=Collector("contributors")):
                return collector.values()

        async with session_factory() as session:
            sprints = (await session.exec(select(FixtureSprint))).all()

        dtos = [SprintDTO(id=s.id, name=s.name) for s in sprints]
        result = await Resolver(registry).resolve(dtos)

        # Each sprint should collect owners from tasks via SendTo + Collector
        for sprint_dto in result:
            assert len(sprint_dto.contributors) > 0
            # Contributors should be UserDTO instances loaded via DataLoader
            for c in sprint_dto.contributors:
                assert isinstance(c, UserDTO)
                assert c.name in {"Alice", "Bob"}

    @pytest.mark.usefixtures("test_db")
    async def test_expose_as_and_send_to_combined(self):
        """SubsetConfig expose_as + send_to should work together in Resolver."""
        from sqlmodel import select

        from nexusx.context import Collector
        from nexusx.loader.registry import ErManager
        from nexusx.resolver import Resolver
        from nexusx.subset import SubsetConfig
        from tests.conftest import init_test_db, seed_test_data
        await init_test_db()
        await seed_test_data()

        session_factory = get_test_session_factory()
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=session_factory,
        )

        class UserDTO(DefineSubset):
            __subset__ = SubsetConfig(kls=FixtureUser, fields=["id", "name"])

        class TaskDTO(DefineSubset):
            __subset__ = SubsetConfig(
                kls=FixtureTask,
                fields=["id", "title", "owner_id"],
                send_to=[("owner", "contributors")],
            )
            owner: UserDTO | None = None
            full_title: str = ""

            def post_full_title(self, ancestor_context=None):
                if ancestor_context is None:
                    ancestor_context = {}
                sprint_name = ancestor_context.get("sprint_name", "unknown")
                return f"{sprint_name} / {self.title}"

        class SprintDTO(DefineSubset):
            __subset__ = SubsetConfig(
                kls=FixtureSprint,
                fields=["id", "name"],
                expose_as=[("name", "sprint_name")],
            )
            tasks: list[TaskDTO] = []
            contributors: list[UserDTO] = []

            def post_contributors(self, collector=Collector("contributors")):
                return collector.values()

        async with session_factory() as session:
            sprints = (await session.exec(select(FixtureSprint))).all()

        dtos = [SprintDTO(id=s.id, name=s.name) for s in sprints]
        result = await Resolver(registry).resolve(dtos)

        for sprint_dto in result:
            # ExposeAs: children see sprint_name
            for task_dto in sprint_dto.tasks:
                assert task_dto.full_title == f"{sprint_dto.name} / {task_dto.title}"
            # SendTo + Collector: owners collected
            assert len(sprint_dto.contributors) > 0

    @pytest.mark.usefixtures("test_db")
    async def test_excluded_fields_hidden_in_serialization(self):
        """SubsetConfig excluded_fields should hide fields from model_dump."""
        from sqlmodel import select

        from nexusx.subset import SubsetConfig

        class TaskDTO(DefineSubset):
            __subset__ = SubsetConfig(
                kls=FixtureTask,
                fields=["id", "title", "owner_id"],
                excluded_fields=["owner_id"],
            )

        session_factory = get_test_session_factory()
        async with session_factory() as session:
            tasks = (await session.exec(select(FixtureTask))).all()

        dtos = [TaskDTO.model_validate(t) for t in tasks]
        for dto in dtos:
            # Internally accessible
            assert dto.owner_id is not None
            # Hidden from serialization
            assert "owner_id" not in dto.model_dump()

    @pytest.mark.usefixtures("test_db")
    async def test_fields_all_with_relationships(self):
        """SubsetConfig fields='all' should include all scalar fields + implicit AutoLoad."""
        from sqlmodel import select

        from nexusx.loader.registry import ErManager
        from nexusx.resolver import Resolver
        from nexusx.subset import SubsetConfig
        from tests.conftest import init_test_db, seed_test_data
        await init_test_db()
        await seed_test_data()

        session_factory = get_test_session_factory()
        registry = ErManager(
            entities=[FixtureUser, FixtureSprint, FixtureTask],
            session_factory=session_factory,
        )

        class UserDTO(DefineSubset):
            __subset__ = SubsetConfig(kls=FixtureUser, fields="all")

        # Use explicit fields to avoid relationship fields (sprint, owner)
        # that would cause DetachedInstanceError during model_validate
        class TaskDTO(DefineSubset):
            __subset__ = SubsetConfig(
                kls=FixtureTask,
                fields=["id", "title", "sprint_id", "owner_id"],
            )
            owner: UserDTO | None = None

        async with session_factory() as session:
            tasks = (await session.exec(select(FixtureTask))).all()

        # Build DTOs manually to avoid DetachedInstanceError from relationship attrs
        dtos = [
            TaskDTO(id=t.id, title=t.title, sprint_id=t.sprint_id, owner_id=t.owner_id)
            for t in tasks
        ]
        result = await Resolver(registry).resolve(dtos)

        # All fields present
        for dto in result:
            assert dto.id is not None
            assert dto.title is not None
            assert dto.owner_id is not None
            # Implicit AutoLoad: owner resolved
            assert dto.owner is not None
            assert dto.owner.name in {"Alice", "Bob"}

    @pytest.mark.usefixtures("test_db")
    async def test_send_to_on_subset_field_with_resolver(self):
        """SubsetConfig send_to on a subset field (not extra) should work."""
        from sqlmodel import select

        from nexusx.context import Collector
        from nexusx.resolver import Resolver
        from nexusx.subset import SubsetConfig

        class TaskDTO(DefineSubset):
            __subset__ = SubsetConfig(
                kls=FixtureTask,
                fields=["id", "title"],
                send_to=[("title", "all_titles")],
            )

        class SprintDTO(DefineSubset):
            __subset__ = SubsetConfig(kls=FixtureSprint, fields=["id", "name"])
            tasks: list[TaskDTO] = []
            all_titles: list[str] = []

            def post_all_titles(self, collector=Collector("all_titles")):
                return collector.values()

        session_factory = get_test_session_factory()
        async with session_factory() as session:
            sprints = (await session.exec(select(FixtureSprint))).all()

        dtos = [SprintDTO(id=s.id, name=s.name) for s in sprints]
        result = await Resolver().resolve(dtos)

        # Collector should have collected task titles
        for sprint_dto in result:
            assert len(sprint_dto.all_titles) == len(sprint_dto.tasks)
            assert all(isinstance(t, str) for t in sprint_dto.all_titles)


# ──────────────────────────────────────────────────────────
# Test: build_dto_select
# ──────────────────────────────────────────────────────────


class TestBuildDtoSelect:
    def test_basic_column_selection(self):
        """build_dto_select should select only the DTO's subset columns."""
        from nexusx.subset import SubsetConfig, build_dto_select

        class UserSub(DefineSubset):
            __subset__ = SubsetConfig(kls=FixtureUser, fields=["id", "name"])

        stmt = build_dto_select(UserSub)

        # Verify the statement's columns match subset fields
        cols = {c.name for c in stmt.selected_columns}
        assert cols == {"id", "name"}

    def test_fk_field_included_in_select(self):
        """FK fields should appear in the select statement."""
        from nexusx.subset import SubsetConfig, build_dto_select

        class TaskSub(DefineSubset):
            __subset__ = SubsetConfig(
                kls=FixtureTask, fields=["id", "title", "owner_id"],
            )

        stmt = build_dto_select(TaskSub)
        cols = {c.name for c in stmt.selected_columns}
        assert cols == {"id", "title", "owner_id"}

    def test_relationship_fields_filtered(self):
        """Relationship field names should be excluded from the select."""
        from nexusx.subset import SubsetConfig, build_dto_select

        # FixtureTask has 'sprint' and 'owner' as relationship fields
        class TaskSub(DefineSubset):
            __subset__ = SubsetConfig(kls=FixtureTask, fields=["id", "title"])

        stmt = build_dto_select(TaskSub)
        cols = {c.name for c in stmt.selected_columns}
        # Only scalar columns, no relationship names
        assert "sprint" not in cols
        assert "owner" not in cols
        assert cols == {"id", "title"}

    def test_with_where_clause(self):
        """build_dto_select with where should include the filter."""
        from nexusx.subset import SubsetConfig, build_dto_select

        class UserSub(DefineSubset):
            __subset__ = SubsetConfig(kls=FixtureUser, fields=["id", "name"])

        stmt = build_dto_select(UserSub, where=FixtureUser.id == 1)
        compiled = stmt.compile(compile_kwargs={"literal_binds": True})
        assert "id = 1" in str(compiled).lower() or "WHERE" in str(compiled)

    def test_non_define_subset_raises(self):
        """Passing a non-DefineSubset class should raise ValueError."""
        from nexusx.subset import build_dto_select

        with pytest.raises(ValueError, match="not a DefineSubset DTO"):
            build_dto_select(BaseModel)

    def test_plain_pydantic_model_raises(self):
        """A plain Pydantic model without __subset_fields__ should raise."""
        from nexusx.subset import build_dto_select

        class MyModel(BaseModel):
            x: int

        with pytest.raises(ValueError, match="not a DefineSubset DTO"):
            build_dto_select(MyModel)

    @pytest.mark.usefixtures("test_db")
    async def test_end_to_end_query_and_conversion(self):
        """build_dto_select should produce a statement that works with session.exec."""
        from nexusx.subset import SubsetConfig, build_dto_select

        class TaskSub(DefineSubset):
            __subset__ = SubsetConfig(
                kls=FixtureTask, fields=["id", "title", "owner_id"],
            )

        stmt = build_dto_select(TaskSub)
        session_factory = get_test_session_factory()

        async with session_factory() as session:
            rows = (await session.exec(stmt)).all()

        dtos = [TaskSub(**dict(row._mapping)) for row in rows]
        assert len(dtos) > 0
        for dto in dtos:
            assert dto.id is not None
            assert dto.title is not None
            assert dto.owner_id is not None

    @pytest.mark.usefixtures("test_db")
    async def test_with_where_returns_subset(self):
        """build_dto_select with where should filter results."""
        from nexusx.subset import SubsetConfig, build_dto_select

        class UserSub(DefineSubset):
            __subset__ = SubsetConfig(kls=FixtureUser, fields=["id", "name"])

        stmt = build_dto_select(UserSub, where=FixtureUser.name == "Alice")
        session_factory = get_test_session_factory()

        async with session_factory() as session:
            rows = (await session.exec(stmt)).all()

        dtos = [UserSub(**dict(row._mapping)) for row in rows]
        assert len(dtos) == 1
        assert dtos[0].name == "Alice"

    @pytest.mark.usefixtures("test_db")
    async def test_with_resolver_integration(self):
        """build_dto_select + dict(row._mapping) + Resolver should work end-to-end."""
        from nexusx.loader.registry import ErManager
        from nexusx.resolver import Resolver
        from nexusx.subset import SubsetConfig, build_dto_select

        class UserSub(DefineSubset):
            __subset__ = SubsetConfig(kls=FixtureUser, fields=["id", "name"])

        class TaskSub(DefineSubset):
            __subset__ = SubsetConfig(
                kls=FixtureTask, fields=["id", "title", "owner_id"],
            )
            owner: UserSub | None = None

        session_factory = get_test_session_factory()
        registry = ErManager(
            entities=[FixtureUser, FixtureTask, FixtureSprint],
            session_factory=session_factory,
        )

        stmt = build_dto_select(TaskSub)
        async with session_factory() as session:
            rows = (await session.exec(stmt)).all()
        dtos = [TaskSub(**dict(row._mapping)) for row in rows]

        result = await Resolver(registry).resolve(dtos)
        for dto in result:
            assert dto.owner is not None
            assert dto.owner.name in {"Alice", "Bob"}


# ──────────────────────────────────────────────────────────
# P0/P1: Subset validation, PK auto-inject, FK handling
# ──────────────────────────────────────────────────────────


class TestSubsetValidation:
    def test_subset_dict_type_raises(self):
        """__subset__ with a dict should raise ValueError."""

        with pytest.raises(ValueError, match="tuple of"):
            class Bad(DefineSubset):
                __subset__ = {"entity": SampleUser, "fields": ["id"]}  # type: ignore

    def test_subset_wrong_length_tuple_raises(self):
        """__subset__ with 3-element tuple should raise ValueError."""

        with pytest.raises(ValueError, match="tuple of"):
            class Bad(DefineSubset):
                __subset__ = (SampleUser, ("id",), "extra")  # type: ignore

    def test_subsetconfig_fields_illegal_type_raises(self):
        """SubsetConfig with fields as int should raise ValidationError."""
        from pydantic import ValidationError

        from nexusx.subset import SubsetConfig

        with pytest.raises(ValidationError):
            SubsetConfig(kls=SampleUser, fields=42)  # type: ignore


class TestPKAutoInject:
    def test_pk_auto_included_even_if_not_in_fields(self):
        """PK field should be auto-included for DataLoader key resolution."""

        class UserDTO(DefineSubset):
            __subset__ = (SampleUser, ("name",))

        assert "id" in UserDTO.model_fields
        dto = UserDTO(id=1, name="Alice")
        assert dto.id == 1

    def test_pk_auto_excluded_when_omitted(self):
        """Auto-included PK should be excluded from serialization when in omit_fields."""
        from nexusx.subset import SubsetConfig

        class UserDTO(DefineSubset):
            __subset__ = SubsetConfig(kls=SampleUser, omit_fields=["email", "id"])

        dto = UserDTO(name="Alice", id=1)
        dumped = dto.model_dump()
        # id is auto-included but excluded from serialization because it's in omit_fields
        assert "id" not in dumped
        assert "email" not in dumped
        assert dumped["name"] == "Alice"
        # But id should still be accessible as attribute for DataLoader
        assert dto.id == 1


class TestFKFieldHandling:
    def test_fk_field_explicitly_included(self):
        """Explicitly included FK field should appear in subset."""
        from tests.conftest import FixtureTask

        class TaskDTO(DefineSubset):
            __subset__ = (FixtureTask, ("id", "title", "owner_id"))

        assert "owner_id" in TaskDTO.model_fields
        dto = TaskDTO(id=1, title="T", owner_id=5)
        assert dto.owner_id == 5

    def test_fk_field_not_in_fields_excluded(self):
        """FK fields not in __subset__ should not appear in serialized output."""
        from tests.conftest import FixtureTask

        class TaskDTO(DefineSubset):
            __subset__ = (FixtureTask, ("id", "title"))

        # FK should be auto-included for Resolver but excluded from serialization
        assert "owner_id" in TaskDTO.model_fields
        dto = TaskDTO(id=1, title="T", owner_id=5)
        assert dto.owner_id == 5
        dumped = dto.model_dump()
        assert "owner_id" not in dumped
        assert dumped["title"] == "T"

    def test_fk_auto_included_for_resolver(self):
        """FK fields should be auto-included and excluded from serialization,
        mirroring PK auto-inject behavior, so Resolver can use them as DataLoader keys."""

        class TaskDTO(DefineSubset):
            __subset__ = (FixtureTask, ("id", "title"))

        # FK fields auto-included
        assert "sprint_id" in TaskDTO.model_fields
        assert "owner_id" in TaskDTO.model_fields

        dto = TaskDTO(id=1, title="My Task", sprint_id=10, owner_id=20)
        assert dto.sprint_id == 10
        assert dto.owner_id == 20

        # But excluded from serialization
        dumped = dto.model_dump()
        assert "sprint_id" not in dumped
        assert "owner_id" not in dumped
        assert dumped["title"] == "My Task"

    def test_fk_auto_excluded_with_explicit_fields(self):
        """FK auto-include should work with SubsetConfig + excluded_fields too."""
        from tests.conftest import FixtureTask

        class TaskDTO(DefineSubset):
            __subset__ = SubsetConfig(
                kls=FixtureTask,
                fields=["id", "title"],
            )

        assert "owner_id" in TaskDTO.model_fields
        dto = TaskDTO(id=1, title="T", owner_id=5)
        assert dto.owner_id == 5
        assert "owner_id" not in dto.model_dump()

    def test_omit_fk_without_relationship_allowed(self):
        """Omitting a FK is fine when no relationship field depends on it."""

        class TaskDTO(DefineSubset):
            __subset__ = SubsetConfig(
                kls=FixtureTask, omit_fields=["owner_id"],
            )

        assert "owner_id" not in TaskDTO.model_fields

    def test_omit_fk_with_relationship_raises(self):
        """Omitting a FK that a relationship field needs should raise ValueError."""
        import pytest

        class OwnerDTO(DefineSubset):
            __subset__ = (FixtureUser, ("id", "name"))

        with pytest.raises(ValueError, match="Cannot omit FK field 'owner_id'"):
            class BadDTO(DefineSubset):
                __subset__ = SubsetConfig(
                    kls=FixtureTask, omit_fields=["owner_id"],
                )
                owner: OwnerDTO | None = None
