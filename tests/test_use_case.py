"""Tests for the UseCase module — UseCaseService + ServiceIntrospector.

The 3.0 release removed the legacy direct-call MCP server
(``create_use_case_mcp_server`` / ``create_use_case_flat_server``). Tests for
that surface lived here previously; they've been removed along with the code.
The new GraphQL MCP lives in ``tests/test_compose_*.py``. The orthogonal
``ServiceIntrospector`` (still used by JSON-RPC + Voyager) is still covered here.
"""

from __future__ import annotations

import datetime
import typing
import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from nexusx.decorator import mutation, query
from nexusx.subset import DefineSubset
from nexusx.use_case.business import UseCaseService
from nexusx.use_case.introspector import (
    ServiceIntrospector,
    _auto_summary,
    _build_selection_example,
    _collect_core_types,
    _collect_dto_types,
    _generate_dto_sdl,
    _get_selection_model,
    _is_fk_field,
    _type_to_legacy_name,
    _type_to_param_schema,
    _type_to_sdl_name,
)

# ──────────────────────────────────────────────────
# Test DTOs
# ──────────────────────────────────────────────────


class UserDTO(BaseModel):
    id: int
    name: str


class TaskDTO(BaseModel):
    id: int
    title: str
    owner: UserDTO | None = None


# ──────────────────────────────────────────────────
# Test Services
# ──────────────────────────────────────────────────


class UserService(UseCaseService):
    """User management service."""

    @query
    async def list_users(cls) -> list[UserDTO]:
        """Get all users."""
        return [UserDTO(id=1, name="Alice"), UserDTO(id=2, name="Bob")]

    @query
    async def get_user(cls, user_id: int) -> UserDTO | None:
        """Get a user by ID."""
        if user_id == 1:
            return UserDTO(id=1, name="Alice")
        return None

    @mutation
    async def create_user(cls, name: str, email: str) -> UserDTO:
        """Create a new user."""
        return UserDTO(id=99, name=name)


class TaskService(UseCaseService):
    """Task management service."""

    @query
    async def list_tasks(cls) -> list[TaskDTO]:
        """Get all tasks."""
        return [
            TaskDTO(id=1, title="Task 1", owner=UserDTO(id=1, name="Alice")),
        ]

    @classmethod
    async def _internal_helper(cls) -> str:
        """This should NOT be exposed (no @query/@mutation)."""
        return "private"

    @classmethod
    async def bare_classmethod(cls) -> str:
        """This should NOT be discovered (no @query/@mutation decorator)."""
        return "bare"

    @query
    async def get_task(cls, task_id: int, include_owner: bool = True) -> TaskDTO | None:
        """Get a task by ID."""
        return TaskDTO(id=task_id, title="Test Task")

    @mutation
    async def delete_task(cls, task_id: int) -> bool:
        """Delete a task."""
        return True


# ──────────────────────────────────────────────────
# Test DTOs and Services for Type Coercion
# ──────────────────────────────────────────────────


class EventDTO(BaseModel):
    id: uuid.UUID
    name: str
    occurred_at: datetime.datetime
    event_date: datetime.date
    event_time: datetime.time


class TypeCoercionService(UseCaseService):
    """Service with complex type parameters for testing type coercion."""

    @query
    async def get_by_uuid(cls, item_id: uuid.UUID) -> str:
        """Get by UUID."""
        return f"uuid:{item_id.version}:{str(item_id)}"

    @query
    async def get_by_datetime(cls, ts: datetime.datetime) -> str:
        """Get by datetime."""
        return f"dt:{ts.isoformat()}"

    @query
    async def get_by_date(cls, d: datetime.date) -> str:
        """Get by date."""
        return f"date:{d.isoformat()}"

    @query
    async def get_by_time(cls, t: datetime.time) -> str:
        """Get by time."""
        return f"time:{t.isoformat()}"

    @query
    async def get_by_decimal(cls, amount: Decimal) -> str:
        """Get by decimal."""
        return f"decimal:{str(amount)}"

    @query
    async def get_optional_uuid(cls, item_id: uuid.UUID | None = None) -> str:
        """Optional UUID."""
        return f"uuid:{str(item_id)}"

    @query
    async def get_optional_datetime(
        cls, ts: datetime.datetime | None = None
    ) -> str:
        """Optional datetime."""
        return f"dt:{ts.isoformat() if ts else 'none'}"

    @query
    async def get_by_uuid_list(cls, ids: list[uuid.UUID]) -> str:
        """List of UUIDs."""
        return f"ids:{','.join(str(i) for i in ids)}"

    @query
    async def create_event(cls, event: EventDTO) -> str:
        """Create event from DTO."""
        return f"event:{event.id}:{event.name}:{event.occurred_at.isoformat()}"

    @query
    async def get_with_mixed_types(
        cls,
        item_id: uuid.UUID,
        ts: datetime.datetime,
        name: str,
        count: int,
    ) -> str:
        """Mixed types."""
        return f"mixed:{str(item_id)}:{ts.isoformat()}:{name}:{count}"


