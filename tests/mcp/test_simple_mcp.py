"""Tests for simplified MCP server configuration."""

from __future__ import annotations

import inspect

import pytest
from sqlmodel import Field, SQLModel

from nexusx import mutation, query
from nexusx.mcp import create_simple_mcp_server
from nexusx.mcp.managers.single_app_manager import SingleAppManager


def _get_tools_dict(mcp):
    """Get tools as dict {name: tool} from FastMCP (compatible with fastmcp 3.x)."""
    components = mcp._local_provider._components
    return {
        key.split(":")[1].split("@")[0]: value
        for key, value in components.items()
        if key.startswith("tool:")
    }


# Mock entities for testing (not test classes)
class SimpleMCPMockBaseEntity(SQLModel):
    """Base class for mock test entities."""

    __test__ = False  # Tell pytest this is not a test class


class SimpleMCPMockUser(SimpleMCPMockBaseEntity, table=True):
    """Mock user entity for testing."""

    __test__ = False
    __tablename__ = "simple_mcp_mock_user"  # Unique table name to avoid conflicts

    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str

    @query
    async def get_users(
        cls, limit: int = 10
    ) -> list[SimpleMCPMockUser]:
        """Get all mock users."""
        # Return mock data
        # Note: limit might be passed as string due to GraphQL argument conversion
        limit_int = int(limit) if isinstance(limit, str) else limit
        users = [
            SimpleMCPMockUser(id=1, name="Alice", email="alice@example.com"),
            SimpleMCPMockUser(id=2, name="Bob", email="bob@example.com"),
            SimpleMCPMockUser(id=3, name="Charlie", email="charlie@example.com"),
        ]
        return users[:limit_int]

    @query
    async def get_user(
        cls, id: int
    ) -> SimpleMCPMockUser | None:
        """Get a mock user by ID."""
        return SimpleMCPMockUser(id=id, name="Test User", email="test@example.com")

    @mutation
    async def create_user(
        cls, name: str, email: str
    ) -> SimpleMCPMockUser:
        """Create a new mock user."""
        return SimpleMCPMockUser(id=99, name=name, email=email)


class TestSingleAppManager:
    """Test cases for SingleAppManager."""

    def test_init_with_base_entity(self) -> None:
        """Test SingleAppManager initialization."""
        manager = SingleAppManager(base=SimpleMCPMockBaseEntity)

        assert manager.handler is not None
        assert manager.tracer is not None
        assert manager.sdl_generator is not None

    def test_init_with_description(self) -> None:
        """Test initialization with description."""
        manager = SingleAppManager(base=SimpleMCPMockBaseEntity, description="Test API")

        assert manager.handler is not None
        # Description is passed to SDLGenerator
        sdl_generator = manager.handler.get_sdl_generator()
        assert sdl_generator._query_description == "Test API"
        assert sdl_generator._mutation_description == "Test API"

    def test_entity_names_property(self) -> None:
        """Test entity_names property."""
        manager = SingleAppManager(base=SimpleMCPMockBaseEntity)

        entity_names = manager.entity_names

        assert isinstance(entity_names, set)
        assert "SimpleMCPMockUser" in entity_names


class TestGetSchema:
    """Test cases for get_schema tool."""

    def test_get_schema_returns_sdl(self) -> None:
        """Test get_schema returns SDL format."""
        mcp = create_simple_mcp_server(base=SimpleMCPMockBaseEntity)
        tools = _get_tools_dict(mcp)
        get_schema_tool = tools.get("get_schema")

        result = get_schema_tool.fn()

        assert result["success"] is True
        assert "sdl" in result["data"]
        assert "type Query" in result["data"]["sdl"]

    def test_get_schema_includes_mutations(self) -> None:
        """Test get_schema includes mutations when allow_mutation=True."""
        mcp = create_simple_mcp_server(base=SimpleMCPMockBaseEntity, allow_mutation=True)
        tools = _get_tools_dict(mcp)
        get_schema_tool = tools.get("get_schema")

        result = get_schema_tool.fn()

        assert result["success"] is True
        assert "type Mutation" in result["data"]["sdl"]

    def test_get_schema_excludes_mutations_by_default(self) -> None:
        """Test get_schema excludes mutations when allow_mutation=False (default)."""
        mcp = create_simple_mcp_server(base=SimpleMCPMockBaseEntity)
        tools = _get_tools_dict(mcp)
        get_schema_tool = tools.get("get_schema")

        result = get_schema_tool.fn()

        assert result["success"] is True
        assert "type Query" in result["data"]["sdl"]
        assert "type Mutation" not in result["data"]["sdl"]


