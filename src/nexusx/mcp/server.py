"""MCP Server for nexusx.

Provides a FastMCP server that exposes multiple GraphQL applications as MCP tools
with three-layer progressive disclosure for reduced context usage.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from nexusx.mcp.application import Application
from nexusx.mcp.managers import MultiAppManager
from nexusx.mcp.tools.multi_app_tools import register_multi_app_tools

if TYPE_CHECKING:
    from fastmcp import FastMCP


def create_mcp_server(
    apps: list[Application | dict[str, Any]],
    name: str = "Multi-App nexusx API",
    allow_mutation: bool = False,
) -> FastMCP:
    """Create an MCP server that exposes multiple GraphQL APIs as tools.

    This function creates a FastMCP server with multi-app support and three-layer
    progressive disclosure:

    **Layer 0 (App Discovery):**
    - list_apps: List all available applications

    **Layer 1 (Lightweight):**
    - list_queries: List query names and descriptions for a specific app
    - list_mutations: List mutation names and descriptions for a specific app
      (if allow_mutation=True)

    **Layer 2 (On-demand):**
    - get_query_schema: Get query details + related type introspection
    - get_mutation_schema: Get mutation details + related type introspection
      (if allow_mutation=True)

    **Layer 3 (Execution):**
    - graphql_query: Execute GraphQL queries
    - graphql_mutation: Execute GraphQL mutations
      (if allow_mutation=True)

    All tools (except list_apps) require a mandatory app_name parameter.

    Args:
        apps: List of :class:`Application` instances (preferred), or legacy
            ``AppConfig`` dicts (deprecated, triggers ``DeprecationWarning``).
            Each app has its own GraphQL schema and independent database.
        name: Name of the MCP server (shown in MCP clients).
        allow_mutation: If True, registers mutation-related tools (list_mutations,
            get_mutation_schema, graphql_mutation) and includes mutations_count
            in list_apps. Default is False (read-only mode).

    Returns:
        A configured FastMCP server instance. Its ``lifespan`` is wired so that
        ``manager.dispose()`` runs on shutdown, releasing any engines owned by
        ``Application(url=...)`` instances.

    Example:
        ```python
        from myapp.blog import BlogBaseEntity, BLOG_DATABASE_URL
        from myapp.shop import ShopBaseEntity, SHOP_DATABASE_URL
        from nexusx.mcp import Application, create_mcp_server

        apps = [
            Application(
                name="blog",
                base=BlogBaseEntity,
                url=BLOG_DATABASE_URL,
                description="Blog system API",
                query_description="Query users, posts, and comments",
                mutation_description="Create and update blog data",
            ),
            Application(
                name="shop",
                base=ShopBaseEntity,
                url=SHOP_DATABASE_URL,
                description="E-commerce system API",
            ),
        ]

        mcp = create_mcp_server(
            apps=apps,
            name="My Multi-App GraphQL API"
        )

        # Run with stdio transport (default)
        mcp.run()

        # Or run with HTTP transport
        mcp.run(transport="streamable-http")
        ```

    .. deprecated::
        Passing ``AppConfig`` dict entries is deprecated; use :class:`Application`
        instead. The dict form will be removed in a future release.

    Tools provided (when allow_mutation=False, default):
        - list_apps(): List all available apps
        - list_queries(app_name): List queries for an app
        - get_query_schema(name, app_name, response_type): Get query details
        - graphql_query(query, app_name): Execute a GraphQL query

    Additional tools (when allow_mutation=True):
        - list_mutations(app_name): List mutations for an app
        - get_mutation_schema(name, app_name, response_type): Get mutation details
        - graphql_mutation(mutation, app_name): Execute a GraphQL mutation
    """
    from fastmcp import FastMCP

    # Create the multi-app manager
    manager = MultiAppManager(apps)

    # Wire lifespan so manager.dispose() runs on server shutdown,
    # releasing any engines owned by Applications constructed with url=.
    @asynccontextmanager
    async def _lifespan(_mcp: FastMCP) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await manager.dispose()

    # Create the FastMCP server
    mcp = FastMCP(name, lifespan=_lifespan)

    # Register all multi-app tools
    register_multi_app_tools(mcp, manager, allow_mutation=allow_mutation)

    return mcp


def create_simple_mcp_server(
    base: type,
    name: str = "nexusx API",
    desc: str | None = None,
    allow_mutation: bool = False,
    session_factory: Callable | None = None,
) -> FastMCP:
    """Create a simplified MCP server for single-app scenarios.

    This function creates a FastMCP server with only 2-3 tools, eliminating
    the complexity of multi-app management and progressive disclosure.
    Perfect for simple GraphQL APIs with a single database.

    **Tools provided (when allow_mutation=False, default):**
    - get_schema: Get the complete GraphQL schema in SDL format
    - graphql_query: Execute GraphQL queries

    **Additional tool (when allow_mutation=True):**
    - graphql_mutation: Execute GraphQL mutations

    All tools work without requiring an app_name parameter.

    Args:
        base: SQLModel base class. All subclasses with @query/@mutation
              decorators will be automatically discovered.
        name: Name of the MCP server (shown in MCP clients).
        desc: Optional description for the GraphQL schema (used for both
              Query and Mutation type descriptions).
        allow_mutation: If True, registers graphql_mutation tool and includes
            Mutation type in schema. Default is False (read-only mode).
        session_factory: Async session factory for DataLoader relationship
            loading. Required if queries return entities with relationships.

    Returns:
        A configured FastMCP server instance with 2-3 simplified tools.

    Example:
        ```python
        from sqlmodel import SQLModel
        from nexusx import query
        from nexusx.mcp import create_simple_mcp_server

        class BaseEntity(SQLModel):
            pass

        class User(BaseEntity, table=True):
            id: int
            name: str

            @query
            async def get_users(cls) -> list['User']:
                return await fetch_users()

        # Create simplified MCP server
        mcp = create_simple_mcp_server(
            base=BaseEntity,
            name="My Blog API",
            desc="Blog system with users and posts"
        )

        # Run with stdio transport (default)
        mcp.run()

        # Or run with HTTP transport
        mcp.run(transport="streamable-http")
        ```

    Note:
        For multi-app scenarios with separate databases, use create_mcp_server()
        instead, which provides app discovery and routing capabilities.

    Tools provided (when allow_mutation=False, default):
        - get_schema(): Get the complete GraphQL schema
        - graphql_query(query): Execute a GraphQL query

    Additional tool (when allow_mutation=True):
        - graphql_mutation(mutation): Execute a GraphQL mutation
    """
    from fastmcp import FastMCP

    from nexusx.mcp.managers.single_app_manager import SingleAppManager
    from nexusx.mcp.tools.simple_tools import register_simple_tools

    # Create the single-app manager
    manager = SingleAppManager(base=base, description=desc, session_factory=session_factory)

    # Create the FastMCP server
    mcp = FastMCP(name)

    # Register simplified tools (no app_name required)
    register_simple_tools(mcp, manager, allow_mutation=allow_mutation)

    return mcp

