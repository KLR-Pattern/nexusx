"""Tests for ``nexusx.use_case.compose_executor`` (User Story 2 — Layer 3).

Covers FR-004a (no outer Resolver wrap), FR-006 (Layer 3 contract),
FR-008 (introspection rejection), and the executor's happy paths and
error paths.

These tests exercise ``execute_compose_query`` directly (no MCP layer).
``test_compose_mcp_server.py`` covers the 4-layer MCP server end-to-end.
"""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import BaseModel

from nexusx.decorator import mutation, query
from nexusx.use_case.business import UseCaseService
from nexusx.use_case.compose_executor import (
    execute_compose_query,
    is_introspection_query,
)
from nexusx.use_case.compose_schema import build_compose_schema
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


class _Counter:
    """Records call ordering to verify the no-double-Resolver invariant."""

    def __init__(self) -> None:
        self.calls: list[str] = []


class UserService(UseCaseService):
    """User management."""

    @query
    async def list_users(cls) -> list[UserSummary]:
        return [UserSummary(id=1, name="Alice"), UserSummary(id=2, name="Bob")]

    @query
    async def get_user(cls, user_id: int) -> UserSummary | None:
        if user_id == 1:
            return UserSummary(id=1, name="Alice")
        return None


class TaskService(UseCaseService):
    """Task management."""

    @query
    async def list_tasks(cls) -> list[TaskSummary]:
        return [
            TaskSummary(id=1, title="A", owner=UserSummary(id=1, name="Alice")),
            TaskSummary(id=2, title="B", owner=None),
        ]

    @query
    async def get_task(cls, task_id: int) -> TaskSummary | None:
        return TaskSummary(id=task_id, title=f"Task {task_id}")

    @mutation
    async def create_task(cls, title: str) -> TaskSummary:
        return TaskSummary(id=99, title=title)


class ContextService(UseCaseService):
    """Service that needs FromContext."""

    @query
    async def echo_actor(
        cls,
        actor: Annotated[str, FromContext()],
    ) -> str:
        return f"hi {actor}"


@pytest.fixture
def app() -> UseCaseAppConfig:
    return UseCaseAppConfig(
        name="project",
        services=[UserService, TaskService, ContextService],
    )


@pytest.fixture
def schema(app: UseCaseAppConfig):
    return build_compose_schema(app)


# ──────────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────────


class TestHappyPath:
    async def test_single_service_single_method(self, app, schema) -> None:
        result = await execute_compose_query(
            app, schema, "{ UserService { list_users { id name } } }"
        )
        assert result["errors"] == []
        users = result["data"]["UserService"]["list_users"]
        assert len(users) == 2
        # Field projection: only id and name should be on the model
        assert set(users[0].model_dump().keys()) == {"id", "name"}

    async def test_multi_service_query(self, app, schema) -> None:
        result = await execute_compose_query(
            app,
            schema,
            "{ UserService { list_users { id } } TaskService { list_tasks { id title } } }",
        )
        assert result["errors"] == []
        assert "UserService" in result["data"]
        assert "TaskService" in result["data"]

    async def test_wrapper_field_is_rejected(self, app, schema) -> None:
        result = await execute_compose_query(
            app,
            schema,
            "{ Op { UserService { list_users { id } } } }",
        )
        assert result["data"] is None
        assert "Service 'Op' not found" in result["errors"][0]["message"]

    async def test_method_with_args(self, app, schema) -> None:
        result = await execute_compose_query(
            app, schema, "{ TaskService { get_task(task_id: 5) { id title } } }"
        )
        task = result["data"]["TaskService"]["get_task"]
        assert task.id == 5
        assert task.title == "Task 5"

    async def test_nested_dto_projection(self, app, schema) -> None:
        result = await execute_compose_query(
            app,
            schema,
            "{ TaskService { list_tasks { id title owner { name } } } }",
        )
        tasks = result["data"]["TaskService"]["list_tasks"]
        assert tasks[0].owner.name == "Alice"
        # Only `name` requested → only `name` should be on the projected owner
        assert set(tasks[0].owner.model_dump().keys()) == {"name"}

    async def test_optional_return_none(self, app, schema) -> None:
        result = await execute_compose_query(
            app, schema, "{ UserService { get_user(user_id: 99) { id } } }"
        )
        assert result["errors"] == []
        assert result["data"]["UserService"]["get_user"] is None


# ──────────────────────────────────────────────────────────────────────
# Field projection (FR-007)
# ──────────────────────────────────────────────────────────────────────


class TestFieldProjection:
    async def test_projection_returns_subset_of_fields(self, app, schema) -> None:
        result = await execute_compose_query(
            app, schema, "{ UserService { list_users { name } } }"
        )
        users = result["data"]["UserService"]["list_users"]
        assert all(set(u.model_dump().keys()) == {"name"} for u in users)

    async def test_scalar_return_is_not_projected(self, app, schema) -> None:
        # echo_actor returns str (scalar). No sub-fields → return as-is.
        result = await execute_compose_query(
            app,
            schema,
            "{ ContextService { echo_actor } }",
            context={"actor": "Charlie"},
        )
        assert result["data"]["ContextService"]["echo_actor"] == "hi Charlie"


# ──────────────────────────────────────────────────────────────────────
# FromContext injection
# ──────────────────────────────────────────────────────────────────────


class TestFromContextInjection:
    async def test_context_value_passed_to_method(self, app, schema) -> None:
        result = await execute_compose_query(
            app,
            schema,
            "{ ContextService { echo_actor } }",
            context={"actor": "Dave"},
        )
        assert result["errors"] == []
        assert result["data"]["ContextService"]["echo_actor"] == "hi Dave"

    async def test_missing_required_from_context_errors_cleanly(
        self, app, schema
    ) -> None:
        result = await execute_compose_query(
            app,
            schema,
            "{ ContextService { echo_actor } }",
            context={},  # no "actor" key
        )
        assert result["data"] is None
        assert len(result["errors"]) == 1
        assert "Required FromContext parameter 'actor'" in result["errors"][0]["message"]


