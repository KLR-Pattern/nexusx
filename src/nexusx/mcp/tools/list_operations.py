"""list_queries and list_mutations MCP tools.

These tools provide the first layer of progressive disclosure,
returning only operation names and descriptions to minimize context usage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexusx.mcp.types.errors import create_success_response

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from nexusx.mcp.builders.type_tracer import TypeTracer


def register_list_operations_tools(mcp: FastMCP, tracer: TypeTracer) -> None:
    """Register list_queries and list_mutations tools with the MCP server.

    Args:
        mcp: The FastMCP server instance.
        tracer: The TypeTracer instance.
    """

    @mcp.tool()
    def list_queries() -> dict[str, Any]:
        """List all available GraphQL queries.

        Queries are grouped by entity (``{ Entity { method {} } }``). Returns a
        lightweight list of methods, each tagged with its entity. Use this tool
        first to discover available queries, then use get_query_schema with the
        entity and method to get detailed information.

        Returns:
            Dictionary containing:
            - success: True
            - data: List of {entity, method, name, description} method dicts

        Example response:
            {
                "success": true,
                "data": [
                    {"entity": "User", "method": "get_all", "name": "User.get_all"},
                    {"entity": "User", "method": "by_id", "name": "User.by_id"}
                ]
            }
        """
        try:
            queries = tracer.list_group_operations("Query")
            return create_success_response(queries)
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "error_type": "internal_error",
            }

    @mcp.tool()
    def list_mutations() -> dict[str, Any]:
        """List all available GraphQL mutations.

        Mutations are grouped by entity (``{ Entity { method {} } }``). Returns a
        lightweight list of methods, each tagged with its entity. Use this tool
        first to discover available mutations, then use get_mutation_schema with
        the entity and method to get detailed information.

        Returns:
            Dictionary containing:
            - success: True
            - data: List of {entity, method, name, description} method dicts

        Example response:
            {
                "success": true,
                "data": [
                    {"entity": "User", "method": "create", "name": "User.create"},
                    {"entity": "User", "method": "update", "name": "User.update"}
                ]
            }
        """
        try:
            mutations = tracer.list_group_operations("Mutation")
            return create_success_response(mutations)
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "error_type": "internal_error",
            }
