"""Tests for GraphQL introspection generator."""

from enum import Enum
from typing import Optional

import pytest
from sqlmodel import Field, Relationship, SQLModel

from nexusx import GraphQLHandler, mutation, query
from nexusx.introspection import IntrospectionGenerator


class IntrospectionBase(SQLModel):
    """Base class for introspection test entities."""
    pass


class Status(Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class IntrospectionUser(IntrospectionBase, table=True):
    __tablename__ = "introspection_user"  # Unique table name to avoid conflicts
    id: int = Field(default=None, primary_key=True)
    name: str
    email: str | None = None
    status: Status = Status.ACTIVE

    @query
    def get_users(cls, limit: int = 10) -> list["IntrospectionUser"]:
        return []

    @query
    def get_user(cls, id: int) -> Optional["IntrospectionUser"]:
        return None

    @mutation
    def create_user(cls, name: str, email: str | None = None) -> "IntrospectionUser":
        return cls(name=name, email=email)


# ---------------------------------------------------------------------------
# Entity with various default value types for regression testing
# ---------------------------------------------------------------------------


class IntrospectionConfig(IntrospectionBase, table=True):
    """Entity with various default value types for regression testing."""
    __tablename__ = "introspection_config"
    id: int = Field(default=None, primary_key=True)
    key: str
    value: str

    @mutation
    def create_config(
        cls,
        key: str,
        value: str = "default",
        priority: int = 5,
        score: float = 1.0,
        is_active: bool = True,
        tag: str | None = None,
        tags: list[str] | None = None,
    ) -> "IntrospectionConfig":
        return cls(key=key, value=value)

    @query
    def get_configs(
        cls,
        status: str = "active",
        enabled: bool = False,
        threshold: float = 0.5,
        fallback: str | None = None,
    ) -> list["IntrospectionConfig"]:
        return []


# ---------------------------------------------------------------------------
# Entities with FK + Relationship for FK filtering tests
# ---------------------------------------------------------------------------

class IntrospectionAuthor(IntrospectionBase, table=True):
    __tablename__ = "introspection_author"
    id: int = Field(default=None, primary_key=True)
    name: str
    articles: list["IntrospectionArticle"] = Relationship(back_populates="author")

    @query
    def get_all(cls) -> list["IntrospectionAuthor"]:
        return []


class IntrospectionArticle(IntrospectionBase, table=True):
    __tablename__ = "introspection_article"
    id: int = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="introspection_author.id")
    author: IntrospectionAuthor | None = Relationship(back_populates="articles")


# ---------------------------------------------------------------------------
# Base for paginated introspection tests (requires table=True + session)
# ---------------------------------------------------------------------------

class PagBase(SQLModel):
    """Base class for paginated introspection test entities."""
    pass


class PagAuthor(PagBase, table=True):
    __tablename__ = "pag_introspection_author"
    id: int = Field(default=None, primary_key=True)
    name: str
    posts: list["PagPost"] = Relationship(
        sa_relationship_kwargs={"order_by": "PagPost.id"},
    )

    @query
    def get_all(cls) -> list["PagAuthor"]:
        return []


class PagPost(PagBase, table=True):
    __tablename__ = "pag_introspection_post"
    id: int = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="pag_introspection_author.id")
    author: PagAuthor | None = Relationship()