# ──────────────────────────────────────────────────────────────────────
# Introspection rejection (FR-008)
# ──────────────────────────────────────────────────────────────────────


class TestIntrospectionRejection:
    @pytest.mark.parametrize(
        "query",
        [
            "{ __schema { types { name } } }",
            "{ __type(name: \"UserSummary\") { name } }",
            "{ UserService { list_users { __typename } } }",
            "{ __schema }",
        ],
    )
    async def test_introspection_queries_rejected(
        self, app, schema, query: str
    ) -> None:
        result = await execute_compose_query(app, schema, query)
        assert result["data"] is None
        assert len(result["errors"]) == 1
        msg = result["errors"][0]["message"]
        assert "introspection is not available" in msg
        assert "describe_compose_schema" in msg

    def test_is_introspection_query_detects_schema(self) -> None:
        assert is_introspection_query("{ __schema { types { name } } }") is True

    def test_is_introspection_query_detects_type(self) -> None:
        assert is_introspection_query(
            "{ __type(name: \"X\") { name } }"
        ) is True

    def test_is_introspection_query_detects_typename_nested(self) -> None:
        assert is_introspection_query("{ A { b { __typename } } }") is True

    def test_is_introspection_query_negative_for_regular_query(self) -> None:
        assert is_introspection_query("{ A { b { c } } }") is False

    def test_is_introspection_query_negative_for_invalid_syntax(self) -> None:
        # Invalid syntax returns False (parse error → executor surfaces it instead).
        assert is_introspection_query("not even graphql") is False


# ──────────────────────────────────────────────────────────────────────
# Error handling
# ──────────────────────────────────────────────────────────────────────


class TestErrorHandling:
    async def test_unknown_service(self, app, schema) -> None:
        result = await execute_compose_query(
            app, schema, "{ UnknownService { anything { id } } }"
        )
        assert result["data"] is None
        assert "Service 'UnknownService' not found" in result["errors"][0]["message"]

    async def test_unknown_method(self, app, schema) -> None:
        result = await execute_compose_query(
            app, schema, "{ UserService { unknown_method { id } } }"
        )
        assert result["data"] is None
        assert "Method 'UserService.unknown_method' not found" in result["errors"][0]["message"]

    async def test_method_exception_becomes_error(self, app, schema) -> None:
        # get_user returns None for user_id != 1, no exception. Use a service
        # that explicitly raises to verify the exception path.
        class RaisingService(UseCaseService):
            @query
            async def boom(cls) -> int:
                raise RuntimeError("kaboom")

        app2 = UseCaseAppConfig(name="raise", services=[RaisingService])
        schema2 = build_compose_schema(app2)
        result = await execute_compose_query(
            app2, schema2, "{ RaisingService { boom } }"
        )
        assert result["data"] is None
        assert "RaisingService.boom raised RuntimeError" in result["errors"][0]["message"]

    async def test_malformed_query_returns_parse_error(self, app, schema) -> None:
        result = await execute_compose_query(app, schema, "{ UserService { list_users")  # missing close
        assert result["data"] is None
        assert "Failed to parse query" in result["errors"][0]["message"]

    async def test_mutation_blocked_when_enable_mutation_false(
        self, app, schema
    ) -> None:
        app_no_mut = UseCaseAppConfig(
            name="project", services=[TaskService], enable_mutation=False
        )
        schema_no_mut = build_compose_schema(app_no_mut)
        result = await execute_compose_query(
            app_no_mut,
            schema_no_mut,
            "{ TaskService { create_task(title: \"x\") { id } } }",
        )
        assert result["data"] is None
        assert "enable_mutation=False" in result["errors"][0]["message"]


# ──────────────────────────────────────────────────────────────────────
# FR-004a: no outer Resolver wrap
# ──────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────
# FR-004a: no outer Resolver wrap
# ──────────────────────────────────────────────────────────────────────


class _ResolverAwareDTO(BaseModel):
    """DTO whose ``derived`` field depends on Resolver to fill in."""

    id: int
    derived: int = 0

    def resolve_derived(self) -> int:
        return self.id * 100


class _ServiceSkippingResolver(UseCaseService):
    @query
    async def m(cls) -> _ResolverAwareDTO:
        # Intentionally do NOT call Resolver().resolve().
        return _ResolverAwareDTO(id=5)


class TestNoOuterResolverWrap:
    """FR-004a: GraphQL execution layer must NOT wrap results in Resolver().

    Service methods own Resolver invocation. If a DTO has a ``resolve_*``
    field that the service method did NOT process (because it didn't call
    Resolver().resolve()), the GraphQL layer should NOT silently fix it up.
    """

    async def test_resolve_field_left_untouched_when_service_skips_resolver(
        self,
    ) -> None:
        from nexusx.resolver import Resolver

        app = UseCaseAppConfig(name="noresolver", services=[_ServiceSkippingResolver])
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app, schema, "{ _ServiceSkippingResolver { m { id derived } } }"
        )
        # Resolver NOT auto-invoked: derived stays at its default (0).
        # If the GraphQL layer had wrapped in Resolver, derived would be 500.
        assert result["data"]["_ServiceSkippingResolver"]["m"].derived == 0

        # Sanity check that the DTO + Resolver would otherwise do the right thing.
        processed = await Resolver().resolve(_ResolverAwareDTO(id=5))
        assert processed.derived == 500
