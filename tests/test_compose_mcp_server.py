"""Tests for ``nexusx.use_case.compose_mcp_server`` (User Story 2 — Layers 0–2).

Exercises the 4-layer progressive-disclosure MCP server via ``call_tool``,
mirroring how an MCP client consumes the server. Layer 3 (``compose_query``)
is also covered here for envelope verification (the executor's behavior is
covered in ``test_compose_executor.py``).
"""

from __future__ import annotations

import json
from typing import Annotated, Any

import pytest
from pydantic import BaseModel

from nexusx.decorator import mutation, query
from nexusx.use_case.business import UseCaseService
from nexusx.use_case.compose_mcp_server import create_use_case_graphql_mcp_server
from nexusx.use_case.context import FromContext
from nexusx.use_case.types import UseCaseAppConfig

# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


class UserSummary(BaseModel):
    id: int
    name: str


class TaskSummary(BaseModel):
    id: int
    title: str
    owner: UserSummary | None = None


class UserService(UseCaseService):
    """User management."""

    @query
    async def list_users(cls) -> list[UserSummary]:
        return [UserSummary(id=1, name="Alice"), UserSummary(id=2, name="Bob")]

    @query
    async def get_user(cls, user_id: int) -> UserSummary | None:
        return UserSummary(id=user_id, name=f"User {user_id}")


class TaskService(UseCaseService):
    """Task management."""

    @query
    async def list_tasks(cls) -> list[TaskSummary]:
        return [TaskSummary(id=1, title="A", owner=UserSummary(id=1, name="Alice"))]

    @mutation
    async def create_task(cls, title: str) -> TaskSummary:
        return TaskSummary(id=99, title=title)


class ContextService(UseCaseService):
    """FromContext demo service."""

    @query
    async def actor_name(cls, actor: Annotated[str, FromContext()]) -> str:
        return actor


@pytest.fixture
def mcp_server():
    return create_use_case_graphql_mcp_server(
        apps=[
            UseCaseAppConfig(
                name="project",
                services=[UserService, TaskService],
                description="Project management",
            ),
            UseCaseAppConfig(
                name="admin",
                services=[ContextService],
                description="Admin app",
            ),
        ],
        name="Test MCP",
    )


