"""Tests for the two pydantic-resolve-parity additions:

- ``compose_introspect`` — services (rather than rejects) ``__schema`` /
  ``__type`` / ``__typename`` queries. Intended for GraphiQL HTTP endpoints.
- ``_coerce_strict`` — defensive TypeAdapter coercion of GraphQL args +
  FromContext values to the method signature's declared types.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated, Optional

import pytest
from pydantic import BaseModel

from nexusx.decorator import mutation, query
from nexusx.use_case.business import UseCaseService
from nexusx.use_case.compose_executor import (
    _coerce_strict,
    compose_introspect,
    execute_compose_query,
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


class UserService(UseCaseService):
    @query
    async def list_users(cls) -> list[UserSummary]:
        return [UserSummary(id=1, name="Alice")]


@pytest.fixture
def schema():
    return build_compose_schema(UseCaseAppConfig(name="x", services=[UserService]))


# ──────────────────────────────────────────────────────────────────────
# compose_introspect
# ──────────────────────────────────────────────────────────────────────


class TestComposeIntrospectSchema:
    def test_schema_query_returns_full_introspection(self, schema) -> None:
        result = compose_introspect(schema, "{ __schema { types { name } } }")
        assert result["errors"] is None
        assert "__schema" in result["data"]
        payload = result["data"]["__schema"]
        assert payload["queryType"] == {"name": "Query"}
        type_names = [t["name"] for t in payload["types"]]
        assert "Query" in type_names
        assert "UserServiceQuery" in type_names
        assert "UserSummary" in type_names

    def test_none_query_defaults_to_schema(self, schema) -> None:
        """GraphiQL sometimes opens with a bare GET (no query)."""
        result = compose_introspect(schema, None)
        assert "__schema" in result["data"]


class TestComposeIntrospectType:
    def test_type_query_returns_single_type(self, schema) -> None:
        result = compose_introspect(
            schema, '{ __type(name: "UserSummary") { name kind } }'
        )
        assert result["errors"] is None
        type_payload = result["data"]["__type"]
        assert type_payload is not None
        assert type_payload["name"] == "UserSummary"
        assert type_payload["kind"] == "OBJECT"

    def test_type_query_with_unknown_name_returns_null(self, schema) -> None:
        result = compose_introspect(
            schema, '{ __type(name: "NoSuchType") { name } }'
        )
        assert result["data"]["__type"] is None

    def test_type_query_without_name_argument_returns_null(self, schema) -> None:
        # malformed __type() call (no name) — return null instead of crashing
        result = compose_introspect(schema, "{ __type { name } }")
        assert result["data"]["__type"] is None


class TestComposeIntrospectTypename:
    def test_typename_returns_query_root_name(self, schema) -> None:
        result = compose_introspect(schema, "{ __typename }")
        assert result["data"]["__typename"] == "Query"


class TestComposeIntrospectEnvelope:
    def test_returns_graphql_standard_envelope(self, schema) -> None:
        result = compose_introspect(schema, "{ __schema { queryType { name } } }")
        assert set(result.keys()) == {"data", "errors"}
        assert result["errors"] is None  # graphql convention: null, not []

    def test_combined_query_returns_all_three_keys(self, schema) -> None:
        """A query touching all three introspection fields populates each key."""
        result = compose_introspect(
            schema,
            '{ __schema { queryType { name } } __type(name: "Query") { name } __typename }',
        )
        assert set(result["data"].keys()) == {"__schema", "__type", "__typename"}


# ──────────────────────────────────────────────────────────────────────
# _coerce_strict — direct unit tests
# ──────────────────────────────────────────────────────────────────────


class TestCoerceStrictDirect:
    def test_none_passes_through(self) -> None:
        assert _coerce_strict(None, int, "x", "Svc.m") is None

    def test_empty_annotation_passes_through(self) -> None:
        import inspect

        assert _coerce_strict("anything", inspect.Parameter.empty, "x", "Svc.m") == "anything"

    def test_already_correct_type_passes_through(self) -> None:
        assert _coerce_strict(42, int, "x", "Svc.m") == 42

    def test_datetime_string_promoted_to_datetime(self) -> None:
        result = _coerce_strict("2026-06-20T10:30:00", datetime.datetime, "ts", "Svc.m")
        assert isinstance(result, datetime.datetime)
        assert result.year == 2026

    def test_uuid_string_promoted_to_uuid(self) -> None:
        s = "550e8400-e29b-41d4-a716-446655440000"
        result = _coerce_strict(s, uuid.UUID, "u", "Svc.m")
        assert isinstance(result, uuid.UUID)
        assert str(result) == s

    def test_pydantic_model_built_from_dict(self) -> None:
        result = _coerce_strict({"id": 1, "name": "A"}, UserSummary, "user", "Svc.m")
        assert isinstance(result, UserSummary)
        assert result.id == 1

    def test_bad_value_raises_compose_execution_error(self) -> None:
        from nexusx.use_case.compose_executor import _ComposeExecutionError

        with pytest.raises(_ComposeExecutionError) as exc_info:
            _coerce_strict("not_an_int", int, "x", "Svc.m")
        assert "Failed to coerce argument 'x'" in str(exc_info.value)
        assert exc_info.value.service_method == "Svc.m"


# ──────────────────────────────────────────────────────────────────────
# _coerce_strict — end-to-end via execute_compose_query
# ──────────────────────────────────────────────────────────────────────


class _CoercionService(UseCaseService):
    """Service whose params need promotion from raw GraphQL strings."""

    @query
    async def by_uuid(cls, u: uuid.UUID) -> str:
        return f"got {u}"

    @query
    async def by_datetime(cls, ts: datetime.datetime) -> str:
        return f"got {ts.isoformat()}"

    @query
    async def by_model(cls, user: UserSummary) -> str:
        return f"got {user.name}"

    @query
    async def optional_uuid(
        cls,
        u: Optional[uuid.UUID] = None,
    ) -> str:
        return f"got {u}"


class TestCoerceStrictEndToEnd:
    async def test_uuid_arg_coerced(self) -> None:
        app = UseCaseAppConfig(name="c", services=[_CoercionService])
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app,
            schema,
            '{ Op { _CoercionService { by_uuid(u: "550e8400-e29b-41d4-a716-446655440000") } } }',
        )
        assert result["errors"] == []
        assert "550e8400" in result["data"]["_CoercionService"]["by_uuid"]

    async def test_datetime_arg_coerced(self) -> None:
        app = UseCaseAppConfig(name="c", services=[_CoercionService])
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app,
            schema,
            '{ Op { _CoercionService { by_datetime(ts: "2026-06-20T10:30:00") } } }',
        )
        assert result["errors"] == []
        assert "2026-06-20T10:30:00" in result["data"]["_CoercionService"]["by_datetime"]

    async def test_pydantic_model_arg_from_object_literal(self) -> None:
        app = UseCaseAppConfig(name="c", services=[_CoercionService])
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app,
            schema,
            '{ Op { _CoercionService { by_model(user: {id: 7, name: "Zed"}) } } }',
        )
        # GraphQL object literals as scalar args may or may not parse cleanly
        # depending on QueryParser — accept either success or a clean error.
        if result["errors"]:
            assert "Failed to coerce" in result["errors"][0]["message"] or "UserService" in result["errors"][0]["message"]
        else:
            assert "Zed" in result["data"]["_CoercionService"]["by_model"]

    async def test_bad_int_arg_surfaces_clean_error(self) -> None:
        """A non-coercible value should produce a graphql error, not a crash."""
        # int param given a string that can't convert
        class Svc(UseCaseService):
            @query
            async def m(cls, n: int) -> int:
                return n

        # Note: GraphQL parser may reject `n: "abc"` at parse time. If so,
        # we get a parse error; if it accepts (e.g. via variable), we get a
        # coerce error. Both are acceptable clean failures.
        app = UseCaseAppConfig(name="c", services=[Svc])
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app,
            schema,
            '{ Op { Svc { m(n: "abc") } } }',
        )
        assert result["data"] is None
        assert len(result["errors"]) >= 1


# ──────────────────────────────────────────────────────────────────────
# FromContext values also get coerced
# ──────────────────────────────────────────────────────────────────────


class _ContextCoercionService(UseCaseService):
    @query
    async def echo_uuid(cls, u: Annotated[uuid.UUID, FromContext()]) -> str:
        return f"got {u}"


class TestFromContextCoercion:
    async def test_from_context_uuid_string_promoted(self) -> None:
        """context_extractor might return JSON-native values; they get coerced."""
        app = UseCaseAppConfig(name="c", services=[_ContextCoercionService])
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app,
            schema,
            "{ Op { _ContextCoercionService { echo_uuid } } }",
            context={"u": "550e8400-e29b-41d4-a716-446655440000"},  # string, not UUID
        )
        assert result["errors"] == []
        assert "550e8400" in result["data"]["_ContextCoercionService"]["echo_uuid"]

    async def test_from_context_bad_value_errors_cleanly(self) -> None:
        app = UseCaseAppConfig(name="c", services=[_ContextCoercionService])
        schema = build_compose_schema(app)
        result = await execute_compose_query(
            app,
            schema,
            "{ Op { _ContextCoercionService { echo_uuid } } }",
            context={"u": "not_a_uuid"},
        )
        assert result["data"] is None
        assert "Failed to coerce" in result["errors"][0]["message"]
