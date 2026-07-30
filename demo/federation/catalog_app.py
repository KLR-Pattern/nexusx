"""Federation demo — CATALOG service (entry; mounts reviews).

Run: uv run uvicorn demo.federation.catalog_app:app --port 8022

This is the service clients talk to. Open http://localhost:8022/ for GraphiQL,
or http://localhost:8022/voyager for the ER diagram of the composed federated
graph (catalog + materialized reviews/users, tagged by owning service). Try the
deep multi-branch chain:

    { Product { by_filter { id name
        reviews { title rating comments { text author { name config { theme } } } } } } }

A single query to catalog traverses catalog → reviews → users transparently:
Product → Review → Comment (local to reviews) → User (remote to users) →
UserConfig (local to users). Each mounted service receives exactly one nested
gql query and resolves its own subgraph.
"""


from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from demo.federation._common import initialize_with_retry, make_app
from nexusx import (
    AutoQueryConfig,
    DefineSubset,
    GraphQLHandler,
    UseCaseAppConfig,
    UseCaseService,
    create_use_case_router,
    query,
)
from nexusx.federation import RemoteRelationship, RemoteService
from nexusx.voyager import create_use_case_voyager

REVIEWS_URL = "http://localhost:8021"  # base URL of the reviews service

# Remote service roots — declared once, used everywhere (relationships + DTOs).
# `reviews` is mounted by catalog, so it carries its url; `users` is reached
# only transitively (through reviews), so it needs no url here.
reviews = RemoteService("reviews", url=REVIEWS_URL)


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
            fk="id", target=list[reviews.Review],
            name="reviews", join_remote="product_id",
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
    # initialize() derives services from the RemoteRelationship declarations.
    await initialize_with_retry(handler)


app = make_app(handler, on_startup=on_startup, title="Fed demo — catalog (mounts reviews)")

# Voyager ER visualization of the COMPOSED federated graph. catalog is the
# composition entry, so its er_manager — after the lifespan federates reviews
# (and transitively users) — holds the full graph with materialized remote
# types tagged by owning service (FR-016). VoyagerContext keeps er_manager by
# reference and builds DOT per request, so /voyager reflects the post-federation
# graph. Open http://localhost:8022/voyager (ER diagram tab).
voyager_app = create_use_case_voyager(
    services=[],
    er_manager=handler._er_manager,
    name="Fed demo — composed graph",
)
app.mount("/voyager", voyager_app)


@app.get("/")
async def root() -> dict:
    return {
        "message": "Fed demo — catalog (mounts reviews)",
        "graphql": "/graphql",
        "voyager": "/voyager",
        "er_introspection": "/nexusx/er-introspection",
    }


# ── DefineSubset DTOs: RemoteRef for remote types ───────────────────────
# Declare DTOs at module load. RemoteRef marks remote types — DefineSubset
# defers them. federate() resolves RemoteRef → materialized pydantic class.
# After federate, these are normal DefineSubset DTOs — no dynamic type(),
# no __annotations__, no ceremony.
#
# Scope note: the Resolver (γ) path traverses CROSS-SERVICE edges (Product →
# Review). Edges LOCAL to a member (Review → Comment, User → UserConfig) are
# resolved within that member's own gql response — the gql (β) path above
# traverses the full nested chain; the Resolver tree below is the cross-service
# projection. (See specs/012-federation for the β/γ distinction.)

# `reviews` declared at top; `users` is reached only transitively (via reviews),
# so it needs no url here — its types are still referenceable for DTOs.
users = RemoteService("users")


class UserConfigDTO(DefineSubset):
    """Subset of the remote users.UserConfig (resolved at federate time)."""

    __subset__ = (users.UserConfig, ("theme",))


class UserDTO(DefineSubset):
    """Subset of the remote users.User + its config (resolved at federate)."""

    __subset__ = (users.User, ("name",))
    config: UserConfigDTO | None = None


class CommentDTO(DefineSubset):
    """Subset of the remote reviews.Comment + nested author (resolved at federate)."""

    __subset__ = (reviews.Comment, ("text",))
    author: UserDTO | None = None


class ReviewDTO(DefineSubset):
    """Subset of the remote reviews.Review + nested comments (resolved at federate)."""

    __subset__ = (reviews.Review, ("title", "rating"))
    comments: list[CommentDTO] = Field(default_factory=list)


class ProductDTO(DefineSubset):
    """Subset of the local Product + nested reviews."""

    __subset__ = (Product, ("id", "name"))
    reviews: list[ReviewDTO] = Field(default_factory=list)


_resolver_cls = None


class CatalogService(UseCaseService):
    """Business-logic surface over the federated graph."""

    @query
    async def composed_tree(cls) -> list[dict]:
        """DefineSubset + Resolver over federated schema.

        DTOs declared at module load with RemoteRef — federate resolves them.
        Resolver auto-loads the cross-service tree via RemoteLoaders.
        model_dump serializes everything (relationships are model_fields).
        No gql string, no for-loop, no dynamic type().
        """
        global _resolver_cls
        if _resolver_cls is None:
            _resolver_cls = handler._er_manager.create_resolver()
        async with async_session() as s:
            products = (await s.exec(select(Product))).all()
        dtos = [ProductDTO(id=p.id, name=p.name) for p in products]
        resolved = await _resolver_cls().resolve(dtos)
        return [p.model_dump(mode="json") for p in resolved]


# Expose the UseCase service as REST alongside the GraphQL surface.
app.include_router(
    create_use_case_router(UseCaseAppConfig(name="catalog", services=[CatalogService]))
)
