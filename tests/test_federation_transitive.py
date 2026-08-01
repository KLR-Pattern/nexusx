"""US2 — transitive cross-service discovery.

catalog mounts ONLY reviews; reviews itself mounts users (Review.author →
users.TransUser). catalog must reach users TRANSITIVELY through reviews'
fragment (which carries author.target_endpoint), without catalog mounting
users explicitly (FR-005). This locks in the β + relative-composition path that
the demo exercises and that a unit test previously missed.
"""

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.applications import Starlette
from starlette.routing import Mount

from nexusx import AutoQueryConfig, GraphQLHandler
from nexusx.federation import RemoteRelationship, RemoteService
from nexusx.federation.http import GraphQLTransport
from nexusx.federation.introspect import build_federable_app

# Remote service roots — name + url, declared once, referenced below.
users = RemoteService("users", url="http://test/users")
reviews = RemoteService("reviews", url="http://test/reviews")

# Module-level entities with unique names → no SQLAlchemy clsregistry clashes
# with other test modules' Review/Product/User classes.


class _UsersBase(SQLModel):
    pass


class _ReviewsBase(SQLModel):
    pass


class _CatalogBase(SQLModel):
    pass


class TransUser(_UsersBase, table=True):
    __tablename__ = "fed_trans_user"
    id: int | None = Field(default=None, primary_key=True)
    name: str


class TransReview(_ReviewsBase, table=True):
    __tablename__ = "fed_trans_review"
    id: int | None = Field(default=None, primary_key=True)
    product_id: int
    author_id: int
    title: str
    __relationships__ = [
        RemoteRelationship(
            fk="author_id", target=users.TransUser,
            name="author", join_remote="id",
        ),
    ]


class TransProduct(_CatalogBase, table=True):
    __tablename__ = "fed_trans_product"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[reviews.TransReview],
            name="reviews", join_remote="product_id",
        ),
    ]


@pytest.fixture(scope="module")
async def _engines():
    eng = {
        "users": create_async_engine("sqlite+aiosqlite:///:memory:"),
        "reviews": create_async_engine("sqlite+aiosqlite:///:memory:"),
        "catalog": create_async_engine("sqlite+aiosqlite:///:memory:"),
    }
    for e in eng.values():
        async with e.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
    yield eng
    for e in eng.values():
        await e.dispose()


@pytest.mark.asyncio
async def test_transitive_discovery_reaches_users_through_reviews(_engines):
    users_sf = async_sessionmaker(_engines["users"], class_=AsyncSession, expire_on_commit=False)
    async with users_sf() as s:
        s.add(TransUser(id=1, name="Alice"))
        s.add(TransUser(id=2, name="Bob"))
        await s.commit()

    reviews_sf = async_sessionmaker(
        _engines["reviews"], class_=AsyncSession, expire_on_commit=False
    )
    async with reviews_sf() as s:
        s.add(TransReview(id=1, product_id=1, author_id=1, title="Loved it"))
        s.add(TransReview(id=2, product_id=1, author_id=2, title="Meh"))
        await s.commit()

    catalog_sf = async_sessionmaker(
        _engines["catalog"], class_=AsyncSession, expire_on_commit=False
    )
    async with catalog_sf() as s:
        s.add(TransProduct(id=1, name="Widget"))
        await s.commit()

    users_h = GraphQLHandler(
        base=_UsersBase, session_factory=users_sf,
        auto_query_config=AutoQueryConfig(batch_keys={"TransUser": ["id"]}),
        service_name="users",
    )
    reviews_h = GraphQLHandler(
        base=_ReviewsBase, session_factory=reviews_sf,
        auto_query_config=AutoQueryConfig(batch_keys={"TransReview": ["product_id", "author_id"]}),
        service_name="reviews",
        # Opt in so catalog can discover users' endpoint transitively through
        # reviews' introspection payload (suppressed by default to avoid leaking
        # internal topology).
        expose_mounted_endpoints=True,
    )
    catalog_h = GraphQLHandler(
        base=_CatalogBase, session_factory=catalog_sf,
        auto_query_config=AutoQueryConfig(), service_name="catalog",
    )

    composite = Starlette(routes=[
        Mount("/users", app=build_federable_app(users_h)),
        Mount("/reviews", app=build_federable_app(reviews_h)),
    ])
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=composite), base_url="http://test")
    transport = GraphQLTransport(client=client)

    # reviews mounts users; catalog mounts ONLY reviews.
    await reviews_h.er.initialize(transport=transport)
    await catalog_h.er.initialize(transport=transport)

    try:
        res = await catalog_h.execute(
            "{ TransProduct { by_id(id: 1) { id reviews { title author { name } } } } }"
        )
        assert not res.get("errors"), res
        product = res["data"]["TransProduct"]["by_id"]
        by_title = {r["title"]: r for r in product["reviews"]}
        # author reached transitively through reviews (which mounted users).
        assert by_title["Loved it"]["author"]["name"] == "Alice"
        assert by_title["Meh"]["author"]["name"] == "Bob"
        # catalog only declared `reviews` — `users` must NOT be in its declared
        # mounts (it was discovered transitively, inside federate()).
        assert "users" not in catalog_h._er_manager._mounted_services
        assert set(catalog_h._er_manager._mounted_services) == {"reviews"}
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_introspection_endpoint_respects_auth_dependency():
    """P1b: build_federable_app(dependencies=...) gates BOTH routes.

    The introspection endpoint exposes the full ER topology (and internal URLs
    when expose_mounted_endpoints=True), so production deployments must protect
    it. The ``dependencies`` seam applies to /graphql and /nexusx/er-introspection.
    """
    from fastapi import Depends, HTTPException

    def deny() -> None:
        raise HTTPException(status_code=403, detail="forbidden")

    class _FakeHandler:
        async def execute(self, *_args, **_kwargs):
            return {"data": None}

    app = build_federable_app(_FakeHandler(), dependencies=[Depends(deny)])
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    try:
        res = await client.get("/nexusx/er-introspection")
        assert res.status_code == 403
        res2 = await client.post("/graphql", json={"query": "{ __typename }"})
        assert res2.status_code == 403
    finally:
        await client.aclose()