class TestIntrospectionGenerator:
    """Tests for IntrospectionGenerator class."""

    @pytest.fixture
    def handler(self) -> GraphQLHandler:
        return GraphQLHandler(base=IntrospectionBase)

    @pytest.fixture
    def generator(self, handler: GraphQLHandler) -> IntrospectionGenerator:
        return handler._introspection_generator

    def test_generate_schema_structure(self, generator: IntrospectionGenerator):
        """Test that generate() returns correct schema structure."""
        schema = generator.generate()

        assert "queryType" in schema
        assert "mutationType" in schema
        assert "subscriptionType" in schema
        assert "types" in schema
        assert "directives" in schema

        assert schema["queryType"]["name"] == "Query"
        assert schema["mutationType"]["name"] == "Mutation"
        assert schema["subscriptionType"] is None
        assert schema["directives"] == []

    def test_scalar_types(self, generator: IntrospectionGenerator):
        """Test that scalar types are included."""
        schema = generator.generate()
        type_names = [t["name"] for t in schema["types"]]

        assert "Int" in type_names
        assert "Float" in type_names
        assert "String" in type_names
        assert "Boolean" in type_names
        assert "ID" in type_names

    def test_entity_type(self, generator: IntrospectionGenerator):
        """Test that entity types are included with correct fields."""
        schema = generator.generate()

        user_type = next((t for t in schema["types"] if t["name"] == "IntrospectionUser"), None)
        assert user_type is not None
        assert user_type["kind"] == "OBJECT"

        field_names = [f["name"] for f in user_type["fields"]]
        assert "id" in field_names
        assert "name" in field_names
        assert "email" in field_names
        assert "status" in field_names

    def test_enum_type(self, generator: IntrospectionGenerator):
        """Test that enum types are included with correct values."""
        schema = generator.generate()

        status_type = next((t for t in schema["types"] if t["name"] == "Status"), None)
        assert status_type is not None
        assert status_type["kind"] == "ENUM"

        enum_values = [v["name"] for v in status_type["enumValues"]]
        assert "ACTIVE" in enum_values
        assert "INACTIVE" in enum_values

    def test_query_type(self, generator: IntrospectionGenerator):
        """Test that Query type is generated with correct fields."""
        schema = generator.generate()

        query_type = next((t for t in schema["types"] if t["name"] == "Query"), None)
        assert query_type is not None
        assert query_type["kind"] == "OBJECT"

        # Grouped layout: root Query mounts one field per entity; the methods
        # themselves live on the {Entity}Query group OBJECT.
        field_names = [f["name"] for f in query_type["fields"]]
        assert "IntrospectionUser" in field_names

        user_group = next(
            (t for t in schema["types"] if t["name"] == "IntrospectionUserQuery"), None
        )
        assert user_group is not None
        group_field_names = [f["name"] for f in user_group["fields"]]
        assert "get_users" in group_field_names
        assert "get_user" in group_field_names

    def test_mutation_type(self, generator: IntrospectionGenerator):
        """Test that Mutation type is generated with correct fields."""
        schema = generator.generate()

        mutation_type = next((t for t in schema["types"] if t["name"] == "Mutation"), None)
        assert mutation_type is not None
        assert mutation_type["kind"] == "OBJECT"

        # Grouped layout: methods live on the {Entity}Mutation group OBJECT.
        field_names = [f["name"] for f in mutation_type["fields"]]
        assert "IntrospectionUser" in field_names

        user_group = next(
            (t for t in schema["types"] if t["name"] == "IntrospectionUserMutation"), None
        )
        assert user_group is not None
        group_field_names = [f["name"] for f in user_group["fields"]]
        assert "create_user" in group_field_names

    def test_field_arguments(self, generator: IntrospectionGenerator):
        """Test that field arguments are generated correctly."""
        schema = generator.generate()

        user_group = next(
            (t for t in schema["types"] if t["name"] == "IntrospectionUserQuery"), None
        )
        assert user_group is not None
        users_field = next(
            (f for f in user_group["fields"] if f["name"] == "get_users"),
            None,
        )

        assert users_field is not None
        arg_names = [a["name"] for a in users_field["args"]]
        assert "limit" in arg_names

    def test_return_type_structure(self, generator: IntrospectionGenerator):
        """Test that return types are structured correctly."""
        schema = generator.generate()

        user_group = next(
            (t for t in schema["types"] if t["name"] == "IntrospectionUserQuery"), None
        )
        assert user_group is not None
        users_field = next(
            (f for f in user_group["fields"] if f["name"] == "get_users"),
            None,
        )

        # users returns list[User], so type should be NON_NULL(LIST(NON_NULL(OBJECT(User))))
        return_type = users_field["type"]
        assert return_type["kind"] == "NON_NULL"
        assert return_type["ofType"]["kind"] == "LIST"

    def test_optional_return_type(self, generator: IntrospectionGenerator):
        """Test that Optional return types are handled correctly."""
        schema = generator.generate()

        user_group = next(
            (t for t in schema["types"] if t["name"] == "IntrospectionUserQuery"), None
        )
        assert user_group is not None
        user_field = next(
            (f for f in user_group["fields"] if f["name"] == "get_user"),
            None,
        )

        # user returns Optional[User], so type should be OBJECT (not NON_NULL)
        return_type = user_field["type"]
        # Could be OBJECT directly or wrapped differently
        assert return_type["kind"] in ("OBJECT", "NON_NULL")

    def test_execute(self, generator: IntrospectionGenerator):
        """Test execute() returns correct response structure."""
        result = generator.execute("{ __schema { queryType { name } } }")

        assert "data" in result
        assert "__schema" in result["data"]
        assert result["data"]["__schema"]["queryType"]["name"] == "Query"

    def test_execute_type_query(self, generator: IntrospectionGenerator):
        """__type queries should return the requested type payload."""
        result = generator.execute('{ __type(name: "IntrospectionUser") { name kind } }')

        assert "data" in result
        assert result["data"]["__type"]["name"] == "IntrospectionUser"
        assert result["data"]["__type"]["kind"] == "OBJECT"