# ──────────────────────────────────────────────────
# Tests: UseCaseService
# ──────────────────────────────────────────────────


class TestUseCaseService:
    def test_discovers_query_methods(self):
        """Methods with @query are discovered."""
        assert "list_users" in UserService.__use_case_methods__
        assert "get_user" in UserService.__use_case_methods__

    def test_discovers_mutation_methods(self):
        """Methods with @mutation are discovered."""
        assert "create_user" in UserService.__use_case_methods__

    def test_method_has_kind(self):
        """Discovered methods have correct kind."""
        assert UserService.__use_case_methods__["list_users"]["kind"] == "query"
        assert UserService.__use_case_methods__["create_user"]["kind"] == "mutation"

    def test_method_has_description(self):
        """Discovered methods have description from docstring."""
        assert (
            UserService.__use_case_methods__["list_users"]["description"]
            == "Get all users."
        )
        assert (
            UserService.__use_case_methods__["create_user"]["description"]
            == "Create a new user."
        )

    def test_excludes_private_methods(self):
        """Methods starting with _ are excluded."""
        assert "_internal_helper" not in TaskService.__use_case_methods__

    def test_excludes_bare_classmethods(self):
        """Methods without @query/@mutation are not discovered."""
        assert "bare_classmethod" not in TaskService.__use_case_methods__

    def test_excludes_get_tag_name(self):
        """get_tag_name is excluded from use case methods."""
        for service_cls in [UserService, TaskService]:
            assert "get_tag_name" not in service_cls.__use_case_methods__

    def test_get_tag_name_returns_class_name(self):
        """get_tag_name returns the class name by default."""
        assert UserService.get_tag_name() == "UserService"
        assert TaskService.get_tag_name() == "TaskService"

    def test_use_case_service_base_has_empty_methods(self):
        """UseCaseService base class has empty __use_case_methods__."""
        assert UseCaseService.__use_case_methods__ == {}


# ──────────────────────────────────────────────────
# Tests: _type_to_sdl_name
# ──────────────────────────────────────────────────


class TestTypeToSdlName:
    def test_int(self):
        assert _type_to_sdl_name(int) == "Int!"

    def test_str(self):
        assert _type_to_sdl_name(str) == "String!"

    def test_float(self):
        assert _type_to_sdl_name(float) == "Float!"

    def test_bool(self):
        assert _type_to_sdl_name(bool) == "Boolean!"

    def test_list_of_int(self):
        assert _type_to_sdl_name(list[int]) == "[Int!]!"

    def test_optional_int(self):
        assert _type_to_sdl_name(int | None) == "Int"

    def test_list_of_dto(self):
        assert _type_to_sdl_name(list[UserDTO]) == "[UserDTO!]!"

    def test_optional_dto(self):
        assert _type_to_sdl_name(UserDTO | None) == "UserDTO"

    def test_dto_class(self):
        assert _type_to_sdl_name(UserDTO) == "UserDTO!"

    def test_dict(self):
        assert _type_to_sdl_name(dict) == "JSON"

    def test_empty_annotation(self):
        from inspect import Parameter

        assert _type_to_sdl_name(Parameter.empty) == "String"


# ──────────────────────────────────────────────────
# Tests: ServiceIntrospector
# ──────────────────────────────────────────────────


