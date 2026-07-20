"""Tests for enhanced MCP schema information."""

from __future__ import annotations

from sqlmodel import Field, SQLModel

from nexusx import GraphQLHandler, mutation, query
from nexusx.mcp.builders.schema_formatter import SchemaFormatter
from nexusx.mcp.builders.type_tracer import TypeTracer


class SchemaTestBase(SQLModel):
    """Dedicated base class for schema tests to avoid cross-test contamination."""

    __test__ = False


class TestEntity(SchemaTestBase):
    """Test entity with descriptions."""

    __test__ = False  # Tell pytest this is not a test class

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(description="User's full name")
    email: str = Field(description="Unique email address")

    @query
    async def get_all(cls, limit: int = 10) -> list[TestEntity]:
        """Get all items."""
        return []

    @query
    async def get_by_id(cls, id: int) -> TestEntity | None:
        """Get item by its unique identifier."""
        return None

    @mutation
    async def create(cls, name: str, count: int = 1) -> TestEntity:
        """Create a new item."""
        return TestEntity(name=name)


class TestFieldDescriptions:
    """Test field description extraction."""

    def test_field_description_extracted(self) -> None:
        """Field(description="...") should be extracted."""
        handler = GraphQLHandler(base=SchemaTestBase)
        handler.entities = [TestEntity]
        formatter = SchemaFormatter(handler)
        schema = formatter.get_schema_info()

        test_type = next(
            (t for t in schema["types"] if t["name"] == "TestEntity"), None
        )
        assert test_type is not None

        name_field = next(
            (f for f in test_type["scalar_fields"] if f["name"] == "name"), None
        )
        assert name_field is not None
        assert name_field["description"] == "User's full name"

    def test_field_without_description_is_none(self) -> None:
        """Fields without description should have None."""
        handler = GraphQLHandler(base=SchemaTestBase)
        handler.entities = [TestEntity]
        formatter = SchemaFormatter(handler)
        schema = formatter.get_schema_info()

        test_type = next(
            (t for t in schema["types"] if t["name"] == "TestEntity"), None
        )
        assert test_type is not None

        id_field = next(
            (f for f in test_type["scalar_fields"] if f["name"] == "id"), None
        )
        assert id_field is not None
        assert id_field["description"] is None


class TestMethodDocstrings:
    """Test method docstring extraction."""

    def test_docstring_used_as_description(self) -> None:
        """Docstring should be used as description."""
        handler = GraphQLHandler(base=SchemaTestBase)
        handler.entities = [TestEntity]
        introspection = handler._introspection_generator.generate()
        tracer = TypeTracer(introspection, {TestEntity.__name__})

        # Under the grouped layout the method lives on the {Entity}Query type.
        operation = tracer.get_group_operation("Query", "TestEntity", "get_all")
        assert operation is not None
        assert operation["description"] == "Get all items."

    def test_docstring_used_for_get_by_id(self) -> None:
        """Docstring should be used for get_by_id."""
        handler = GraphQLHandler(base=SchemaTestBase)
        handler.entities = [TestEntity]
        introspection = handler._introspection_generator.generate()
        tracer = TypeTracer(introspection, {TestEntity.__name__})

        operation = tracer.get_group_operation("Query", "TestEntity", "get_by_id")
        assert operation is not None
        assert operation["description"] == "Get item by its unique identifier."


class TestArgumentDefaults:
    """Test argument default value extraction."""

    def test_default_value_extracted(self) -> None:
        """Argument default value should be extracted."""
        handler = GraphQLHandler(base=SchemaTestBase)
        handler.entities = [TestEntity]
        introspection = handler._introspection_generator.generate()
        tracer = TypeTracer(introspection, {TestEntity.__name__})

        operation = tracer.get_group_operation("Query", "TestEntity", "get_all")
        assert operation is not None

        limit_arg = next(
            (a for a in operation["args"] if a["name"] == "limit"), None
        )
        assert limit_arg is not None
        assert limit_arg["defaultValue"] == "10"

    def test_required_argument_no_default(self) -> None:
        """Required arguments should have no default value."""
        handler = GraphQLHandler(base=SchemaTestBase)
        handler.entities = [TestEntity]
        introspection = handler._introspection_generator.generate()
        tracer = TypeTracer(introspection, {TestEntity.__name__})

        operation = tracer.get_group_operation("Query", "TestEntity", "get_by_id")
        assert operation is not None

        id_arg = next(
            (a for a in operation["args"] if a["name"] == "id"), None
        )
        assert id_arg is not None
        # Required args are wrapped in NON_NULL at the outermost kind.
        assert id_arg["type"]["kind"] == "NON_NULL"
        assert id_arg["defaultValue"] is None