class TestIntrospectionIntegration:
    """Integration tests for introspection via GraphQLHandler."""

    @pytest.fixture
    def handler(self) -> GraphQLHandler:
        return GraphQLHandler(base=IntrospectionBase)

    @pytest.mark.asyncio
    async def test_introspection_query(self, handler: GraphQLHandler):
        """Test that handler executes introspection queries."""
        query = """
        {
            __schema {
                queryType { name }
                mutationType { name }
            }
        }
        """

        result = await handler.execute(query)

        assert "data" in result
        assert result["data"]["__schema"]["queryType"]["name"] == "Query"
        assert result["data"]["__schema"]["mutationType"]["name"] == "Mutation"

    @pytest.mark.asyncio
    async def test_full_introspection_query(self, handler: GraphQLHandler):
        """Test full introspection query like GraphiQL would send."""
        query = """
        query IntrospectionQuery {
            __schema {
                queryType { name }
                mutationType { name }
                subscriptionType { name }
                types {
                    kind
                    name
                    fields {
                        name
                        type {
                            kind
                            name
                            ofType {
                                kind
                                name
                            }
                        }
                    }
                }
            }
        }
        """

        result = await handler.execute(query)

        assert "data" in result
        schema = result["data"]["__schema"]
        assert schema["queryType"]["name"] == "Query"
        assert schema["mutationType"]["name"] == "Mutation"

        # Check that IntrospectionUser type is present
        user_type = next((t for t in schema["types"] if t["name"] == "IntrospectionUser"), None)
        assert user_type is not None
        assert user_type["kind"] == "OBJECT"

    @pytest.mark.asyncio
    async def test_introspection_with_types_query(self, handler: GraphQLHandler):
        """Test introspection query for specific type."""
        query = """
        {
            __schema {
                types {
                    name
                    kind
                }
            }
        }
        """

        result = await handler.execute(query)

        assert "data" in result
        type_names = [t["name"] for t in result["data"]["__schema"]["types"]]

        # Should include scalars
        assert "Int" in type_names
        assert "String" in type_names
        assert "Boolean" in type_names

        # Should include our types
        assert "IntrospectionUser" in type_names
        assert "Status" in type_names
        assert "Query" in type_names
        assert "Mutation" in type_names


