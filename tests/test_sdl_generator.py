"""Tests for SDL generator."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel
from sqlmodel import Field, SQLModel

from nexusx import mutation, query
from nexusx.sdl_generator import SDLGenerator, _python_type_to_graphql
from nexusx.type_converter import TypeConverter
from nexusx.utils.schema_helpers import get_core_types, is_input_type


# Define entities at module level to avoid metadata conflicts
class UserForTest(SQLModel):
    """Test User entity without table mapping."""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str

    @query
    async def get_all(
        cls, limit: int = 10
    ) -> list["UserForTest"]:
        """Get all users with optional query optimization."""
        return [
            UserForTest(id=1, name="Alice", email="alice@example.com"),
            UserForTest(id=2, name="Bob", email="bob@example.com"),
        ][:limit]

    @query
    async def get_by_id(
        cls, id: int
    ) -> Optional["UserForTest"]:
        """Get user by ID."""
        users = {
            1: UserForTest(id=1, name="Alice", email="alice@example.com"),
            2: UserForTest(id=2, name="Bob", email="bob@example.com"),
        }
        return users.get(id)

    @mutation
    async def create(
        cls, name: str, email: str
    ) -> "UserForTest":
        """Create a new user."""
        return UserForTest(id=3, name=name, email=email)


class PostForTest(SQLModel):
    """Test Post entity without table mapping."""

    id: int | None = Field(default=None, primary_key=True)
    title: str
    content: str = ""
    author_id: int


class TestSDLGenerator:
    """Test cases for SDLGenerator."""

    def test_generate_types(self) -> None:
        """Test that GraphQL types are generated correctly."""
        generator = SDLGenerator([UserForTest, PostForTest])
        sdl = generator.generate()

        assert "type UserForTest" in sdl
        assert "type PostForTest" in sdl
        assert "id: Int" in sdl
        assert "name: String!" in sdl
        assert "email: String!" in sdl

    def test_generate_query_type(self) -> None:
        """Test that Query type is generated correctly."""
        generator = SDLGenerator([UserForTest])
        sdl = generator.generate()

        assert "type Query" in sdl
        # New naming: userForTestGetAll, userForTestGetById
        assert "userForTestGetAll(limit: Int): [UserForTest!]!" in sdl
        assert "userForTestGetById(id: Int!): UserForTest" in sdl

    def test_generate_mutation_type(self) -> None:
        """Test that Mutation type is generated correctly."""
        generator = SDLGenerator([UserForTest])
        sdl = generator.generate()

        assert "type Mutation" in sdl
        # New naming: userForTestCreate
        assert "userForTestCreate(name: String!, email: String!): UserForTest!" in sdl

    def test_snake_case_preserved(self) -> None:
        """Test that snake_case field names are preserved (no conversion to camelCase)."""
        generator = SDLGenerator([PostForTest])
        sdl = generator.generate()

        # author_id should remain as snake_case
        assert "author_id: Int!" in sdl

    def test_query_meta_not_in_sdl(self) -> None:
        """Test that query_meta parameter is not included in SDL."""
        generator = SDLGenerator([UserForTest])
        sdl = generator.generate()

        # query_meta should not appear in the generated SDL
        assert "query_meta" not in sdl
        assert "QueryMeta" not in sdl

        # But other parameters should be there
        assert "limit: Int" in sdl
        assert "id: Int!" in sdl
        assert "name: String!" in sdl
        assert "email: String!" in sdl


# Additional test entities for helper function tests
class StatusEnum(Enum):
    """Test enum for SDL tests."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class EntityForHelperTest(SQLModel):
    """Test entity for helper tests."""

    id: int | None
    name: str


class InputModelForTest(BaseModel):
    """Test input model."""

    field1: str
    field2: int


class InputSQLModelForTest(SQLModel):
    """Test input SQLModel (not an entity)."""

    input_field: str


