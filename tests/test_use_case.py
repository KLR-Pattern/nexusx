"""Tests for the UseCase module — UseCaseService, ServiceIntrospector, and MCP server."""

from __future__ import annotations

import datetime
import json
import uuid
from decimal import Decimal

import pytest
from pydantic import BaseModel

from nexusx.decorator import mutation, query
from nexusx.use_case.business import UseCaseService
from nexusx.use_case.introspector import (
    ServiceIntrospector,
    _type_to_sdl_name,
)
from nexusx.use_case.server import create_use_case_mcp_server
from nexusx.use_case.types import UseCaseAppConfig

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
        assert _type_to_sdl_name(int) == "Int"

    def test_str(self):
        assert _type_to_sdl_name(str) == "String"

    def test_float(self):
        assert _type_to_sdl_name(float) == "Float"

    def test_bool(self):
        assert _type_to_sdl_name(bool) == "Boolean"

    def test_list_of_int(self):
        assert _type_to_sdl_name(list[int]) == "[Int!]!"

    def test_optional_int(self):
        assert _type_to_sdl_name(int | None) == "Int"

    def test_list_of_dto(self):
        assert _type_to_sdl_name(list[UserDTO]) == "[UserDTO!]!"

    def test_optional_dto(self):
        assert _type_to_sdl_name(UserDTO | None) == "UserDTO"

    def test_dto_class(self):
        assert _type_to_sdl_name(UserDTO) == "UserDTO"

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
# Tests: MCP Server (integration)
# ──────────────────────────────────────────────────

APP_NAME = "test_app"


def _make_mcp_server():
    return create_use_case_mcp_server(
        apps=[
            UseCaseAppConfig(
                name=APP_NAME,
                services=[UserService, TaskService],
                description="Test app",
            ),
        ],
        name="Test UseCase API",
    )


def _make_mcp_server_no_mutation():
    return create_use_case_mcp_server(
        apps=[
            UseCaseAppConfig(
                name=APP_NAME,
                services=[UserService, TaskService],
                description="Test app",
                enable_mutation=False,
            ),
        ],
        name="Test UseCase API",
    )