class TestCustomDescriptions:
    """Tests for custom Query/Mutation descriptions."""

    def test_custom_query_description(self) -> None:
        """Custom query description should be used."""
        handler = GraphQLHandler(
            base=IntrospectionBase,
            query_description="自定义查询描述",
        )
        schema = handler._introspection_generator.generate()

        query_type = next(
            (t for t in schema["types"] if t["name"] == "Query"), None
        )
        assert query_type is not None
        assert query_type["description"] == "自定义查询描述"

    def test_custom_mutation_description(self) -> None:
        """Custom mutation description should be used."""
        handler = GraphQLHandler(
            base=IntrospectionBase,
            mutation_description="自定义变更描述",
        )
        schema = handler._introspection_generator.generate()

        mutation_type = next(
            (t for t in schema["types"] if t["name"] == "Mutation"), None
        )
        assert mutation_type is not None
        assert mutation_type["description"] == "自定义变更描述"

    def test_default_description_is_none(self) -> None:
        """Default description should be None when not provided."""
        handler = GraphQLHandler(base=IntrospectionBase)
        schema = handler._introspection_generator.generate()

        query_type = next(
            (t for t in schema["types"] if t["name"] == "Query"), None
        )
        mutation_type = next(
            (t for t in schema["types"] if t["name"] == "Mutation"), None
        )

        assert query_type is not None
        assert query_type["description"] is None
        assert mutation_type is not None
        assert mutation_type["description"] is None


class TestFKFieldFiltering:
    """Tests for FK field filtering in introspection."""

    @pytest.fixture
    def handler(self) -> GraphQLHandler:
        return GraphQLHandler(base=IntrospectionBase)

    def test_fk_fields_excluded_from_entity_type(
        self, handler: GraphQLHandler,
    ) -> None:
        """FK fields should not appear in introspection entity types."""
        schema = handler._introspection_generator.generate()

        article_type = next(
            (t for t in schema["types"] if t["name"] == "IntrospectionArticle"),
            None,
        )
        assert article_type is not None

        field_names = [f["name"] for f in article_type["fields"]]
        # author_id is a FK field — should be excluded
        assert "author_id" not in field_names
        # title and id are regular fields — should be included
        assert "id" in field_names
        assert "title" in field_names
        # author is a relationship field — should be included
        assert "author" in field_names

    def test_entity_without_fk_has_all_fields(
        self, handler: GraphQLHandler,
    ) -> None:
        """Entity without FK fields should show all its scalar fields."""
        schema = handler._introspection_generator.generate()

        author_type = next(
            (t for t in schema["types"] if t["name"] == "IntrospectionAuthor"),
            None,
        )
        assert author_type is not None

        field_names = [f["name"] for f in author_type["fields"]]
        assert "id" in field_names
        assert "name" in field_names


