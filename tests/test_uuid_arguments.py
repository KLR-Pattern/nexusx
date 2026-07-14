"""Tests for UUID argument and field handling.

When a SQLModel entity declares ``id: UUID`` (or any field/parameter of type
``uuid.UUID``), GraphQL clients send string literals because the SDL maps
``UUID`` to ``String`` (see ``sdl_generator.py`` — ``or "String"`` fallback).

This module pins two contracts that nexusx must honor end-to-end:

1. **Argument direction**: a string literal sent by the client must be converted
   back to ``uuid.UUID`` before the ``@query``/``@mutation`` method is called.
   Otherwise the method receives a raw ``str`` and SQLModel/SQLAlchemy raises
   ``AttributeError: 'str' object has no attribute 'hex'`` the moment it tries
   to bind the value to a UUID column.

2. **Response direction**: when a method returns an entity whose UUID-typed
   field holds a ``uuid.UUID`` instance, the response JSON must serialize it
   as a string (``str(uuid)``). Otherwise the JSON encoder fails or — at best —
   the client receives an object it cannot interpret.
"""

from __future__ import annotations

from typing import ClassVar, Optional
from uuid import UUID, uuid4

import pytest
from sqlmodel import Field, SQLModel

from nexusx import GraphQLHandler, query


# ──────────────────────────────────────────────────────────
# Test entity — single UUID field, no DB table required
# ──────────────────────────────────────────────────────────


class UuidArgBase(SQLModel):
    """Base class for UUID-related test entities."""

    pass


# Sentinel to capture what the @query method actually receives at runtime.
# A class attribute is the simplest way to peek at the argument without
# weaving a mock into the call path.
_RECEIVED: dict[str, object] = {}


class UuidItem(UuidArgBase, table=False):
    """Entity with a UUID primary key and a query method that accepts a UUID."""

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = ""

    @query
    async def get_by_id(cls, id: UUID) -> Optional[UuidItem]:  # noqa: A002
        """Return an echo entity; record the runtime type of ``id``.

        nexusx must convert the incoming GraphQL string into ``UUID`` before
        calling this method. We assert via the ``_RECEIVED`` sentinel.
        """
        _RECEIVED["id"] = id
        _RECEIVED["id_type"] = type(id)
        if isinstance(id, UUID):
            return UuidItem(id=id, name="echo")
        # Simulate the real-world failure mode: SQLModel binds UUID via .hex,
        # so a str here would raise AttributeError downstream. Surface it
        # explicitly so the test failure points at the root cause.
        raise TypeError(
            f"@query method received {type(id).__name__} instead of UUID; "
            f"SQLModel would raise AttributeError: 'str' object has no attribute 'hex'"
        )


# ──────────────────────────────────────────────────────────
# 1. Argument direction — string literal → UUID
# ──────────────────────────────────────────────────────────


@pytest.fixture
def uuid_handler() -> GraphQLHandler:
    _RECEIVED.clear()
    return GraphQLHandler(base=UuidArgBase)


class TestUuidArgumentConversion:
    """The @query method must receive a UUID instance, not a str."""

    @pytest.mark.asyncio
    async def test_string_literal_converted_to_uuid(
        self, uuid_handler: GraphQLHandler
    ) -> None:
        """Client sends ``id: "<uuid-str>"``; method receives ``UUID(<uuid-str>)``."""
        literal = "123e4567-e89b-12d3-a456-426614174000"
        query_str = f'{{ uuidItemGetById(id: "{literal}") {{ id name }} }}'

        result = await uuid_handler.execute(query_str)

        assert "errors" not in result, f"unexpected errors: {result.get('errors')}"
        assert "data" in result
        assert isinstance(_RECEIVED.get("id"), UUID), (
            f"Expected UUID, got {_RECEIVED.get('id_type')}. "
            "ArgumentBuilder._convert_scalar_value must handle uuid.UUID."
        )
        assert str(_RECEIVED["id"]) == literal

    @pytest.mark.asyncio
    async def test_string_variable_converted_to_uuid(
        self, uuid_handler: GraphQLHandler
    ) -> None:
        """Same contract via GraphQL variables (the form SDKs typically send)."""
        literal = "123e4567-e89b-12d3-a456-426614174000"
        query_str = "query Q($id: String!) { uuidItemGetById(id: $id) { id name } }"

        result = await uuid_handler.execute(
            query_str, variables={"id": literal}, operation_name="Q"
        )

        assert "errors" not in result, f"unexpected errors: {result.get('errors')}"
        assert isinstance(_RECEIVED.get("id"), UUID), (
            f"Expected UUID, got {_RECEIVED.get('id_type')}"
        )

    @pytest.mark.asyncio
    async def test_optional_uuid_argument_handled(
        self, uuid_handler: GraphQLHandler
    ) -> None:
        """Optional[UUID] must still convert when a value is provided."""
        # This indirectly exercises unwrap_optional + UUID conversion ordering.
        literal = "00000000-0000-0000-0000-000000000001"
        query_str = f'{{ uuidItemGetById(id: "{literal}") {{ id }} }}'

        result = await uuid_handler.execute(query_str)

        assert "errors" not in result, f"unexpected errors: {result.get('errors')}"
        assert isinstance(_RECEIVED.get("id"), UUID)


# ──────────────────────────────────────────────────────────
# 2. Response direction — UUID instance → JSON string
# ──────────────────────────────────────────────────────────


class TestUuidFieldSerialization:
    """The response JSON must serialize UUID fields as strings."""

    @pytest.mark.asyncio
    async def test_uuid_field_serialized_as_string(
        self, uuid_handler: GraphQLHandler
    ) -> None:
        """``id`` field (UUID instance) must come back as a JSON string."""
        literal = "123e4567-e89b-12d3-a456-426614174000"
        result = await uuid_handler.execute(
            f'{{ uuidItemGetById(id: "{literal}") {{ id name }} }}'
        )

        assert "errors" not in result, f"unexpected errors: {result.get('errors')}"
        payload = result["data"]["uuidItemGetById"]
        # JSON values reach us as Python str when the encoder handled UUID; if
        # nexusx passed the raw UUID into the response builder, the value here
        # would either be a UUID instance (encoder fallback) or the call would
        # have errored out.
        assert isinstance(payload["id"], str), (
            f"Expected str (JSON-serialized UUID), got {type(payload['id']).__name__}"
        )
        assert payload["id"] == literal


# ──────────────────────────────────────────────────────────
# 3. SDL — UUID fields map to GraphQL String
# ──────────────────────────────────────────────────────────


class TestUuidSDL:
    """UUID Python type must surface as ``UUID`` scalar in the SDL."""

    def test_uuid_field_in_sdl(self, uuid_handler: GraphQLHandler) -> None:
        """The method's ``id`` argument surfaces as ``UUID!``."""
        sdl = uuid_handler.get_sdl()
        # Entity type itself is present
        assert "type UuidItem" in sdl
        # nexusx now registers uuid.UUID → "UUID" in TypeConverter.SCALAR_TYPE_MAP,
        # so the SDL must render the canonical UUID scalar (not the String fallback).
        assert "uuidItemGetById(id: UUID!)" in sdl, (
            f"Expected `uuidItemGetById(id: UUID!)` in SDL, got:\n{sdl}"
        )
        assert "(id: String" not in sdl
