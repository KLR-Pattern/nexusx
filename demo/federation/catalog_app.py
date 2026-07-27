"""Federation demo — CATALOG service (entry; mounts reviews).

Run: uv run uvicorn demo.federation.catalog_app:app --port 8022

This is the service clients talk to. Open http://localhost:8022/ for GraphiQL
and try:

    { Product { by_filter { id name reviews { title rating author { name } } } } }

A single query to catalog traverses catalog → reviews → users transparently;
each mounted service receives exactly one nested gql query.
"""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from demo.federation._common import federate_with_retry, make_app
from nexusx import (
    AutoQueryConfig,
    DefineSubset,
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


# ── UseCaseService: federation data → DefineSubset projection ────────────
# Demonstrates composing the federated GraphQL surface (handler.execute) with
# the UseCase / Core-API surface (DefineSubset): the service queries the
# cross-service graph, then projects it into a DefineSubset DTO sourced from
# the LOCAL Product, with computed fields derived from the REMOTE reviews/users
# data (the "post"-style transform). The remote types themselves are dynamic
# (materialized at federate-time), so the remote-derived bits live as computed
# fields on a DTO subsetted from the local entry entity.


class ProductSummary(DefineSubset):
    """Projected view of a Product plus federation-derived aggregates."""

    __subset__ = (Product, ("id", "name"))
    review_count: int = 0
    avg_rating: float = 0.0
    top_reviewer: str | None = None


class CatalogService(UseCaseService):
    """Business-logic surface over the federated graph."""

    @query
    async def product_summaries(cls) -> list[ProductSummary]:
        """Per-product review aggregates, projected from the federated graph."""
        res = await handler.execute(
            "{ Product { by_filter { id name reviews { rating author { name } } } } }"
        )
        products = (
            ((res.get("data") or {}).get("Product") or {}).get("by_filter") or []
        )
        out: list[ProductSummary] = []
        for p in products:
            reviews = p.get("reviews") or []
            ratings = [r["rating"] for r in reviews]
            reviewers = [r["author"]["name"] for r in reviews if r.get("author")]
            out.append(
                ProductSummary(
                    id=p["id"],
                    name=p["name"],
                    review_count=len(reviews),
                    avg_rating=round(sum(ratings) / len(ratings), 2) if ratings else 0.0,
                    top_reviewer=(
                        max(set(reviewers), key=reviewers.count) if reviewers else None
                    ),
                )
            )
        return out


# Expose the UseCase service as REST alongside the GraphQL surface.
app.include_router(
    create_use_case_router(UseCaseAppConfig(name="catalog", services=[CatalogService]))
)
