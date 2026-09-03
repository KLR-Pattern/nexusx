"""Tests for ``nexusx.use_case.compose_executor`` (User Story 2 — Layer 3).

Covers FR-004a (no outer Resolver wrap), FR-006 (Layer 3 contract),
FR-008 (introspection rejection), and the executor's happy paths and
error paths.

These tests exercise ``execute_compose_query`` directly (no MCP layer).
``test_compose_mcp_server.py`` covers the 4-layer MCP server end-to-end.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, ClassVar

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


class NullableMemberSummary(BaseModel):
    id: int
    secret: str


class NullableCollectionSummary(BaseModel):
    title: str
    members: list[NullableMemberSummary | None]


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


class NullableCollectionService(UseCaseService):
    @query
    async def get_collection(cls) -> NullableCollectionSummary:
        return NullableCollectionSummary(
            title="hidden",
            members=[
                NullableMemberSummary(id=1, secret="hidden"),
                None,
            ],
        )


@pytest.fixture
def app() -> UseCaseAppConfig:
    return UseCaseAppConfig(
        name="project",
        services=[
            UserService,
            TaskService,
            ContextService,
            NullableCollectionService,
        ],
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

    async def test_nullable_list_items_preserve_projection(self, app, schema) -> None:
        result = await execute_compose_query(
            app,
            schema,
            "{ NullableCollectionService { get_collection { members { id } } } }",
        )

        collection = result["data"]["NullableCollectionService"]["get_collection"]
        assert set(collection.model_dump().keys()) == {"members"}
        assert collection.members[1] is None
        assert set(collection.members[0].model_dump().keys()) == {"id"}

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
        # specs/023: per-field — the failing key nulls, siblings unaffected.
        assert result["data"] == {"ContextService": {"echo_actor": None}}
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
        # specs/023: execution failures are per-field — the key nulls with an
        # errors entry (QUERY_FAILED) instead of nulling the whole response.
        class RaisingService(UseCaseService):
            @query
            async def boom(cls) -> int:
                raise RuntimeError("kaboom")

        app2 = UseCaseAppConfig(name="raise", services=[RaisingService])
        schema2 = build_compose_schema(app2)
        result = await execute_compose_query(
            app2, schema2, "{ RaisingService { boom } }"
        )
        assert result["data"] == {"RaisingService": {"boom": None}}
        assert "RaisingService.boom raised RuntimeError" in result["errors"][0]["message"]
        assert result["errors"][0]["extensions"]["code"] == "QUERY_FAILED"
        # specs/023 polish: per-field errors carry the qualified method too
        # (aligned with the fail-fast path) — MCP consumers locate the
        # failure without parsing the message.
        assert (
            result["errors"][0]["extensions"]["service_method"]
            == "RaisingService.boom"
        )

    async def test_malformed_query_returns_parse_error(self, app, schema) -> None:
        result = await execute_compose_query(
            app, schema, "{ UserService { list_users"  # missing close
        )
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


# ──────────────────────────────────────────────────────────────────────
# US1 (specs/023): aliases must fail loudly — never silently dropped
# ──────────────────────────────────────────────────────────────────────


class _AliasGuardDTO(BaseModel):
    id: int
    label: str


class _AliasGuardService(UseCaseService):
    """Counts invocations so tests can assert zero execution on rejection."""

    calls: ClassVar[list[str]] = []

    @query
    async def fetch(cls, tag: str = "x") -> list[_AliasGuardDTO]:
        _AliasGuardService.calls.append(f"fetch:{tag}")
        return [_AliasGuardDTO(id=1, label=tag)]

    @query
    async def boom(cls, tag: str = "x") -> list[_AliasGuardDTO]:
        _AliasGuardService.calls.append(f"boom:{tag}")
        raise RuntimeError(f"boom {tag}")

    @mutation
    async def write(cls, tag: str = "x") -> _AliasGuardDTO:
        _AliasGuardService.calls.append(f"write:{tag}")
        return _AliasGuardDTO(id=2, label=tag)

    @mutation
    async def flaky_write(cls, tag: str = "x") -> _AliasGuardDTO:
        _AliasGuardService.calls.append(f"flaky_write:{tag}")
        if tag == "fail":
            raise RuntimeError("flaky exploded")
        return _AliasGuardDTO(id=3, label=tag)


def _guard_app() -> UseCaseAppConfig:
    _AliasGuardService.calls = []
    return UseCaseAppConfig(name="guard", services=[_AliasGuardService])


class TestAliasRejection:
    """US1: any alias in a compose query → explicit error, zero execution."""

    async def test_aliased_query_field_is_supported(self) -> None:
        """specs/023 B1a: aliased @query methods are now supported (US2).

        Superseded the US1-phase rejection; see TestAliasQueryFanout for the
        full matrix (different args, dedup-free, projection isolation)."""
        app = _guard_app()
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app, schema, "{ _AliasGuardService { a: fetch(tag: \"q\") { id } } }"
        )
        assert result["errors"] == []
        assert result["data"]["_AliasGuardService"]["a"][0].id == 1
        assert _AliasGuardService.calls == ["fetch:q"]

    async def test_aliased_mutation_field_is_supported(self) -> None:
        """specs/023 B1b: aliased mutations execute serially (US3).

        Superseded the US1/US2-phase rejection; TestAliasMutationThreeState
        covers the full three-state matrix (fail-stop, dedup-free)."""
        app = _guard_app()
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app, schema,
            'mutation { _AliasGuardService { a: write(tag: "m") { id } } }',
        )
        assert result["errors"] == []
        assert result["data"]["_AliasGuardService"]["a"].id == 2
        assert _AliasGuardService.calls == ["write:m"]

    async def test_nested_alias_is_rejected(self) -> None:
        app = _guard_app()
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app, schema, "{ _AliasGuardService { fetch { l: label } } }"
        )
        assert result["data"] is None
        assert result["errors"], "nested alias must produce an error"
        assert result["errors"][0]["extensions"]["code"] == "ALIAS_CONFLICT"
        assert _AliasGuardService.calls == []

    async def test_unaliased_query_still_works(self) -> None:
        """Guard against over-rejection: no alias → normal execution."""
        app = _guard_app()
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app, schema, '{ _AliasGuardService { fetch(tag: "ok") { id label } } }'
        )
        assert result["errors"] == []
        assert result["data"]["_AliasGuardService"]["fetch"][0].label == "ok"
        assert _AliasGuardService.calls == ["fetch:ok"]


class TestAliasQueryFanout:
    """US2 (specs/023): aliased query methods execute independently."""

    async def test_two_aliases_different_args_both_execute(self) -> None:
        app = _guard_app()
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app, schema,
            '{ _AliasGuardService { '
            'a: fetch(tag: "hi") { id label } '
            'b: fetch(tag: "lo") { id label } } }',
        )
        assert result["errors"] == []
        data = result["data"]["_AliasGuardService"]
        assert set(data) == {"a", "b"}
        assert data["a"][0].label == "hi"
        assert data["b"][0].label == "lo"
        assert sorted(_AliasGuardService.calls) == ["fetch:hi", "fetch:lo"]

    async def test_same_method_same_args_not_deduplicated(self) -> None:
        """FR-011 (query half): identical aliased calls still run N times."""
        app = _guard_app()
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app, schema,
            '{ _AliasGuardService { '
            'a: fetch(tag: "same") { id } '
            'b: fetch(tag: "same") { id } } }',
        )
        assert result["errors"] == []
        assert _AliasGuardService.calls == ["fetch:same", "fetch:same"]

    async def test_projection_isolated_per_alias(self) -> None:
        """Each alias projects only the sub-fields it declared."""
        app = _guard_app()
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app, schema,
            '{ _AliasGuardService { '
            'a: fetch(tag: "p") { id } '
            'b: fetch(tag: "p") { id label } } }',
        )
        assert result["errors"] == []
        data = result["data"]["_AliasGuardService"]
        assert set(data["a"][0].model_dump()) == {"id"}
        assert set(data["b"][0].model_dump()) == {"id", "label"}

    async def test_failed_alias_does_not_kill_sibling(self) -> None:
        """Queries have no fail-stop: a failing alias nulls only itself."""
        app = _guard_app()
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app, schema,
            '{ _AliasGuardService { '
            'good: fetch(tag: "ok") { id } '
            'bad: boom(tag: "nope") { id } } }',
        )
        assert result["data"]["_AliasGuardService"]["good"][0].id == 1
        assert result["data"]["_AliasGuardService"]["bad"] is None
        assert any(
            "boom nope" in e["message"] for e in result["errors"]
        )

    async def test_response_key_conflict_reports_error(self) -> None:
        """FR-007: duplicate response keys are rejected, not deduplicated."""
        app = _guard_app()
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app, schema, "{ _AliasGuardService { a: fetch { id } a: fetch { id } } }"
        )
        assert result["data"] is None
        assert "conflict" in result["errors"][0]["message"].lower()
        assert _AliasGuardService.calls == []


class TestAliasMutationThreeState:
    """US3 (specs/023): aliased mutations run serially with per-call feedback.

    Three states per response key: succeeded (value), failed (null +
    MUTATION_FAILED), skipped (null + SKIPPED_PRIOR_FAILURE, fail-stop).
    """

    async def test_issue140_end_to_end_all_invocations_execute(self) -> None:
        """The original report: 6 aliased add_node created 1 node."""
        app = _guard_app()
        schema = build_compose_schema(app)
        q = (
            "mutation { _AliasGuardService { "
            + " ".join(f'n{i}: write(tag: "n{i}") {{ id label }}' for i in range(1, 7))
            + " } }"
        )
        result = await execute_compose_query(app, schema, q)
        assert result["errors"] == []
        data = result["data"]["_AliasGuardService"]
        assert set(data) == {f"n{i}" for i in range(1, 7)}
        assert all(data[k].label == k for k in data)
        assert len(_AliasGuardService.calls) == 6

    async def test_partial_failure_three_states(self) -> None:
        app = _guard_app()
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app, schema,
            "mutation { _AliasGuardService { "
            'first: flaky_write(tag: "ok") { id label } '
            'bad: flaky_write(tag: "fail") { id } '
            'last: flaky_write(tag: "also-ok") { id } } }',
        )
        data = result["data"]["_AliasGuardService"]
        # Succeeded results survive (D4: no whole-group nulling).
        assert data["first"].id == 3
        assert data["first"].label == "ok"
        # The failing call nulls its own key with MUTATION_FAILED.
        assert data["bad"] is None
        bad = [e for e in result["errors"]
               if e.get("extensions", {}).get("code") == "MUTATION_FAILED"]
        assert len(bad) == 1
        assert bad[0]["path"] == ["_AliasGuardService", "bad"]
        # Fail-stop: everything after the failure is SKIPPED, not executed.
        assert data["last"] is None
        skipped = [e for e in result["errors"]
                   if e.get("extensions", {}).get("code") == "SKIPPED_PRIOR_FAILURE"]
        assert len(skipped) == 1
        assert skipped[0]["path"] == ["_AliasGuardService", "last"]
        assert _AliasGuardService.calls == ["flaky_write:ok", "flaky_write:fail"]

    async def test_serial_declaration_order(self) -> None:
        app = _guard_app()
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app, schema,
            "mutation { _AliasGuardService { "
            'c: write(tag: "3") { id } '
            'a: write(tag: "1") { id } '
            'b: write(tag: "2") { id } } }',
        )
        assert result["errors"] == []
        # Execution follows DECLARATION order (c, a, b), not alias sort.
        assert _AliasGuardService.calls == ["write:3", "write:1", "write:2"]
        assert list(result["data"]["_AliasGuardService"]) == ["c", "a", "b"]

    async def test_same_method_same_args_n_side_effects(self) -> None:
        """FR-011 mutation half: identical aliased mutations must ALL run."""
        app = _guard_app()
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app, schema,
            'mutation { _AliasGuardService { '
            'a: write(tag: "dup") { id } b: write(tag: "dup") { id } } }',
        )
        assert result["errors"] == []
        assert _AliasGuardService.calls == ["write:dup", "write:dup"]

    async def test_enable_mutation_false_orthogonal_to_aliases(self) -> None:
        app = UseCaseAppConfig(
            name="guard", services=[_AliasGuardService], enable_mutation=False
        )
        _AliasGuardService.calls = []
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app, schema, 'mutation { _AliasGuardService { a: write { id } } }'
        )
        assert result["data"] is None
        assert "enable_mutation=False" in result["errors"][0]["message"]
        assert _AliasGuardService.calls == []


class TestTopLevelAlias:
    """specs/023: service-level aliases — lookup by original name, response
    keyed by the alias."""

    async def test_two_aliased_service_groups_fan_out(self) -> None:
        app = _guard_app()
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app, schema,
            '{ g1: _AliasGuardService { fetch(tag: "a") { id } } '
            'g2: _AliasGuardService { fetch(tag: "b") { id } } }',
        )
        assert result["errors"] == []
        data = result["data"]
        assert set(data) == {"g1", "g2"}
        assert data["g1"]["fetch"][0].id == 1
        assert sorted(_AliasGuardService.calls) == ["fetch:a", "fetch:b"]

    async def test_aliased_group_error_path_uses_response_keys(self) -> None:
        """specs/023 P2: error paths carry response keys — a failing method
        under an aliased group reports path ['group_alias', 'method_alias'],
        matching the data keys the client received."""

        class BoomService(UseCaseService):
            @query
            async def boom(cls) -> int:
                raise RuntimeError("kaboom")

        app = UseCaseAppConfig(name="boomapp", services=[BoomService])
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app, schema, "{ g: BoomService { b: boom } }"
        )
        assert result["data"] == {"g": {"b": None}}
        assert result["errors"][0]["path"] == ["g", "b"]
        assert result["errors"][0]["extensions"]["code"] == "QUERY_FAILED"


class TestQueryCancellationPropagates:
    """specs/023 review P1: gather(return_exceptions=True) delivers
    CancelledError as a VALUE — it must be re-raised, not downgraded to a
    QUERY_FAILED error entry. Otherwise a cancelled request (client
    disconnect, asyncio.timeout) keeps executing its mutations and returns
    a normal response."""

    async def test_cancelled_query_method_propagates_and_skips_mutations(
        self,
    ) -> None:
        calls: list[str] = []

        class CancelService(UseCaseService):
            @query
            async def cancel_me(cls) -> int:
                calls.append("cancel_me")
                raise asyncio.CancelledError()

            @mutation
            async def write(cls) -> int:
                calls.append("write")
                return 1

        app = UseCaseAppConfig(
            name="cancel", services=[CancelService], enable_mutation=True
        )
        schema = build_compose_schema(app)
        with pytest.raises(asyncio.CancelledError):
            await execute_compose_query(
                app, schema, "{ CancelService { cancel_me write { id } } }"
            )
        assert calls == ["cancel_me"]  # the mutation never ran

    async def test_external_cancel_stops_execution(self) -> None:
        started = asyncio.Event()
        calls: list[str] = []

        class SlowService(UseCaseService):
            @query
            async def slow(cls) -> int:
                calls.append("slow")
                started.set()
                await asyncio.sleep(10)
                return 1

            @mutation
            async def write(cls) -> int:
                calls.append("write")
                return 2

        app = UseCaseAppConfig(
            name="slow", services=[SlowService], enable_mutation=True
        )
        schema = build_compose_schema(app)

        async def run() -> None:
            task = asyncio.create_task(
                execute_compose_query(
                    app, schema, "{ SlowService { slow write { id } } }"
                )
            )
            await started.wait()
            task.cancel()
            await task

        with pytest.raises(asyncio.CancelledError):
            await run()
        assert calls == ["slow"]  # cancelled before the mutation ran

    async def test_plain_exception_still_per_field(self) -> None:
        """Regression guard: ordinary Exception stays a per-field
        QUERY_FAILED (sibling results kept) — the fix only changes the
        non-Exception BaseException path."""

        class BoomService(UseCaseService):
            @query
            async def boom(cls) -> int:
                raise RuntimeError("kaboom")

            @query
            async def ok(cls) -> int:
                return 7

        app = UseCaseAppConfig(name="boomsvc", services=[BoomService])
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app, schema, "{ BoomService { boom ok } }"
        )
        assert result["data"] == {"BoomService": {"boom": None, "ok": 7}}
        assert result["errors"][0]["extensions"]["code"] == "QUERY_FAILED"


class TestOperationScopeFailStop:
    """specs/023 FR-006 (review follow-up): mutation fail-stop propagates
    across service-group boundaries — GraphQL mutations are serial at
    OPERATION level. Later groups' mutations are skipped and marked
    SKIPPED_PRIOR_FAILURE; queries are unaffected by the abort flag."""

    async def test_later_service_mutations_skipped_after_earlier_failure(
        self,
    ) -> None:
        calls: list[str] = []

        class SvcA(UseCaseService):
            @mutation
            async def bad(cls) -> int:
                calls.append("bad")
                raise RuntimeError("A exploded")

        class SvcB(UseCaseService):
            @mutation
            async def write(cls) -> int:
                calls.append("write")
                return 99

        app = UseCaseAppConfig(
            name="opstop", services=[SvcA, SvcB], enable_mutation=True
        )
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app, schema, "mutation { SvcA { bad } SvcB { write } }"
        )
        assert result["data"] == {
            "SvcA": {"bad": None},
            "SvcB": {"write": None},
        }
        assert [
            (e["extensions"]["code"], e["path"]) for e in result["errors"]
        ] == [
            ("MUTATION_FAILED", ["SvcA", "bad"]),
            ("SKIPPED_PRIOR_FAILURE", ["SvcB", "write"]),
        ]
        assert calls == ["bad"]  # SvcB.write never executed

    async def test_queries_unaffected_by_abort_flag(self) -> None:
        """The abort flag only gates mutations — a later group's queries
        still run (FR-005: query failures have no fail-stop either way)."""
        calls: list[str] = []

        class SvcA(UseCaseService):
            @mutation
            async def bad(cls) -> int:
                calls.append("bad")
                raise RuntimeError("A exploded")

        class SvcB(UseCaseService):
            @query
            async def fetch(cls) -> int:
                calls.append("fetch")
                return 7

        app = UseCaseAppConfig(
            name="opstopq", services=[SvcA, SvcB], enable_mutation=True
        )
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app, schema, "mutation { SvcA { bad } SvcB { fetch } }"
        )
        assert result["data"]["SvcB"]["fetch"] == 7
        assert calls == ["bad", "fetch"]
        assert len(result["errors"]) == 1  # only the MUTATION_FAILED entry


class TestSingleOperationConstraint:
    """issue #142: compose_query takes a bare query string with no
    operationName channel — the document must contain exactly one
    operation. Same-name groups across operations can no longer
    cross-contaminate (silent field leakage on ≤6.1.2)."""

    async def test_multi_operation_document_rejected(self) -> None:
        app = _guard_app()
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app, schema,
            "{ _AliasGuardService { fetch { id } } } "
            "query Q { _AliasGuardService { fetch { id label } } }",
        )
        assert result["data"] is None
        assert "exactly one operation" in result["errors"][0]["message"]
        assert _AliasGuardService.calls == []  # nothing executed

    async def test_single_operation_unchanged(self) -> None:
        app = _guard_app()
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app, schema, "{ _AliasGuardService { fetch { id label } } }"
        )
        assert result["errors"] == []
        assert _AliasGuardService.calls == ["fetch:x"]