async def _call(mcp_server: Any, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Invoke a tool and parse its JSON ToolResult content into a dict.

    FastMCP wraps tool return values in a ``ToolResult`` whose first content
    item is a JSON-encoded string; tests want the raw dict.
    """
    result = await mcp_server.call_tool(tool_name, args)
    return json.loads(result.content[0].text)


# ──────────────────────────────────────────────────────────────────────
# Layer 0 — list_apps
# ──────────────────────────────────────────────────────────────────────


class TestLayer0ListApps:
    async def test_returns_success_envelope(self, mcp_server) -> None:
        data = await _call(mcp_server, "list_apps", {})
        assert data["success"] is True
        assert "data" in data

    async def test_lists_all_apps_with_metadata(self, mcp_server) -> None:
        data = await _call(mcp_server, "list_apps", {})
        app_names = [a["name"] for a in data["data"]["apps"]]
        assert app_names == ["project", "admin"]
        for entry in data["data"]["apps"]:
            assert "services_count" in entry
            assert "description" in entry

    async def test_hint_points_to_describe_compose_schema(self, mcp_server) -> None:
        data = await _call(mcp_server, "list_apps", {})
        assert "describe_compose_schema" in data["data"]["hint"]


# ──────────────────────────────────────────────────────────────────────
# Layer 1 — describe_compose_schema
# ──────────────────────────────────────────────────────────────────────


class TestLayer1DescribeSchema:
    async def test_returns_success_envelope(self, mcp_server) -> None:
        data = await _call(mcp_server, "describe_compose_schema", {"app_name": "project"})
        assert data["success"] is True

    async def test_lists_services_and_methods_compactly(self, mcp_server) -> None:
        data = await _call(mcp_server, "describe_compose_schema", {"app_name": "project"})
        services = data["data"]["services"]
        svc_names = [s["name"] for s in services]
        assert "UserService" in svc_names
        assert "TaskService" in svc_names

        task_svc = next(s for s in services if s["name"] == "TaskService")
        method_names = [m["name"] for m in task_svc["methods"]]
        assert "list_tasks" in method_names
        assert "create_task" in method_names
        for m in task_svc["methods"]:
            assert m["kind"] in {"query", "mutation"}

    async def test_compact_payload_excludes_arg_details(self, mcp_server) -> None:
        data = await _call(mcp_server, "describe_compose_schema", {"app_name": "project"})
        for svc in data["data"]["services"]:
            for m in svc["methods"]:
                assert "args" not in m
                assert "return_type" not in m

    async def test_unknown_app_returns_error_envelope(self, mcp_server) -> None:
        data = await _call(mcp_server, "describe_compose_schema", {"app_name": "nope"})
        assert data["success"] is False
        assert data["error_type"] == "app_not_found"

    async def test_case_insensitive_app_lookup(self, mcp_server) -> None:
        data = await _call(mcp_server, "describe_compose_schema", {"app_name": "PROJECT"})
        assert data["success"] is True


# ──────────────────────────────────────────────────────────────────────
# Layer 2 — describe_compose_method
# ──────────────────────────────────────────────────────────────────────


class TestLayer2DescribeMethod:
    async def test_returns_args_and_return_type(self, mcp_server) -> None:
        data = await _call(
            mcp_server,
            "describe_compose_method",
            {
                "app_name": "project",
                "service_name": "UserService",
                "method_name": "get_user",
            },
        )
        assert data["success"] is True
        method = data["data"]["method"]
        assert method["name"] == "get_user"
        assert method["kind"] == "query"
        assert method["return_type"] == "UserSummary"
        arg_tuples = [(a["name"], a["type"], a["has_default"]) for a in method["args"]]
        assert arg_tuples == [("user_id", "Int!", False)]

    async def test_returns_sdl_fragment(self, mcp_server) -> None:
        data = await _call(
            mcp_server,
            "describe_compose_method",
            {
                "app_name": "project",
                "service_name": "TaskService",
                "method_name": "list_tasks",
            },
        )
        sdl = data["data"]["sdl"]
        assert "type TaskServiceQuery" in sdl
        assert "list_tasks" in sdl
        # Transitive closure of return type:
        assert "type TaskSummary" in sdl
        assert "type UserSummary" in sdl

    async def test_unknown_service_returns_service_not_found(self, mcp_server) -> None:
        data = await _call(
            mcp_server,
            "describe_compose_method",
            {"app_name": "project", "service_name": "Nope", "method_name": "anything"},
        )
        assert data["success"] is False
        assert data["error_type"] == "service_not_found"

    async def test_unknown_method_returns_method_not_found(self, mcp_server) -> None:
        data = await _call(
            mcp_server,
            "describe_compose_method",
            {
                "app_name": "project",
                "service_name": "UserService",
                "method_name": "nonexistent",
            },
        )
        assert data["success"] is False
        assert data["error_type"] == "method_not_found"

    async def test_mutation_kind_labeled_correctly(self, mcp_server) -> None:
        data = await _call(
            mcp_server,
            "describe_compose_method",
            {
                "app_name": "project",
                "service_name": "TaskService",
                "method_name": "create_task",
            },
        )
        assert data["success"] is True
        assert data["data"]["method"]["kind"] == "mutation"


# ──────────────────────────────────────────────────────────────────────
# Layer 3 — compose_query (envelope verification)
# ──────────────────────────────────────────────────────────────────────


class TestLayer3ComposeQuery:
    async def test_returns_graphql_standard_envelope(self, mcp_server) -> None:
        data = await _call(
            mcp_server,
            "compose_query",
            {"app_name": "project", "query": "{ UserService { list_users { id name } } }"},
        )
        # Layer 3 returns {data, errors}, NOT {success, data}.
        assert "data" in data
        assert "errors" in data
        assert "success" not in data

    async def test_data_nested_by_service_then_method(self, mcp_server) -> None:
        data = await _call(
            mcp_server,
            "compose_query",
            {"app_name": "project", "query": "{ UserService { list_users { id } } }"},
        )
        assert data["errors"] == []
        assert "UserService" in data["data"]
        assert "list_users" in data["data"]["UserService"]

    async def test_introspection_query_rejected_with_hint(self, mcp_server) -> None:
        data = await _call(
            mcp_server,
            "compose_query",
            {"app_name": "project", "query": "{ __schema { types { name } } }"},
        )
        assert data["data"] is None
        assert len(data["errors"]) == 1
        msg = data["errors"][0]["message"]
        assert "introspection is not available" in msg
        assert "describe_compose_schema" in msg

    async def test_unknown_app_returns_error_in_errors_array(self, mcp_server) -> None:
        data = await _call(
            mcp_server,
            "compose_query",
            {"app_name": "nope", "query": "{ X { y } }"},
        )
        assert data["data"] is None
        assert len(data["errors"]) == 1
        assert "not found" in data["errors"][0]["message"]

    async def test_wrapper_field_is_rejected(self, mcp_server) -> None:
        data = await _call(
            mcp_server,
            "compose_query",
            {"app_name": "project", "query": "{ Op { UserService { list_users { id } } } }"},
        )
        assert data["data"] is None
        assert "Service 'Op' not found" in data["errors"][0]["message"]


# ──────────────────────────────────────────────────────────────────────
# FromContext plumbing through Layer 3
# ──────────────────────────────────────────────────────────────────────


class TestFromContextPlumbing:
    async def test_missing_required_context_returns_error(self, mcp_server) -> None:
        data = await _call(
            mcp_server,
            "compose_query",
            {"app_name": "admin", "query": "{ ContextService { actor_name } }"},
        )
        assert data["data"] is None
        assert "Required FromContext parameter 'actor'" in data["errors"][0]["message"]

    async def test_context_extractor_supplies_value(self) -> None:
        async def extractor(_request):
            return {"actor": "Eve"}

        mcp = create_use_case_graphql_mcp_server(
            apps=[
                UseCaseAppConfig(
                    name="admin",
                    services=[ContextService],
                    context_extractor=extractor,
                )
            ]
        )
        data = await _call(
            mcp,
            "compose_query",
            {"app_name": "admin", "query": "{ ContextService { actor_name } }"},
        )
        assert data["errors"] == []
        assert data["data"]["ContextService"]["actor_name"] == "Eve"
