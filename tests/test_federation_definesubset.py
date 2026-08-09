"""Composition: federation β-fetch + DefineSubset.model_validate (declarative).

Locks the pattern demo/federation/catalog_app.composed_tree demonstrates:
federation fetches the cross-service graph with one nested gql per service (β);
DefineSubset + pydantic's model_validate then shape the nested result into a
DTO tree — NO manual per-row assembly, NO for-loop over children. federation is
the fetch layer; DefineSubset is the shaping layer.
"""

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.applications import Starlette
from starlette.routing import Mount

from nexusx import AutoQueryConfig, DefineSubset, GraphQLHandler
from nexusx.federation import RemoteRelationship, RemoteService
from nexusx.federation.http import GraphQLTransport
from nexusx.federation.introspect import build_federable_app

# Remote service roots — name + url, declared once, referenced below.
users = RemoteService("users", url="http://test/users")
reviews = RemoteService("reviews", url="http://test/reviews")


class _UB(SQLModel):
    pass


class _RB(SQLModel):
    pass


class _CB(SQLModel):
    pass


class DSUser(_UB, table=True):
    __tablename__ = "fed_ds_user"
    __federation_keys__ = ["id"]
    id: int | None = Field(default=None, primary_key=True)
    name: str


class DSReview(_RB, table=True):
    __tablename__ = "fed_ds_review"
    __federation_keys__ = ["product_id", "author_id"]
    id: int | None = Field(default=None, primary_key=True)
    product_id: int
    author_id: int
    title: str
    rating: int
    __relationships__ = [
        RemoteRelationship(
            fk="author_id", target=users.DSUser,
            name="author", join_remote="id",
        ),
    ]


class DSProduct(_CB, table=True):
    __tablename__ = "fed_ds_product"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[reviews.DSReview],
            name="reviews", join_remote="product_id",
        ),
    ]


# DTO tree mirroring the graph. Local entry entity via DefineSubset; remote
# levels are plain BaseModel (the materialized remote types are dynamic, so they
# are shaped by field selection, not DefineSubset over a source class).
class UserDTO(BaseModel):
    name: str


class ReviewDTO(BaseModel):
    title: str
    rating: int
    author: UserDTO | None = None


class ProductDTO(DefineSubset):
    __subset__ = (DSProduct, ("id", "name"))
    reviews: list[ReviewDTO] = Field(default_factory=list)


@pytest.mark.asyncio
async def test_composed_tree_via_beta_fetch_and_model_validate():
    engines = {k: create_async_engine("sqlite+aiosqlite:///:memory:") for k in ("u", "r", "c")}
    try:
        for e in engines.values():
            async with e.begin() as conn:
                await conn.run_sync(SQLModel.metadata.create_all)

        def sf(k):
            return async_sessionmaker(engines[k], class_=AsyncSession, expire_on_commit=False)

        async with sf("u")() as s:
            s.add(DSUser(id=1, name="Alice"))
            s.add(DSUser(id=2, name="Bob"))
            await s.commit()
        async with sf("r")() as s:
            s.add(DSReview(id=1, product_id=1, author_id=1, title="Great", rating=5))
            s.add(DSReview(id=2, product_id=1, author_id=2, title="Okay", rating=3))
            s.add(DSReview(id=3, product_id=2, author_id=1, title="Mediocre", rating=2))
            await s.commit()
        async with sf("c")() as s:
            s.add(DSProduct(id=1, name="Widget"))
            s.add(DSProduct(id=2, name="Gadget"))
            await s.commit()

        users_h = GraphQLHandler(
            base=_UB, session_factory=sf("u"),
            auto_query_config=AutoQueryConfig(),
            service_name="users",
        )
        reviews_h = GraphQLHandler(
            base=_RB, session_factory=sf("r"),
            auto_query_config=AutoQueryConfig(),
            service_name="reviews",
            expose_mounted_endpoints=True,
        )
        catalog_h = GraphQLHandler(
            base=_CB, session_factory=sf("c"),
            auto_query_config=AutoQueryConfig(), service_name="catalog",
        )

        composite = Starlette(routes=[
            Mount("/users", app=build_federable_app(users_h)),
            Mount("/reviews", app=build_federable_app(reviews_h)),
        ])
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=composite), base_url="http://test")
        transport = GraphQLTransport(client=client)
        await reviews_h.er.initialize(transport=transport)
        await catalog_h.er.initialize(transport=transport)

        try:
            # β fetch: one nested gql returns Product → Review → author.
            res = await catalog_h.execute(
                "{ DSProduct { by_filter { id name reviews { title rating author { name } } } } }"
            )
            assert not res.get("errors"), res
            products = (
                ((res.get("data") or {}).get("DSProduct") or {}).get("by_filter") or []
            )
            # Declarative shaping: model_validate recurses the nested dict into the
            # DTO tree — one root-level comprehension, no for-loop over children.
            tree = [ProductDTO.model_validate(p) for p in products]
        finally:
            await client.aclose()

        by_name = {p.name: p for p in tree}
        widget = by_name["Widget"]
        assert {r.title for r in widget.reviews} == {"Great", "Okay"}
        # author reached transitively (catalog mounted only reviews; users via reviews).
        assert {r.author.name for r in widget.reviews} == {"Alice", "Bob"}
        gadget = by_name["Gadget"]
        assert [r.title for r in gadget.reviews] == ["Mediocre"]
        assert gadget.reviews[0].author.name == "Alice"
    finally:
        for e in engines.values():
            await e.dispose()
