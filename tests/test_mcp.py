"""Tests for MCP integration."""

from __future__ import annotations

import pytest

from nexusx.mcp.types.errors import (
    MCPError,
    MCPErrors,
    create_error_response,
    create_success_response,
)

# Check if fastmcp module is available
try:
    import fastmcp  # noqa: F401

    HAS_MCP = True
except ImportError:
    HAS_MCP = False


class TestMCPErrors:
    """Tests for MCP error handling."""

    def test_create_error_response_with_mcp_error(self) -> None:
        """Test creating error response from MCPError."""
        error = MCPError(MCPErrors.VALIDATION_ERROR, "Invalid input")
        response = create_error_response(error)
        assert response == {
            "success": False,
            "error": "Invalid input",
            "error_type": "validation_error",
        }

    def test_create_error_response_with_string(self) -> None:
        """Test creating error response from string."""
        response = create_error_response("Something went wrong")
        assert response == {
            "success": False,
            "error": "Something went wrong",
            "error_type": "internal_error",
        }

    def test_create_error_response_with_string_and_type(self) -> None:
        """Test creating error response with explicit type."""
        response = create_error_response(
            "Field not found",
            MCPErrors.TYPE_NOT_FOUND,
        )
        assert response == {
            "success": False,
            "error": "Field not found",
            "error_type": "type_not_found",
        }

    def test_create_success_response(self) -> None:
        """Test creating success response."""
        response = create_success_response({"id": 1, "name": "John"})
        assert response == {
            "success": True,
            "data": {"id": 1, "name": "John"},
        }


class TestSchemaFormatter:
    """Tests for SchemaFormatter with simple test entities."""

    def test_get_schema_info_structure(self) -> None:
        """Test that get_schema_info returns proper structure using test entities."""

        from sqlmodel import Field, SQLModel

        from nexusx import query
        from nexusx.handler import GraphQLHandler
        from nexusx.mcp.builders.schema_formatter import SchemaFormatter

        # Define test base and entity
        class TestBase(SQLModel):
            pass

        class TestUser(TestBase, table=False):
            """Test user entity."""

            id: int = Field(primary_key=True)
            name: str

            @query
            async def get_all(cls) -> list[TestUser]:
                return []

        handler = GraphQLHandler(base=TestBase)
        formatter = SchemaFormatter(handler)
        info = formatter.get_schema_info()

        assert "queries" in info
        assert "mutations" in info
        assert "types" in info

        # Check queries — under the grouped layout the SchemaFormatter exposes
        # one entry per entity group on the root Query type.
        assert len(info["queries"]) > 0
        query_names = [q["name"] for q in info["queries"]]
        assert "TestUser" in query_names

        # Check types
        assert len(info["types"]) > 0
        type_names = [t["name"] for t in info["types"]]
        assert "TestUser" in type_names

    def test_type_has_scalar_fields(self) -> None:
        """Test that types have scalar fields."""
        from sqlmodel import Field, SQLModel

        from nexusx import query
        from nexusx.handler import GraphQLHandler
        from nexusx.mcp.builders.schema_formatter import SchemaFormatter

        class TestBase(SQLModel):
            pass

        class TestPost(TestBase, table=False):
            id: int = Field(primary_key=True)
            title: str
            content: str

            @query
            async def get_all(cls) -> list[TestPost]:
                return []

        handler = GraphQLHandler(base=TestBase)
        formatter = SchemaFormatter(handler)
        info = formatter.get_schema_info()

        # Find TestPost type
        post_type = next((t for t in info["types"] if t["name"] == "TestPost"), None)
        assert post_type is not None

        # Check scalar fields
        scalar_names = [f["name"] for f in post_type["scalar_fields"]]
        assert "id" in scalar_names
        assert "title" in scalar_names
        assert "content" in scalar_names

    def test_query_has_arguments(self) -> None:
        """Test that queries have properly formatted arguments."""

        from sqlmodel import Field, SQLModel

        from nexusx import query
        from nexusx.handler import GraphQLHandler
        from nexusx.mcp.builders.type_tracer import TypeTracer

        class TestBase(SQLModel):
            pass

        class TestItem(TestBase, table=False):
            id: int = Field(primary_key=True)
            name: str

            @query
            async def get_by_id(cls, item_id: int) -> TestItem | None:
                return None

        handler = GraphQLHandler(base=TestBase)
        introspection = handler._introspection_generator.generate()
        entity_names = {e.__name__ for e in handler.entities}
        tracer = TypeTracer(introspection, entity_names)

        # Under the grouped layout the method lives on the {Entity}Query type,
        # fetched via get_group_operation.
        item_query = tracer.get_group_operation("Query", "TestItem", "get_by_id")
        assert item_query is not None

        # Check arguments
        arg_names = [a["name"] for a in item_query["args"]]
        assert "item_id" in arg_names

        # Check that the argument has a type
        id_arg = next((a for a in item_query["args"] if a["name"] == "item_id"), None)
        assert id_arg is not None
        assert "type" in id_arg


