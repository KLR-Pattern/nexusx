"""Integration tests for multi-app MCP tools."""

import pytest
from sqlmodel import Field, SQLModel

from nexusx import mutation, query

# Skip all tests in this module if fastmcp is not installed
pytest.importorskip("fastmcp")

from nexusx.mcp import Application, create_mcp_server  # noqa: E402


def _get_tools_dict(mcp):
    """Get tools as dict {name: tool} from FastMCP (compatible with fastmcp 3.x)."""
    components = mcp._local_provider._components
    return {
        key.split(":")[1].split("@")[0]: value
        for key, value in components.items()
        if key.startswith("tool:")
    }


# Test models for App 1
class BlogBaseEntity(SQLModel):
    """Base entity for Blog app."""

    pass


class BlogUser(BlogBaseEntity, table=True):
    """Blog user entity."""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str

    @query
    async def get_blog_users(cls, limit: int = 10) -> list["BlogUser"]:
        """Get blog users."""
        return []

    @mutation
    async def create_blog_user(cls, name: str, email: str) -> "BlogUser":
        """Create a blog user."""
        return BlogUser(name=name, email=email)


# Test models for App 2
class ShopBaseEntity(SQLModel):
    """Base entity for Shop app."""

    pass


class ShopProduct(ShopBaseEntity, table=True):
    """Shop product entity."""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    description: str = ""

    @query
    async def get_shop_products(cls, limit: int = 10) -> list["ShopProduct"]:
        """Get shop products."""
        return []

    @mutation
    async def create_shop_product(
        cls, name: str, description: str = ""
    ) -> "ShopProduct":
        """Create a shop product."""
        return ShopProduct(name=name, description=description)


@pytest.fixture
def multi_app_mcp():
    """Create a multi-app MCP server for testing."""
    apps = [
        Application(
            name="blog",
            base=BlogBaseEntity,
            description="Blog application",
            query_description="Query blog data",
            mutation_description="Mutate blog data",
        ),
        Application(
            name="shop",
            base=ShopBaseEntity,
            description="Shop application",
            query_description="Query shop data",
            mutation_description="Mutate shop data",
        ),
    ]
    return create_mcp_server(apps=apps, name="Test Multi-App", allow_mutation=True)


