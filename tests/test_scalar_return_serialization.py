"""Tests for scalar return-value serialization.

When a ``@query``/``@mutation`` method returns a Python scalar (``bool``,
``int``, ``str``, ``uuid.UUID``) or a list of scalars (``list[UUID]``,
``list[str]``), the GraphQL response must contain the scalar value directly
under the field name. The SDL is correct (``Boolean!``, ``[UUID!]!``, etc.),
but ``QueryExecutor._serialize_item`` historically fell back to
``{"_value": str(item)}`` whenever an item lacked ``model_dump`` and the
selection had no sub-fields, producing responses like::

    {"data": {"deleteXxx": {"_value": "True"}}}    # expected: true
    {"data": {"setXxx": [{"_value": "uuid1"}, ...]}}  # expected: ["uuid1", ...]

These tests pin the contract that scalar and scalar-list returns serialize
as JSON-native scalars (booleans, ints, strings) without wrapping.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlmodel import Field, SQLModel

from nexusx import GraphQLHandler, mutation


class ScalarReturnBase(SQLModel):
    """Base class for scalar-return test entities."""

    pass


# Sentinel capturing the runtime method results so we can assert the wire
# format independent of what the method returned.
_LAST_RESULT: dict[str, object] = {}


class ScalarReturnDemo(ScalarReturnBase, table=False):
    """Entity that exposes mutations returning each scalar type."""

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    @mutation
    async def return_bool(cls) -> bool:
        """Return a single boolean (typical delete/ack shape)."""
        _LAST_RESULT["bool"] = True
        return True

    @mutation
    async def return_int(cls) -> int:
        """Return a single int (typical count shape)."""
        _LAST_RESULT["int"] = 42
        return 42

    @mutation
    async def return_str(cls) -> str:
        """Return a single str."""
        _LAST_RESULT["str"] = "hello"
        return "hello"

    @mutation
    async def return_uuid(cls) -> UUID:
        """Return a single UUID."""
        value = uuid4()
        _LAST_RESULT["uuid"] = value
        return value

    @mutation
    async def return_uuid_list(cls) -> list[UUID]:
        """Return list[UUID] (typical reorder/set shape)."""
        ids = [uuid4(), uuid4()]
        _LAST_RESULT["uuid_list"] = ids
        return ids

    @mutation
    async def return_str_list(cls) -> list[str]:
        """Return list[str]."""
        items = ["a", "b", "c"]
        _LAST_RESULT["str_list"] = items
        return items


@pytest.fixture
def scalar_handler() -> GraphQLHandler:
    _LAST_RESULT.clear()
    return GraphQLHandler(base=ScalarReturnBase)


# ──────────────────────────────────────────────────────────
# 1. Single scalar returns
# ──────────────────────────────────────────────────────────


class TestSingleScalarReturn:
    """Scalar returns must surface as JSON-native scalars, not ``{"_value": ...}``."""

    @pytest.mark.asyncio
    async def test_bool_returned_as_native(
        self, scalar_handler: GraphQLHandler
    ) -> None:
        """``return_bool() -> bool`` must come back as JSON ``true``."""
        result = await scalar_handler.execute(
            "mutation { ScalarReturnDemo { return_bool } }"
        )

        assert "errors" not in result, f"errors: {result.get('errors')}"
        value = result["data"]["ScalarReturnDemo"]["return_bool"]
        # The wire value is a Python bool, which JSON-encodes to ``true``.
        # ``{"_value": "True"}`` would be a dict and a string — both wrong.
        assert value is True, (
            f"Expected bool True, got {value!r} ({type(value).__name__})"
        )

    @pytest.mark.asyncio
    async def test_int_returned_as_native(
        self, scalar_handler: GraphQLHandler
    ) -> None:
        """``return_int() -> int`` must come back as JSON int."""
        result = await scalar_handler.execute(
            "mutation { ScalarReturnDemo { return_int } }"
        )

        assert "errors" not in result, f"errors: {result.get('errors')}"
        value = result["data"]["ScalarReturnDemo"]["return_int"]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"Expected int, got {value!r} ({type(value).__name__})"
        )
        assert value == 42

    @pytest.mark.asyncio
    async def test_str_returned_as_native(
        self, scalar_handler: GraphQLHandler
    ) -> None:
        """``return_str() -> str`` must come back as JSON string."""
        result = await scalar_handler.execute(
            "mutation { ScalarReturnDemo { return_str } }"
        )

        assert "errors" not in result, f"errors: {result.get('errors')}"
        value = result["data"]["ScalarReturnDemo"]["return_str"]
        assert value == "hello", (
            f"Expected 'hello', got {value!r} ({type(value).__name__})"
        )

    @pytest.mark.asyncio
    async def test_uuid_returned_as_native(
        self, scalar_handler: GraphQLHandler
    ) -> None:
        """``return_uuid() -> UUID`` must come back as JSON string of the UUID."""
        result = await scalar_handler.execute(
            "mutation { ScalarReturnDemo { return_uuid } }"
        )

        assert "errors" not in result, f"errors: {result.get('errors')}"
        value = result["data"]["ScalarReturnDemo"]["return_uuid"]
        assert isinstance(value, str), (
            f"Expected str (JSON-serialized UUID), got {type(value).__name__}"
        )
        assert value == str(_LAST_RESULT["uuid"])


# ──────────────────────────────────────────────────────────
# 2. List-of-scalar returns
# ──────────────────────────────────────────────────────────


class TestScalarListReturn:
    """List-of-scalar returns must serialize as a flat list, not list of dicts."""

    @pytest.mark.asyncio
    async def test_uuid_list_returned_flat(
        self, scalar_handler: GraphQLHandler
    ) -> None:
        """``return_uuid_list() -> list[UUID]`` → ``["uuid1", "uuid2"]``."""
        result = await scalar_handler.execute(
            "mutation { ScalarReturnDemo { return_uuid_list } }"
        )

        assert "errors" not in result, f"errors: {result.get('errors')}"
        value = result["data"]["ScalarReturnDemo"]["return_uuid_list"]
        assert isinstance(value, list), f"Expected list, got {type(value).__name__}"
        assert len(value) == 2
        # Every element must be a string, not an ``{"_value": ...}`` dict.
        assert all(isinstance(x, str) for x in value), (
            f"Expected all str, got {[type(x).__name__ for x in value]}"
        )
        expected = [str(u) for u in _LAST_RESULT["uuid_list"]]
        assert value == expected

    @pytest.mark.asyncio
    async def test_str_list_returned_flat(
        self, scalar_handler: GraphQLHandler
    ) -> None:
        """``return_str_list() -> list[str]`` → ``["a", "b", "c"]``."""
        result = await scalar_handler.execute(
            "mutation { ScalarReturnDemo { return_str_list } }"
        )

        assert "errors" not in result, f"errors: {result.get('errors')}"
        value = result["data"]["ScalarReturnDemo"]["return_str_list"]
        assert value == ["a", "b", "c"], (
            f"Expected ['a','b','c'], got {value!r}"
        )


# ──────────────────────────────────────────────────────────
# 3. SDL — scalar return types render correctly
# ──────────────────────────────────────────────────────────


class TestScalarReturnSDL:
    """Pin SDL rendering of scalar return types (already works, floor test)."""

    def test_bool_return_sdl(self, scalar_handler: GraphQLHandler) -> None:
        sdl = scalar_handler.get_sdl()
        assert "return_bool: Boolean!" in sdl

    def test_int_return_sdl(self, scalar_handler: GraphQLHandler) -> None:
        sdl = scalar_handler.get_sdl()
        assert "return_int: Int!" in sdl

    def test_uuid_list_return_sdl(self, scalar_handler: GraphQLHandler) -> None:
        sdl = scalar_handler.get_sdl()
        assert "return_uuid_list: [UUID!]!" in sdl
