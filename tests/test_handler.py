"""Tests for GraphQLHandler."""

from __future__ import annotations

import pytest
from sqlmodel import Field, Relationship, SQLModel

from nexusx import GraphQLHandler, mutation, query


# Define test base class
class HandlerTestBase(SQLModel):
    """Base class for test entities."""

    pass


class HandlerTestUser(HandlerTestBase, table=False):
    """Test user entity."""

    id: int = Field(primary_key=True)
    name: str
    email: str

    @query
    async def get_all(
        cls, limit: int = 10
    ) -> list[HandlerTestUser]:
        """Get all test users."""
        return [
            HandlerTestUser(id=1, name="Alice", email="alice@example.com"),
            HandlerTestUser(id=2, name="Bob", email="bob@example.com"),
        ][:limit]

    @query
    async def get_by_id(
        cls, id: int
    ) -> HandlerTestUser | None:
        """Get test user by ID."""
        return HandlerTestUser(id=id, name="Test", email="test@example.com")


class HandlerTestPost(HandlerTestBase, table=False):
    """Test post entity."""

    id: int = Field(primary_key=True)
    title: str
    content: str = ""

    @query
    async def get_all(cls) -> list[HandlerTestPost]:
        """Get all test posts."""
        return []

    @mutation
    async def create(cls, title: str, content: str) -> HandlerTestPost:
        """Create a test post."""
        return HandlerTestPost(id=1, title=title, content=content)


class HandlerTestNoDecorators(HandlerTestBase, table=False):
    """Entity without @query or @mutation decorators - should be ignored."""

    id: int = Field(primary_key=True)
    name: str


class TestDiscoverFromBase:
    """Tests for _discover_from_base method."""

    def test_discovers_entities_with_query(self) -> None:
        """Test that entities with @query are discovered."""
        handler = GraphQLHandler(base=HandlerTestBase)

        entity_names = [e.__name__ for e in handler.entities]
        assert "HandlerTestUser" in entity_names
        assert "HandlerTestPost" in entity_names

    def test_discovers_entities_with_mutation(self) -> None:
        """Test that entities with @mutation are discovered."""
        handler = GraphQLHandler(base=HandlerTestBase)

        entity_names = [e.__name__ for e in handler.entities]
        assert "HandlerTestPost" in entity_names  # Has @mutation

    def test_ignores_entities_without_decorators(self) -> None:
        """Test that entities without @query/@mutation are ignored."""
        handler = GraphQLHandler(base=HandlerTestBase)

        entity_names = [e.__name__ for e in handler.entities]
        assert "HandlerTestNoDecorators" not in entity_names