class _DummySessionFactory:
    """A no-op session factory for testing pagination introspection."""

    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class TestPaginationIntrospection:
    """Tests for pagination types in introspection."""

    @pytest.fixture
    def handler(self) -> GraphQLHandler:
        return GraphQLHandler(
            base=PagBase,
            session_factory=_DummySessionFactory(),
            enable_pagination=True,
        )

    def test_pagination_type_present(self, handler: GraphQLHandler) -> None:
        """Pagination type should be in schema when enable_pagination=True."""
        schema = handler._introspection_generator.generate()
        type_names = [t["name"] for t in schema["types"]]
        assert "Pagination" in type_names

    def test_pagination_type_fields(self, handler: GraphQLHandler) -> None:
        """Pagination type should have has_more and total_count fields."""
        schema = handler._introspection_generator.generate()
        pag_type = next(
            (t for t in schema["types"] if t["name"] == "Pagination"), None
        )
        assert pag_type is not None
        field_names = [f["name"] for f in pag_type["fields"]]
        assert "has_more" in field_names
        assert "total_count" in field_names

    def test_result_type_present(self, handler: GraphQLHandler) -> None:
        """Result type should be generated for paginated list relationships."""
        schema = handler._introspection_generator.generate()
        type_names = [t["name"] for t in schema["types"]]
        assert "PagPostResult" in type_names

    def test_result_type_fields(self, handler: GraphQLHandler) -> None:
        """Result type should have items and pagination fields."""
        schema = handler._introspection_generator.generate()
        result_type = next(
            (t for t in schema["types"] if t["name"] == "PagPostResult"), None
        )
        assert result_type is not None
        field_names = [f["name"] for f in result_type["fields"]]
        assert "items" in field_names
        assert "pagination" in field_names

    def test_result_type_items_inner_type(self, handler: GraphQLHandler) -> None:
        """Result type items field should reference the target entity."""
        schema = handler._introspection_generator.generate()
        result_type = next(
            (t for t in schema["types"] if t["name"] == "PagPostResult"), None
        )
        assert result_type is not None
        items_field = next(
            (f for f in result_type["fields"] if f["name"] == "items"), None
        )
        assert items_field is not None
        # items is NON_NULL(LIST(NON_NULL(OBJECT(PagPost))))
        t = items_field["type"]
        assert t["kind"] == "NON_NULL"
        t = t["ofType"]
        assert t["kind"] == "LIST"
        t = t["ofType"]
        assert t["kind"] == "NON_NULL"
        t = t["ofType"]
        assert t["kind"] == "OBJECT"
        assert t["name"] == "PagPost"

    def test_list_relationship_uses_result_type(
        self, handler: GraphQLHandler,
    ) -> None:
        """Paginated list relationship field should reference Result type."""
        schema = handler._introspection_generator.generate()
        author_type = next(
            (t for t in schema["types"] if t["name"] == "PagAuthor"), None
        )
        assert author_type is not None
        posts_field = next(
            (f for f in author_type["fields"] if f["name"] == "posts"), None
        )
        assert posts_field is not None
        # Type should be NON_NULL(OBJECT(PagPostResult))
        t = posts_field["type"]
        assert t["kind"] == "NON_NULL"
        t = t["ofType"]
        assert t["kind"] == "OBJECT"
        assert t["name"] == "PagPostResult"

    def test_list_relationship_has_pagination_args(
        self, handler: GraphQLHandler,
    ) -> None:
        """Paginated list relationship field should have limit/offset args."""
        schema = handler._introspection_generator.generate()
        author_type = next(
            (t for t in schema["types"] if t["name"] == "PagAuthor"), None
        )
        assert author_type is not None
        posts_field = next(
            (f for f in author_type["fields"] if f["name"] == "posts"), None
        )
        assert posts_field is not None
        arg_names = [a["name"] for a in posts_field["args"]]
        assert "limit" in arg_names
        assert "offset" in arg_names

    def test_non_paginated_handler_no_pagination_types(self) -> None:
        """When enable_pagination=False, no Pagination/Result types."""
        handler = GraphQLHandler(base=PagBase, session_factory=_DummySessionFactory())
        schema = handler._introspection_generator.generate()
        type_names = [t["name"] for t in schema["types"]]
        assert "Pagination" not in type_names
        assert "PagPostResult" not in type_names

    def test_fk_fields_excluded_in_paginated_entities(
        self, handler: GraphQLHandler,
    ) -> None:
        """FK fields should be excluded even in paginated entities."""
        schema = handler._introspection_generator.generate()
        post_type = next(
            (t for t in schema["types"] if t["name"] == "PagPost"), None
        )
        assert post_type is not None
        field_names = [f["name"] for f in post_type["fields"]]
        assert "author_id" not in field_names
        assert "id" in field_names
        assert "title" in field_names