class TestMultiAppTools:
    """Integration tests for multi-app MCP tools."""

    def test_server_creation(self, multi_app_mcp):
        """Test that multi-app MCP server is created successfully."""
        assert multi_app_mcp is not None
        assert multi_app_mcp.name == "Test Multi-App"

    def test_list_apps_tool(self, multi_app_mcp):
        """Test list_apps tool returns all configured apps."""
        # Get the tool
        tools = _get_tools_dict(multi_app_mcp)
        list_apps_tool = tools.get("list_apps")

        assert list_apps_tool is not None

        # Execute the tool (not async)
        result = list_apps_tool.fn()

        assert result["success"] is True
        assert len(result["data"]) == 2

        # Check app names
        app_names = [app["name"] for app in result["data"]]
        assert "blog" in app_names
        assert "shop" in app_names

        # Check that each app has required fields
        for app in result["data"]:
            assert "name" in app
            assert "description" in app
            assert "queries_count" in app
            assert "mutations_count" in app

    def test_list_queries_with_valid_app(self, multi_app_mcp):
        """Test list_queries tool with a valid app_name."""
        tools = _get_tools_dict(multi_app_mcp)
        list_queries_tool = tools.get("list_queries")

        result = list_queries_tool.fn(app_name="blog")

        assert result["success"] is True
        assert isinstance(result["data"], list)
        assert len(result["data"]) > 0

        # Check that query has required fields
        query = result["data"][0]
        assert "name" in query
        assert "description" in query

    def test_list_queries_with_invalid_app(self, multi_app_mcp):
        """Test list_queries tool with an invalid app_name."""
        tools = _get_tools_dict(multi_app_mcp)
        list_queries_tool = tools.get("list_queries")

        result = list_queries_tool.fn(app_name="nonexistent")

        assert result["success"] is False
        assert "not found" in result["error"]
        assert "error_type" in result

    def test_list_mutations_with_valid_app(self, multi_app_mcp):
        """Test list_mutations tool with a valid app_name."""
        tools = _get_tools_dict(multi_app_mcp)
        list_mutations_tool = tools.get("list_mutations")

        result = list_mutations_tool.fn(app_name="shop")

        assert result["success"] is True
        assert isinstance(result["data"], list)
        assert len(result["data"]) > 0

        # Check that mutation has required fields
        mutation = result["data"][0]
        assert "name" in mutation
        assert "description" in mutation

    def test_list_mutations_with_invalid_app(self, multi_app_mcp):
        """Test list_mutations tool with an invalid app_name."""
        tools = _get_tools_dict(multi_app_mcp)
        list_mutations_tool = tools.get("list_mutations")

        result = list_mutations_tool.fn(app_name="nonexistent")

        assert result["success"] is False
        assert "not found" in result["error"]

    def test_get_query_schema_sdl_format(self, multi_app_mcp):
        """Test get_query_schema tool with SDL format."""
        tools = _get_tools_dict(multi_app_mcp)
        get_query_schema_tool = tools.get("get_query_schema")

        # First get the list of queries to find a valid query name
        list_queries_tool = tools.get("list_queries")
        queries_result = list_queries_tool.fn(app_name="blog")
        query_name = queries_result["data"][0]["name"]

        result = get_query_schema_tool.fn(
            name=query_name, app_name="blog", response_type="sdl"
        )

        assert result["success"] is True
        assert "sdl" in result["data"]
        assert query_name in result["data"]["sdl"]

    def test_get_query_schema_introspection_format(self, multi_app_mcp):
        """Test get_query_schema tool with introspection format."""
        tools = _get_tools_dict(multi_app_mcp)
        get_query_schema_tool = tools.get("get_query_schema")

        # First get the list of queries to find a valid query name
        list_queries_tool = tools.get("list_queries")
        queries_result = list_queries_tool.fn(app_name="blog")
        query_name = queries_result["data"][0]["name"]

        result = get_query_schema_tool.fn(
            name=query_name, app_name="blog", response_type="introspection"
        )

        assert result["success"] is True
        assert "operation" in result["data"]
        assert "types" in result["data"]

    def test_get_query_schema_invalid_query(self, multi_app_mcp):
        """Test get_query_schema tool with an invalid query name."""
        tools = _get_tools_dict(multi_app_mcp)
        get_query_schema_tool = tools.get("get_query_schema")

        result = get_query_schema_tool.fn(
            name="nonexistent_query", app_name="blog", response_type="sdl"
        )

        assert result["success"] is False
        assert "not found" in result["error"]

    def test_get_mutation_schema_sdl_format(self, multi_app_mcp):
        """Test get_mutation_schema tool with SDL format."""
        tools = _get_tools_dict(multi_app_mcp)
        get_mutation_schema_tool = tools.get("get_mutation_schema")

        # First get the list of mutations to find a valid mutation name
        list_mutations_tool = tools.get("list_mutations")
        mutations_result = list_mutations_tool.fn(app_name="shop")
        mutation_name = mutations_result["data"][0]["name"]

        result = get_mutation_schema_tool.fn(
            name=mutation_name, app_name="shop", response_type="sdl"
        )

        assert result["success"] is True
        assert "sdl" in result["data"]
        assert mutation_name in result["data"]["sdl"]

    @pytest.mark.asyncio
    async def test_graphql_query_with_valid_app(self, multi_app_mcp):
        """Test graphql_query tool with a valid app_name."""
        tools = _get_tools_dict(multi_app_mcp)
        graphql_query_tool = tools.get("graphql_query")

        result = await graphql_query_tool.fn(
            query="{ blogUserGetBlogUsers(limit: 1) { id } }", app_name="blog"
        )

        assert result["success"] is True
        assert "blogUserGetBlogUsers" in result["data"]

    @pytest.mark.asyncio
    async def test_graphql_query_with_invalid_app(self, multi_app_mcp):
        """Test graphql_query tool with an invalid app_name."""
        tools = _get_tools_dict(multi_app_mcp)
        graphql_query_tool = tools.get("graphql_query")

        result = await graphql_query_tool.fn(
            query="{ __typename }", app_name="nonexistent"
        )

        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_graphql_query_empty_query(self, multi_app_mcp):
        """Test graphql_query tool with an empty query."""
        tools = _get_tools_dict(multi_app_mcp)
        graphql_query_tool = tools.get("graphql_query")

        result = await graphql_query_tool.fn(query="", app_name="blog")

        assert result["success"] is False
        assert "required" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_graphql_mutation_with_valid_app(self, multi_app_mcp):
        """Test graphql_mutation tool with a valid app_name."""
        tools = _get_tools_dict(multi_app_mcp)
        graphql_mutation_tool = tools.get("graphql_mutation")

        result = await graphql_mutation_tool.fn(
            mutation='mutation { shopProductCreateShopProduct(name: "Test", '
                     'description: "A product") { id name } }',
            app_name="shop",
        )

        assert result["success"] is True
        assert "shopProductCreateShopProduct" in result["data"]

    @pytest.mark.asyncio
    async def test_graphql_mutation_with_invalid_app(self, multi_app_mcp):
        """Test graphql_mutation tool with an invalid app_name."""
        tools = _get_tools_dict(multi_app_mcp)
        graphql_mutation_tool = tools.get("graphql_mutation")

        result = await graphql_mutation_tool.fn(
            mutation='mutation { test { id } }', app_name="nonexistent"
        )

        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_graphql_mutation_empty_mutation(self, multi_app_mcp):
        """Test graphql_mutation tool with an empty mutation."""
        tools = _get_tools_dict(multi_app_mcp)
        graphql_mutation_tool = tools.get("graphql_mutation")

        result = await graphql_mutation_tool.fn(mutation="", app_name="shop")

        assert result["success"] is False
        assert "required" in result["error"].lower()

    def test_apps_are_isolated(self, multi_app_mcp):
        """Test that queries to different apps return different schemas."""
        tools = _get_tools_dict(multi_app_mcp)

        # Get queries from blog app
        list_queries_tool = tools.get("list_queries")
        blog_queries = list_queries_tool.fn(app_name="blog")

        # Get queries from shop app
        shop_queries = list_queries_tool.fn(app_name="shop")

        # They should have different queries
        blog_query_names = [q["name"] for q in blog_queries["data"]]
        shop_query_names = [q["name"] for q in shop_queries["data"]]

        # Blog should have blog-related queries
        assert any("blog" in name.lower() for name in blog_query_names)

        # Shop should have shop-related queries
        assert any("shop" in name.lower() for name in shop_query_names)

        # They should not share the same queries
        assert blog_query_names != shop_query_names