@pytest.mark.skipif(not HAS_MCP, reason="fastmcp package not installed")
class TestMCPServerCreation:
    """Tests for MCP server creation."""

    def test_create_mcp_server_with_test_entities(self) -> None:
        """Test that MCP server can be created with test entities."""
        from sqlmodel import Field, SQLModel

        from nexusx import query
        from nexusx.mcp import create_mcp_server

        class TestBase(SQLModel):
            pass

        class TestEntity(TestBase, table=False):
            id: int = Field(primary_key=True)
            name: str

            @query
            async def get_all(cls) -> list[TestEntity]:
                return []

        apps = [
            {
                "name": "test",
                "base": TestBase,
                "description": "Test application",
            }
        ]
        mcp = create_mcp_server(
            apps=apps,
            name="Test API",
        )

        # Check that server was created
        assert mcp is not None
        assert mcp.name == "Test API"


class TestListOperations:
    """Tests for list_queries and list_mutations tools."""

    def test_list_queries_returns_names_and_descriptions(self) -> None:
        """Test that list_queries returns names and descriptions."""
        from sqlmodel import Field, SQLModel

        from nexusx import query
        from nexusx.handler import GraphQLHandler
        from nexusx.mcp.builders.type_tracer import TypeTracer

        class TestBase(SQLModel):
            pass

        class TestUser(TestBase, table=False):
            id: int = Field(primary_key=True)
            name: str

            @query
            async def get_all(cls) -> list[TestUser]:
                """Get all test users."""
                return []

        handler = GraphQLHandler(base=TestBase)
        introspection = handler._introspection_generator.generate()
        entity_names = {e.__name__ for e in handler.entities}
        tracer = TypeTracer(introspection, entity_names)

        # Under the grouped layout, methods are listed via list_group_operations
        # which returns one entry per method tagged with its entity.
        queries = tracer.list_group_operations("Query")

        assert len(queries) == 1
        assert queries[0]["entity"] == "TestUser"
        assert queries[0]["method"] == "get_all"
        assert queries[0]["name"] == "TestUser.get_all"
        assert queries[0]["description"] == "Get all test users."

    def test_list_queries_empty_when_no_queries(self) -> None:
        """Test that list_queries returns empty list when no queries."""
        from sqlmodel import SQLModel

        from nexusx.handler import GraphQLHandler
        from nexusx.mcp.builders.type_tracer import TypeTracer

        class TestBase(SQLModel):
            pass

        handler = GraphQLHandler(base=TestBase)
        introspection = handler._introspection_generator.generate()
        entity_names = {e.__name__ for e in handler.entities}
        tracer = TypeTracer(introspection, entity_names)

        queries = tracer.list_operation_fields("Query")

        assert queries == []

    def test_list_mutations_returns_names_and_descriptions(self) -> None:
        """Test that list_mutations returns names and descriptions."""
        from sqlmodel import Field, SQLModel

        from nexusx import mutation
        from nexusx.handler import GraphQLHandler
        from nexusx.mcp.builders.type_tracer import TypeTracer

        class TestBase(SQLModel):
            pass

        class TestUser(TestBase, table=False):
            id: int = Field(primary_key=True)
            name: str

            @mutation
            async def create(cls, name: str) -> TestUser:
                """Create a test user."""
                return TestUser(id=1, name=name)

        handler = GraphQLHandler(base=TestBase)
        introspection = handler._introspection_generator.generate()
        entity_names = {e.__name__ for e in handler.entities}
        tracer = TypeTracer(introspection, entity_names)

        # Under the grouped layout, methods are listed via list_group_operations.
        mutations = tracer.list_group_operations("Mutation")

        assert len(mutations) == 1
        assert mutations[0]["entity"] == "TestUser"
        assert mutations[0]["method"] == "create"
        assert mutations[0]["name"] == "TestUser.create"