def _make_introspector() -> ServiceIntrospector:
    return ServiceIntrospector([UserService, TaskService])


class TestServiceIntrospector:
    def test_list_services(self):
        introspector = _make_introspector()
        services = introspector.list_services()
        assert len(services) == 2

        user_svc = next(s for s in services if s["name"] == "UserService")
        assert user_svc["description"] == "User management service."
        assert user_svc["methods_count"] == 3  # list_users + get_user + create_user

        task_svc = next(s for s in services if s["name"] == "TaskService")
        assert task_svc["methods_count"] == 3  # list_tasks + get_task + delete_task

    def test_describe_service_methods(self):
        introspector = _make_introspector()
        info = introspector.describe_service("UserService")
        assert info is not None
        assert info["name"] == "UserService"
        assert len(info["methods"]) == 3

    def test_describe_service_method_kind(self):
        """Methods include kind field in describe output."""
        introspector = _make_introspector()
        info = introspector.describe_service("UserService")
        assert info is not None

        list_users = next(m for m in info["methods"] if m["name"] == "list_users")
        assert list_users["kind"] == "query"

        create_user = next(m for m in info["methods"] if m["name"] == "create_user")
        assert create_user["kind"] == "mutation"

    def test_describe_service_signatures(self):
        introspector = _make_introspector()
        info = introspector.describe_service("UserService")
        assert info is not None

        list_users = next(m for m in info["methods"] if m["name"] == "list_users")
        assert list_users["description"] == "Get all users."
        assert "list_users()" in list_users["signature"]
        assert "list[UserDTO]" in list_users["signature"]
        assert "[UserDTO!]!" in list_users["signature_sdl"]

        get_user = next(m for m in info["methods"] if m["name"] == "get_user")
        assert "user_id" in get_user["signature"]
        assert "UserDTO" in get_user["signature"]

    def test_describe_service_types(self):
        """types field contains SDL type definitions for referenced DTOs."""
        introspector = _make_introspector()
        info = introspector.describe_service("UserService")
        assert info is not None

        types_str = info["types"]
        assert "type UserDTO" in types_str
        assert "id: Int" in types_str
        assert "name: String!" in types_str

    def test_describe_service_task_types(self):
        """types includes nested DTOs from return values."""
        introspector = _make_introspector()
        info = introspector.describe_service("TaskService")
        assert info is not None

        types_str = info["types"]
        assert "type TaskDTO" in types_str
        assert "type UserDTO" in types_str
        assert "owner: UserDTO" in types_str

    def test_describe_service_with_params(self):
        introspector = _make_introspector()
        info = introspector.describe_service("UserService")
        assert info is not None

        get_user = next(m for m in info["methods"] if m["name"] == "get_user")
        assert "user_id" in get_user["parameters"]

    def test_describe_service_not_found(self):
        introspector = _make_introspector()
        assert introspector.describe_service("nonexistent") is None

    def test_get_service(self):
        introspector = _make_introspector()
        assert introspector.get_service("UserService") is UserService
        assert introspector.get_service("nonexistent") is None

    def test_uses_class_docstring_as_description(self):
        introspector = _make_introspector()
        info = introspector.describe_service("TaskService")
        assert info is not None
        assert info["description"] == "Task management service."


# ──────────────────────────────────────────────────
class SelectionMetaDTO(BaseModel):
    source: str


class SelectionUserDTO(BaseModel):
    id: int
    name: str
    email: str


class SelectionTaskDTO(BaseModel):
    id: int
    title: str
    owner: SelectionUserDTO | None = None
    watchers: list[SelectionUserDTO | None] = []
    metadata: dict = {}
    meta: SelectionMetaDTO | None = None


