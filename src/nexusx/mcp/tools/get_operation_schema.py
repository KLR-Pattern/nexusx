"""get_query_schema and get_mutation_schema MCP tools.

These tools provide the second layer of progressive disclosure,
returning operation details and related type introspection data.

Supports two output formats:
- "sdl" (default): Schema Definition Language format, more compact
- "introspection": Full GraphQL introspection format
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from nexusx.mcp.types.errors import (
    MCPErrors,
    create_error_response,
    create_success_response,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from nexusx.mcp.builders.type_tracer import TypeTracer
    from nexusx.sdl_generator import SDLGenerator


def register_get_operation_schema_tools(
    mcp: FastMCP, tracer: TypeTracer, sdl_generator: SDLGenerator
) -> None:
    """Register get_query_schema and get_mutation_schema tools with the MCP server.

    Args:
        mcp: The FastMCP server instance.
        tracer: The TypeTracer instance.
        sdl_generator: The SDLGenerator instance for direct SDL generation.
    """

    @mcp.tool()
    def get_query_schema(
        entity: str,
        method: str,
        response_type: Literal["sdl", "introspection"] = "sdl"
    ) -> dict[str, Any]:
        """Get detailed schema information for a specific GraphQL query.

        Queries are grouped by entity (``{ Entity { method {} } }``); each
        query is identified by its entity and method name. Returns the query's
        arguments, return type, and related entity types. Use this after
        list_queries to get detailed information before executing a query.

        Args:
            entity: The entity (group) the query belongs to, e.g. "User".
            method: The method name verbatim, e.g. "get_all", "by_id".
            response_type: Output format - "sdl" (default, compact) or "introspection" (full).

        Returns:
            Dictionary containing:
            - success: True if found, False otherwise
            - data: (if successful) Dictionary with:
                - sdl: (when response_type="sdl") SDL format string
                - operation: (when response_type="introspection") Query introspection
                - types: (when response_type="introspection") Related type introspections
            - error: (if failed) Error message
            - error_type: (if failed) Error type

        Example SDL response:
            {
                "success": true,
                "data": {
                    "sdl": "# Query\\nget_all(limit: Int): [User!]!\\n\\n"
                    "# Related Types\\ntype User { ... }"
                }
            }
        """
        try:
            # For SDL format, use SDLGenerator directly (more efficient)
            if response_type == "sdl":
                sdl = sdl_generator.generate_operation_sdl(entity, method, "Query")
                if sdl is None:
                    return create_error_response(
                        f"Query '{entity}.{method}' not found",
                        MCPErrors.TYPE_NOT_FOUND,
                    )
                return create_success_response({"sdl": sdl})

            # For introspection format, use TypeTracer
            operation = tracer.get_group_operation("Query", entity, method)
            if operation is None:
                return create_error_response(
                    f"Query '{entity}.{method}' not found",
                    MCPErrors.TYPE_NOT_FOUND,
                )

            # Collect related types from return type
            return_type = operation.get("type")
            related_type_names = tracer.collect_related_types(return_type)

            # Get introspection data for related types
            types = tracer.get_introspection_for_types(related_type_names)

            return create_success_response({
                "operation": operation,
                "types": types,
            })

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "error_type": "internal_error",
            }

    @mcp.tool()
    def get_mutation_schema(
        entity: str,
        method: str,
        response_type: Literal["sdl", "introspection"] = "sdl"
    ) -> dict[str, Any]:
        """Get detailed schema information for a specific GraphQL mutation.

        Mutations are grouped by entity (``{ Entity { method {} } }``); each
        mutation is identified by its entity and method name. Returns the
        mutation's arguments, return type, and related entity types. Use this
        after list_mutations to get detailed information before executing a mutation.

        Args:
            entity: The entity (group) the mutation belongs to, e.g. "User".
            method: The method name verbatim, e.g. "create", "update".
            response_type: Output format - "sdl" (default, compact) or "introspection" (full).

        Returns:
            Dictionary containing:
            - success: True if found, False otherwise
            - data: (if successful) Dictionary with:
                - sdl: (when response_type="sdl") SDL format string
                - operation: (when response_type="introspection") Mutation introspection
                - types: (when response_type="introspection") Related type introspections
            - error: (if failed) Error message
            - error_type: (if failed) Error type

        Example SDL response:
            {
                "success": true,
                "data": {
                    "sdl": "# Mutation\\ncreate(name: String!, email: String!): User!\\n\\n"
                    "# Related Types\\ntype User { ... }"
                }
            }
        """
        try:
            # For SDL format, use SDLGenerator directly (more efficient)
            if response_type == "sdl":
                sdl = sdl_generator.generate_operation_sdl(entity, method, "Mutation")
                if sdl is None:
                    return create_error_response(
                        f"Mutation '{entity}.{method}' not found",
                        MCPErrors.TYPE_NOT_FOUND,
                    )
                return create_success_response({"sdl": sdl})

            # For introspection format, use TypeTracer
            operation = tracer.get_group_operation("Mutation", entity, method)
            if operation is None:
                return create_error_response(
                    f"Mutation '{entity}.{method}' not found",
                    MCPErrors.TYPE_NOT_FOUND,
                )

            # Collect related types from return type
            return_type = operation.get("type")
            related_type_names = tracer.collect_related_types(return_type)

            # Also collect types from input arguments
            for arg in operation.get("args", []):
                arg_types = tracer.collect_related_types(arg.get("type"))
                related_type_names.update(arg_types)

            # Get introspection data for related types
            types = tracer.get_introspection_for_types(related_type_names)

            return create_success_response({
                "operation": operation,
                "types": types,
            })

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "error_type": "internal_error",
            }
