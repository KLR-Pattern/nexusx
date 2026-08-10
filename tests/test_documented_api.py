"""Smoke tests for public APIs used by the documentation."""

from __future__ import annotations

import pytest
from sqlmodel import Field, SQLModel

from nexusx import AutoQueryConfig, GraphQLHandler, UseCaseService, mutation, query
from nexusx.voyager import create_use_case_voyager


class DocumentedBase(SQLModel):
    pass


class DocumentedPost(DocumentedBase, table=False):
    id: int
    title: str

    @query
    async def get_all(cls, limit: int = 10) -> list[DocumentedPost]:
        return []


class DocumentedAutoBase(SQLModel):
    pass


class DocumentedUser(DocumentedAutoBase, table=False):
    id: int | None = Field(default=None, primary_key=True)
    name: str


class DocumentedService(UseCaseService):
    @query
    async def visible_query(cls) -> str:
        return "visible"

    @mutation
    async def visible_mutation(cls) -> bool:
        return True

    @classmethod
    async def hidden_helper(cls) -> str:
        return "hidden"


def _unused_session_factory():
    raise AssertionError("schema smoke tests must not open a database session")


def _tool_names(mcp) -> set[str]:
    return {
        key.split(":")[1].split("@")[0]
        for key in mcp._local_provider._components
        if key.startswith("tool:")
    }


def test_grouped_graphql_sdl_matches_documentation() -> None:
    sdl = GraphQLHandler(base=DocumentedBase).get_sdl()

    assert "type DocumentedPostQuery {" in sdl
    assert "get_all(limit: Int): [DocumentedPost!]!" in sdl
    assert "DocumentedPost: DocumentedPostQuery!" in sdl


def test_auto_query_config_is_policy_and_generates_grouped_queries() -> None:
    handler = GraphQLHandler(
        base=DocumentedAutoBase,
        session_factory=_unused_session_factory,
        auto_query_config=AutoQueryConfig(),
    )
    sdl = handler.get_sdl()

    assert "type DocumentedUserQuery {" in sdl
    assert "by_id(id: Int!): DocumentedUser" in sdl
    assert "by_filter(" in sdl
    assert "DocumentedUser: DocumentedUserQuery!" in sdl


def test_use_case_discovers_only_decorated_methods() -> None:
    methods = DocumentedService.__use_case_methods__

    assert set(methods) == {"visible_query", "visible_mutation"}
    assert methods["visible_query"]["kind"] == "query"
    assert methods["visible_mutation"]["kind"] == "mutation"


def test_voyager_documented_routes_and_methods() -> None:
    app = create_use_case_voyager(
        services=[DocumentedService],
        gzip_minimum_size=-1,
    )
    routes = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    assert ("GET", "/dot") in routes
    assert ("POST", "/dot-search") in routes
    assert ("POST", "/er-diagram") in routes
    assert ("POST", "/er-diagram-subgraph") in routes
    assert ("POST", "/source") in routes
    assert ("POST", "/docstring") in routes


def test_simple_mcp_is_read_only_by_default() -> None:
    pytest.importorskip("fastmcp")
    from nexusx.mcp import create_single_app_mcp_server

    read_only = create_single_app_mcp_server(base=DocumentedBase)
    writable = create_single_app_mcp_server(
        base=DocumentedBase,
        allow_mutation=True,
    )

    assert _tool_names(read_only) == {"get_schema", "graphql_query"}
    assert _tool_names(writable) == {
        "get_schema",
        "graphql_query",
        "graphql_mutation",
    }