class SelectionService(UseCaseService):
    """Service for selection projection tests."""

    @query
    async def get_task(cls) -> SelectionTaskDTO:
        """Get a task with nested DTO fields."""
        return SelectionTaskDTO(
            id=1,
            title="Task 1",
            owner=SelectionUserDTO(id=10, name="Alice", email="a@example.com"),
            watchers=[SelectionUserDTO(id=11, name="Bob", email="b@example.com")],
            metadata={"priority": "high", "hidden": True},
            meta=SelectionMetaDTO(source="demo"),
        )

    @query
    async def list_tasks(cls) -> list[SelectionTaskDTO]:
        """List tasks with nested DTO fields."""
        return [await cls.get_task()]

    @query
    async def get_missing_owner(cls) -> SelectionTaskDTO:
        """Return a task with a nullable nested DTO set to None."""
        return SelectionTaskDTO(id=2, title="Task 2", owner=None)

    @query
    async def list_empty(cls) -> list[SelectionTaskDTO]:
        """Return an empty task list."""
        return []

    @query
    async def get_count(cls) -> int:
        """Return a non-Pydantic value."""
        return 1

    @query
    async def list_users_with_gaps(cls) -> list[SelectionUserDTO | None]:
        """Return a list with nullable DTO items."""
        return [
            SelectionUserDTO(id=11, name="Bob", email="b@example.com"),
            None,
        ]

    @query
    async def get_task_with_missing_watcher(cls) -> SelectionTaskDTO:
        """Return a DTO with a nullable list element."""
        task = await cls.get_task()
        task.watchers = [
            SelectionUserDTO(id=11, name="Bob", email="b@example.com"),
            None,
        ]
        return task


# ──────────────────────────────────────────────────
# Tests: ServiceIntrospector Selection Metadata
# ──────────────────────────────────────────────────


class TestServiceIntrospectorSelection:
    def test_describe_service_includes_selection_usage(self):
        """describe_service includes selection_usage metadata."""
        introspector = ServiceIntrospector([SelectionService])
        info = introspector.describe_service("SelectionService")
        assert info is not None
        assert info["selection_usage"]["format"].startswith("Rootless GraphQL-like")
        assert "types" in info["selection_usage"]["source"]
        assert any(
            "Nested Pydantic DTO fields require sub-selection." == rule
            for rule in info["selection_usage"]["rules"]
        )

    def test_describe_service_marks_selection_capability_per_method(self):
        """Methods returning DTOs get selection_supported=True, others False."""
        introspector = ServiceIntrospector([SelectionService])
        info = introspector.describe_service("SelectionService")
        assert info is not None

        methods = {m["name"]: m for m in info["methods"]}

        get_task = methods["get_task"]
        assert get_task["selection_supported"] is True
        assert get_task["selection_example"] is not None
        assert "id" in get_task["selection_example"]

        get_count = methods["get_count"]
        assert get_count["selection_supported"] is False
        assert get_count["selection_example"] is None


# ──────────────────────────────────────────────────

# ──────────────────────────────────────────────────
# Tests: introspector type-machinery branches
# ──────────────────────────────────────────────────


class TestTypeToParamSchema:
    """_type_to_param_schema — JSON-Schema-lite for method parameters."""

    def test_unresolved_string_annotation(self):
        assert _type_to_param_schema("UserDTO") == {
            "type": "string",
            "description": "<unresolved: UserDTO>",
        }

    def test_dict_maps_to_object(self):
        assert _type_to_param_schema(dict) == {"type": "object"}

    def test_dto_maps_to_object_with_title(self):
        assert _type_to_param_schema(UserDTO) == {
            "type": "object",
            "title": "UserDTO",
        }

    def test_list_of_scalar(self):
        assert _type_to_param_schema(list[int]) == {
            "type": "array",
            "items": {"type": "integer"},
        }

    def test_bare_typing_list(self):
        # Bare (unparameterized) typing.List: origin is list, no args.
        assert _type_to_param_schema(typing.List) == {"type": "array"}  # noqa: UP006

    def test_optional_scalar(self):
        assert _type_to_param_schema(int | None) == {
            "anyOf": [{"type": "integer"}, {"type": "null"}],
        }

    def test_optional_list(self):
        schema = _type_to_param_schema(list[int] | None)
        assert schema == {
            "anyOf": [
                {"type": "array", "items": {"type": "integer"}},
                {"type": "null"},
            ],
        }

    def test_multi_arm_union_without_none(self):
        schema = _type_to_param_schema(int | str)
        assert schema == {"anyOf": [{"type": "integer"}, {"type": "string"}]}

    def test_annotated_unwraps_to_inner(self):
        assert _type_to_param_schema(Annotated[int, "docs"]) == {"type": "integer"}

    def test_unresolvable_returns_empty(self):
        # Union of two non-None types that BOTH fail to map → empty schema.
        assert _type_to_param_schema(typing.Union[object, bytes]) == {}  # noqa: UP007