class TestUseCaseMcpServer:
    @pytest.fixture
    def mcp_server(self):
        return _make_mcp_server()

    def test_server_creation(self, mcp_server):
        """Server is created successfully with 4 tools."""
        assert mcp_server is not None

    @pytest.mark.asyncio
    async def test_list_apps(self, mcp_server):
        """list_apps returns all registered apps."""
        result = await mcp_server.call_tool("list_apps", {})
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert len(data["data"]) == 1
        assert data["data"][0]["name"] == APP_NAME
        assert data["data"][0]["services_count"] == 2

    @pytest.mark.asyncio
    async def test_list_services_tool(self, mcp_server):
        """list_services returns all registered services for an app."""
        result = await mcp_server.call_tool("list_services", {"app_name": APP_NAME})
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert len(data["data"]) == 2

    @pytest.mark.asyncio
    async def test_list_services_case_insensitive(self, mcp_server):
        """list_services works with case-insensitive app name."""
        result = await mcp_server.call_tool("list_services", {"app_name": "Test_App"})
        data = json.loads(result.content[0].text)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_describe_service_tool(self, mcp_server):
        """describe_service returns method details with SDL signatures."""
        result = await mcp_server.call_tool(
            "describe_service",
            {"app_name": APP_NAME, "service_name": "UserService"},
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"]["name"] == "UserService"
        assert len(data["data"]["methods"]) == 3
        # Check that types field has SDL
        assert "type UserDTO" in data["data"]["types"]

    @pytest.mark.asyncio
    async def test_describe_service_method_kind(self, mcp_server):
        """describe_service methods include kind field."""
        result = await mcp_server.call_tool(
            "describe_service",
            {"app_name": APP_NAME, "service_name": "UserService"},
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True

        methods = data["data"]["methods"]
        list_users = next(m for m in methods if m["name"] == "list_users")
        assert list_users["kind"] == "query"

        create_user = next(m for m in methods if m["name"] == "create_user")
        assert create_user["kind"] == "mutation"

    @pytest.mark.asyncio
    async def test_describe_service_not_found(self, mcp_server):
        """describe_service returns error for unknown service."""
        result = await mcp_server.call_tool(
            "describe_service",
            {"app_name": APP_NAME, "service_name": "unknown"},
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_call_use_case_no_params(self, mcp_server):
        """call_use_case works with no parameters."""
        result = await mcp_server.call_tool(
            "call_use_case",
            {
                "app_name": APP_NAME,
                "service_name": "UserService",
                "method_name": "list_users",
                "params": "{}",
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert len(data["data"]) == 2
        assert data["data"][0]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_call_use_case_with_params(self, mcp_server):
        """call_use_case passes parameters to the method."""
        result = await mcp_server.call_tool(
            "call_use_case",
            {
                "app_name": APP_NAME,
                "service_name": "UserService",
                "method_name": "get_user",
                "params": json.dumps({"user_id": 1}),
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"]["id"] == 1
        assert data["data"]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_call_use_case_returns_null(self, mcp_server):
        """call_use_case handles None return values."""
        result = await mcp_server.call_tool(
            "call_use_case",
            {
                "app_name": APP_NAME,
                "service_name": "UserService",
                "method_name": "get_user",
                "params": json.dumps({"user_id": 999}),
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"] is None

    @pytest.mark.asyncio
    async def test_call_use_case_app_not_found(self, mcp_server):
        """call_use_case returns error for unknown app."""
        result = await mcp_server.call_tool(
            "call_use_case",
            {
                "app_name": "unknown",
                "service_name": "UserService",
                "method_name": "list_users",
                "params": "{}",
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_call_use_case_service_not_found(self, mcp_server):
        """call_use_case returns error for unknown service."""
        result = await mcp_server.call_tool(
            "call_use_case",
            {
                "app_name": APP_NAME,
                "service_name": "unknown",
                "method_name": "foo",
                "params": "{}",
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_call_use_case_method_not_found(self, mcp_server):
        """call_use_case returns error for unknown method."""
        result = await mcp_server.call_tool(
            "call_use_case",
            {
                "app_name": APP_NAME,
                "service_name": "UserService",
                "method_name": "nonexistent",
                "params": "{}",
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_call_use_case_invalid_json(self, mcp_server):
        """call_use_case returns error for invalid JSON params."""
        result = await mcp_server.call_tool(
            "call_use_case",
            {
                "app_name": APP_NAME,
                "service_name": "UserService",
                "method_name": "list_users",
                "params": "invalid",
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_call_use_case_invalid_param_type(self, mcp_server):
        """call_use_case returns error when params is not a dict."""
        result = await mcp_server.call_tool(
            "call_use_case",
            {
                "app_name": APP_NAME,
                "service_name": "UserService",
                "method_name": "list_users",
                "params": "[1,2]",
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_call_use_case_wrong_param_name(self, mcp_server):
        """call_use_case returns error when parameter name doesn't match."""
        result = await mcp_server.call_tool(
            "call_use_case",
            {
                "app_name": APP_NAME,
                "service_name": "UserService",
                "method_name": "get_user",
                "params": json.dumps({"wrong_param": 1}),
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is False


# ──────────────────────────────────────────────────
# Tests: enable_mutation filtering
# ──────────────────────────────────────────────────


class TestEnableMutation:
    @pytest.fixture
    def mcp_server_no_mutation(self):
        return _make_mcp_server_no_mutation()

    @pytest.mark.asyncio
    async def test_list_services_filters_mutation_count(self, mcp_server_no_mutation):
        """list_services hides mutation methods from count when enable_mutation=False."""
        result = await mcp_server_no_mutation.call_tool("list_services", {"app_name": APP_NAME})
        data = json.loads(result.content[0].text)
        assert data["success"] is True

        user_svc = next(s for s in data["data"] if s["name"] == "UserService")
        # Only 2 query methods, create_user (mutation) filtered out
        assert user_svc["methods_count"] == 2

    @pytest.mark.asyncio
    async def test_describe_service_filters_mutations(self, mcp_server_no_mutation):
        """describe_service hides mutation methods when enable_mutation=False."""
        result = await mcp_server_no_mutation.call_tool(
            "describe_service",
            {"app_name": APP_NAME, "service_name": "UserService"},
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True

        method_names = [m["name"] for m in data["data"]["methods"]]
        assert "list_users" in method_names
        assert "get_user" in method_names
        assert "create_user" not in method_names  # mutation filtered

    @pytest.mark.asyncio
    async def test_call_mutation_blocked(self, mcp_server_no_mutation):
        """call_use_case blocks mutation methods when enable_mutation=False."""
        result = await mcp_server_no_mutation.call_tool(
            "call_use_case",
            {
                "app_name": APP_NAME,
                "service_name": "UserService",
                "method_name": "create_user",
                "params": json.dumps({"name": "Test", "email": "test@test.com"}),
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is False
        assert "mutation" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_call_query_still_works(self, mcp_server_no_mutation):
        """call_use_case still allows query methods when enable_mutation=False."""
        result = await mcp_server_no_mutation.call_tool(
            "call_use_case",
            {
                "app_name": APP_NAME,
                "service_name": "UserService",
                "method_name": "list_users",
                "params": "{}",
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert len(data["data"]) == 2


# ──────────────────────────────────────────────────
# Tests: Type Coercion (Pydantic TypeAdapter)
# ──────────────────────────────────────────────────


@pytest.fixture
def type_coercion_server():
    return create_use_case_mcp_server(
        apps=[
            UseCaseAppConfig(
                name="test",
                services=[TypeCoercionService],
            ),
        ],
    )


class TestTypeCoercion:
    """Tests for Pydantic TypeAdapter-based parameter type coercion."""

    @pytest.mark.asyncio
    async def test_uuid_param_coerced(self, type_coercion_server):
        """UUID string is coerced to uuid.UUID."""
        test_uuid = "550e8400-e29b-41d4-a716-446655440000"
        result = await type_coercion_server.call_tool(
            "call_use_case",
            {
                "app_name": "test",
                "service_name": "TypeCoercionService",
                "method_name": "get_by_uuid",
                "params": json.dumps({"item_id": test_uuid}),
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"] == f"uuid:4:{test_uuid}"

    @pytest.mark.asyncio
    async def test_datetime_param_coerced(self, type_coercion_server):
        """ISO datetime string is coerced to datetime.datetime."""
        result = await type_coercion_server.call_tool(
            "call_use_case",
            {
                "app_name": "test",
                "service_name": "TypeCoercionService",
                "method_name": "get_by_datetime",
                "params": json.dumps({"ts": "2024-01-15T10:30:00"}),
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"] == "dt:2024-01-15T10:30:00"

    @pytest.mark.asyncio
    async def test_date_param_coerced(self, type_coercion_server):
        """ISO date string is coerced to datetime.date."""
        result = await type_coercion_server.call_tool(
            "call_use_case",
            {
                "app_name": "test",
                "service_name": "TypeCoercionService",
                "method_name": "get_by_date",
                "params": json.dumps({"d": "2024-01-15"}),
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"] == "date:2024-01-15"

    @pytest.mark.asyncio
    async def test_time_param_coerced(self, type_coercion_server):
        """ISO time string is coerced to datetime.time."""
        result = await type_coercion_server.call_tool(
            "call_use_case",
            {
                "app_name": "test",
                "service_name": "TypeCoercionService",
                "method_name": "get_by_time",
                "params": json.dumps({"t": "10:30:00"}),
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"] == "time:10:30:00"

    @pytest.mark.asyncio
    async def test_decimal_param_coerced(self, type_coercion_server):
        """Decimal string is coerced to Decimal."""
        result = await type_coercion_server.call_tool(
            "call_use_case",
            {
                "app_name": "test",
                "service_name": "TypeCoercionService",
                "method_name": "get_by_decimal",
                "params": json.dumps({"amount": "19.99"}),
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"] == "decimal:19.99"

    @pytest.mark.asyncio
    async def test_optional_uuid_with_value(self, type_coercion_server):
        """UUID string is coerced in Optional[UUID] param."""
        test_uuid = "550e8400-e29b-41d4-a716-446655440000"
        result = await type_coercion_server.call_tool(
            "call_use_case",
            {
                "app_name": "test",
                "service_name": "TypeCoercionService",
                "method_name": "get_optional_uuid",
                "params": json.dumps({"item_id": test_uuid}),
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"] == f"uuid:{test_uuid}"

    @pytest.mark.asyncio
    async def test_optional_uuid_with_null(self, type_coercion_server):
        """None value works for Optional[UUID] param."""
        result = await type_coercion_server.call_tool(
            "call_use_case",
            {
                "app_name": "test",
                "service_name": "TypeCoercionService",
                "method_name": "get_optional_uuid",
                "params": json.dumps({"item_id": None}),
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"] == "uuid:None"

    @pytest.mark.asyncio
    async def test_optional_datetime_with_null(self, type_coercion_server):
        """None value works for Optional[datetime] param."""
        result = await type_coercion_server.call_tool(
            "call_use_case",
            {
                "app_name": "test",
                "service_name": "TypeCoercionService",
                "method_name": "get_optional_datetime",
                "params": json.dumps({"ts": None}),
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"] == "dt:none"

    @pytest.mark.asyncio
    async def test_uuid_list_coerced(self, type_coercion_server):
        """List of UUID strings is coerced to list[uuid.UUID]."""
        ids = [
            "550e8400-e29b-41d4-a716-446655440000",
            "6fa459ea-ee8a-3ca4-894e-db77e160355e",
        ]
        result = await type_coercion_server.call_tool(
            "call_use_case",
            {
                "app_name": "test",
                "service_name": "TypeCoercionService",
                "method_name": "get_by_uuid_list",
                "params": json.dumps({"ids": ids}),
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"] == f"ids:{','.join(ids)}"

    @pytest.mark.asyncio
    async def test_basemodel_param_coerced(self, type_coercion_server):
        """Dict is coerced to BaseModel, including nested UUID/datetime fields."""
        event_data = {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "name": "test_event",
            "occurred_at": "2024-01-15T10:30:00",
            "event_date": "2024-01-15",
            "event_time": "10:30:00",
        }
        result = await type_coercion_server.call_tool(
            "call_use_case",
            {
                "app_name": "test",
                "service_name": "TypeCoercionService",
                "method_name": "create_event",
                "params": json.dumps({"event": event_data}),
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert "550e8400-e29b-41d4-a716-446655440000" in data["data"]
        assert "test_event" in data["data"]

    @pytest.mark.asyncio
    async def test_mixed_types_coerced(self, type_coercion_server):
        """Mixed types: UUID and datetime coerced, str and int pass through."""
        test_uuid = "550e8400-e29b-41d4-a716-446655440000"
        result = await type_coercion_server.call_tool(
            "call_use_case",
            {
                "app_name": "test",
                "service_name": "TypeCoercionService",
                "method_name": "get_with_mixed_types",
                "params": json.dumps(
                    {
                        "item_id": test_uuid,
                        "ts": "2024-01-15T10:30:00",
                        "name": "hello",
                        "count": 42,
                    }
                ),
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"] == f"mixed:{test_uuid}:2024-01-15T10:30:00:hello:42"

    @pytest.mark.asyncio
    async def test_existing_simple_params_still_work(self):
        """Regression: simple int param still works after adding coercion."""
        mcp_server = _make_mcp_server()
        result = await mcp_server.call_tool(
            "call_use_case",
            {
                "app_name": APP_NAME,
                "service_name": "UserService",
                "method_name": "get_user",
                "params": json.dumps({"user_id": 1}),
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_basemodel_register_works(self):
        """BaseModel parameter (CreateUserDTO) is coerced from dict."""
        mcp_server = _make_mcp_server()
        result = await mcp_server.call_tool(
            "call_use_case",
            {
                "app_name": APP_NAME,
                "service_name": "UserService",
                "method_name": "create_user",
                "params": json.dumps(
                    {"name": "Charlie", "email": "c@test.com"}
                ),
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"]["name"] == "Charlie"


# ──────────────────────────────────────────────────
# Test DTOs and Services for Selection
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
# Tests: MCP Server Selection (integration)
# ──────────────────────────────────────────────────


@pytest.fixture
def selection_server():
    return create_use_case_mcp_server(
        apps=[
            UseCaseAppConfig(
                name="selection",
                services=[SelectionService],
            ),
        ],
    )


class TestUseCaseMcpServerSelection:
    """Tests for call_use_case selection projection."""

    @pytest.mark.asyncio
    async def test_describe_service_includes_selection_usage(self, selection_server):
        """describe_service response contains selection_usage."""
        result = await selection_server.call_tool(
            "describe_service",
            {"app_name": "selection", "service_name": "SelectionService"},
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        get_user = next(
            m for m in data["data"]["methods"] if m["name"] == "get_task"
        )
        assert get_user["selection_supported"] is True
        assert get_user["selection_example"] is not None
        assert data["data"]["selection_usage"]["format"].startswith(
            "Rootless GraphQL-like"
        )
        assert "selection_supported=true" in data["hint"]

    @pytest.mark.asyncio
    async def test_selection_filters_single_dto(self, selection_server):
        result = await selection_server.call_tool(
            "call_use_case",
            {
                "app_name": "selection",
                "service_name": "SelectionService",
                "method_name": "get_task",
                "params": "{}",
                "selection": "{ id owner { name } }",
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"]["id"] == 1
        assert "title" not in data["data"]
        assert data["data"]["owner"]["name"] == "Alice"
        assert "email" not in data["data"]["owner"]

    @pytest.mark.asyncio
    async def test_selection_filters_list_dto(self, selection_server):
        result = await selection_server.call_tool(
            "call_use_case",
            {
                "app_name": "selection",
                "service_name": "SelectionService",
                "method_name": "list_tasks",
                "params": "{}",
                "selection": "{ watchers { name } }",
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert len(data["data"]) == 1
        assert "id" not in data["data"][0]
        assert len(data["data"][0]["watchers"]) == 1
        assert data["data"][0]["watchers"][0]["name"] == "Bob"

    @pytest.mark.asyncio
    async def test_selection_preserves_none_in_top_level_list(self, selection_server):
        result = await selection_server.call_tool(
            "call_use_case",
            {
                "app_name": "selection",
                "service_name": "SelectionService",
                "method_name": "list_users_with_gaps",
                "params": "{}",
                "selection": "{ name }",
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"][0]["name"] == "Bob"
        assert data["data"][1] is None

    @pytest.mark.asyncio
    async def test_selection_preserves_none_in_nested_list(self, selection_server):
        result = await selection_server.call_tool(
            "call_use_case",
            {
                "app_name": "selection",
                "service_name": "SelectionService",
                "method_name": "get_task_with_missing_watcher",
                "params": "{}",
                "selection": "{ watchers { name } }",
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"]["watchers"][0]["name"] == "Bob"
        assert data["data"]["watchers"][1] is None

    @pytest.mark.asyncio
    async def test_selection_preserves_none_nested_dto(self, selection_server):
        result = await selection_server.call_tool(
            "call_use_case",
            {
                "app_name": "selection",
                "service_name": "SelectionService",
                "method_name": "get_missing_owner",
                "params": "{}",
                "selection": "{ id owner { name } }",
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"]["id"] == 2
        assert data["data"]["owner"] is None

    @pytest.mark.asyncio
    async def test_selection_preserves_empty_list(self, selection_server):
        result = await selection_server.call_tool(
            "call_use_case",
            {
                "app_name": "selection",
                "service_name": "SelectionService",
                "method_name": "list_empty",
                "params": "{}",
                "selection": "{ id }",
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"] == []

    @pytest.mark.asyncio
    async def test_selection_rejects_non_pydantic_return(self, selection_server):
        result = await selection_server.call_tool(
            "call_use_case",
            {
                "app_name": "selection",
                "service_name": "SelectionService",
                "method_name": "get_count",
                "params": "{}",
                "selection": "{ id }",
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is False
        assert "selection" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_selection_rejects_unknown_field(self, selection_server):
        result = await selection_server.call_tool(
            "call_use_case",
            {
                "app_name": "selection",
                "service_name": "SelectionService",
                "method_name": "get_task",
                "params": "{}",
                "selection": "{ missing }",
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is False
        assert "Unknown field" in data["error"]

    @pytest.mark.asyncio
    async def test_selection_rejects_missing_dto_sub_selection(self, selection_server):
        result = await selection_server.call_tool(
            "call_use_case",
            {
                "app_name": "selection",
                "service_name": "SelectionService",
                "method_name": "get_task",
                "params": "{}",
                "selection": "{ owner }",
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is False
        assert "requires sub-selection" in data["error"]

    @pytest.mark.asyncio
    async def test_selection_rejects_scalar_sub_selection(self, selection_server):
        result = await selection_server.call_tool(
            "call_use_case",
            {
                "app_name": "selection",
                "service_name": "SelectionService",
                "method_name": "get_task",
                "params": "{}",
                "selection": "{ title { value } }",
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is False
        assert "cannot have sub-selection" in data["error"]

    @pytest.mark.asyncio
    async def test_selection_rejects_arguments(self, selection_server):
        result = await selection_server.call_tool(
            "call_use_case",
            {
                "app_name": "selection",
                "service_name": "SelectionService",
                "method_name": "get_task",
                "params": "{}",
                "selection": "{ watchers(limit: 1) { name } }",
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is False
        assert "arguments are not supported" in data["error"]

    @pytest.mark.asyncio
    async def test_selection_rejects_empty_string(self, selection_server):
        result = await selection_server.call_tool(
            "call_use_case",
            {
                "app_name": "selection",
                "service_name": "SelectionService",
                "method_name": "get_task",
                "params": "{}",
                "selection": "",
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is False
        assert "selection cannot be empty" in data["error"]

    @pytest.mark.asyncio
    async def test_selection_rejects_syntax_error(self, selection_server):
        result = await selection_server.call_tool(
            "call_use_case",
            {
                "app_name": "selection",
                "service_name": "SelectionService",
                "method_name": "get_task",
                "params": "{}",
                "selection": "{ id ",
            },
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is False