class TestGetOperationSchema:
    """Tests for get_query_schema and get_mutation_schema tools."""

    def test_get_query_schema_returns_operation_info(self) -> None:
        """Test that get_query_schema returns operation info."""
        from sqlmodel import Field, SQLModel

        from nexusx import query
        from nexusx.handler import GraphQLHandler
        from nexusx.mcp.builders.type_tracer import TypeTracer

        class TestBase(SQLModel):
            pass

        class TestUser(TestBase, table=False):
            id: int = Field(primary_key=True)
            name: str

            @query
            async def get_by_id(cls, user_id: int) -> TestUser | None:
                """Get user by ID."""
                return None

        handler = GraphQLHandler(base=TestBase)
        introspection = handler._introspection_generator.generate()
        entity_names = {e.__name__ for e in handler.entities}
        tracer = TypeTracer(introspection, entity_names)

        # Under the grouped layout, fetch the method via get_group_operation.
        operation = tracer.get_group_operation("Query", "TestUser", "get_by_id")

        assert operation is not None
        assert operation["name"] == "get_by_id"
        assert len(operation["args"]) == 1
        assert operation["args"][0]["name"] == "user_id"

    def test_get_query_schema_returns_related_types(self) -> None:
        """Test that get_query_schema can collect related types from introspection data."""
        # This test uses manually constructed introspection data to avoid
        # Python's forward reference issues when classes are defined inside methods.
        # See test_type_tracer.py for comprehensive tests of type tracing.
        from nexusx.mcp.builders.type_tracer import TypeTracer

        introspection = {
            "types": [
                {
                    "kind": "OBJECT",
                    "name": "Query",
                    "fields": [
                        {
                            "name": "users",
                            "description": "Get all users",
                            "args": [],
                            "type": {
                                "kind": "NON_NULL",
                                "ofType": {
                                    "kind": "LIST",
                                    "ofType": {
                                        "kind": "NON_NULL",
                                        "ofType": {"kind": "OBJECT", "name": "User"},
                                    },
                                },
                            },
                        }
                    ],
                },
                {
                    "kind": "OBJECT",
                    "name": "User",
                    "fields": [
                        {
                            "name": "id",
                            "type": {
                                "kind": "NON_NULL",
                                "ofType": {"kind": "SCALAR", "name": "Int"},
                            },
                        },
                        {
                            "name": "posts",
                            "type": {
                                "kind": "NON_NULL",
                                "ofType": {
                                    "kind": "LIST",
                                    "ofType": {
                                        "kind": "NON_NULL",
                                        "ofType": {"kind": "OBJECT", "name": "Post"},
                                    },
                                },
                            },
                        },
                    ],
                },
                {
                    "kind": "OBJECT",
                    "name": "Post",
                    "fields": [
                        {
                            "name": "id",
                            "type": {
                                "kind": "NON_NULL",
                                "ofType": {"kind": "SCALAR", "name": "Int"},
                            },
                        },
                        {
                            "name": "author",
                            "type": {
                                "kind": "NON_NULL",
                                "ofType": {"kind": "OBJECT", "name": "User"},
                            },
                        },
                    ],
                },
            ]
        }

        tracer = TypeTracer(introspection, {"User", "Post"})

        # Get operation and collect related types
        operation = tracer.get_operation_field("Query", "users")
        assert operation is not None

        related_types = tracer.collect_related_types(operation["type"])

        # Should include both User and Post (User -> posts -> Post)
        assert "User" in related_types
        assert "Post" in related_types

    def test_get_query_schema_nonexistent_returns_none(self) -> None:
        """Test that get_query_schema returns None for nonexistent query."""
        from sqlmodel import SQLModel

        from nexusx.handler import GraphQLHandler
        from nexusx.mcp.builders.type_tracer import TypeTracer

        class TestBase(SQLModel):
            pass

        handler = GraphQLHandler(base=TestBase)
        introspection = handler._introspection_generator.generate()
        entity_names = {e.__name__ for e in handler.entities}
        tracer = TypeTracer(introspection, entity_names)

        operation = tracer.get_operation_field("Query", "nonexistent")

        assert operation is None

    def test_get_mutation_schema_returns_operation_info(self) -> None:
        """Test that get_mutation_schema returns operation info."""
        from sqlmodel import Field, SQLModel

        from nexusx import mutation
        from nexusx.handler import GraphQLHandler
        from nexusx.mcp.builders.type_tracer import TypeTracer

        class TestBase(SQLModel):
            pass

        class TestUser(TestBase, table=False):
            id: int = Field(primary_key=True)
            name: str

            @mutation
            async def create(cls, name: str) -> TestUser:
                return TestUser(id=1, name=name)

        handler = GraphQLHandler(base=TestBase)
        introspection = handler._introspection_generator.generate()
        entity_names = {e.__name__ for e in handler.entities}
        tracer = TypeTracer(introspection, entity_names)

        # Under the grouped layout, fetch the method via get_group_operation.
        operation = tracer.get_group_operation("Mutation", "TestUser", "create")

        assert operation is not None
        assert operation["name"] == "create"

    def test_operation_with_no_arguments(self) -> None:
        """Test operation with no arguments."""
        from sqlmodel import Field, SQLModel

        from nexusx import query
        from nexusx.handler import GraphQLHandler
        from nexusx.mcp.builders.type_tracer import TypeTracer

        class TestBase(SQLModel):
            pass

        class TestUser(TestBase, table=False):
            id: int = Field(primary_key=True)
            name: str

            @query
            async def get_all(cls) -> list[TestUser]:
                return []

        handler = GraphQLHandler(base=TestBase)
        introspection = handler._introspection_generator.generate()
        entity_names = {e.__name__ for e in handler.entities}
        tracer = TypeTracer(introspection, entity_names)

        # Under the grouped layout, fetch the method via get_group_operation.
        operation = tracer.get_group_operation("Query", "TestUser", "get_all")

        assert operation is not None
        assert operation["args"] == []


