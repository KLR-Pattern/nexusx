"""Regression coverage for Literal fields in compose DTOs."""

import enum
from typing import Literal

import pytest
from pydantic import BaseModel

from nexusx.decorator import query
from nexusx.use_case.business import UseCaseService
from nexusx.use_case.compose_executor import execute_compose_query
from nexusx.use_case.compose_schema import UnsupportedTypeError, build_compose_schema
from nexusx.use_case.compose_type_mapper import ComposeTypeMapper
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