class TestGetCoreTypes:
    """Test cases for get_core_types() helper function."""

    def test_get_core_types_simple_type(self) -> None:
        """Test extracting core type from simple type."""
        result = get_core_types(int)
        assert result == [int]

    def test_get_core_types_optional(self) -> None:
        """Test extracting core types from Optional[T]."""
        result = get_core_types(int | None)
        assert result == [int]

    def test_get_core_types_union(self) -> None:
        """Test extracting core types from Union[T, U]."""
        result = get_core_types(int | str)
        assert set(result) == {int, str}

    def test_get_core_types_list(self) -> None:
        """Test extracting core types from list[T]."""
        result = get_core_types(list[int])
        assert result == [int]

    def test_get_core_types_list_of_optional(self) -> None:
        """Test extracting core types from list[Optional[T]]."""
        result = get_core_types(list[int | None])
        assert result == [int]

    def test_get_core_types_nested(self) -> None:
        """Test extracting core types from nested types."""
        result = get_core_types(list[int | str | None])
        assert set(result) == {int, str}

    def test_get_core_types_none_in_union(self) -> None:
        """Test that None is excluded from Union."""
        result = get_core_types(int | None)
        assert result == [int]
        assert type(None) not in result

    def test_get_core_types_empty_list(self) -> None:
        """Test extracting core type from untyped list.

        Note: Untyped list returns the list class itself.
        """
        result = get_core_types(list)
        # Untyped list returns the list class itself
        assert result == [list]

    def test_get_core_types_non_type(self) -> None:
        """Test extracting core type from non-type returns empty."""
        result = get_core_types("string_annotation")
        assert result == []


class TestIsInputType:
    """Test cases for is_input_type() helper function."""

    def test_is_input_type_sqlmodel(self) -> None:
        """Test that SQLModel subclasses are input types."""
        assert is_input_type(EntityForHelperTest) is True
        assert is_input_type(InputSQLModelForTest) is True

    def test_is_input_type_basemodel(self) -> None:
        """Test that BaseModel subclasses are input types."""
        assert is_input_type(InputModelForTest) is True

    def test_is_input_type_scalar(self) -> None:
        """Test that scalar types are not input types."""
        assert is_input_type(int) is False
        assert is_input_type(str) is False
        assert is_input_type(bool) is False

    def test_is_input_type_enum(self) -> None:
        """Test that enum types are not input types."""
        assert is_input_type(StatusEnum) is False

    def test_is_input_type_non_class(self) -> None:
        """Test that non-class values are not input types."""
        assert is_input_type("string") is False
        assert is_input_type(123) is False