class TestGraphQLHandlerWithBase:
    """Tests for GraphQLHandler with base parameter."""

    @pytest.fixture
    def handler(self) -> GraphQLHandler:
        """Create handler with base parameter."""
        return GraphQLHandler(base=HandlerTestBase)

    def test_handler_creates_sdl_generator(self, handler: GraphQLHandler) -> None:
        """Test that handler creates SDL generator with discovered entities."""
        sdl = handler.get_sdl()

        assert "type HandlerTestUser" in sdl
        assert "type HandlerTestPost" in sdl

    def test_handler_discovers_query_methods(self, handler: GraphQLHandler) -> None:
        """Test that handler discovers query methods."""
        # Grouped layout: {entity_name: {method_name: (entity, method)}}
        assert "HandlerTestUser" in handler._query_methods
        assert "get_all" in handler._query_methods["HandlerTestUser"]
        assert "get_by_id" in handler._query_methods["HandlerTestUser"]
        assert "HandlerTestPost" in handler._query_methods
        assert "get_all" in handler._query_methods["HandlerTestPost"]

    def test_handler_discovers_mutation_methods(self, handler: GraphQLHandler) -> None:
        """Test that handler discovers mutation methods."""
        # Grouped layout: {entity_name: {method_name: (entity, method)}}
        assert "HandlerTestPost" in handler._mutation_methods
        assert "create" in handler._mutation_methods["HandlerTestPost"]

    @pytest.mark.asyncio
    async def test_execute_query(self, handler: GraphQLHandler) -> None:
        """Test executing a query."""
        result = await handler.execute("{ HandlerTestUser { get_all { id name } } }")

        assert "data" in result
        assert "HandlerTestUser" in result["data"]
        assert "get_all" in result["data"]["HandlerTestUser"]
        assert len(result["data"]["HandlerTestUser"]["get_all"]) == 2
        assert result["data"]["HandlerTestUser"]["get_all"][0]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_execute_mutation(self, handler: GraphQLHandler) -> None:
        """Test executing a mutation."""
        result = await handler.execute(
            'mutation { HandlerTestPost { create(title: "Hello", content: "World") { id title } } }'
        )

        assert "data" in result
        assert "HandlerTestPost" in result["data"]
        assert "create" in result["data"]["HandlerTestPost"]
        assert result["data"]["HandlerTestPost"]["create"]["title"] == "Hello"

    @pytest.mark.asyncio
    async def test_introspection_query(self, handler: GraphQLHandler) -> None:
        """Test introspection query."""
        result = await handler.execute("{ __schema { queryType { name } } }")

        assert "data" in result
        assert result["data"]["__schema"]["queryType"]["name"] == "Query"

    @pytest.mark.asyncio
    async def test_type_introspection_query(self, handler: GraphQLHandler) -> None:
        """Test __type introspection query."""
        result = await handler.execute('{ __type(name: "HandlerTestUser") { name kind } }')

        assert "data" in result
        assert result["data"]["__type"]["name"] == "HandlerTestUser"
        assert result["data"]["__type"]["kind"] == "OBJECT"

    @pytest.mark.asyncio
    async def test_mixed_query_with_introspection(self, handler: GraphQLHandler) -> None:
        """Normal query fields should coexist with introspection fields."""
        result = await handler.execute(
            "{ HandlerTestUser { get_all { id } } __schema { queryType { name } } }"
        )

        assert "data" in result
        assert "HandlerTestUser" in result["data"]
        assert "get_all" in result["data"]["HandlerTestUser"]
        assert result["data"]["__schema"]["queryType"]["name"] == "Query"

    @pytest.mark.asyncio
    async def test_rejects_aliases(self, handler: GraphQLHandler) -> None:
        """Aliases should fail fast with an explicit error."""
        result = await handler.execute("{ HandlerTestUser { get_all { userId: id } } }")

        assert "errors" in result
        assert any("aliases are not supported" in error["message"] for error in result["errors"])


# ============================================================================
# Tests for Relationship-based entity discovery
# ============================================================================


class HandlerTestAuthor(HandlerTestBase, table=False):
    """Author with @query - root entity."""

    id: int = Field(primary_key=True)
    name: str
    books: list[HandlerTestBook] = Relationship(back_populates="author")

    @query
    async def get_all(cls) -> list[HandlerTestAuthor]:
        """Get all test authors."""
        return []


class HandlerTestBook(HandlerTestBase, table=False):
    """Book WITHOUT @query/@mutation - discovered via Relationship."""

    id: int = Field(primary_key=True)
    title: str
    author_id: int = Field(foreign_key="handler_test_author.id")
    author: HandlerTestAuthor | None = Relationship(back_populates="books")


class HandlerTestIsolated(HandlerTestBase, table=False):
    """Isolated entity - no decorators AND no relationships - should NOT be discovered."""

    id: int = Field(primary_key=True)
    data: str


class TestDiscoverFromBaseWithRelationships:
    """Tests for _discover_from_base with Relationship traversal."""

    def test_discovers_root_entities_with_decorators(self) -> None:
        """Test that root entities with @query are discovered."""
        handler = GraphQLHandler(base=HandlerTestBase)

        entity_names = [e.__name__ for e in handler.entities]
        # Root entity: has @query
        assert "HandlerTestAuthor" in entity_names

    def test_discovers_related_entities_without_decorators(self) -> None:
        """Test that entities related via Relationship are discovered even without decorators."""
        handler = GraphQLHandler(base=HandlerTestBase)

        entity_names = [e.__name__ for e in handler.entities]
        # Related entity: no decorators but connected via Relationship
        assert "HandlerTestBook" in entity_names

    def test_ignores_isolated_entities_without_decorators(self) -> None:
        """Test that isolated entities without decorators are NOT discovered."""
        handler = GraphQLHandler(base=HandlerTestBase)

        entity_names = [e.__name__ for e in handler.entities]
        # Isolated entity: no decorators and no relationships
        assert "HandlerTestIsolated" not in entity_names

    def test_sdl_includes_related_entity_types(self) -> None:
        """Test that SDL generation includes related entity types."""
        handler = GraphQLHandler(base=HandlerTestBase)
        sdl = handler.get_sdl()

        # SDL should include the related entity type
        assert "type HandlerTestBook" in sdl
        assert "type HandlerTestAuthor" in sdl