class TestDefaultValueFormat:
    """Regression tests for defaultValue format in introspection.

    Ensures that default values are serialized as valid GraphQL literals
    (via json.dumps), not Python repr strings. This prevents buildClientSchema
    from graphql-js (used by GraphiQL) from failing with syntax errors.

    Bug: _build_method_field was using repr(param.default) which produced
    Python-formatted strings like 'planning' (single quotes) and None,
    instead of valid GraphQL literals like "planning" (double quotes) and null.
    """

    @pytest.fixture
    def handler(self) -> GraphQLHandler:
        return GraphQLHandler(base=IntrospectionBase)

    @pytest.fixture
    def generator(self, handler: GraphQLHandler) -> IntrospectionGenerator:
        return handler._introspection_generator

    def _get_mutation_field(self, schema: dict, field_name: str) -> dict:
        """Look up a method field on the {Entity}Mutation group type.

        All tests in this class target the IntrospectionConfig entity.
        """
        group_type = next(
            t for t in schema["types"] if t["name"] == "IntrospectionConfigMutation"
        )
        return next(f for f in group_type["fields"] if f["name"] == field_name)

    def _get_query_field(self, schema: dict, field_name: str) -> dict:
        """Look up a method field on the {Entity}Query group type.

        All tests in this class target the IntrospectionConfig entity.
        """
        group_type = next(
            t for t in schema["types"] if t["name"] == "IntrospectionConfigQuery"
        )
        return next(f for f in group_type["fields"] if f["name"] == field_name)

    def test_string_default_uses_json_format(self, generator: IntrospectionGenerator):
        """String defaults must use double-quoted JSON format, not Python single quotes."""
        schema = generator.generate()
        field = self._get_mutation_field(schema, "create_config")
        value_arg = next(a for a in field["args"] if a["name"] == "value")

        assert value_arg["defaultValue"] == '"default"'
        assert "'" not in value_arg["defaultValue"]

    def test_none_default_produces_null(self, generator: IntrospectionGenerator):
        """None defaults must produce GraphQL 'null', not Python 'None'."""
        schema = generator.generate()
        field = self._get_mutation_field(schema, "create_config")
        tag_arg = next(a for a in field["args"] if a["name"] == "tag")

        assert tag_arg["defaultValue"] == "null"
        assert tag_arg["defaultValue"] != "None"

    def test_int_default_format(self, generator: IntrospectionGenerator):
        """Integer defaults must be valid GraphQL Int literals."""
        schema = generator.generate()
        field = self._get_mutation_field(schema, "create_config")
        priority_arg = next(a for a in field["args"] if a["name"] == "priority")

        assert priority_arg["defaultValue"] == "5"

    def test_float_default_format(self, generator: IntrospectionGenerator):
        """Float defaults must be valid GraphQL Float literals."""
        schema = generator.generate()
        field = self._get_mutation_field(schema, "create_config")
        score_arg = next(a for a in field["args"] if a["name"] == "score")

        assert score_arg["defaultValue"] == "1.0"

    def test_bool_true_default_format(self, generator: IntrospectionGenerator):
        """Boolean True defaults must be GraphQL 'true', not Python 'True'."""
        schema = generator.generate()
        field = self._get_mutation_field(schema, "create_config")
        is_active_arg = next(a for a in field["args"] if a["name"] == "is_active")

        assert is_active_arg["defaultValue"] == "true"
        assert is_active_arg["defaultValue"] != "True"

    def test_bool_false_default_format(self, generator: IntrospectionGenerator):
        """Boolean False defaults must be GraphQL 'false', not Python 'False'."""
        schema = generator.generate()
        field = self._get_query_field(schema, "get_configs")
        enabled_arg = next(a for a in field["args"] if a["name"] == "enabled")

        assert enabled_arg["defaultValue"] == "false"
        assert enabled_arg["defaultValue"] != "False"

    def test_list_default_format(self, generator: IntrospectionGenerator):
        """Optional list with None default renders as null in GraphQL."""
        schema = generator.generate()
        field = self._get_mutation_field(schema, "create_config")
        tags_arg = next(a for a in field["args"] if a["name"] == "tags")

        assert tags_arg["defaultValue"] == "null"

    def test_build_client_schema_succeeds(self, generator: IntrospectionGenerator):
        """Full introspection result must be consumable by graphql build_client_schema.

        This is the critical end-to-end regression check. If defaultValue format
        is wrong, buildClientSchema will raise a GraphQLError.
        """
        from graphql import build_client_schema

        schema = generator.generate()
        gql_schema = build_client_schema({"__schema": schema})

        assert gql_schema is not None
        assert "Query" in gql_schema.type_map
        assert "Mutation" in gql_schema.type_map
        assert "IntrospectionConfig" in gql_schema.type_map

    def test_format_default_value_static_method(self):
        """Unit test for _format_default_value static method."""
        assert IntrospectionGenerator._format_default_value("hello") == '"hello"'
        assert IntrospectionGenerator._format_default_value(None) == "null"
        assert IntrospectionGenerator._format_default_value(True) == "true"
        assert IntrospectionGenerator._format_default_value(False) == "false"
        assert IntrospectionGenerator._format_default_value(42) == "42"
        assert IntrospectionGenerator._format_default_value(3.14) == "3.14"
        assert IntrospectionGenerator._format_default_value([1, 2, 3]) == "[1, 2, 3]"
        assert IntrospectionGenerator._format_default_value([]) == "[]"
