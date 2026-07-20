"""Multi-app MCP tools registration.

This module registers all MCP tools for multi-app support with required app_name parameter.
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

    from nexusx.mcp.managers.multi_app_manager import MultiAppManager


def register_multi_app_tools(
    mcp: FastMCP, manager: MultiAppManager, allow_mutation: bool = False
) -> None:
    """Register all multi-app tools with the MCP server.

    Args:
        mcp: The FastMCP server instance
        manager: The MultiAppManager instance
        allow_mutation: If True, registers mutation-related tools (list_mutations,
            get_mutation_schema, graphql_mutation) and includes mutations_count
            in list_apps. Default is False (read-only mode).
    """

    # Layer 0: Application discovery
    @mcp.tool()
    def list_apps() -> dict[str, Any]:
        """List all available applications.

        Returns a list of all configured applications with their metadata.
        Use this tool first to discover available apps, then use app_name
        parameter with other tools.

        IMPORTANT: All subsequent tool calls (except this one) require the app_name parameter.
        Choose an app_name from the returned list and use it in all future calls.

        Returns:
            Dictionary containing:
            - success: True
            - data: List of app info dictionaries with name, description,
                    queries_count, and mutations_count
            - hint: Reminder to use app_name in subsequent calls

        Example response:
            {
                "success": true,
                "data": [
                    {
                        "name": "blog",
                        "description": "Blog API",
                        "queries_count": 5,
                        "mutations_count": 3
                    }
                ],
                "hint": "Use 'blog' as app_name parameter in subsequent tool calls"
            }
        """
        try:
            apps_info = [
                {
                    "name": app.name,
                    "description": app.description,
                    "queries_count": len(
                        app.tracer.list_group_operations("Query")
                    ),
                    "mutations_count": len(
                        app.tracer.list_group_operations("Mutation")
                    )
                    if allow_mutation
                    else 0,
                }
                for app in manager.apps.values()
            ]

            # Add helpful hint about app_name usage
            app_names = [app["name"] for app in apps_info]
            hint = (
                f"IMPORTANT: All subsequent tool calls require app_name parameter. "
                f"Available apps: {app_names}. "
                f"Example: list_queries(app_name='{app_names[0]}')"
            )

            return {
                "success": True,
                "data": apps_info,
                "hint": hint,
            }
        except Exception as e:
            return create_error_response(str(e), MCPErrors.INTERNAL_ERROR)

    # Layer 1: List operations
    @mcp.tool()
    def list_queries(app_name: str) -> dict[str, Any]:
        """List all available GraphQL queries for a specific application.

        Queries are grouped by entity (``{ Entity { method {} } }``). Returns a
        lightweight list of methods, each tagged with its entity. Use this tool
        after list_apps to discover queries for a specific app, then use
        get_query_schema with the entity and method to get detailed information.

        Args:
            app_name: Name of the application (required). Get available names from list_apps().

        Returns:
            Dictionary containing:
            - success: True
            - data: List of {entity, method, name, description} method dicts
            - hint: Reminder to use the same app_name in subsequent calls

        Example:
            list_queries(app_name="blog")
        """
        try:
            app = manager.get_app(app_name)
            queries = app.tracer.list_group_operations("Query")

            # Add reminder about app_name
            result = create_success_response(queries)
            result["hint"] = (
                f"Working with app '{app_name}'. "
                f"Remember to use app_name='{app_name}' in all subsequent calls "
                f"(get_query_schema, graphql_query, etc.)"
            )
            return result
        except ValueError as e:
            return create_error_response(str(e), MCPErrors.APP_NOT_FOUND)
        except Exception as e:
            return create_error_response(str(e), MCPErrors.INTERNAL_ERROR)

    if allow_mutation:

        @mcp.tool()
        def list_mutations(app_name: str) -> dict[str, Any]:
            """List all available GraphQL mutations for a specific application.

            Mutations are grouped by entity (``{ Entity { method {} } }``). Returns a
            lightweight list of methods, each tagged with its entity. Use this tool
            after list_apps to discover mutations for a specific app, then use
            get_mutation_schema with the entity and method to get detailed information.

            Args:
                app_name: Name of the application (required). Get available names from list_apps().

            Returns:
                Dictionary containing:
                - success: True
                - data: List of {entity, method, name, description} method dicts
                - hint: Reminder to use the same app_name in subsequent calls

            Example:
                list_mutations(app_name="blog")
            """
            try:
                app = manager.get_app(app_name)
                mutations = app.tracer.list_group_operations("Mutation")

                # Add reminder about app_name
                result = create_success_response(mutations)
                result["hint"] = (
                    f"Working with app '{app_name}'. "
                    f"Remember to use app_name='{app_name}' in all subsequent calls "
                    f"(get_mutation_schema, graphql_mutation, etc.)"
                )
                return result
            except ValueError as e:
                return create_error_response(str(e), MCPErrors.APP_NOT_FOUND)
            except Exception as e:
                return create_error_response(str(e), MCPErrors.INTERNAL_ERROR)

    # Layer 2: Get operation schema
    @mcp.tool()
    def get_query_schema(
        entity: str, method: str, app_name: str, response_type: str = "sdl"
    ) -> dict[str, Any]:
        """Get detailed schema information for a specific GraphQL query.

        Queries are grouped by entity (``{ Entity { method {} } }``); each query
        is identified by its entity and method name. Use this tool to understand
        a query's arguments, return type, and related types. Supports two formats:
        - sdl: GraphQL Schema Definition Language (compact, AI-friendly)
        - introspection: detailed introspection data

        Args:
            entity: The entity (group) the query belongs to, e.g. "User".
            method: The method name verbatim, e.g. "get_all", "by_id".
            app_name: Name of the application (required)
            response_type: Response format - "sdl" or "introspection" (default: "sdl")

        Returns:
            Dictionary containing:
            - success: True
            - data: Schema information in requested format

        Examples:
            # SDL format (recommended)
            get_query_schema(entity="User", method="get_all", app_name="blog", response_type="sdl")

            # Introspection format
            get_query_schema(
                entity="User", method="get_all", app_name="blog", response_type="introspection"
            )
        """
        try:
            app = manager.get_app(app_name)

            if response_type == "sdl":
                sdl = app.sdl_generator.generate_operation_sdl(entity, method, "Query")
                if sdl is None:
                    return create_error_response(
                        f"Query '{entity}.{method}' not found in app '{app.name}'",
                        MCPErrors.TYPE_NOT_FOUND,
                    )
                result = create_success_response({"sdl": sdl})
                result["hint"] = (
                    f"Ready to execute query on app '{app_name}'. "
                    f"Use graphql_query(query=..., app_name='{app_name}')"
                )
                return result

            # Introspection format
            operation = app.tracer.get_group_operation("Query", entity, method)
            if operation is None:
                return create_error_response(
                    f"Query '{entity}.{method}' not found in app '{app.name}'",
                    MCPErrors.TYPE_NOT_FOUND,
                )

            # Collect related types
            return_type = operation.get("type")
            related_type_names = app.tracer.collect_related_types(return_type)
            types = app.tracer.get_introspection_for_types(related_type_names)

            result = create_success_response(
                {
                    "operation": operation,
                    "types": types,
                }
            )
            result["hint"] = (
                f"Ready to execute query on app '{app_name}'. "
                f"Use graphql_query(query=..., app_name='{app_name}')"
            )
            return result
        except ValueError as e:
            return create_error_response(str(e), MCPErrors.APP_NOT_FOUND)
        except Exception as e:
            return create_error_response(str(e), MCPErrors.INTERNAL_ERROR)

    if allow_mutation:

        @mcp.tool()
        def get_mutation_schema(
            entity: str, method: str, app_name: str, response_type: str = "sdl"
        ) -> dict[str, Any]:
            """Get detailed schema information for a specific GraphQL mutation.

            Mutations are grouped by entity (``{ Entity { method {} } }``); each
            mutation is identified by its entity and method name. Use this tool to
            understand a mutation's arguments, return type, and related types. Supports
            two formats:
            - sdl: GraphQL Schema Definition Language (compact, AI-friendly)
            - introspection: detailed introspection data

            Args:
                entity: The entity (group) the mutation belongs to, e.g. "User".
                method: The method name verbatim, e.g. "create", "update".
                app_name: Name of the application (required)
                response_type: Response format - "sdl" or "introspection" (default: "sdl")

            Returns:
                Dictionary containing:
                - success: True
                - data: Schema information in requested format

            Examples:
                # SDL format (recommended)
                get_mutation_schema(
                    entity="User", method="create", app_name="blog", response_type="sdl"
                )

                # Introspection format
                get_mutation_schema(
                    entity="User", method="create", app_name="blog", response_type="introspection"
                )
            """
            try:
                app = manager.get_app(app_name)

                if response_type == "sdl":
                    sdl = app.sdl_generator.generate_operation_sdl(entity, method, "Mutation")
                    if sdl is None:
                        return create_error_response(
                            f"Mutation '{entity}.{method}' not found in app '{app.name}'",
                            MCPErrors.TYPE_NOT_FOUND,
                        )
                    return create_success_response({"sdl": sdl})

                # Introspection format
                operation = app.tracer.get_group_operation("Mutation", entity, method)
                if operation is None:
                    return create_error_response(
                        f"Mutation '{entity}.{method}' not found in app '{app.name}'",
                        MCPErrors.TYPE_NOT_FOUND,
                    )

                # Collect related types
                return_type = operation.get("type")
                related_type_names = app.tracer.collect_related_types(return_type)

                # Include argument types
                for arg in operation.get("args", []):
                    arg_types = app.tracer.collect_related_types(arg.get("type"))
                    related_type_names.update(arg_types)

                types = app.tracer.get_introspection_for_types(related_type_names)

                return create_success_response(
                    {
                        "operation": operation,
                        "types": types,
                    }
                )
            except ValueError as e:
                return create_error_response(str(e), MCPErrors.APP_NOT_FOUND)
            except Exception as e:
                return create_error_response(str(e), MCPErrors.INTERNAL_ERROR)

    # Layer 3: Execute operations
    @mcp.tool()
    async def graphql_query(query: str, app_name: str) -> dict[str, Any]:
        """Execute a GraphQL query on a specific application.

        Use this tool to execute GraphQL queries after discovering available
        operations with list_queries and understanding their schema with
        get_query_schema.

        Args:
            query: A GraphQL query string
            app_name: Name of the application (required)

        Returns:
            Dictionary containing:
            - success: True if query succeeded
            - data: The query result (if successful)
            - error: Error message (if failed)
            - error_type: Type of error (if failed)

        Examples:
            # Simple query
            graphql_query(
                query="{ User { get_all(limit: 10) { id name email } } }",
                app_name="blog"
            )

            # Query with relationships
            graphql_query(
                query="{ User { by_id(id: 1) { name posts { title } } } }",
                app_name="blog"
            )
        """
        if not query or not query.strip():
            return create_error_response(
                "query is required and cannot be empty",
                MCPErrors.MISSING_REQUIRED_FIELD,
            )

        try:
            app = manager.get_app(app_name)
            result = await app.handler.execute(query)

            if "errors" in result:
                error_messages = [
                    err.get("message", "Unknown error") for err in result["errors"]
                ]
                error_response = create_error_response(
                    "; ".join(error_messages),
                    MCPErrors.QUERY_EXECUTION_ERROR,
                )
                error_response["hint"] = (
                    f"Error occurred on app '{app_name}'. "
                    f"Use the same app_name='{app_name}' for retry."
                )
                return error_response

            # Success - add reminder about app_name for future calls
            response = create_success_response(result.get("data"))
            response["hint"] = (
                f"Query executed on app '{app_name}'. "
                f"For future queries, remember to use app_name='{app_name}'."
            )
            return response
        except ValueError as e:
            return create_error_response(str(e), MCPErrors.APP_NOT_FOUND)
        except Exception as e:
            return create_error_response(str(e), MCPErrors.INTERNAL_ERROR)

    if allow_mutation:

        @mcp.tool()
        async def graphql_mutation(mutation: str, app_name: str) -> dict[str, Any]:
            """Execute a GraphQL mutation on a specific application.

            Use this tool to execute GraphQL mutations after discovering available
            operations with list_mutations and understanding their schema with
            get_mutation_schema.

            Args:
                mutation: A GraphQL mutation string
                app_name: Name of the application (required)

            Returns:
                Dictionary containing:
                - success: True if mutation succeeded
                - data: The mutation result (if successful)
                - error: Error message (if failed)
                - error_type: Type of error (if failed)

            Examples:
                # Create mutation
                graphql_mutation(
                    mutation='mutation { User { create(name: "Alice", '
                    'email: "alice@example.com") { id name } } }',
                    app_name="blog"
                )

                # Update mutation
                graphql_mutation(
                    mutation='mutation { Post { update(id: 1, title: "New Title") { id title } } }',
                    app_name="blog"
                )
            """
            if not mutation or not mutation.strip():
                return create_error_response(
                    "mutation is required and cannot be empty",
                    MCPErrors.MISSING_REQUIRED_FIELD,
                )

            try:
                app = manager.get_app(app_name)
                result = await app.handler.execute(mutation)

                if "errors" in result:
                    error_messages = [
                        err.get("message", "Unknown error") for err in result["errors"]
                    ]
                    error_response = create_error_response(
                        "; ".join(error_messages),
                        MCPErrors.MUTATION_EXECUTION_ERROR,
                    )
                    error_response["hint"] = (
                        f"Error occurred on app '{app_name}'. "
                        f"Use the same app_name='{app_name}' for retry."
                    )
                    return error_response

                # Success - add reminder about app_name for future calls
                response = create_success_response(result.get("data"))
                response["hint"] = (
                    f"Mutation executed on app '{app_name}'. "
                    f"For future mutations, remember to use app_name='{app_name}'."
                )
                return response
            except ValueError as e:
                return create_error_response(str(e), MCPErrors.APP_NOT_FOUND)
            except Exception as e:
                return create_error_response(str(e), MCPErrors.INTERNAL_ERROR)