class TestGraphQLQuery:
    """Test cases for graphql_query tool."""

    @pytest.mark.asyncio
    async def test_graphql_query_with_valid_query(self) -> None:
        """Test graphql_query with valid query."""
        mcp = create_simple_mcp_server(base=SimpleMCPMockBaseEntity)
        tools = _get_tools_dict(mcp)
        graphql_query_tool = tools.get("graphql_query")

        result = await graphql_query_tool.fn(
            query="{ SimpleMCPMockUser { get_users(limit: 1) { id name } } }"
        )

        assert result["success"] is True
        assert "SimpleMCPMockUser" in result["data"]
        assert "get_users" in result["data"]["SimpleMCPMockUser"]

    @pytest.mark.asyncio
    async def test_graphql_query_with_invalid_syntax(self) -> None:
        """Test graphql_query with invalid syntax."""
        mcp = create_simple_mcp_server(base=SimpleMCPMockBaseEntity)
        tools = _get_tools_dict(mcp)
        graphql_query_tool = tools.get("graphql_query")

        result = await graphql_query_tool.fn(query="{ invalid syntax }")

        assert result["success"] is False
        assert "error" in result
        assert result["error_type"] == "query_execution_error"

    @pytest.mark.asyncio
    async def test_graphql_query_with_empty_query(self) -> None:
        """Test graphql_query with empty query."""
        mcp = create_simple_mcp_server(base=SimpleMCPMockBaseEntity)
        tools = _get_tools_dict(mcp)
        graphql_query_tool = tools.get("graphql_query")

        result = await graphql_query_tool.fn(query="")

        assert result["success"] is False
        assert result["error_type"] == "missing_required_field"

    @pytest.mark.asyncio
    async def test_graphql_query_with_none_query(self) -> None:
        """Test graphql_query with None query."""
        mcp = create_simple_mcp_server(base=SimpleMCPMockBaseEntity)
        tools = _get_tools_dict(mcp)
        graphql_query_tool = tools.get("graphql_query")

        result = await graphql_query_tool.fn(query=None)

        assert result["success"] is False
        assert result["error_type"] == "missing_required_field"

    @pytest.mark.asyncio
    async def test_graphql_query_with_get_by_id(self) -> None:
        """Test graphql_query with get by ID."""
        mcp = create_simple_mcp_server(base=SimpleMCPMockBaseEntity)
        tools = _get_tools_dict(mcp)
        graphql_query_tool = tools.get("graphql_query")

        result = await graphql_query_tool.fn(
            query="{ SimpleMCPMockUser { get_user(id: 1) { id name email } } }"
        )

        assert result["success"] is True
        assert "get_user" in result["data"]["SimpleMCPMockUser"]


class TestGraphQLMutation:
    """Test cases for graphql_mutation tool."""

    @pytest.mark.asyncio
    async def test_graphql_mutation_create(self) -> None:
        """Test graphql_mutation with create mutation."""
        mcp = create_simple_mcp_server(base=SimpleMCPMockBaseEntity, allow_mutation=True)
        tools = _get_tools_dict(mcp)
        graphql_mutation_tool = tools.get("graphql_mutation")

        result = await graphql_mutation_tool.fn(
            mutation=(
                'mutation { SimpleMCPMockUser { create_user('
                'name: "Test", email: "test@example.com") { id name } } }'
            )
        )

        assert result["success"] is True
        assert "SimpleMCPMockUser" in result["data"]
        assert result["data"]["SimpleMCPMockUser"]["create_user"]["name"] == "Test"

    @pytest.mark.asyncio
    async def test_graphql_mutation_with_invalid_syntax(self) -> None:
        """Test graphql_mutation with invalid syntax."""
        mcp = create_simple_mcp_server(base=SimpleMCPMockBaseEntity, allow_mutation=True)
        tools = _get_tools_dict(mcp)
        graphql_mutation_tool = tools.get("graphql_mutation")

        result = await graphql_mutation_tool.fn(mutation="mutation { invalid }")

        assert result["success"] is False
        assert result["error_type"] == "mutation_execution_error"

    @pytest.mark.asyncio
    async def test_graphql_mutation_with_empty_mutation(self) -> None:
        """Test graphql_mutation with empty mutation."""
        mcp = create_simple_mcp_server(base=SimpleMCPMockBaseEntity, allow_mutation=True)
        tools = _get_tools_dict(mcp)
        graphql_mutation_tool = tools.get("graphql_mutation")

        result = await graphql_mutation_tool.fn(mutation="")

        assert result["success"] is False
        assert result["error_type"] == "missing_required_field"

    @pytest.mark.asyncio
    async def test_graphql_mutation_with_none_mutation(self) -> None:
        """Test graphql_mutation with None mutation."""
        mcp = create_simple_mcp_server(base=SimpleMCPMockBaseEntity, allow_mutation=True)
        tools = _get_tools_dict(mcp)
        graphql_mutation_tool = tools.get("graphql_mutation")

        result = await graphql_mutation_tool.fn(mutation=None)

        assert result["success"] is False
        assert result["error_type"] == "missing_required_field"

    def test_mutation_tool_not_registered_by_default(self) -> None:
        """Test graphql_mutation is not registered when allow_mutation=False."""
        mcp = create_simple_mcp_server(base=SimpleMCPMockBaseEntity)
        tools = _get_tools_dict(mcp)

        assert "graphql_mutation" not in tools


