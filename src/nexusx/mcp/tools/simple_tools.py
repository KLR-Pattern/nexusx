"""Simplified MCP tools for single-app scenarios.

This module registers simplified MCP tools that don't require app_name parameter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexusx.mcp.types.errors import (
    MCPErrors,
    create_error_response,
    create_success_response,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from nexusx.mcp.managers.single_app_manager import SingleAppManager


def register_simple_tools(
    mcp: FastMCP, manager: SingleAppManager, allow_mutation: bool = False
) -> None:
    """Register simplified tools for single-app scenarios.

    These tools are designed for single-application scenarios where:
    - No app routing is needed
    - Direct access to GraphQL operations is preferred
    - Simplicity is valued over progressive disclosure

    Args:
        mcp: The FastMCP server instance
        manager: The SingleAppManager instance
        allow_mutation: If True, registers graphql_mutation tool and includes
            Mutation type in schema. Default is False (read-only mode).
    """

    @mcp.tool()
    def get_schema() -> dict[str, Any]:
        """Get the complete GraphQL schema in SDL format.

        Single discovery entry point. Returns the full SDL: entity types
        with their fields and relationships, Result wrapper types, and
        every Query/Mutation operation. Read this before writing any
        query — the field signatures here are authoritative.

        List relationship fields come in two shapes:
        - ``field: [Entity!]!`` — plain list, select fields directly
        - ``field(...): EntityResult!`` — wrapped, select
          ``field { items { ... } pagination { has_more total_count } }``

        Example: ``{ User { posts(limit: 10) { items { id } } } }``

        Inside graphql_query, every call is processed as:
        - The query is validated against this schema.
        - Root fields resolve to entity queries (e.g. by_filter) with the
          given arguments.
        - Relationship fields are batch-loaded per nesting level via
          DataLoaders — one query per relationship level, not per row.
        - Only selected fields are returned.

        Returns:
            Dictionary containing:
            - success: True
            - data: {"sdl": "GraphQL SDL string"}

        Example response:
            {
                "success": true,
                "data": {
                    "sdl": "type Query { users(limit: Int): [User!]! ... }"
                }
            }
        """
        try:
            sdl = manager.handler.get_sdl(include_mutations=allow_mutation)
            return create_success_response({"sdl": sdl})
        except Exception as e:
            return create_error_response(str(e), MCPErrors.INTERNAL_ERROR)

    @mcp.tool()
    async def graphql_query(query: str) -> dict[str, Any]:
        """Execute a GraphQL query.

        Use this tool to fetch data from your GraphQL API.
        First use get_schema to discover available queries and their structure.

        Args:
            query: A GraphQL query string (must be valid GraphQL syntax)

        Returns:
            Dictionary containing:
            - success: True if query succeeded
            - data: The query result (if successful)
            - error: Error message (if failed)
            - error_type: Type of error (if failed)

        Examples (queries are entity-rooted — the entity name comes first,
        then its operations):
            # List entities: entity -> by_filter / by_id
            { Team { by_filter(limit: 10) { id name } } }

            # Traverse a relationship
            { Hero { by_id(id: 1) { name team { name } } } }

            # Custom @query methods appear under their entity
            { User { get_users(limit: 5) { id name } } }
        """
        if not query or not query.strip():
            return create_error_response(
                "query is required and cannot be empty",
                MCPErrors.MISSING_REQUIRED_FIELD,
            )

        try:
            result = await manager.handler.execute(query)

            if "errors" in result:
                error_messages = [
                    err.get("message", "Unknown error") for err in result["errors"]
                ]
                return create_error_response(
                    "; ".join(error_messages),
                    MCPErrors.QUERY_EXECUTION_ERROR,
                )

            return create_success_response(result.get("data"))
        except Exception as e:
            return create_error_response(str(e), MCPErrors.INTERNAL_ERROR)

    if allow_mutation:

        @mcp.tool()
        async def graphql_mutation(mutation: str) -> dict[str, Any]:
            """Execute a GraphQL mutation.

            Use this tool to create, update, or delete data.
            First use get_schema to discover available mutations and their input types.

            Args:
                mutation: A GraphQL mutation string (must be valid GraphQL syntax)

            Returns:
                Dictionary containing:
                - success: True if mutation succeeded
                - data: The mutation result (if successful)
                - error: Error message (if failed)
                - error_type: Type of error (if failed)

            Examples:
                # Create mutation with inline arguments
                mutation {
                    createUser(name: "Alice", email: "alice@example.com") {
                        id
                        name
                    }
                }

                # Update mutation
                mutation {
                    updatePost(id: 1, title: "New Title") {
                        id
                        title
                    }
                }

                # Create with input type
                mutation {
                    createUserWithInput(input: {name: "Bob", email: "bob@example.com"}) {
                        id
                    }
                }
            """
            if not mutation or not mutation.strip():
                return create_error_response(
                    "mutation is required and cannot be empty",
                    MCPErrors.MISSING_REQUIRED_FIELD,
                )

            try:
                result = await manager.handler.execute(mutation)

                if "errors" in result:
                    error_messages = [
                        err.get("message", "Unknown error") for err in result["errors"]
                    ]
                    return create_error_response(
                        "; ".join(error_messages),
                        MCPErrors.MUTATION_EXECUTION_ERROR,
                    )

                return create_success_response(result.get("data"))
            except Exception as e:
                return create_error_response(str(e), MCPErrors.INTERNAL_ERROR)