class TestPythonTypeToGraphql:
    """Test cases for _python_type_to_graphql() helper function."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.converter = TypeConverter({"EntityForHelperTest"})

    def test_int_type(self) -> None:
        """Test converting int type."""
        result = _python_type_to_graphql(int, self.converter)
        assert result == "Int!"

    def test_str_type(self) -> None:
        """Test converting str type."""
        result = _python_type_to_graphql(str, self.converter)
        assert result == "String!"

    def test_bool_type(self) -> None:
        """Test converting bool type."""
        result = _python_type_to_graphql(bool, self.converter)
        assert result == "Boolean!"

    def test_float_type(self) -> None:
        """Test converting float type."""
        result = _python_type_to_graphql(float, self.converter)
        assert result == "Float!"

    def test_optional_int(self) -> None:
        """Test converting Optional[int] type."""
        result = _python_type_to_graphql(int | None, self.converter)
        assert result == "Int"

    def test_optional_str(self) -> None:
        """Test converting Optional[str] type."""
        result = _python_type_to_graphql(str | None, self.converter)
        assert result == "String"

    def test_list_int(self) -> None:
        """Test converting list[int] type."""
        result = _python_type_to_graphql(list[int], self.converter)
        assert result == "[Int!]!"

    def test_list_optional_int(self) -> None:
        """Test converting list[Optional[int]] type.

        Optional inside list is detected, element is nullable (no !).
        """
        result = _python_type_to_graphql(list[int | None], self.converter)
        assert result == "[Int]!"

    def test_list_str(self) -> None:
        """Test converting list[str] type."""
        result = _python_type_to_graphql(list[str], self.converter)
        assert result == "[String!]!"

    def test_entity_type(self) -> None:
        """Test converting entity type."""
        result = _python_type_to_graphql(EntityForHelperTest, self.converter)
        assert result == "EntityForHelperTest!"

    def test_optional_entity(self) -> None:
        """Test converting Optional[Entity] type."""
        result = _python_type_to_graphql(EntityForHelperTest | None, self.converter)
        assert result == "EntityForHelperTest"

    def test_list_entity(self) -> None:
        """Test converting list[Entity] type."""
        result = _python_type_to_graphql(list[EntityForHelperTest], self.converter)
        assert result == "[EntityForHelperTest!]!"

    def test_enum_type(self) -> None:
        """Test converting enum type.

        Note: Enum types are not marked as required by default.
        """
        result = _python_type_to_graphql(StatusEnum, self.converter)
        assert result == "StatusEnum"


class TestSDLGeneratorEnums:
    """Test cases for SDLGenerator enum handling."""

    def test_enum_in_sdl(self) -> None:
        """Test that enums are included in SDL."""

        class EnumEntity(SQLModel):
            id: int | None
            status: StatusEnum

        generator = SDLGenerator([EnumEntity])
        sdl = generator.generate()

        assert "enum StatusEnum" in sdl
        # Enum values use .value (lowercase), not the enum member names
        assert "active" in sdl
        assert "inactive" in sdl

    def test_enum_type_field(self) -> None:
        """Test that enum fields have correct type."""

        class EnumEntity(SQLModel):
            id: int | None
            status: StatusEnum

        generator = SDLGenerator([EnumEntity])
        sdl = generator.generate()

        # status is not a required field, so no ! at the end
        assert "status: StatusEnum" in sdl


class TestSDLGeneratorInputTypes:
    """Test cases for SDLGenerator input type handling."""

    def test_input_type_collection(self) -> None:
        """Test that input types are collected from method parameters."""

        class InputModel(BaseModel):
            name: str
            value: int

        class EntityWithInput(SQLModel):
            id: int | None

            @mutation
            def create_with_input(
                cls, input_data: InputModel
            ) -> "EntityWithInput":
                """Create entity with input."""
                return EntityWithInput(id=1)

        generator = SDLGenerator([EntityWithInput])
        sdl = generator.generate()

        assert "input InputModel" in sdl
        assert "name: String!" in sdl
        assert "value: Int!" in sdl

    def test_nested_input_types(self) -> None:
        """Test that nested input types are collected."""

        class InnerInput(BaseModel):
            field: str

        class OuterInput(BaseModel):
            inner: InnerInput

        class EntityWithNestedInput(SQLModel):
            id: int | None

            @mutation
            def create_nested(
                cls, data: OuterInput
            ) -> "EntityWithNestedInput":
                """Create entity with nested input."""
                return EntityWithNestedInput(id=1)

        generator = SDLGenerator([EntityWithNestedInput])
        sdl = generator.generate()

        assert "input InnerInput" in sdl
        assert "input OuterInput" in sdl


class TestSDLGeneratorOperationSDL:
    """Test cases for SDLGenerator.generate_operation_sdl()."""

    def test_generate_operation_sdl_query(self) -> None:
        """Test generating SDL for a single query."""
        generator = SDLGenerator([UserForTest])
        sdl = generator.generate_operation_sdl("userForTestGetAll", "Query")

        assert sdl is not None
        assert "userForTestGetAll" in sdl
        assert "limit: Int" in sdl
        assert "UserForTest" in sdl

    def test_generate_operation_sdl_mutation(self) -> None:
        """Test generating SDL for a single mutation."""
        generator = SDLGenerator([UserForTest])
        sdl = generator.generate_operation_sdl("userForTestCreate", "Mutation")

        assert sdl is not None
        assert "userForTestCreate" in sdl
        assert "name: String!" in sdl

    def test_generate_operation_sdl_not_found(self) -> None:
        """Test generating SDL for non-existent operation."""
        generator = SDLGenerator([UserForTest])
        sdl = generator.generate_operation_sdl("nonExistent", "Query")

        assert sdl is None

    def test_generate_operation_sdl_includes_related_types(self) -> None:
        """Test that operation SDL includes related entity types."""

        class AuthorForTest(SQLModel):
            id: int | None
            name: str

        class ArticleForTest(SQLModel):
            id: int | None
            title: str
            author: AuthorForTest

            @query
            def get_all(
                cls
            ) -> list["ArticleForTest"]:
                """Get all articles."""
                return []

        generator = SDLGenerator([AuthorForTest, ArticleForTest])
        sdl = generator.generate_operation_sdl("articleForTestGetAll", "Query")

        assert sdl is not None
        assert "ArticleForTest" in sdl
        assert "AuthorForTest" in sdl


# ──────────────────────────────────────────────────────────
# Additional coverage tests
# ──────────────────────────────────────────────────────────


class TestSDLGeneratorExtras:
    def test_empty_list_type_converts_to_string(self):
        """list without type args falls through to String! (non-list branch)."""
        converter = TypeConverter({"EntityForHelperTest"})
        result = _python_type_to_graphql(list, converter)
        # list (bare) has no origin match for list, so it falls through
        assert result == "String!"

    def test_pagination_types_generated(self):
        """enable_pagination=True should produce Pagination and Result types."""
        from nexusx.loader.registry import ErManager
        from tests.conftest import FixtureSprint, FixtureTask, FixtureUser

        registry = ErManager(
            entities=[FixtureSprint, FixtureTask, FixtureUser],
            session_factory=lambda: None,
            enable_pagination=True,
        )
        generator = SDLGenerator([FixtureSprint, FixtureTask, FixtureUser])
        sdl = generator.generate(enable_pagination=True, loader_registry=registry)

        assert "type Pagination" in sdl
        assert "has_more: Boolean!" in sdl
        assert "total_count: Int" in sdl
        assert "FixtureTaskResult" in sdl

    def test_no_pagination_types_when_disabled(self):
        """Without enable_pagination, no Pagination type should appear."""
        generator = SDLGenerator([UserForTest])
        sdl = generator.generate()
        assert "type Pagination" not in sdl

    def test_generate_input_type_skips_underscore_fields(self):
        """Fields starting with _ should be excluded from input types."""

        class UnderscoreEntity(SQLModel):
            _private: str = ""
            id: int | None
            name: str

        generator = SDLGenerator([UnderscoreEntity])
        # _generate_input_type is called internally
        sdl = generator.generate()
        # The entity type should not include _private
        assert "_private" not in sdl

    def test_generate_with_no_query_methods(self):
        """Entity without @query/@mutation should produce only type definition."""

        class SimpleEntity(SQLModel):
            id: int | None
            value: str

        generator = SDLGenerator([SimpleEntity])
        sdl = generator.generate()
        assert "type SimpleEntity" in sdl
        assert "type Query" not in sdl

    def test_method_default_params_are_optional(self):
        """Method params with defaults should be optional (no !) in SDL."""

        class DefaultParamEntity(SQLModel):
            id: int | None

            @query
            async def search(cls, limit: int = 10, offset: int = 0) -> list["DefaultParamEntity"]:
                return []

        generator = SDLGenerator([DefaultParamEntity])
        sdl = generator.generate()
        # Optional params should not have !
        assert "limit: Int" in sdl
        assert "offset: Int" in sdl
        # Should not have limit: Int!
        assert "limit: Int!" not in sdl

    def test_generate_operation_sdl_with_missing_return_type(self):
        """Method with unresolvable return type should still generate SDL."""

        class NoReturnEntity(SQLModel):
            id: int | None

            @query
            def get_all(cls):
                return []

        generator = SDLGenerator([NoReturnEntity])
        sdl = generator.generate_operation_sdl("noReturnEntityGetAll", "Query")
        assert sdl is not None
        assert "noReturnEntityGetAll" in sdl

    def test_collect_related_entities_unreachable(self):
        """Type hint referencing non-entity should not crash."""

        class IsolatedEntity(SQLModel):
            id: int | None
            name: str

        generator = SDLGenerator([IsolatedEntity])
        # generate_operation_sdl internally calls _collect_related_entities
        sdl = generator.generate_operation_sdl("nonExistent", "Query")
        assert sdl is None
