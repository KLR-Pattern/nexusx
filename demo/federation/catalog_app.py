"""Federation demo — CATALOG service (entry; mounts reviews).

Run: uv run uvicorn demo.federation.catalog_app:app --port 8022

This is the service clients talk to. Open http://localhost:8022/ for GraphiQL
and try:

    { Product { by_filter { id name reviews { title rating author { name } } } } }

A single query to catalog traverses catalog → reviews → users transparently;
each mounted service receives exactly one nested gql query.
"""

from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from demo.federation._common import federate_with_retry, make_app
from nexusx import (
    AutoQueryConfig,
    GraphQLHandler,
    UseCaseAppConfig,
    UseCaseService,
    create_use_case_router,
    query,
)
from nexusx.federation import RemoteRelationship

REVIEWS_URL = "http://localhost:8021"  # base URL of the reviews service


class CatalogBase(SQLModel):
    pass


class Product(CatalogBase, table=True):
    __tablename__ = "fed_demo_product"
    model_config = {"extra": "allow"}
    id: int | None = Field(default=None, primary_key=True)
    name: str

    # reviews live on the reviews service, joined by Product.id ↔ Review.product_id.
    __relationships__ = [
        RemoteRelationship(
            name="reviews", target="reviews.Review",
            join_local="id", join_remote="product_id", is_list=True,
        ),
    ]


engine = create_async_engine("sqlite+aiosqlite:///fed_catalog.db")
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with async_session() as s:
        if not (await s.exec(select(Product))).first():
            s.add(Product(name="Widget"))
            s.add(Product(name="Gadget"))
            await s.commit()


handler = GraphQLHandler(
    base=CatalogBase,
    session_factory=async_session,
    auto_query_config=AutoQueryConfig(),
    service_name="catalog",
)


async def on_startup() -> None:
    await init_db()
    # catalog mounts reviews. Reviews itself mounts users, so catalog transitively
    # reaches users through reviews — one nested gql per service per traversal.
    await federate_with_retry(handler, {"reviews": REVIEWS_URL})


app = make_app(handler, on_startup=on_startup, title="Fed demo — catalog (mounts reviews)")


# ── UseCaseService: Resolver-driven cross-service composition ────────────
# The Resolver auto-loads Product.reviews via RemoteLoader (→ reviews service),
# then traverses each Review (ErManager-aware: discovers author via the registry)
# and auto-loads author via RemoteLoader (→ users service). The whole federated
# tree is built DECLARATIVELY — no gql string, no for-loop, no model_validate.

_resolver_cls: Any = None


class CatalogService(UseCaseService):
    """Business-logic surface over the federated graph."""

    @query
    async def composed_tree(cls) -> list[dict]:
        """Resolver-driven cross-service composition: Product → Review → author.

        The Resolver auto-loads the federated tree via ErManager loaders
        (RemoteLoaders). No gql string, no manual data-assembly for-loop.
        """
        global _resolver_cls
        if _resolver_cls is None:
            _resolver_cls = handler._er_manager.create_resolver()
        async with async_session() as s:
            products = (await s.exec(select(Product))).all()
        resolved = await _resolver_cls().resolve(products)
        # Resolver auto-loaded reviews (→ reviews svc) + author (→ users svc).
        # Serialize: SQLModel table=True doesn't include extra attrs in
        # model_dump, so read them directly.
        return [
            {
                "id": p.id,
                "name": p.name,
                "reviews": [
                    {
                        "title": r.title,
                        "rating": r.rating,
                        "author": (
                            {"name": a.name} if (a := getattr(r, "author", None)) else None
                        ),
                    }
                    for r in (getattr(p, "reviews", None) or [])
                ],
            }
            for p in resolved
        ]


# Expose the UseCase service as REST alongside the GraphQL surface.
app.include_router(
    create_use_case_router(UseCaseAppConfig(name="catalog", services=[CatalogService]))
)
