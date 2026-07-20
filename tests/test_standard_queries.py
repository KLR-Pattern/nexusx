"""Test the standard query (by_id, by_filter) generation functionality."""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from sqlmodel import Field, SQLModel

from nexusx import AutoQueryConfig, GraphQLHandler, add_standard_queries, query


class ExplicitSearchFilter(BaseModel):
    keyword: str | None = None


class _Result:
    def __init__(self, first_value=None, all_values=None):
        self._first_value = first_value
        self._all_values = all_values or []

    def first(self):
        return self._first_value

    def all(self):
        return self._all_values


class _RecordingSession:
    def __init__(self, state: dict[str, object], result: _Result | None = None):
        self._state = state
        self._result = result or _Result()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def exec(self, stmt):
        self._state["stmt"] = stmt
        return self._result


def _session_factory(state: dict[str, object], result: _Result | None = None):
    async def factory():
        return _RecordingSession(state, result)

    return factory


def test_standard_queries_functionality():
    """Test that standard queries can be added and generate correct SDL."""
    # Create test entities
    class TestBase(SQLModel):
        id: int | None = Field(default=None, primary_key=True)

    class TestUser(TestBase, table=False):
        name: str
        email: str
        age: int | None = None

    # Add standard queries
    config = AutoQueryConfig(session_factory=_session_factory({}))
    add_standard_queries([TestUser], config)

    # Verify methods exist
    assert hasattr(TestUser, "by_id")
    assert hasattr(TestUser, "by_filter")

    # Generate SDL
    handler = GraphQLHandler(base=TestBase)
    sdl = handler.get_sdl()

    # Verify SDL contains expected content (grouped by entity at the GraphQL root)
    assert "TestUser: TestUserQuery!" in sdl
    assert "type TestUserQuery {" in sdl
    assert "by_id(id: Int!): TestUser" in sdl
    assert "by_filter(filter: TestUserFilterInput, limit: Int): [TestUser!]!" in sdl
    assert "input TestUserFilterInput" in sdl
    assert "name: String" in sdl
    assert "email: String" in sdl
    assert "age: Int" in sdl


def test_disable_standard_queries():
    """Test that standard queries can be disabled."""
    # Create test entities
    class TestBase2(SQLModel):
        id: int | None = Field(default=None, primary_key=True)

    class TestUser2(TestBase2, table=False):
        name: str
        email: str

    # Add standard queries with disabled
    config = AutoQueryConfig(
        session_factory=_session_factory({}),
        enabled=False,
    )
    add_standard_queries([TestUser2], config)

    # Verify methods not added
    assert not hasattr(TestUser2, "by_id")
    assert not hasattr(TestUser2, "by_filter")


def test_only_generate_by_filter():
    """Test that we can generate only by_filter."""
    # Create test entities
    class TestBase3(SQLModel):
        id: int | None = Field(default=None, primary_key=True)

    class TestUser3(TestBase3, table=False):
        name: str
        email: str

    # Add standard queries with only by_filter
    config = AutoQueryConfig(
        session_factory=_session_factory({}),
        generate_by_id=False,
    )
    add_standard_queries([TestUser3], config)

    # Verify methods
    assert not hasattr(TestUser3, "by_id")
    assert hasattr(TestUser3, "by_filter")


def test_dont_override_existing_methods():
    """Test that existing methods are not overridden."""
    # Create test entities
    class TestBase4(SQLModel):
        id: int | None = Field(default=None, primary_key=True)

    class TestUser4(TestBase4, table=False):
        name: str
        email: str

        @staticmethod
        def by_id():
            return "existing method"

        @staticmethod
        def by_filter():
            return "existing filter"

    # Add standard queries
    config = AutoQueryConfig(session_factory=_session_factory({}))
    add_standard_queries([TestUser4], config)

    # Verify existing methods are preserved
    assert TestUser4.by_id() == "existing method"
    assert TestUser4.by_filter() == "existing filter"


def test_auto_query_config_discovers_entities_without_existing_methods():
    """Test auto query config includes undecorated entities."""

    class TestBase5(SQLModel):
        pass

    class TestUser5(TestBase5, table=False):
        id: int | None = Field(default=None, primary_key=True)
        name: str

    handler = GraphQLHandler(
        base=TestBase5,
        auto_query_config=AutoQueryConfig(session_factory=_session_factory({})),
    )
    sdl = handler.get_sdl()

    assert "TestUser5: TestUser5Query!" in sdl
    assert "type TestUser5Query {" in sdl
    assert "by_id(id: Int!): TestUser5" in sdl
    assert "by_filter(filter: TestUser5FilterInput, limit: Int): [TestUser5!]!" in sdl