class TestTypeNames:
    def test_sdl_bare_typing_list(self):
        assert _type_to_sdl_name(typing.List) == "[String!]!"  # noqa: UP006

    def test_sdl_union_without_none_uses_first_arm(self):
        assert _type_to_sdl_name(int | str) == "Int!"

    def test_sdl_dict_is_json(self):
        assert _type_to_sdl_name(dict) == "JSON"

    def test_sdl_plain_class_falls_back_to_name(self):
        import datetime

        assert _type_to_sdl_name(datetime.date) == "Date!"

    def test_sdl_non_type_annotation_is_string(self):
        assert _type_to_sdl_name(object()) == "String"

    def test_legacy_string_annotation(self):
        assert _type_to_legacy_name("UserDTO") == "string"

    def test_legacy_bare_typing_list(self):
        assert _type_to_legacy_name(typing.List) == "list[any]"  # noqa: UP006

    def test_legacy_optional_scalar(self):
        assert _type_to_legacy_name(int | None) == "int"

    def test_legacy_union_without_none(self):
        assert _type_to_legacy_name(int | str) == "int"

    def test_legacy_dict(self):
        assert _type_to_legacy_name(dict) == "dict"

    def test_legacy_plain_class(self):
        import datetime

        assert _type_to_legacy_name(datetime.date) == "date"


class TestCollectDtoTypes:
    def test_bare_list_is_empty(self):
        # Intentional VALUE (bare typing.List), not an annotation.
        assert _collect_dto_types(typing.List) == []  # noqa: UP006

    def test_annotated_unwraps(self):
        assert _collect_dto_types(Annotated[UserDTO, "meta"]) == [UserDTO]

    def test_union_collects_all_arms(self):
        result = _collect_dto_types(list[UserDTO] | TaskDTO)
        assert UserDTO in result and TaskDTO in result


class TestSelectionHelpers:
    def test_get_selection_model_rejects_string(self):
        assert _get_selection_model("UserDTO") is None

    def test_get_selection_model_rejects_multi_dto_union(self):
        assert _get_selection_model(UserDTO | TaskDTO) is None

    def test_collect_core_types_list_and_union(self):
        assert _collect_core_types(list[int]) == [int]
        assert _collect_core_types(int | str) == [int, str]
        assert _collect_core_types(Annotated[int, "m"]) == [int]
        assert _collect_core_types("UserDTO") == []

    def test_example_two_scalars_picks_first_two(self):
        class TwoScalars(BaseModel):
            a: int
            b: str

        assert _build_selection_example(TwoScalars) == "{ a b }"

    def test_example_self_referencing_guard(self):
        class NodeDTO(BaseModel):
            name: str
            child: NodeDTO | None = None

        NodeDTO.model_rebuild()
        # Cycle guard returns a scalar-only example instead of looping.
        example = _build_selection_example(NodeDTO)
        assert example is not None
        assert "name" in example


class _FkBase(SQLModel):
    pass


class FkOwner(_FkBase, table=True):
    __tablename__ = "intros_fk_owner"
    id: int | None = SQLField(default=None, primary_key=True)
    name: str


class FkItem(_FkBase, table=True):
    __tablename__ = "intros_fk_item"
    id: int | None = SQLField(default=None, primary_key=True)
    owner_id: int = SQLField(foreign_key="intros_fk_owner.id")
    title: str


class FkItemDTO(DefineSubset):
    """An item DTO."""

    __subset__ = (FkItem, ("id", "owner_id", "title"))


class TestDtoSdlGeneration:
    def test_fk_field_hidden_from_sdl(self):
        assert _is_fk_field("owner_id", FkItemDTO) is True
        assert _is_fk_field("title", FkItemDTO) is False

        sdl = _generate_dto_sdl(FkItemDTO)
        assert "owner_id" not in sdl
        assert "title" in sdl

    def test_docstring_rendered_as_type_description(self):
        class DocDTO(BaseModel):
            """Documented DTO."""

            id: int

        sdl = _generate_dto_sdl(DocDTO)
        assert '"""Documented DTO."""' in sdl


