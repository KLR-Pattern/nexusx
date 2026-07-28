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


# ── UseCaseService: DefineSubset + Resolver over federated schema ────────
# Remote types are materialized as first-class pydantic schema (from ER
# introspection). DefineSubset targets them; Resolver auto-loads the cross-
# service tree via RemoteLoaders. model_dump serializes everything (relationships
# are proper model_fields). No gql string, no for-loop, no manual serialization.

from nexusx import DefineSubset

_resolver_cls = None
_dto_tree = None  # (ProductDTO, ReviewDTO) built dynamically post-federate


def _build_dto_tree():
    """Build DefineSubset DTOs over materialized types (first-class pydantic schema).

    Materialized types exist only after federate() (dynamic create_model), so the
    DTOs are built lazily. Once built, they behave exactly like normal DefineSubset
    DTOs — the Resolver auto-loads, model_dump serializes, everything works.
    """
    global _dto_tree
    if _dto_tree is not None:
        return _dto_tree

    fed = handler._er_manager._fed_registry
    fed_review = fed.get("reviews.Review")
    fed_user = fed.get("users.User")

    # DefineSubset over the REMOTE Review — picks title + rating + author_id
    # (author_id is the join key the Resolver reads to auto-load author).
    ReviewDTO = type("ReviewDTO", (DefineSubset,), {
        "__subset__": (fed_review, ("title", "rating", "author_id")),
        "author": None,
        "__annotations__": {"author": fed_user | None},
        "__module__": __name__,
    })

    # DefineSubset over the LOCAL Product — picks id + name, adds reviews.
    ProductDTO = type("ProductDTO", (DefineSubset,), {
        "__subset__": (Product, ("id", "name")),
        "reviews": [],
        "__annotations__": {"reviews": list[ReviewDTO]},
        "__module__": __name__,
    })

    _dto_tree = (ProductDTO, ReviewDTO)
    return _dto_tree


class CatalogService(UseCaseService):
    """Business-logic surface over the federated graph."""

    @query
    async def composed_tree(cls) -> list[dict]:
        """DefineSubset + Resolver over federated schema.

        DTOs are built from materialized types (first-class pydantic schema).
        The Resolver auto-loads reviews (→ reviews svc) and author (→ users svc)
        via RemoteLoaders. model_dump serializes the full tree (relationships
        are model_fields). No gql string, no for-loop.
        """
        global _resolver_cls
        ProductDTO, _ReviewDTO = _build_dto_tree()
        if _resolver_cls is None:
            _resolver_cls = handler._er_manager.create_resolver()
        async with async_session() as s:
            products = (await s.exec(select(Product))).all()
        # Build root DTOs (just scalars — Resolver fills relationships).
        dtos = [ProductDTO(id=p.id, name=p.name) for p in products]
        resolved = await _resolver_cls().resolve(dtos)
        # model_dump now includes relationships (they're model_fields)!
        return [p.model_dump(mode="json") for p in resolved]


# Expose the UseCase service as REST alongside the GraphQL surface.
app.include_router(
    create_use_case_router(UseCaseAppConfig(name="catalog", services=[CatalogService]))
)
