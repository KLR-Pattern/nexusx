"""Regression coverage for Literal fields in compose DTOs."""

import enum
from typing import Literal

import pytest
from pydantic import BaseModel

from nexusx.decorator import query
from nexusx.use_case.business import UseCaseService
from nexusx.use_case.compose_executor import execute_compose_query
from nexusx.use_case.compose_schema import UnsupportedTypeError, build_compose_schema
from nexusx.use_case.compose_type_mapper import ComposeTypeMapper, describe_literal_values
from nexusx.use_case.types import UseCaseAppConfig


class FollowUpTaskDTO(BaseModel):
    title: str
    status: Literal["open"] = "open"


class TaskStatus(str, enum.Enum):
    OPEN = "open"


class MeetingService(UseCaseService):
    @query
    async def list_follow_up_tasks(cls) -> list[FollowUpTaskDTO]: ...

    @query
    async def echo_status(cls, status: Literal["open", "closed"]) -> str:
        return status


def test_compose_schema_supports_single_string_literal_dto_field() -> None:
    schema = build_compose_schema(
        UseCaseAppConfig(name="meeting-literal", services=[MeetingService])
    )

    task_type = schema.registry["FollowUpTaskDTO"]
    status_field = next(field for field in task_type.fields if field.name == "status")

    assert status_field.type_ref.kind == "NON_NULL"
    assert status_field.type_ref.of_type is not None
    assert status_field.type_ref.of_type.kind == "SCALAR"
    assert status_field.type_ref.of_type.name == "String"


def test_compose_type_mapper_supports_multiple_literals_of_one_type() -> None:
    ref = ComposeTypeMapper().map_python_type(Literal["open", "closed"])

    assert ref.kind == "NON_NULL"
    assert ref.of_type is not None
    assert ref.of_type.kind == "SCALAR"
    assert ref.of_type.name == "String"


def test_compose_type_mapper_treats_none_literal_as_nullable() -> None:
    ref = ComposeTypeMapper().map_python_type(Literal["open", None])

    assert ref.kind == "SCALAR"
    assert ref.name == "String"


def test_compose_type_mapper_rejects_mixed_literal_types() -> None:
    with pytest.raises(UnsupportedTypeError, match="must share one Python type"):
        ComposeTypeMapper().map_python_type(Literal["open", 1])


def test_compose_type_mapper_rejects_enum_member_literals() -> None:
    with pytest.raises(UnsupportedTypeError, match="Use the enum class directly"):
        ComposeTypeMapper().map_python_type(Literal[TaskStatus.OPEN])


@pytest.mark.parametrize(
    ("status", "has_errors"),
    [("open", False), ("pending", True)],
)
async def test_literal_argument_constraints_are_enforced(status: str, has_errors: bool) -> None:
    app = UseCaseAppConfig(name="meeting-literal-input", services=[MeetingService])
    schema = build_compose_schema(app)

    result = await execute_compose_query(
        app,
        schema,
        f'{{ MeetingService {{ echo_status(status: "{status}") }} }}',
    )

    assert bool(result["errors"]) is has_errors
    if not has_errors:
        assert result["data"]["MeetingService"]["echo_status"] == status


class DescribedTaskDTO(BaseModel):
    status: Literal["open", "closed"] = "open"
    mode: Literal["fast"] | None = None


class DescribedService(UseCaseService):
    @query
    async def pick(cls, mode: Literal["fast", "slow"]) -> DescribedTaskDTO:
        return DescribedTaskDTO(status="open")


def test_literal_field_description_lists_allowed_values() -> None:
    schema = build_compose_schema(
        UseCaseAppConfig(name="meeting-literal-desc", services=[MeetingService])
    )

    task_type = schema.registry["FollowUpTaskDTO"]
    status_field = next(field for field in task_type.fields if field.name == "status")

    assert status_field.description == "Allowed values: open"


def test_literal_argument_description_lists_allowed_values() -> None:
    schema = build_compose_schema(
        UseCaseAppConfig(name="meeting-literal-arg", services=[MeetingService])
    )

    service_type = schema.registry["MeetingServiceQuery"]
    method = next(f for f in service_type.fields if f.name == "echo_status")
    status_arg = next(a for a in method.args if a.name == "status")

    assert status_arg.description == "Allowed values: open, closed"


def test_existing_description_is_kept_and_extended() -> None:
    schema = build_compose_schema(
        UseCaseAppConfig(name="described-literal", services=[DescribedService])
    )

    task_type = schema.registry["DescribedTaskDTO"]
    by_name = {f.name: f for f in task_type.fields}
    assert by_name["status"].description == "Allowed values: open, closed"
    # Optional[Literal[...]] keeps the values, the nullable type, and tells
    # agents that null is a legal input.
    assert by_name["mode"].description == "Allowed values: fast (or null)"
    assert by_name["mode"].type_ref.kind == "SCALAR"


def test_int_literal_values_render_in_description() -> None:
    assert describe_literal_values(None, Literal[1, 2]) == "Allowed values: 1, 2"
    ref = ComposeTypeMapper().map_python_type(Literal[1, 2])
    assert ref.of_type is not None and ref.of_type.name == "Int"


# ---------------------------------------------------------------------------
# Input-side surfacing — agents constructing input objects need the allowed
# values at least as much as agents reading outputs.
# ---------------------------------------------------------------------------


class TaskFilterDTO(BaseModel):
    status: Literal["open", "closed"] = "open"


class FilterService(UseCaseService):
    @query
    async def filter_tasks(cls, filt: TaskFilterDTO) -> TaskFilterDTO:
        return filt


def test_literal_input_object_field_description_lists_allowed_values() -> None:
    schema = build_compose_schema(
        UseCaseAppConfig(name="literal-input-desc", services=[FilterService])
    )

    input_type = schema.registry["TaskFilterDTOInput"]
    status_field = next(f for f in input_type.input_fields if f.name == "status")

    assert status_field.description == "Allowed values: open, closed"


# ---------------------------------------------------------------------------
# list[Literal[...]] — both unwrap implementations (type mapping + description)
# recurse through list.
# ---------------------------------------------------------------------------


class TaggedTaskDTO(BaseModel):
    tags: list[Literal["alpha", "beta"]] = []


class TaggedService(UseCaseService):
    @query
    async def tagged(cls) -> TaggedTaskDTO:
        return TaggedTaskDTO()


def test_list_of_literals_maps_to_list_of_element_scalar() -> None:
    ref = ComposeTypeMapper().map_python_type(list[Literal["alpha", "beta"]])

    assert ref.kind == "NON_NULL"
    assert ref.of_type is not None and ref.of_type.kind == "LIST"
    element = ref.of_type.of_type
    assert element is not None
    assert element.kind == "NON_NULL"
    assert element.of_type is not None and element.of_type.name == "String"


def test_list_literal_field_description_lists_allowed_values() -> None:
    schema = build_compose_schema(UseCaseAppConfig(name="list-literal", services=[TaggedService]))

    task_type = schema.registry["TaggedTaskDTO"]
    tags_field = next(f for f in task_type.fields if f.name == "tags")

    assert tags_field.description == "Allowed values: alpha, beta"


# ---------------------------------------------------------------------------
# Value formatting — descriptions must spell values the way GraphQL does.
# ---------------------------------------------------------------------------


def test_bool_literal_values_render_as_graphql_literals() -> None:
    assert describe_literal_values(None, Literal[True, False]) == ("Allowed values: true, false")


def test_none_member_literal_description_mentions_null() -> None:
    assert describe_literal_values(None, Literal["open", None]) == (
        "Allowed values: open (or null)"
    )
