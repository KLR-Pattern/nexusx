"""US1/US4 (T019): catalog schema renders a federated paginated relationship
(declared via RemoteRelationship.sort_field) as {items, pagination} + limit/offset
args — without forcing the global enable_pagination toggle on the mounter.

Covers the catalog side. The member side (by_<key>_in_page root return type) is
tracked separately — it is the remaining blocker for full US1 e2e.
"""

import os
import tempfile

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.applications import Starlette
from starlette.routing import Mount

from nexusx import GraphQLHandler
from nexusx.federation import RemoteRelationship, RemoteService
from nexusx.federation.http import GraphQLTransport
from nexusx.federation.introspect import build_federable_app
from nexusx.standard_queries import AutoQueryConfig

reviews = RemoteService("reviews", url="http://test/reviews")


class RProductBase(SQLModel):
    pass


class RReviewBase(SQLModel):
    pass


class RReview(RReviewBase, table=True):
    __tablename__ = "fed_pag_render_review"
    id: int | None = Field(default=None, primary_key=True)
    product_id: int
    title: str
    rating: int


class RProduct(RProductBase, table=True):
    __tablename__ = "fed_pag_render_product"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[reviews.RReview],
            name="reviews", join_remote="product_id",
            sort_field="rating",  # pagination switch
        ),
    ]


def _engine():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return create_async_engine(f"sqlite+aiosqlite:///{path}")


_cat_engine = _engine()
_rev_engine = _engine()
_cat_sf = async_sessionmaker(_cat_engine, class_=AsyncSession, expire_on_commit=False)
_rev_sf = async_sessionmaker(_rev_engine, class_=AsyncSession, expire_on_commit=False)
_seeded = False


async def _ensure_seed():
    global _seeded
    if _seeded:
        return
    async with _cat_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with _rev_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with _cat_sf() as s:
        s.add(RProduct(id=1, name="P1"))
        await s.commit()
    async with _rev_sf() as s:
        s.add(RReview(id=1, product_id=1, title="R1", rating=5))
        await s.commit()
    _seeded = True


@pytest.fixture
async def catalog():
    await _ensure_seed()
    reviews_handler = GraphQLHandler(
        base=RReviewBase, session_factory=_rev_sf,
        auto_query_config=AutoQueryConfig(batch_keys={"RReview": ["product_id"]}),
        service_name="reviews",
    )
    reviews_app = build_federable_app(reviews_handler)
    catalog_handler = GraphQLHandler(
        base=RProductBase, session_factory=_cat_sf,
        auto_query_config=AutoQueryConfig(), service_name="catalog",
    )
    composite = Starlette(routes=[Mount("/reviews", app=reviews_app)])
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=composite), base_url="http://test",
    )
    transport = GraphQLTransport(client=client)
    await catalog_handler.er.initialize(transport=transport)
    yield catalog_handler
    await client.aclose()


def _unwrap_type_name(type_ref: dict) -> str | None:
    """Drill NON_NULL/LIST wrappers to the named OBJECT/SCALAR."""
    while type_ref.get("ofType"):
        type_ref = type_ref["ofType"]
    return type_ref.get("name")


@pytest.mark.asyncio
async def test_sdl_renders_paginated_remote_as_result(catalog):
    sdl = catalog.get_sdl()
    # The remote to-many declared with sort_field renders as a Result field.
    assert "reviews(limit: Int, offset: Int = 0): RReviewResult!" in sdl
    # Result + Pagination types are generated.
    assert "type RReviewResult {" in sdl
    assert "items: [RReview!]!" in sdl
    assert "pagination: Pagination!" in sdl


@pytest.mark.asyncio
async def test_introspection_renders_paginated_remote_as_result(catalog):
    intro = catalog.get_introspection_data()
    types = {t["name"]: t for t in intro["types"]}
    assert "RReviewResult" in types
    assert "Pagination" in types
    product = types["RProduct"]
    reviews_field = next(f for f in product["fields"] if f["name"] == "reviews")
    arg_names = {a["name"] for a in reviews_field["args"]}
    assert "limit" in arg_names
    assert "offset" in arg_names
    assert _unwrap_type_name(reviews_field["type"]) == "RReviewResult"