@pytest.mark.asyncio
async def test_by_filter_execution_uses_input_model_values():
    """Test by_filter converts GraphQL input objects into usable filter values."""

    class TestBase6(SQLModel):
        pass

    class TestUser6(TestBase6, table=True):
        id: int | None = Field(default=None, primary_key=True)
        name: str
        age: int | None = None

    state: dict[str, object] = {}
    handler = GraphQLHandler(
        base=TestBase6,
        auto_query_config=AutoQueryConfig(session_factory=_session_factory(state)),
    )

    result = await handler.execute(
        '{ TestUser6 { by_filter(filter: {name: "alice", age: 30}) { id name } } }'
    )

    assert "errors" not in result
    stmt = state["stmt"]
    where_clause = str(stmt.whereclause)
    assert "name" in where_clause
    assert "age" in where_clause


def test_filter_input_includes_inherited_fields():
    """Test filter input includes fields inherited from the base entity."""

    class TenantBase(SQLModel):
        id: int | None = Field(default=None, primary_key=True)
        tenant_id: int

    class TenantUser(TenantBase, table=False):
        name: str

    add_standard_queries(
        [TenantUser],
        AutoQueryConfig(session_factory=_session_factory({})),
    )

    handler = GraphQLHandler(base=TenantBase)
    sdl = handler.get_sdl()

    assert "input TenantUserFilterInput" in sdl
    assert "tenant_id: Int" in sdl


@pytest.mark.asyncio
async def test_by_id_uses_actual_primary_key_name_and_type():
    """Test by_id uses the entity primary key field instead of hard-coded id."""

    class TestBase7(SQLModel):
        pass

    class Product(TestBase7, table=True):
        code: str = Field(primary_key=True)
        name: str

    state: dict[str, object] = {}
    handler = GraphQLHandler(
        base=TestBase7,
        auto_query_config=AutoQueryConfig(session_factory=_session_factory(state)),
    )
    sdl = handler.get_sdl()

    assert "by_id(code: String!): Product" in sdl
    assert "Product: ProductQuery!" in sdl
    assert "type ProductQuery {" in sdl

    result = await handler.execute('{ Product { by_id(code: "sku-1") { code name } } }')

    assert "errors" not in result
    where_clause = str(state["stmt"].whereclause)
    assert "code" in where_clause


@pytest.mark.asyncio
async def test_by_id_ignores_non_primary_id_field():
    """A non-primary id field should not block real primary key discovery."""

    class TestBase7B(SQLModel):
        pass

    class CatalogItem(TestBase7B, table=True):
        id: int | None = None
        code: str = Field(primary_key=True)
        name: str

    state: dict[str, object] = {}
    handler = GraphQLHandler(
        base=TestBase7B,
        auto_query_config=AutoQueryConfig(session_factory=_session_factory(state)),
    )
    sdl = handler.get_sdl()

    assert "by_id(code: String!): CatalogItem" in sdl
    assert "CatalogItem: CatalogItemQuery!" in sdl
    assert "type CatalogItemQuery {" in sdl

    result = await handler.execute('{ CatalogItem { by_id(code: "sku-2") { code name } } }')

    assert "errors" not in result
    where_clause = str(state["stmt"].whereclause)
    assert "code" in where_clause


def test_existing_custom_filter_input_is_not_overridden_in_sdl():
    """Test auto queries do not replace explicit filter input types on custom queries."""

    class TestBase8(SQLModel):
        pass

    class TestUser8(TestBase8, table=False):
        id: int | None = Field(default=None, primary_key=True)
        name: str

        @query
        async def search(cls, filter: ExplicitSearchFilter) -> list[TestUser8]:
            return []

    add_standard_queries(
        [TestUser8],
        AutoQueryConfig(
            session_factory=_session_factory({}),
            generate_by_filter=False,
        ),
    )

    handler = GraphQLHandler(base=TestBase8)
    sdl = handler.get_sdl()

    assert "input ExplicitSearchFilter" in sdl
    # Custom @query method now lives inside the TestUser8 group with its verbatim name.
    assert "TestUser8: TestUser8Query!" in sdl
    assert "type TestUser8Query {" in sdl
    assert "search(filter: ExplicitSearchFilter!): [TestUser8!]!" in sdl
    assert "input TestUser8FilterInput" not in sdl
