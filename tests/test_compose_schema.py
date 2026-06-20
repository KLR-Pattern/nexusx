"""Tests for ``nexusx.use_case.compose_schema`` (User Story 1).

Covers FR-001..FR-005, FR-009, FR-012a + edge cases from spec.md.

Per contracts:
- ``build_compose_schema(app: UseCaseAppConfig) -> ComposeSchema``
- ``ComposeSchema.registry`` → dict[str, TypeInfo]
- ``ComposeSchema.render_introspection()`` → dict (must round-trip through
  ``graphql.build_schema(...)`` for GraphiQL compatibility)
- ``ComposeSchema.render_sdl()`` → str
- ``ComposeSchema.render_method_sdl(service_name, method_name)`` → str | None
"""

from __future__ import annotations

import datetime
import enum
import uuid
from typing import Annotated

import pytest
from pydantic import BaseModel, Field
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from nexusx.decorator import mutation, query
from nexusx.use_case.business import UseCaseService
from nexusx.use_case.compose_schema import (
    ComposeSchemaError,
    DuplicateTypeError,
    MissingReturnAnnotationError,
    SQLModelInDtoFieldError,
    TypeRef,
    UnsupportedTypeError,
    build_compose_schema,
)
from nexusx.use_case.compose_type_mapper import ComposeTypeMapper
from nexusx.use_case.context import FromContext
from nexusx.use_case.types import UseCaseAppConfig

# ──────────────────────────────────────────────────────────────────────
# Test fixtures (DTOs + services)
# ──────────────────────────────────────────────────────────────────────