class TestConfigSimpleMCPServer:
    """Test cases for create_simple_mcp_server function."""

    def test_config_simple_mcp_server_creation(self) -> None:
        """Test creating simple MCP server."""
        mcp = create_simple_mcp_server(
            base=SimpleMCPMockBaseEntity, name="Test API", desc="Test Description"
        )

        assert mcp is not None
        assert mcp.name == "Test API"

    def test_config_simple_mcp_server_with_defaults(self) -> None:
        """Test creating simple MCP server with defaults."""
        mcp = create_simple_mcp_server(base=SimpleMCPMockBaseEntity)

        assert mcp.name == "nexusx API"

    def test_config_simple_mcp_server_tools_registered(self) -> None:
        """Test that only 2 tools are registered by default (allow_mutation=False)."""
        mcp = create_simple_mcp_server(base=SimpleMCPMockBaseEntity)
        tools = _get_tools_dict(mcp)

        # Should only have 2 tools by default
        assert len(tools) == 2
        assert "get_schema" in tools
        assert "graphql_query" in tools

        # Should NOT have mutation tools
        assert "graphql_mutation" not in tools

        # Should NOT have multi-app tools
        assert "list_apps" not in tools
        assert "list_queries" not in tools
        assert "list_mutations" not in tools
        assert "get_query_schema" not in tools
        assert "get_mutation_schema" not in tools

    def test_config_simple_mcp_server_tools_with_mutation(self) -> None:
        """Test that 3 tools are registered when allow_mutation=True."""
        mcp = create_simple_mcp_server(base=SimpleMCPMockBaseEntity, allow_mutation=True)
        tools = _get_tools_dict(mcp)

        # Should have 3 tools
        assert len(tools) == 3
        assert "get_schema" in tools
        assert "graphql_query" in tools
        assert "graphql_mutation" in tools

    def test_config_simple_mcp_server_no_app_name_parameter(self) -> None:
        """Test that tools do not require app_name parameter."""
        mcp = create_simple_mcp_server(base=SimpleMCPMockBaseEntity, allow_mutation=True)
        tools = _get_tools_dict(mcp)

        # Check graphql_query tool signature
        graphql_query_tool = tools.get("graphql_query")
        sig = inspect.signature(graphql_query_tool.fn)
        params = list(sig.parameters.keys())

        assert "query" in params
        assert "app_name" not in params

        # Check graphql_mutation tool signature
        graphql_mutation_tool = tools.get("graphql_mutation")
        sig = inspect.signature(graphql_mutation_tool.fn)
        params = list(sig.parameters.keys())

        assert "mutation" in params
        assert "app_name" not in params


class TestSimpleMCPIntegration:
    """Integration tests for simplified MCP server."""

    @pytest.mark.asyncio
    async def test_full_workflow(self) -> None:
        """Test full workflow: get schema -> query -> mutation."""
        mcp = create_simple_mcp_server(base=SimpleMCPMockBaseEntity, allow_mutation=True)
        tools = _get_tools_dict(mcp)

        # Step 1: Get schema
        get_schema_tool = tools.get("get_schema")
        schema_result = get_schema_tool.fn()

        assert schema_result["success"] is True
        assert "type Query" in schema_result["data"]["sdl"]
        assert "type Mutation" in schema_result["data"]["sdl"]

        # Step 2: Execute query
        graphql_query_tool = tools.get("graphql_query")
        query_result = await graphql_query_tool.fn(
            query="{ SimpleMCPMockUser { get_users(limit: 2) { id name } } }"
        )

        assert query_result["success"] is True
        assert "SimpleMCPMockUser" in query_result["data"]

        # Step 3: Execute mutation
        graphql_mutation_tool = tools.get("graphql_mutation")
        mutation_result = await graphql_mutation_tool.fn(
            mutation=(
                'mutation { SimpleMCPMockUser { create_user('
                'name: "New User", email: "new@example.com") { id name } } }'
            )
        )

        assert mutation_result["success"] is True
        assert "SimpleMCPMockUser" in mutation_result["data"]
        assert mutation_result["data"]["SimpleMCPMockUser"]["create_user"]["name"] == "New User"

    @pytest.mark.asyncio
    async def test_read_only_workflow(self) -> None:
        """Test read-only workflow: get schema -> query (no mutations)."""
        mcp = create_simple_mcp_server(base=SimpleMCPMockBaseEntity)
        tools = _get_tools_dict(mcp)

        # Step 1: Get schema - should not include mutations
        get_schema_tool = tools.get("get_schema")
        schema_result = get_schema_tool.fn()

        assert schema_result["success"] is True
        assert "type Query" in schema_result["data"]["sdl"]
        assert "type Mutation" not in schema_result["data"]["sdl"]

        # Step 2: Execute query
        graphql_query_tool = tools.get("graphql_query")
        query_result = await graphql_query_tool.fn(
            query="{ SimpleMCPMockUser { get_users(limit: 2) { id name } } }"
        )

        assert query_result["success"] is True
        assert "SimpleMCPMockUser" in query_result["data"]

        # Step 3: Mutation tool should not be available
        assert "graphql_mutation" not in tools

