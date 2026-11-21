"""MCP Server for nexusx.

Provides a FastMCP server that exposes multiple GraphQL applications as MCP tools
with three-layer progressive disclosure for reduced context usage.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from nexusx.mcp.application import Application
from nexusx.mcp.managers import MultiAppManager
from nexusx.mcp.tools.multi_app_tools import register_multi_app_tools

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from nexusx.handler import GraphQLHandler
    from nexusx.standard_queries import AutoQueryConfig


# Pagination volume contract — auto-appended to MCP server ``instructions``
# when the schema exposes Result-wrapped fields (2026-11 pagination contract).
# This is the SINGLE home of the contract prose: instructions carry it once,
# globally, ahead of any tool call; tool descriptions keep only examples and
# a pointer. Not expressible in SDL (arg-level descriptions are a separate
# follow-up), so instructions are the earliest agent-visible channel.
PAGINATION_CONTRACT_NOTE = (
    "Paginated list fields return {items, pagination} and require volume "
    "intent — pass limit: N or fetchAll: true (no default page size; "
    "fetchAll overrides limit/offset and a server-side cap errors instead "
    "of truncating). Prefer limit windows; fetchAll after checking "
    "total_count."
)


def _merge_pagination_note(
    instructions: str | None, *handlers: GraphQLHandler
) -> str | None:
    """Append the pagination contract iff any handler's schema paginates.

    Detection reuses ``has_any_paginated_relationship`` — the same gate
    SDL/introspection render under (D3: one judgment, three consumers).
    Apps without paginated fields are untouched: ``None`` stays ``None``
    (6.8.0's "default sends nothing" holds for them). Caller-passed
    instructions come first; a caller who already covers the contract
    verbatim is not duplicated.
    """
    from nexusx.utils.pagination_schema import has_any_paginated_relationship

    if not any(
        has_any_paginated_relationship(h.er, h.entities) for h in handlers
    ):
        return instructions
    if instructions and PAGINATION_CONTRACT_NOTE in instructions:
        return instructions
    return "\n\n".join(p for p in (instructions, PAGINATION_CONTRACT_NOTE) if p)


def _ensure_operations(handler: GraphQLHandler, context: str) -> None:
    """Raise ValueError if the handler discovered no GraphQL operations.

    Guards MCP server builders against standing up a server whose schema has
    nothing to query (no @query/@mutation methods and no auto_query_config),
    which would otherwise silently serve an empty schema.
    """
    if not handler.has_operations:
        raise ValueError(
            f"{context}: GraphQL schema has no operations. "
            "Define @query/@mutation methods on your entities, "
            "or pass auto_query_config=AutoQueryConfig(...) to "
            "auto-generate by_id/by_filter queries."
        )


def create_multi_app_mcp_server(
    apps: list[Application],
    name: str = "Multi-App nexusx API",
    allow_mutation: bool = False,
    instructions: str | None = None,
) -> FastMCP:
    """Create an MCP server that exposes multiple GraphQL APIs as tools.

    ``instructions`` ride the initialize handshake (the agent's first read).
    When any mounted app's schema has paginated (Result-wrapped) fields, the
    pagination volume contract is auto-appended after the caller's text —
    see ``PAGINATION_CONTRACT_NOTE``.

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
        apps: List of :class:`Application` instances. Each app has its own
            GraphQL schema and independent database.
        name: Name of the MCP server (shown in MCP clients).
        allow_mutation: If True, registers mutation-related tools (list_mutations,
            get_mutation_schema, graphql_mutation) and includes mutations_count
            in list_apps. Default is False (read-only mode).

    Returns:
        A configured FastMCP server instance. Its ``lifespan`` is wired so that
        ``manager.dispose()`` runs on shutdown, releasing any engines owned by
        ``Application(url=...)`` instances.

    Raises:
        ValueError: If any application's schema has no operations (no
            @query/@mutation methods and no auto_query_config).

    Example:
        ```python
        from myapp.blog import BlogBaseEntity, BLOG_DATABASE_URL
        from myapp.shop import ShopBaseEntity, SHOP_DATABASE_URL
        from nexusx.mcp import Application, create_multi_app_mcp_server

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

        mcp = create_multi_app_mcp_server(
            apps=apps,
            name="My Multi-App GraphQL API"
        )

        # Run with stdio transport (default)
        mcp.run()

        # Or run with HTTP transport
        mcp.run(transport="streamable-http")
        ```

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

    # Fail fast if any app's schema has no operations (no @query/@mutation
    # and no auto_query_config) — otherwise the MCP serves an empty schema.
    for app_name, resources in manager.apps.items():
        _ensure_operations(resources.handler, f"create_multi_app_mcp_server (app '{app_name}')")

    # Wire lifespan so manager.dispose() runs on server shutdown,
    # releasing any engines owned by Applications constructed with url=.
    @asynccontextmanager
    async def _lifespan(_mcp: FastMCP) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await manager.dispose()

    # Create the FastMCP server (instructions ride the initialize handshake —
    # the agent's first read; None sends nothing). The pagination volume
    # contract is auto-appended when any mounted app paginates.
    instructions = _merge_pagination_note(
        instructions, *(res.handler for res in manager.apps.values())
    )
    mcp = FastMCP(name, instructions=instructions, lifespan=_lifespan)

    # Register all multi-app tools
    register_multi_app_tools(mcp, manager, allow_mutation=allow_mutation)

    return mcp


def create_single_app_mcp_server(
    base: type,
    name: str = "nexusx API",
    desc: str | None = None,
    allow_mutation: bool = False,
    session_factory: Callable | None = None,
    auto_query_config: AutoQueryConfig | None = None,
    instructions: str | None = None,
) -> FastMCP:
    """Create a simplified MCP server for single-app scenarios.

    This function creates a FastMCP server with only 2-3 tools, eliminating
    the complexity of multi-app management and progressive disclosure.
    Perfect for simple GraphQL APIs with a single database.

    **Tools provided (when allow_mutation=False, default):**
    - get_schema: Get the complete GraphQL schema in SDL format (single
      discovery entry point — entity types, relationships, and operations)
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
            with { items, pagination } wrapping. Default False.
        auto_query_config: Optional AutoQueryConfig for auto-generating
            by_id/by_filter queries. Default None.
        instructions: Usage guide agents receive with the ``initialize``
            handshake. When the schema has paginated (Result-wrapped) fields,
            the pagination volume contract is auto-appended after this text
            (see ``PAGINATION_CONTRACT_NOTE``); otherwise it is passed through
            unchanged (``None`` sends nothing).

    Returns:
        A configured FastMCP server instance with 3-4 simplified tools.

    Raises:
        ValueError: If the schema has no operations (no @query/@mutation
            methods and no auto_query_config).

    Example:
        ```python
        from sqlmodel import SQLModel
        from nexusx import query
        from nexusx.mcp import create_single_app_mcp_server

        class BaseEntity(SQLModel):
            pass

        class User(BaseEntity, table=True):
            id: int
            name: str

            @query
            async def get_users(cls) -> list['User']:
                return await fetch_users()

        # Create simplified MCP server
        mcp = create_single_app_mcp_server(
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
        For multi-app scenarios with separate databases, use create_multi_app_mcp_server()
        instead, which provides app discovery and routing capabilities.

    Tools provided (when allow_mutation=False, default):
        - get_schema(): Get the complete GraphQL schema (SDL) — the single
          discovery entry point
        - graphql_query(query): Execute a GraphQL query

    Additional tool (when allow_mutation=True):
        - graphql_mutation(mutation): Execute a GraphQL mutation
    """
    from fastmcp import FastMCP

    from nexusx.mcp.managers.single_app_manager import SingleAppManager
    from nexusx.mcp.tools.simple_tools import register_simple_tools

    # Create the single-app manager
    manager = SingleAppManager(
        base=base,
        description=desc,
        session_factory=session_factory,
        auto_query_config=auto_query_config,
    )
    _ensure_operations(manager.handler, "create_single_app_mcp_server")

    # Create the FastMCP server (instructions ride the initialize handshake —
    # the agent's first read; None sends nothing). The pagination volume
    # contract is auto-appended when the schema has Result-wrapped fields.
    instructions = _merge_pagination_note(instructions, manager.handler)
    mcp = FastMCP(name, instructions=instructions)

    # Register simplified tools (no app_name required)
    register_simple_tools(mcp, manager, allow_mutation=allow_mutation)

    return mcp

