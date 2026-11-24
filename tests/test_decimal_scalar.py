"""`Decimal` is a named custom scalar on BOTH GraphQL paths (issue #160 DESIGN_1).

Before spec 026 the compose path rejected ``Decimal`` with a generic
``UnsupportedTypeError`` while the entity-first path silently mapped it to
``String``. Now both render ``Decimal``; the wire value is the string pydantic
already produced (``model_dump(mode="json")``), so no serialization changes.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlmodel import SQLModel

from nexusx import GraphQLHandler, query
from nexusx.execution.argument_builder import ArgumentBuilder
from nexusx.type_converter import SCALAR_TYPE_MAP
from nexusx.use_case.business import UseCaseService
from nexusx.use_case.compose_schema import build_compose_schema
from nexusx.use_case.compose_type_mapper import ComposeTypeMapper
from nexusx.use_case.types import UseCaseAppConfig


class DecBase(SQLModel):
    pass


class DecItem(DecBase, table=False):
    id: int
    price: Decimal

    @query
    async def get_one(cls, price: Decimal) -> Decimal:  # noqa: UP045 — return type is the point
        return price


@pytest.fixture(scope="module")
def dec_handler() -> GraphQLHandler:
    return GraphQLHandler(base=DecBase, session_factory=lambda: None)


class TestEntityFirst:
    def test_scalar_table(self):
        assert SCALAR_TYPE_MAP[Decimal] == "Decimal"

    def test_sdl_renders_decimal_type_and_argument(self, dec_handler: GraphQLHandler):
        sdl = dec_handler.get_sdl()
        assert "price: Decimal!" in sdl
        assert "get_one(price: Decimal!): Decimal!" in sdl

    def test_introspection_lists_the_scalar(self, dec_handler: GraphQLHandler):
        names = {
            t["name"] for t in dec_handler.get_introspection_data()["types"] if t["kind"] == "SCALAR"
        }
        assert "Decimal" in names


class TestCompose:
    def test_mapper_registers_decimal_scalar(self):
        ref = ComposeTypeMapper().map_python_type(Decimal)
        # non-Optional → NON_NULL(SCALAR Decimal)
        assert ref.kind == "NON_NULL" and ref.of_type is not None
        assert ref.of_type.kind == "SCALAR" and ref.of_type.name == "Decimal"

    def test_schema_sdl_declares_the_scalar(self):
        class DecService(UseCaseService):
            @query
            async def price(cls) -> Decimal:
                return Decimal("1.5")

        schema = build_compose_schema(UseCaseAppConfig(name="dec", services=[DecService]))
        assert "scalar Decimal" in schema.render_sdl()
        assert "price: Decimal!" in schema.render_sdl()


class TestArguments:
    def test_string_literal_becomes_decimal(self):
        assert ArgumentBuilder()._convert_scalar_value("1.50", Decimal) == Decimal("1.50")
        assert ArgumentBuilder()._convert_scalar_value(None, Decimal) is None
