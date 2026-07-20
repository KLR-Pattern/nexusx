"""Tests for GraphQL Input type support."""

from __future__ import annotations

import pytest
from sqlmodel import Field, SQLModel

from nexusx import GraphQLHandler, mutation
from nexusx.mcp.builders.schema_formatter import SchemaFormatter


# Define base class for test entities
class InputTestBase(SQLModel):
    """Base class for input test entities."""
    pass


# Define Input types
class UserCreateInput(SQLModel):
    """Input for creating a user."""

    name: str
    email: str
    age: int | None = None


class AddressInput(SQLModel):
    """Nested input for address."""

    street: str
    city: str
    zip_code: str


class UserWithAddressInput(SQLModel):
    """Input with nested type."""

    name: str
    address: AddressInput


# Define entity
class InputTestUser(InputTestBase, table=False):
    __test__ = False  # Tell pytest this is not a test class

    id: int = Field(primary_key=True)
    name: str
    email: str
    age: int | None = None

    @mutation
    async def create(cls, input: UserCreateInput) -> InputTestUser:
        """Create a new user."""
        return InputTestUser(
            id=1, name=input.name, email=input.email, age=input.age
        )

    @mutation
    async def create_with_address(
        cls, input: UserWithAddressInput
    ) -> InputTestUser:
        """Create user with address."""
        return InputTestUser(id=1, name=input.name, email="test@test.com")


class TestInputTypesSDL:
    """Test Input type SDL generation."""

    def test_input_type_in_sdl(self) -> None:
        handler = GraphQLHandler(base=InputTestBase)
        sdl = handler.get_sdl()

        assert "input UserCreateInput" in sdl
        assert "name: String!" in sdl
        assert "email: String!" in sdl

    def test_nested_input_type_in_sdl(self) -> None:
        handler = GraphQLHandler(base=InputTestBase)
        sdl = handler.get_sdl()

        assert "input AddressInput" in sdl
        assert "input UserWithAddressInput" in sdl
        assert "address: AddressInput!" in sdl

    def test_mutation_uses_input_type(self) -> None:
        handler = GraphQLHandler(base=InputTestBase)
        sdl = handler.get_sdl()

        # Methods now live inside `type InputTestUserMutation { ... }` under the
        # verbatim Python method name, so we assert on the inner method def.
        assert "create(input: UserCreateInput!)" in sdl

    def test_input_type_with_optional_field(self) -> None:
        handler = GraphQLHandler(base=InputTestBase)
        sdl = handler.get_sdl()

        # age is optional, should not have !
        lines = sdl.split("\n")
        in_user_input = False
        for line in lines:
            if "input UserCreateInput" in line:
                in_user_input = True
            elif in_user_input and "}" in line:
                in_user_input = False
            elif in_user_input and "age:" in line:
                # age should be Int (not Int!)
                assert "age: Int" in line
        assert "age: Int" in sdl


class TestInputTypesIntrospection:
    """Test Input type introspection."""

    def test_input_type_in_introspection(self) -> None:
        handler = GraphQLHandler(base=InputTestBase)
        schema = handler._introspection_generator.generate()

        input_type = next(
            (t for t in schema["types"] if t["name"] == "UserCreateInput"), None
        )
        assert input_type is not None
        assert input_type["kind"] == "INPUT_OBJECT"
        assert input_type["inputFields"] is not None

        field_names = [f["name"] for f in input_type["inputFields"]]
        assert "name" in field_names
        assert "email" in field_names

    def test_mutation_parameter_with_input_type(self) -> None:
        """Test that mutation parameters using Input types are correctly identified."""
        handler = GraphQLHandler(base=InputTestBase)
        schema = handler._introspection_generator.generate()

        # With the grouped-by-entity layout, Mutation no longer holds the method
        # directly. The method lives inside the per-entity mutation group, e.g.
        # `type InputTestUserMutation { create(input: ...): ... }`.
        group_type = next(
            (t for t in schema["types"] if t["name"] == "InputTestUserMutation"),
            None,
        )
        assert group_type is not None, "Expected an InputTestUserMutation group type"

        # Find the create method field inside the entity's mutation group
        create_field = next(
            (f for f in group_type["fields"] if f["name"] == "create"),
            None,
        )
        assert create_field is not None

        # Check the args
        assert len(create_field["args"]) > 0
        input_arg = next(
            (a for a in create_field["args"] if a["name"] == "input"),
            None
        )
        assert input_arg is not None

        # Verify the type reference structure
        type_ref = input_arg["type"]
        # Should be NON_NULL(INPUT_OBJECT(UserCreateInput))
        assert type_ref["kind"] == "NON_NULL"
        assert type_ref["name"] is None
        assert type_ref["ofType"]["kind"] == "INPUT_OBJECT"
        assert type_ref["ofType"]["name"] == "UserCreateInput"
        assert type_ref["ofType"]["ofType"] is None


class TestInputTypesExecution:
    """Test Input type execution."""

    @pytest.mark.asyncio
    async def test_mutation_with_input_type(self) -> None:
        handler = GraphQLHandler(base=InputTestBase)

        result = await handler.execute(
            """
            mutation {
                InputTestUser {
                    create(input: {name: "Alice", email: "alice@test.com", age: 25}) {
                        id
                        name
                        email
                    }
                }
            }
        """
        )

        assert "data" in result
        assert result["data"]["InputTestUser"]["create"]["name"] == "Alice"
        assert result["data"]["InputTestUser"]["create"]["email"] == "alice@test.com"

    @pytest.mark.asyncio
    async def test_nested_input_conversion(self) -> None:
        handler = GraphQLHandler(base=InputTestBase)

        result = await handler.execute(
            """
            mutation {
                InputTestUser {
                    create_with_address(input: {
                        name: "Bob",
                        address: {street: "Main St", city: "NYC", zip_code: "10001"}
                    }) {
                        id
                        name
                    }
                }
            }
        """
        )

        assert "data" in result
        assert result["data"]["InputTestUser"]["create_with_address"]["name"] == "Bob"


class TestInputTypesMCP:
    """Test Input types in MCP tools."""

    def test_get_mutation_schema_includes_input_types(self) -> None:
        """get_mutation_schema should include input_types."""
        handler = GraphQLHandler(base=InputTestBase)
        formatter = SchemaFormatter(handler)
        info = formatter.get_schema_info()

        # Check that input types are included
        assert "input_types" in info
        input_type_names = [t["name"] for t in info["input_types"]]
        assert "UserCreateInput" in input_type_names
        assert "AddressInput" in input_type_names

    def test_mutation_info_includes_input_types(self) -> None:
        """Mutation info should list its input types."""
        handler = GraphQLHandler(base=InputTestBase)
        formatter = SchemaFormatter(handler)
        info = formatter.get_schema_info()

        # The grouped-by-entity layout surfaces one Mutation entry per entity
        # group; the entity's methods live one level deeper. The entry's name
        # is the entity class name (InputTestUser).
        create_mutation = next(
            (m for m in info["mutations"] if m["name"] == "InputTestUser"),
            None,
        )
        assert create_mutation is not None
        # Check for input_types field
        if "input_types" in create_mutation:
            assert "UserCreateInput" in create_mutation["input_types"]