# ============================================================================
# Tests for list[str] argument handling
# ============================================================================


class HandlerTestListArg(HandlerTestBase, table=False):
    """Test entity with list[str] argument."""

    id: int = Field(primary_key=True)
    tags: list[str] = Field(default_factory=list)

    @query
    async def get_by_tags(
        cls, tags: list[str]
    ) -> list[HandlerTestListArg]:
        """Get items by tags list."""
        return [HandlerTestListArg(id=i, tags=tags) for i in range(len(tags))]


class TestListStrArgument:
    """Tests for list[str] argument handling with literal values."""

    @pytest.fixture
    def handler(self) -> GraphQLHandler:
        """Create handler with base parameter."""
        return GraphQLHandler(base=HandlerTestBase)

    @pytest.mark.asyncio
    async def test_list_str_argument_literal(self, handler: GraphQLHandler) -> None:
        """Test executing a query with list[str] argument as literal."""
        result = await handler.execute(
            '{ HandlerTestListArg { get_by_tags(tags: ["tag1", "tag2"]) { id tags } } }'
        )

        assert "data" in result
        assert "HandlerTestListArg" in result["data"]
        assert "get_by_tags" in result["data"]["HandlerTestListArg"]
        assert len(result["data"]["HandlerTestListArg"]["get_by_tags"]) == 2
        assert result["data"]["HandlerTestListArg"]["get_by_tags"][0]["tags"] == ["tag1", "tag2"]

    @pytest.mark.asyncio
    async def test_list_str_argument_empty(self, handler: GraphQLHandler) -> None:
        """Test executing a query with empty list[str] argument."""
        result = await handler.execute(
            '{ HandlerTestListArg { get_by_tags(tags: []) { id tags } } }'
        )

        assert "data" in result
        assert "HandlerTestListArg" in result["data"]
        assert "get_by_tags" in result["data"]["HandlerTestListArg"]
        assert len(result["data"]["HandlerTestListArg"]["get_by_tags"]) == 0


# ============================================================================
# Tests for comprehensive list argument handling
# ============================================================================


class HandlerTestListMutation(HandlerTestBase, table=False):
    """Test entity with list argument mutations."""

    id: int = Field(primary_key=True)
    title: str = ""
    items: list[str] = Field(default_factory=list)
    numbers: list[int] = Field(default_factory=list)

    @mutation
    async def create_with_items(
        cls, title: str, items: list[str]
    ) -> HandlerTestListMutation:
        """Create entity with list of strings."""
        return HandlerTestListMutation(id=1, title=title, items=items)

    @mutation
    async def create_with_numbers(
        cls, numbers: list[int]
    ) -> HandlerTestListMutation:
        """Create entity with list of integers."""
        return HandlerTestListMutation(id=1, numbers=numbers)

    @mutation
    async def create_with_mixed_list(
        cls,
        title: str,
        items: list[str],
        numbers: list[int],
    ) -> HandlerTestListMutation:
        """Create entity with multiple list arguments."""
        return HandlerTestListMutation(id=1, title=title, items=items, numbers=numbers)