class DoclessService(UseCaseService):
    # No class docstring — auto summary must come from method docstrings.

    @query
    async def first(cls) -> int:
        """First method docstring."""
        return 1

    @query
    async def second(cls) -> int:
        """Second method docstring."""
        return 2


class BareService(UseCaseService):
    # No docstrings anywhere — auto summary falls back to name + count.

    @query
    async def only(cls) -> int:
        return 1


class ComplexParamsService(UseCaseService):
    """Service exercising composite parameter annotations end-to-end."""

    @query
    async def by_ids(cls, ids: list[int]) -> int:
        """List param."""
        return len(ids)

    @query
    async def maybe(cls, hint: str | None = None) -> str:
        """Optional param."""
        return hint or "none"

    @query
    async def either(cls, key: Annotated[int, "the key"]) -> int:
        """Annotated param."""
        return key

    @query
    async def raw(cls) -> int | str:
        """Union return — selection unsupported."""
        return 0


class TestAutoSummaryAndComplexParams:
    def test_summary_from_method_docstrings(self):
        assert _auto_summary(DoclessService) == (
            "First method docstring.; Second method docstring."
        )

    def test_summary_fallback_name_and_count(self):
        assert _auto_summary(BareService) == "BareService — 1 methods"

    def test_list_services_uses_auto_summary(self):
        introspector = ServiceIntrospector([DoclessService])
        listing = introspector.list_services()
        assert listing[0]["description"] == (
            "First method docstring.; Second method docstring."
        )

    def test_composite_params_in_describe_service(self):
        introspector = ServiceIntrospector([ComplexParamsService])
        info = introspector.describe_service("ComplexParamsService")
        assert info is not None
        methods = {m["name"]: m for m in info["methods"]}

        assert methods["by_ids"]["parameters"]["ids"] == {
            "type": "array",
            "items": {"type": "integer"},
        }
        assert methods["maybe"]["parameters"]["hint"] == {
            "anyOf": [{"type": "string"}, {"type": "null"}],
        }
        assert methods["either"]["parameters"]["key"] == {"type": "integer"}

        # Union return type → selection unsupported, but SDL signature renders.
        assert methods["raw"]["selection_supported"] is False
        assert ": Int" in methods["raw"]["signature_sdl"]


class TestTypeMappingSingleSource:
    """Type-mapping single-source convergence: introspector's SDL names now
    come from the shared ComposeTypeMapper (same names the compose MCP
    schema exposes) — the former 4-entry private table described datetime
    as "datetime" (class-name fallback) and invented a "JSON" scalar."""

    def test_datetime_is_a_real_scalar_now(self):
        import datetime

        assert _type_to_sdl_name(datetime.datetime) == "DateTime!"
        assert _type_to_sdl_name(datetime.date) == "Date!"

    def test_uuid_comes_from_the_shared_table(self):
        import uuid

        # Used to be "UUID" only by luck (class-name fallback happened to
        # match); now it is the registered scalar name, same as compose.
        assert _type_to_sdl_name(uuid.UUID) == "UUID!"

    def test_dict_keeps_descriptive_json(self):
        # compose rejects dict outright; describe renders the conventional
        # JSON scalar name instead of failing the whole description.
        assert _type_to_sdl_name(dict) == "JSON"

    def test_scalar_table_is_single_sourced(self):
        from nexusx.type_converter import SCALAR_TYPE_MAP
        from nexusx.use_case import compose_type_mapper

        assert compose_type_mapper._SCALAR_NAMES is SCALAR_TYPE_MAP

    def test_type_ref_renderer_is_public(self):
        from nexusx.use_case.compose_schema import TypeRef, type_ref_to_sdl

        nested = TypeRef(kind="NON_NULL", name=None,
                         of_type=TypeRef(kind="LIST", name=None,
                                         of_type=TypeRef(kind="NON_NULL", name=None,
                                                         of_type=TypeRef(kind="SCALAR", name="Int", of_type=None))))
        assert type_ref_to_sdl(nested) == "[Int!]!"
