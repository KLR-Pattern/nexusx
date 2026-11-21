"""MCP tool annotations — the hint layer of AI mutation safety.

Locks the annotation rules across all three server surfaces:
- discovery tools are read-only;
- an execution tool (graphql_query / compose_query) is read-only ONLY when
  no reachable schema exposes a Mutation operation — computed from schema
  content, NOT from the allow_mutation flag (the flag gates advertising,
  while the handler still executes whatever the schema contains);
- mutation tools carry destructiveHint.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from sqlmodel import Field, SQLModel

from nexusx import query
from nexusx.decorator import mutation
from nexusx.use_case.business import UseCaseService
from nexusx.use_case.compose_mcp_server import create_use_case_graphql_mcp_server
from nexusx.use_case.types import UseCaseAppConfig


def _get_tools_dict(mcp):
    """Get tools as dict {name: tool} from FastMCP (compatible with fastmcp 3.x)."""
    components = mcp._local_provider._components
    return {
        key.split(":")[1].split("@")[0]: value
        for key, value in components.items()
        if key.startswith("tool:")
    }


def _hints(mcp, name: str) -> tuple[bool | None, bool | None]:
    tool = _get_tools_dict(mcp)[name]
    ann = tool.annotations
    return (ann.read_only_hint, ann.destructive_hint)


# ── entity-side fixtures ────────────────────────────────────────────────


class _AnnBase(SQLModel):
    pass


class _AnnBothEntity(_AnnBase, table=True):
    """Has a @mutation method → its schema exposes a Mutation operation."""

    __tablename__ = "ann_both_entity"
    __test__ = False

    id: int | None = Field(default=None, primary_key=True)

    @query
    async def get_all(cls) -> list[_AnnBothEntity]:
        return []

    @mutation
    async def create(cls) -> _AnnBothEntity:
        return _AnnBothEntity(id=1)


class _AnnQueryOnlyBase(SQLModel):
    pass


class _AnnQueryOnlyEntity(_AnnQueryOnlyBase, table=True):
    """@query only → schema has no Mutation operation."""

    __tablename__ = "ann_query_only_entity"
    __test__ = False

    id: int | None = Field(default=None, primary_key=True)

    @query
    async def get_all(cls) -> list[_AnnQueryOnlyEntity]:
        return []


# ── compose-side fixtures ───────────────────────────────────────────────


class _AnnItem(BaseModel):
    id: int


class _AnnQueryService(UseCaseService):
    @query
    async def list_items(cls) -> list[_AnnItem]:
        return [_AnnItem(id=1)]


class _AnnMixedService(UseCaseService):
    @query
    async def list_items(cls) -> list[_AnnItem]:
        return []

    @mutation
    async def create_item(cls) -> _AnnItem:
        return _AnnItem(id=99)


# ── entity single-app server ────────────────────────────────────────────


class TestSimpleServerAnnotations:
    @pytest.fixture
    def mutation_app_mcp(self):
        from fastmcp import FastMCP

        from nexusx.mcp.managers.single_app_manager import SingleAppManager
        from nexusx.mcp.tools.simple_tools import register_simple_tools

        mcp = FastMCP("ann-simple")
        manager = SingleAppManager(base=_AnnBase)
        register_simple_tools(mcp, manager, allow_mutation=False)
        return mcp

    @pytest.fixture
    def query_only_mcp(self):
        from fastmcp import FastMCP

        from nexusx.mcp.managers.single_app_manager import SingleAppManager
        from nexusx.mcp.tools.simple_tools import register_simple_tools

        mcp = FastMCP("ann-simple-qo")
        manager = SingleAppManager(base=_AnnQueryOnlyBase)
        register_simple_tools(mcp, manager, allow_mutation=False)
        return mcp

    def test_discovery_tools_are_read_only(self, mutation_app_mcp):
        assert _hints(mutation_app_mcp, "get_schema") == (True, None)

    def test_execution_tool_follows_schema_content_not_flag(self, mutation_app_mcp):
        """App HAS a mutation method but allow_mutation=False: graphql_query
        still executes arbitrary GraphQL against a schema with a Mutation
        operation → must NOT claim read-only (content over flag)."""
        ro, de = _hints(mutation_app_mcp, "graphql_query")
        assert ro is False
        assert de is True

    def test_query_only_app_execution_tool_is_read_only(self, query_only_mcp):
        assert _hints(query_only_mcp, "graphql_query") == (True, None)


# ── entity multi-app server ─────────────────────────────────────────────


class TestMultiAppServerAnnotations:
    def _build(self, base, allow_mutation: bool):
        from nexusx.mcp import Application
        from nexusx.mcp.server import create_multi_app_mcp_server

        app = Application(name="ann-app", base=base)
        return create_multi_app_mcp_server(
            apps=[app], name="ann-multi", allow_mutation=allow_mutation
        )

    def test_discovery_tools_are_read_only(self):
        mcp = self._build(_AnnBase, allow_mutation=False)
        for name in ("list_apps", "list_queries", "get_query_schema"):
            assert _hints(mcp, name) == (True, None), name

    def test_execution_tool_follows_schema_content_not_flag(self):
        mcp = self._build(_AnnBase, allow_mutation=False)
        ro, de = _hints(mcp, "graphql_query")
        assert ro is False
        assert de is True

    def test_mutation_tools_when_advertised(self):
        mcp = self._build(_AnnBase, allow_mutation=True)
        assert _hints(mcp, "graphql_mutation") == (False, True)
        assert _hints(mcp, "graphql_query") == (False, True)
        for name in ("list_mutations", "get_mutation_schema"):
            assert _hints(mcp, name) == (True, None), name

    def test_query_only_apps_execution_tool_is_read_only(self):
        mcp = self._build(_AnnQueryOnlyBase, allow_mutation=False)
        assert _hints(mcp, "graphql_query") == (True, None)


# ── compose server ──────────────────────────────────────────────────────


class TestComposeServerAnnotations:
    def test_discovery_tools_are_read_only(self):
        mcp = create_use_case_graphql_mcp_server(
            apps=[
                UseCaseAppConfig(
                    name="annq", services=[_AnnQueryService], description="q"
                )
            ],
            name="ann-compose",
        )
        for name in ("list_apps", "describe_compose_schema", "describe_compose_method"):
            assert _hints(mcp, name) == (True, None), name

    def test_query_only_services_execution_tool_is_read_only(self):
        mcp = create_use_case_graphql_mcp_server(
            apps=[
                UseCaseAppConfig(
                    name="annq", services=[_AnnQueryService], description="q"
                )
            ],
            name="ann-compose-qo",
        )
        assert _hints(mcp, "compose_query") == (True, None)

    def test_mutation_service_makes_execution_tool_destructive(self):
        mcp = create_use_case_graphql_mcp_server(
            apps=[
                UseCaseAppConfig(
                    name="annm", services=[_AnnMixedService], description="m"
                )
            ],
            name="ann-compose-m",
        )
        assert _hints(mcp, "compose_query") == (False, True)