class TestListArgumentInMutation:
    """Tests for list argument handling in mutations."""

    @pytest.fixture
    def handler(self) -> GraphQLHandler:
        """Create handler with base parameter."""
        return GraphQLHandler(base=HandlerTestBase)

    @pytest.mark.asyncio
    async def test_mutation_with_list_str(self, handler: GraphQLHandler) -> None:
        """Test mutation with list[str] argument."""
        query = (
            'mutation { HandlerTestListMutation { create_with_items(title: "Test", '
            'items: ["a", "b", "c"]) { id title items } } }'
        )
        result = await handler.execute(query)

        assert "data" in result
        created = result["data"]["HandlerTestListMutation"]["create_with_items"]
        assert created["title"] == "Test"
        assert created["items"] == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_mutation_with_chinese_strings(self, handler: GraphQLHandler) -> None:
        """Test mutation with Chinese strings in list."""
        query = (
            'mutation { HandlerTestListMutation { create_with_items(title: "任务", '
            'items: ["洗脸", "刷牙", "洗脚"]) { id title items } } }'
        )
        result = await handler.execute(query)

        assert "data" in result
        assert result["data"]["HandlerTestListMutation"]["create_with_items"]["title"] == "任务"
        assert result["data"]["HandlerTestListMutation"]["create_with_items"]["items"] == [
            "洗脸", "刷牙", "洗脚"
        ]

    @pytest.mark.asyncio
    async def test_mutation_with_list_int(self, handler: GraphQLHandler) -> None:
        """Test mutation with list[int] argument."""
        result = await handler.execute(
            "mutation { HandlerTestListMutation { create_with_numbers("
            "numbers: [1, 2, 3, 4, 5]) { id numbers } } }"
        )

        assert "data" in result
        assert result["data"]["HandlerTestListMutation"]["create_with_numbers"]["numbers"] == [
            1, 2, 3, 4, 5
        ]

    @pytest.mark.asyncio
    async def test_mutation_with_empty_list(self, handler: GraphQLHandler) -> None:
        """Test mutation with empty list argument."""
        result = await handler.execute(
            'mutation { HandlerTestListMutation { create_with_items('
            'title: "Empty", items: []) { id title items } } }'
        )

        assert "data" in result
        assert result["data"]["HandlerTestListMutation"]["create_with_items"]["items"] == []

    @pytest.mark.asyncio
    async def test_mutation_with_multiple_lists(
        self, handler: GraphQLHandler
    ) -> None:
        """Test mutation with multiple list arguments."""
        query = (
            'mutation { HandlerTestListMutation { create_with_mixed_list(title: "Mixed", '
            'items: ["x", "y"], numbers: [10, 20]) { id title items numbers } } }'
        )
        result = await handler.execute(query)

        assert "data" in result
        mixed = result["data"]["HandlerTestListMutation"]["create_with_mixed_list"]
        assert mixed["title"] == "Mixed"
        assert mixed["items"] == ["x", "y"]
        assert mixed["numbers"] == [10, 20]

    @pytest.mark.asyncio
    async def test_mutation_with_single_item_list(
        self, handler: GraphQLHandler
    ) -> None:
        """Test mutation with single item in list."""
        result = await handler.execute(
            'mutation { HandlerTestListMutation { create_with_items('
            'title: "Single", items: ["only"]) { id items } } }'
        )

        assert "data" in result
        assert result["data"]["HandlerTestListMutation"]["create_with_items"]["items"] == ["only"]


class TestArgumentBuilderEdgeCases:
    """Tests for edge cases in argument building."""

    @pytest.fixture
    def handler(self) -> GraphQLHandler:
        """Create handler with base parameter."""
        return GraphQLHandler(base=HandlerTestBase)

    @pytest.mark.asyncio
    async def test_list_with_special_characters(
        self, handler: GraphQLHandler
    ) -> None:
        """Test list with special characters in strings."""
        query = (
            'mutation { HandlerTestListMutation { create_with_items(title: "Special", '
            'items: ["hello world", "foo-bar", "test_123"]) { id items } } }'
        )
        result = await handler.execute(query)

        assert "data" in result
        assert result["data"]["HandlerTestListMutation"]["create_with_items"]["items"] == [
            "hello world",
            "foo-bar",
            "test_123",
        ]

    @pytest.mark.asyncio
    async def test_query_list_still_works(self, handler: GraphQLHandler) -> None:
        """Ensure query with list argument still works after fix."""
        result = await handler.execute(
            '{ HandlerTestListArg { get_by_tags(tags: ["alpha", "beta"]) { id tags } } }'
        )

        assert "data" in result
        assert result["data"]["HandlerTestListArg"]["get_by_tags"][0]["tags"] == ["alpha", "beta"]