class TestMultiAppToolsReadOnlyMode:
    """Tests for read-only mode (allow_mutation=False)."""

    @pytest.fixture
    def read_only_mcp(self):
        """Create a multi-app MCP server without mutation support."""
        apps = [
            {
                "name": "blog",
                "base": BlogBaseEntity,
                "description": "Blog application",
            },
        ]
        return create_mcp_server(apps=apps, name="Test Read-Only", allow_mutation=False)

    def test_list_apps_mutations_count_zero(self, read_only_mcp):
        """Test list_apps returns mutations_count=0 when allow_mutation=False."""
        tools = _get_tools_dict(read_only_mcp)
        list_apps_tool = tools.get("list_apps")

        result = list_apps_tool.fn()

        assert result["success"] is True
        # mutations_count should be 0 in read-only mode
        for app in result["data"]:
            assert app["mutations_count"] == 0

    def test_mutation_tools_not_registered(self, read_only_mcp):
        """Test mutation-related tools are not registered when allow_mutation=False."""
        tools = _get_tools_dict(read_only_mcp)

        # These tools should NOT be registered
        assert "list_mutations" not in tools
        assert "get_mutation_schema" not in tools
        assert "graphql_mutation" not in tools

        # These tools SHOULD be registered
        assert "list_apps" in tools
        assert "list_queries" in tools
        assert "get_query_schema" in tools
        assert "graphql_query" in tools

    def test_query_tools_still_work(self, read_only_mcp):
        """Test query tools still work in read-only mode."""
        tools = _get_tools_dict(read_only_mcp)

        # Test list_queries
        list_queries_tool = tools.get("list_queries")
        result = list_queries_tool.fn(app_name="blog")
        assert result["success"] is True
        assert len(result["data"]) > 0