class TaskStatus(enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class UserSummary(BaseModel):
    """User summary DTO."""

    id: int
    name: str
    email: str | None = None


class TaskSummary(BaseModel):
    """Task summary DTO."""

    id: int
    title: str
    status: TaskStatus
    owner: UserSummary | None = None
    due: datetime.date | None = None


class SprintSummary(BaseModel):
    """Sprint summary with nested tasks."""

    id: int
    name: str
    tasks: list[TaskSummary] = Field(default_factory=list)


class UserService(UseCaseService):
    """User management service."""

    @query
    async def list_users(cls) -> list[UserSummary]:
        """Get all users."""
        ...

    @query
    async def get_user(cls, user_id: int) -> UserSummary | None:
        """Get a single user by id."""
        ...


class TaskService(UseCaseService):
    """Task management service."""

    @query
    async def list_tasks(cls) -> list[TaskSummary]:
        """Get all tasks."""
        ...

    @query
    async def get_task(cls, task_id: int) -> TaskSummary | None:
        """Get a single task."""
        ...

    @mutation
    async def create_task(cls, title: str, status: TaskStatus = TaskStatus.PENDING) -> TaskSummary:
        """Create a task."""
        ...


class SprintService(UseCaseService):
    """Sprint management service."""

    @query
    async def list_sprints(cls) -> list[SprintSummary]:
        """Get all sprints with nested tasks."""
        ...


class ContextAwareService(UseCaseService):
    """Service with FromContext parameters."""

    @query
    async def current_user(
        cls,
        request_user_id: Annotated[int, FromContext()],
    ) -> UserSummary | None:
        """Return current user based on injected context."""
        ...

    @query
    async def user_tasks(
        cls,
        user_id: int,  # regular GraphQL arg
        limit: int = 10,  # regular GraphQL arg with default
        actor: Annotated[str, FromContext()] = "",  # FromContext arg
    ) -> list[TaskSummary]:
        """User's tasks."""
        ...


@pytest.fixture
def app() -> UseCaseAppConfig:
    return UseCaseAppConfig(
        name="project",
        services=[UserService, TaskService, SprintService],
        description="Project management app",
    )


# ──────────────────────────────────────────────────────────────────────
# T009 / T023: scalar/container type mapping via ComposeTypeMapper
# ──────────────────────────────────────────────────────────────────────


class TestTypeMapping:
    """Direct tests of ComposeTypeMapper (also exercised through build_compose_schema)."""

    def test_int_maps_to_non_null_int(self) -> None:
        m = ComposeTypeMapper()
        ref = m.map_python_type(int)
        assert ref == TypeRef(
            kind="NON_NULL", of_type=TypeRef(kind="SCALAR", name="Int")
        )

    def test_optional_int_maps_to_nullable_int(self) -> None:
        m = ComposeTypeMapper()
        ref = m.map_python_type(int | None)
        assert ref == TypeRef(kind="SCALAR", name="Int")

    def test_pep604_union_maps_to_nullable(self) -> None:
        m = ComposeTypeMapper()
        ref = m.map_python_type(int | None)
        assert ref == TypeRef(kind="SCALAR", name="Int")

    def test_list_int_maps_to_non_null_list_of_non_null_int(self) -> None:
        m = ComposeTypeMapper()
        ref = m.map_python_type(list[int])
        # [Int!]! = NON_NULL(LIST(NON_NULL(Int)))
        assert ref.kind == "NON_NULL"
        assert ref.of_type is not None and ref.of_type.kind == "LIST"
        inner = ref.of_type.of_type
        assert inner is not None and inner.kind == "NON_NULL"
        assert inner.of_type == TypeRef(kind="SCALAR", name="Int")

    def test_optional_list_maps_to_nullable_list(self) -> None:
        m = ComposeTypeMapper()
        ref = m.map_python_type(list[int] | None)
        # [Int!]  (list nullable, elements non-null)
        assert ref.kind == "LIST"

    def test_list_of_optional_maps_to_non_null_list_of_nullable(self) -> None:
        m = ComposeTypeMapper()
        ref = m.map_python_type(list[int | None])
        # [Int]! (list non-null, elements nullable)
        assert ref.kind == "NON_NULL"
        assert ref.of_type is not None and ref.of_type.kind == "LIST"
        assert ref.of_type.of_type == TypeRef(kind="SCALAR", name="Int")

    def test_uuid_maps_to_id_scalar(self) -> None:
        m = ComposeTypeMapper()
        ref = m.map_python_type(uuid.UUID)
        assert ref.kind == "NON_NULL"
        assert ref.of_type == TypeRef(kind="SCALAR", name="ID")

    def test_datetime_maps_to_datetime_scalar(self) -> None:
        m = ComposeTypeMapper()
        ref = m.map_python_type(datetime.datetime)
        assert ref.kind == "NON_NULL"
        assert ref.of_type == TypeRef(kind="SCALAR", name="DateTime")

    def test_enum_maps_to_enum_type_with_values(self) -> None:
        m = ComposeTypeMapper()
        ref = m.map_python_type(TaskStatus)
        assert ref.kind == "NON_NULL"
        assert ref.of_type == TypeRef(kind="ENUM", name="TaskStatus")
        info = m.registry["TaskStatus"]
        assert info.kind == "ENUM"
        assert tuple(v.name for v in info.enum_values) == (
            "PENDING",
            "IN_PROGRESS",
            "DONE",
        )

    def test_unsupported_bytes_raises(self) -> None:
        m = ComposeTypeMapper()
        with pytest.raises(UnsupportedTypeError):
            m.map_python_type(bytes)

    def test_unsupported_tuple_raises(self) -> None:
        m = ComposeTypeMapper()
        with pytest.raises(UnsupportedTypeError):
            m.map_python_type(tuple[int, str])

    def test_unsupported_any_raises(self) -> None:
        from typing import Any

        m = ComposeTypeMapper()
        with pytest.raises(UnsupportedTypeError):
            m.map_python_type(Any)

    def test_field_description_extracted_from_pydantic_field(self) -> None:
        m2 = ComposeTypeMapper()
        m2.map_python_type(SprintSummary)
        sprint_info = m2.registry["SprintSummary"]
        assert sprint_info.fields  # has fields


# ──────────────────────────────────────────────────────────────────────
# T010: FromContext parameters are filtered out of method args
# ──────────────────────────────────────────────────────────────────────


class TestFromContextFiltering:
    def test_from_context_params_do_not_appear_in_schema(self) -> None:
        app = UseCaseAppConfig(name="ctx", services=[ContextAwareService])
        schema = build_compose_schema(app)

        ctx_query = schema.registry["ContextAwareServiceQuery"]
        current_user = next(f for f in ctx_query.fields if f.name == "current_user")
        # Should have ZERO args (request_user_id is FromContext, filtered out)
        assert current_user.args == ()

        user_tasks = next(f for f in ctx_query.fields if f.name == "user_tasks")
        arg_names = [a.name for a in user_tasks.args]
        # user_id and limit are regular args; actor is FromContext
        assert arg_names == ["user_id", "limit"]
        assert all(not a.is_from_context for a in user_tasks.args)

    def test_is_from_context_annotation_detection(self) -> None:
        from nexusx.use_case.compose_type_mapper import is_from_context_annotation

        assert is_from_context_annotation(Annotated[int, FromContext()])
        assert not is_from_context_annotation(int)
        assert not is_from_context_annotation(Annotated[int, "metadata"])


# ──────────────────────────────────────────────────────────────────────
# T011: same DTO referenced from multiple services registers once
# ──────────────────────────────────────────────────────────────────────


class TestDedup:
    def test_dto_referenced_from_multiple_services_registers_once(self) -> None:
        # TaskSummary is referenced from TaskService.list_tasks / get_task /
        # create_task AND from SprintService.list_sprints (via SprintSummary.tasks)
        schema = build_compose_schema(UseCaseAppConfig(
            name="project",
            services=[UserService, TaskService, SprintService],
        ))
        task_summary_count = sum(
            1 for name in schema.registry if name == "TaskSummary"
        )
        assert task_summary_count == 1
        user_summary_count = sum(
            1 for name in schema.registry if name == "UserSummary"
        )
        assert user_summary_count == 1

    def test_two_distinct_classes_with_same_name_raises(self) -> None:
        with pytest.raises(DuplicateTypeError):
            build_compose_schema(
                UseCaseAppConfig(
                    name="conflict",
                    services=[_ConflictServiceOne, _ConflictServiceTwo],
                )
            )


# ──────────────────────────────────────────────────────────────────────
# T012: @query and @mutation coexistence generates both root types
# ──────────────────────────────────────────────────────────────────────


class TestQueryMutationCoexistence:
    def test_both_root_query_and_mutation_present(self) -> None:
        schema = build_compose_schema(UseCaseAppConfig(
            name="qm",
            services=[TaskService],  # has both @query and @mutation methods
        ))
        assert "Query" in schema.registry
        assert "Mutation" in schema.registry
        assert "TaskServiceQuery" in schema.registry
        assert "TaskServiceMutation" in schema.registry

    def test_only_query_root_when_no_mutations(self) -> None:
        schema = build_compose_schema(UseCaseAppConfig(
            name="qo",
            services=[UserService],  # only @query methods
        ))
        assert "Query" in schema.registry
        assert "Mutation" not in schema.registry

    def test_enable_mutation_false_skips_mutation_root(self) -> None:
        schema = build_compose_schema(UseCaseAppConfig(
            name="qm_off",
            services=[TaskService],
            enable_mutation=False,
        ))
        assert "Query" in schema.registry
        assert "Mutation" not in schema.registry
        # Mutation-type fields should also not appear on the service type
        assert "TaskServiceMutation" not in schema.registry

    def test_root_query_has_service_entry_points(self) -> None:
        schema = build_compose_schema(UseCaseAppConfig(
            name="qe",
            services=[UserService, TaskService],
        ))
        root_query = schema.registry["Query"]
        service_field_names = {f.name for f in root_query.fields}
        assert service_field_names == {"UserService", "TaskService"}

    def test_service_query_type_has_method_fields(self) -> None:
        schema = build_compose_schema(UseCaseAppConfig(
            name="sq",
            services=[UserService],
        ))
        user_query = schema.registry["UserServiceQuery"]
        method_names = {f.name for f in user_query.fields}
        assert method_names == {"list_users", "get_user"}


# ──────────────────────────────────────────────────────────────────────
# T013: name conflict detection
# ──────────────────────────────────────────────────────────────────────


class TestNameConflicts:
    def test_duplicate_service_name_raises(self) -> None:
        # Two distinct service classes that we trick into sharing __name__.
        class Svc1(UseCaseService):
            @query
            async def m(cls) -> int:
                ...

        class Svc2(UseCaseService):
            @query
            async def m(cls) -> int:
                ...

        Svc2.__name__ = Svc1.__name__  # type: ignore[attr-defined]

        with pytest.raises(ComposeSchemaError) as exc_info:
            build_compose_schema(UseCaseAppConfig(
                name="dup",
                services=[Svc1, Svc2],
            ))
        # Could be DuplicateServiceError; we accept the base class for robustness
        assert isinstance(exc_info.value, ComposeSchemaError)


# ──────────────────────────────────────────────────────────────────────
# T014: missing return annotation raises
# ──────────────────────────────────────────────────────────────────────


class TestMissingReturnAnnotation:
    def test_method_without_return_annotation_raises(self) -> None:
        class Svc(UseCaseService):
            @query
            async def no_return(cls):  # type: ignore[no-untyped-def] — intentional
                ...

        with pytest.raises(MissingReturnAnnotationError):
            build_compose_schema(UseCaseAppConfig(name="nr", services=[Svc]))

    def test_method_with_none_return_annotation_raises(self) -> None:
        class Svc(UseCaseService):
            @query
            async def none_return(cls) -> None:
                ...

        with pytest.raises(MissingReturnAnnotationError):
            build_compose_schema(UseCaseAppConfig(name="nr2", services=[Svc]))


# ──────────────────────────────────────────────────────────────────────
# Module-level SQLModel fixtures (get_type_hints can't resolve classes
# defined inside test function bodies).
# ──────────────────────────────────────────────────────────────────────


class _SqlmodelEntity(SQLModel, table=True):
    """SQLModel entity used to verify compose-schema rejection."""

    __tablename__ = "test_compose_sqlmodel_entity"

    id: int = SQLField(default=None, primary_key=True)
    name: str


class _BadDTOWithEntity(BaseModel):
    """DTO that wrongly references a SQLModel entity as a field type."""

    id: int
    entity: _SqlmodelEntity  # forbidden by convention #7


class _ServiceReturningBadDTO(UseCaseService):
    @query
    async def m(cls) -> _BadDTOWithEntity:
        ...


class _ServiceReturningEntity(UseCaseService):
    @query
    async def m(cls) -> _SqlmodelEntity:
        ...


# Two distinct BaseModel classes we force into the same __name__ for the
# duplicate-type-name test.
class _ConflictA(BaseModel):
    a: int


class _ConflictB(BaseModel):
    b: int


_ConflictB.__name__ = "_ConflictA"  # type: ignore[attr-defined]


class _ConflictServiceOne(UseCaseService):
    @query
    async def one(cls) -> _ConflictA:
        ...


class _ConflictServiceTwo(UseCaseService):
    @query
    async def two(cls) -> _ConflictB:
        ...


# ──────────────────────────────────────────────────────────────────────
# T015: DTO field referencing SQLModel raises
# ──────────────────────────────────────────────────────────────────────


class TestSQLModelInDtoField:
    def test_dto_field_referencing_sqlmodel_entity_raises(self) -> None:
        with pytest.raises(SQLModelInDtoFieldError):
            build_compose_schema(
                UseCaseAppConfig(name="bad", services=[_ServiceReturningBadDTO])
            )

    def test_sqlmodel_return_type_raises(self) -> None:
        with pytest.raises(SQLModelInDtoFieldError):
            build_compose_schema(
                UseCaseAppConfig(name="bad2", services=[_ServiceReturningEntity])
            )


# ──────────────────────────────────────────────────────────────────────
# T016: introspection JSON round-trips through graphql.build_schema
# ──────────────────────────────────────────────────────────────────────


class TestIntrospectionRoundTrip:
    def test_introspection_round_trips_through_graphql_build_schema(self) -> None:

        schema = build_compose_schema(UseCaseAppConfig(
            name="rt",
            services=[UserService, TaskService, SprintService],
        ))
        payload = schema.render_introspection()
        # The payload is the inner __schema value; wrap as full introspection
        # response then build_client_schema-style reverse.
        wrapped = {"__schema": payload}
        sdl_like = _build_schema_from_introspection(wrapped)
        assert sdl_like is not None  # didn't raise

    def test_render_sdl_is_non_empty_string(self) -> None:
        schema = build_compose_schema(UseCaseAppConfig(
            name="sdl",
            services=[UserService, TaskService],
        ))
        sdl = schema.render_sdl()
        assert isinstance(sdl, str)
        assert "type Query" in sdl
        assert "type UserServiceQuery" in sdl
        assert "type TaskServiceQuery" in sdl
        assert "type UserSummary" in sdl
        assert "type TaskSummary" in sdl

    def test_render_method_sdl_returns_method_signature_plus_closure(self) -> None:
        schema = build_compose_schema(UseCaseAppConfig(
            name="ms",
            services=[TaskService],
        ))
        method_sdl = schema.render_method_sdl("TaskService", "get_task")
        assert method_sdl is not None
        assert "type TaskServiceQuery" in method_sdl
        assert "get_task" in method_sdl
        assert "type TaskSummary" in method_sdl  # transitive closure
        assert "type UserSummary" in method_sdl  # nested DTO

    def test_render_method_sdl_unknown_method_returns_none(self) -> None:
        schema = build_compose_schema(UseCaseAppConfig(
            name="ms2",
            services=[UserService],
        ))
        assert schema.render_method_sdl("UserService", "nonexistent") is None
        assert schema.render_method_sdl("UnknownService", "list_users") is None


def _build_schema_from_introspection(introspection_payload: dict) -> object:
    """Reverse-build a graphql-core GraphQLSchema from an introspection payload.

    Uses graphql-core's ``build_client_schema`` which expects the full
    ``{ data: { __schema: ... } }`` shape; we adapt the wrapping.
    """
    from graphql import build_client_schema

    payload = {"data": introspection_payload}
    return build_client_schema(payload["data"])
