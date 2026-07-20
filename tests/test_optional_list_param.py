"""Regression test: list[str] | None should produce [String!], not String.

Bug: _python_type_to_graphql() checks `origin is list` before checking Optional.
For `list[str] | None`, `get_origin()` returns UnionType, not list, so the list
check is skipped. Then Optional branch calls _python_type_to_graphql_inner() on
the unwrapped `list[str]`, which doesn't handle list types — falling back to String.

See: sdl_generator._python_type_to_graphql lines 20-48
"""

from sqlmodel import Field, SQLModel

from nexusx import mutation, query
from nexusx.sdl_generator import SDLGenerator, _python_type_to_graphql
from nexusx.type_converter import TypeConverter

# ── Entity with optional list parameters ───────────────────────────────


class ItemForListBug(SQLModel):
    """Test entity with optional list parameter."""

    id: int | None = Field(default=None, primary_key=True)
    name: str

    @mutation
    async def create_with_optional_tags(
        cls, name: str, tags: list[str] | None = None
    ) -> "ItemForListBug":
        """Create item with optional tag list."""
        return ItemForListBug(id=1, name=name)

    @mutation
    async def create_with_required_tags(
        cls, name: str, tags: list[str]
    ) -> "ItemForListBug":
        """Create item with required tag list."""
        return ItemForListBug(id=1, name=name)

    @mutation
    async def create_with_optional_typing(
        cls, name: str, tags: list[str] | None = None
    ) -> "ItemForListBug":
        """Create item using Optional[list[str]] syntax."""
        return ItemForListBug(id=1, name=name)

    @query
    async def search_optional_ints(
        cls, ids: list[int] | None = None
    ) -> list["ItemForListBug"]:
        """Query with optional list[int]."""
        return []

    @query
    async def search_nullable_entities(
        cls, ids: list[int | None] | None = None
    ) -> list["ItemForListBug | None"]:
        """Query with combined outer+inner optional list."""
        return []


def _extract_param_type(sdl: str, mutation_name: str, param_name: str) -> str | None:
    """Extract the GraphQL type of a specific parameter from SDL.

    Returns the type string (e.g. '[String!]!', [String!], String) or None.
    """
    target = f"{mutation_name}("
    for line in sdl.splitlines():
        line = line.strip()
        if target in line:
            # Find "paramName: <Type>" in the parameter list
            needle = f"{param_name}: "
            idx = line.find(needle)
            if idx == -1:
                continue
            start = idx + len(needle)
            rest = line[start:]
            # Type ends at ',' or ')'
            end = len(rest)
            for ch in (",", ")"):
                pos = rest.find(ch)
                if pos != -1 and pos < end:
                    end = pos
            return rest[:end]
    return None


# ── Tests ─────────────────────────────────────────────────────────────


class TestOptionalListParameterBug:
    """list[T] | None and list[T | None] should produce correct GraphQL types."""

    def setup_method(self) -> None:
        self.converter = TypeConverter(set())

    # --- Direct type conversion: outer Optional ---

    def test_list_str_none_produces_list_string(self):
        """list[str] | None should convert to [String!], not String."""
        result = _python_type_to_graphql(list[str] | None, self.converter)
        assert result == "[String!]", f"Expected '[String!]' but got '{result}'"

    def test_optional_list_str_produces_list_string(self):
        """Optional[list[str]] should convert to [String!], not String."""
        result = _python_type_to_graphql(list[str] | None, self.converter)
        assert result == "[String!]", f"Expected '[String!]' but got '{result}'"

    def test_list_int_none_produces_list_int(self):
        """list[int] | None should convert to [Int!], not String."""
        result = _python_type_to_graphql(list[int] | None, self.converter)
        assert result == "[Int!]", f"Expected '[Int!]' but got '{result}'"

    def test_required_list_still_works(self):
        """list[str] (without None) should still produce [String!]!."""
        result = _python_type_to_graphql(list[str], self.converter)
        assert result == "[String!]!"

    # --- Direct type conversion: inner Optional ---

    def test_list_of_optional_entity_produces_nullable_element_list(self):
        """list[Entity | None] should produce [Entity]!, not [String!]."""
        converter = TypeConverter({"ItemForListBug"})
        result = _python_type_to_graphql(
            list[ItemForListBug | None], converter, entity_names={"ItemForListBug"}
        )
        assert result == "[ItemForListBug]!", (
            f"Expected '[ItemForListBug]!' but got '{result}'"
        )

    def test_list_of_optional_scalar_produces_nullable_element_list(self):
        """list[str | None] should produce [String]!, not [String!]."""
        result = _python_type_to_graphql(list[str | None], self.converter)
        assert result == "[String]!", f"Expected '[String]!' but got '{result}'"

    def test_list_of_optional_int_produces_nullable_element_list(self):
        """list[int | None] should produce [Int]!, not [String!]."""
        result = _python_type_to_graphql(list[int | None], self.converter)
        assert result == "[Int]!", f"Expected '[Int]!' but got '{result}'"

    # --- Direct type conversion: combined outer+inner Optional ---

    def test_list_of_optional_str_outer_none(self):
        """list[str | None] | None should produce [String], not String."""
        result = _python_type_to_graphql(list[str | None] | None, self.converter)
        assert result == "[String]", f"Expected '[String]' but got '{result}'"

    def test_list_of_optional_entity_outer_none(self):
        """list[Entity | None] | None should produce [Entity], not String."""
        converter = TypeConverter({"ItemForListBug"})
        result = _python_type_to_graphql(
            list[ItemForListBug | None] | None, converter, entity_names={"ItemForListBug"}
        )
        assert result == "[ItemForListBug]", (
            f"Expected '[ItemForListBug]' but got '{result}'"
        )

    # --- Full SDL generation (precise extraction) ---

    def test_sdl_required_list_param(self):
        """Required list[str] param should produce [String!]!."""
        sdl = SDLGenerator([ItemForListBug]).generate()
        gql_type = _extract_param_type(sdl, "create_with_required_tags", "tags")
        assert gql_type == "[String!]!", f"Expected '[String!]!' but got '{gql_type}'"

    def test_sdl_optional_list_param(self):
        """list[str] | None param should produce [String!], not String."""
        sdl = SDLGenerator([ItemForListBug]).generate()
        gql_type = _extract_param_type(sdl, "create_with_optional_tags", "tags")
        assert gql_type == "[String!]", f"Expected '[String!]' but got '{gql_type}'"

    def test_sdl_optional_typing_list_param(self):
        """Optional[list[str]] (typing module) should also produce [String!]."""
        sdl = SDLGenerator([ItemForListBug]).generate()
        gql_type = _extract_param_type(sdl, "create_with_optional_typing", "tags")
        assert gql_type == "[String!]", f"Expected '[String!]' but got '{gql_type}'"

    def test_sdl_optional_list_int_param(self):
        """list[int] | None param should produce [Int!], not String."""
        sdl = SDLGenerator([ItemForListBug]).generate()
        gql_type = _extract_param_type(sdl, "search_optional_ints", "ids")
        assert gql_type == "[Int!]", f"Expected '[Int!]' but got '{gql_type}'"

    def test_sdl_combined_optional_list_param(self):
        """list[int | None] | None param should produce [Int], not String."""
        sdl = SDLGenerator([ItemForListBug]).generate()
        gql_type = _extract_param_type(sdl, "search_nullable_entities", "ids")
        assert gql_type == "[Int]", f"Expected '[Int]' but got '{gql_type}'"
