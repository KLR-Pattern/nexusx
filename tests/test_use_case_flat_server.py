"""Tests for the flat MCP server — one tool per UseCase method."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from nexusx.decorator import mutation, query
from nexusx.use_case.business import UseCaseService
from nexusx.use_case.flat_server import create_flat_mcp_server
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
        return [TaskDTO(id=1, title="Task 1", owner=UserDTO(id=1, name="Alice"))]

    @query
    async def get_task(cls, task_id: int, include_owner: bool = True) -> TaskDTO | None:
        """Get a task by ID."""
        return TaskDTO(id=task_id, title="Test Task")

    @mutation
    async def delete_task(cls, task_id: int) -> bool:
        """Delete a task."""
        return True


# ──────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────

APP_NAME = "Test_App"


def _make_flat_server(enable_mutation: bool = True) -> object:
    from fastmcp import FastMCP

    config = UseCaseAppConfig(
        name=APP_NAME,
        services=[UserService, TaskService],
        enable_mutation=enable_mutation,
    )
    return create_flat_mcp_server(apps=[config], name="Test Flat API")


# ──────────────────────────────────────────────────
# Tests: Tool registration
# ──────────────────────────────────────────────────


class TestFlatToolRegistration:
    """Verify tools are registered with correct names and parameters."""

    @pytest.fixture
    def server(self):
        return _make_flat_server()

    @pytest.fixture
    def tool_names(self, server):
        import asyncio
        tools = asyncio.run(server.list_tools())
        return {t.name for t in tools}

    def test_server_creation(self, server):
        """Server is created successfully."""
        assert server is not None

    def test_tool_names(self, tool_names):
        """Each method is registered as a separate tool."""
        assert "UserService_list_users" in tool_names
        assert "UserService_get_user" in tool_names
        assert "UserService_create_user" in tool_names
        assert "TaskService_list_tasks" in tool_names
        assert "TaskService_get_task" in tool_names
        assert "TaskService_delete_task" in tool_names

    def test_tool_count(self, tool_names):
        """Total tool count matches number of methods."""
        assert len(tool_names) == 6

    def test_mutation_filtered(self):
        """enable_mutation=False excludes mutation tools."""
        import asyncio
        server = _make_flat_server(enable_mutation=False)
        tools = asyncio.run(server.list_tools())
        tool_names = {t.name for t in tools}
        assert "UserService_create_user" not in tool_names
        assert "TaskService_delete_task" not in tool_names
        assert "UserService_list_users" in tool_names
        assert "TaskService_get_task" in tool_names

    def test_tool_has_description(self, server):
        """Each tool has a description from the method docstring."""
        import asyncio
        tool = asyncio.run(server.get_tool("UserService_list_users"))
        assert "Get all users" in tool.description
        assert f"nexusx://{APP_NAME}/UserService" in tool.description

    def test_tool_parameters_exclude_cls(self, server):
        """Tool parameters do not include cls."""
        import asyncio
        tool = asyncio.run(server.get_tool("UserService_get_user"))
        schema = tool.parameters
        assert "cls" not in schema.get("properties", {})

    def test_tool_parameters_include_method_params(self, server):
        """Tool parameters include actual method parameters."""
        import asyncio
        tool = asyncio.run(server.get_tool("UserService_get_user"))
        schema = tool.parameters
        props = schema.get("properties", {})
        assert "user_id" in props

    def test_tool_includes_selection_param(self, server):
        """Tools include selection parameter."""
        import asyncio
        tool = asyncio.run(server.get_tool("UserService_list_users"))
        schema = tool.parameters
        props = schema.get("properties", {})
        assert "selection" in props


# ──────────────────────────────────────────────────
# Tests: Tool execution
# ──────────────────────────────────────────────────


class TestFlatToolExecution:
    """Verify tools execute correctly via MCP call_tool."""

    @pytest.fixture
    def server(self):
        return _make_flat_server()

    @pytest.mark.asyncio
    async def test_list_users(self, server):
        """UserService_list_users returns user list."""
        result = await server.call_tool("UserService_list_users", {})
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert len(data["data"]) == 2
        assert data["data"][0]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_get_user_found(self, server):
        """UserService_get_user returns user when found."""
        result = await server.call_tool(
            "UserService_get_user", {"user_id": 1}
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"]["id"] == 1
        assert data["data"]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_get_user_not_found(self, server):
        """UserService_get_user returns None when not found."""
        result = await server.call_tool(
            "UserService_get_user", {"user_id": 999}
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"] is None

    @pytest.mark.asyncio
    async def test_create_user_mutation(self, server):
        """UserService_create_user executes as mutation."""
        result = await server.call_tool(
            "UserService_create_user", {"name": "Charlie", "email": "c@x.com"}
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"]["name"] == "Charlie"

    @pytest.mark.asyncio
    async def test_get_task_with_defaults(self, server):
        """TaskService_get_task uses default parameter values."""
        result = await server.call_tool(
            "TaskService_get_task", {"task_id": 42}
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert data["data"]["id"] == 42

    @pytest.mark.asyncio
    async def test_selection_projection(self, server):
        """Selection parameter projects response fields."""
        result = await server.call_tool(
            "UserService_list_users",
            {"selection": "{ id name }"},
        )
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        assert len(data["data"]) == 2


# ──────────────────────────────────────────────────
# Tests: Resources
# ──────────────────────────────────────────────────


class TestFlatResources:
    """Verify MCP resources are registered and return correct content."""

    @pytest.fixture
    def server(self):
        return _make_flat_server()

    @pytest.mark.asyncio
    async def test_app_resource(self, server):
        """nexusx://{app_name} returns app overview."""
        result = await server.read_resource(f"nexusx://{APP_NAME}")
        content = str(result)
        assert "UserService" in content
        assert "TaskService" in content
        assert "Services" in content

    @pytest.mark.asyncio
    async def test_service_resource(self, server):
        """nexusx://{app_name}/{service_name} returns method signatures + types."""
        result = await server.read_resource(f"nexusx://{APP_NAME}/UserService")
        content = str(result)
        assert "list_users" in content
        assert "get_user" in content
        assert "create_user" in content
        assert "UserDTO" in content

    @pytest.mark.asyncio
    async def test_service_resource_has_sdl_types(self, server):
        """Service resource includes SDL type definitions."""
        result = await server.read_resource(f"nexusx://{APP_NAME}/TaskService")
        content = str(result)
        assert "TaskDTO" in content
        assert "UserDTO" in content

    @pytest.mark.asyncio
    async def test_service_resource_mutation_filtered(self):
        """Service resource filters mutations when disabled."""
        server = _make_flat_server(enable_mutation=False)
        result = await server.read_resource(f"nexusx://{APP_NAME}/UserService")
        content = str(result)
        assert "create_user" not in content
        assert "list_users" in content


# ──────────────────────────────────────────────────
# Tests: Empty apps validation
# ──────────────────────────────────────────────────


class TestFlatServerValidation:
    def test_empty_apps_raises(self):
        """Empty apps list raises ValueError."""
        with pytest.raises(ValueError, match="empty"):
            create_flat_mcp_server(apps=[])