class TestThreeLayerProgressiveDisclosure:
    """Integration tests for three-layer progressive disclosure."""

    def test_full_workflow(self) -> None:
        """Test full workflow from list to schema."""
        from sqlmodel import Field, SQLModel

        from nexusx import query
        from nexusx.handler import GraphQLHandler
        from nexusx.mcp.builders.type_tracer import TypeTracer

        class TestBase(SQLModel):
            pass

        class TestUser(TestBase, table=False):
            id: int = Field(primary_key=True)
            name: str

            @query
            async def get_all(cls, limit: int = 10) -> list[TestUser]:
                """Get all test users."""
                return []

        handler = GraphQLHandler(base=TestBase)
        introspection = handler._introspection_generator.generate()
        entity_names = {e.__name__ for e in handler.entities}
        tracer = TypeTracer(introspection, entity_names)

        # Layer 1: List queries (grouped: one entry per method)
        queries = tracer.list_group_operations("Query")
        assert len(queries) == 1
        assert queries[0]["entity"] == "TestUser"
        assert queries[0]["method"] == "get_all"
        assert queries[0]["name"] == "TestUser.get_all"

        # Layer 2: Get query schema (fetch the method from its entity group)
        operation = tracer.get_group_operation("Query", "TestUser", "get_all")
        assert operation is not None
        assert operation["name"] == "get_all"
        assert operation["description"] == "Get all test users."

        # Note: Due to Python's forward reference limitations when classes are
        # defined inside methods, the return type may not be correctly resolved.
        # The TypeTracer tests in test_type_tracer.py cover the full functionality
        # with properly defined classes.
