"""Federation demo — CATALOG service (entry; mounts reviews).

Run: uv run uvicorn demo.federation.catalog_app:app --port 8022

This is the service clients talk to. Open http://localhost:8022/ for GraphiQL,
or http://localhost:8022/voyager for the ER diagram of the composed federated
graph (catalog + materialized reviews/users, tagged by owning service). Try the
deep multi-branch chain:

    { Product { by_filter { id name
        reviews(limit: 5) { items {
          title rating
          comments(limit: 2) { items { text author { name config { theme } } }
                                pagination { has_more total_count } }
        } pagination { has_more } } } } }

The caller picks the order profile and direction at query time (specs/014) —
the member exposes HIGHEST_RATING / NEWEST, the mounter renders them as an enum:

    { Product { by_filter {
      reviews(limit: 5, order: NEWEST, direction: DESC) { items { title } } } } }

A single query to catalog traverses catalog → reviews → users transparently:
Product → Review → Comment (local to reviews) → User (remote to users) →
UserConfig (local to users). Each mounted service receives exactly one nested
gql query and resolves its own subgraph.
"""


from typing import Annotated

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
from nexusx.loader.pagination import Paged
from nexusx.voyager import create_use_case_voyager

REVIEWS_URL = "http://localhost:8021"  # base URL of the reviews service

# Remote service roots — declared once, used everywhere (relationships + DTOs).
# `reviews` is mounted by catalog, so it carries its url; `users` is reached
# only transitively (through reviews), so it needs no url here.
reviews = RemoteService("reviews", url=REVIEWS_URL, color="#3b82f6")
# Alias for DTO field annotations — a field named `reviews` would shadow the
# RemoteService in the class body (Python name lookup), so use rev_svc there.
rev_svc = reviews


class CatalogBase(SQLModel):
    pass


class Product(CatalogBase, table=True):
    __tablename__ = "fed_demo_product"
    model_config = {"extra": "allow"}
    id: int | None = Field(default=None, primary_key=True)
    name: str

    # reviews live on the reviews service, joined by Product.id ↔ Review.product_id.
    # The order profile is chosen by the caller at query time
    # (reviews(order: ..., direction: ...)); it is NOT pinned here. specs/014.
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[reviews.Review],
            name="reviews", join_remote="product_id",
            pagination=True,
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
users = RemoteService("users", color="#10b981")


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
    """Subset of the local Product + nested reviews (member public DTO, Paged)."""

    __subset__ = (Product, ("id", "name"))
    # γ DTO federation: reviews references the member public ReviewDTO (reviews
    # service), with Paged(limit=2) as default (order omitted → member
    # __pagination_orders__ default_order HIGHEST_RATING). The Resolver slices
    # per-parent via the member batch root's ROW_NUMBER top-N.
    reviews: Annotated[list[rev_svc.ReviewDTO], Paged(limit=2)] = Field(
        default_factory=list
    )


class CatalogService(UseCaseService):
    """Business-logic surface over the federated graph."""

    @query
    async def composed_tree(cls) -> list[ReviewDTO]:
        """Composed federated graph as a nested DTO tree (RESTful-style).

        The return type is itself the composition — ReviewDTO → comments →
        CommentDTO → author → UserDTO → config → UserConfigDTO — so the REST
        response and the UseCase voyager page show the full cross-service
        structure as one nested resource. Review/Comment/User rows live on the
        remote services (reviews/users); this method exposes the type graph.
        """
        return []


# ── Voyager visualization ───────────────────────────────────────────────
# catalog is the composition entry; its er_manager (after lifespan federates
# reviews → users) holds the full materialized graph. services=[CatalogService]
# feeds the use case methods above — UseCaseVoyager now clusters their remote
# DTO types by owning service (dashed + declared color) on the UseCase page,
# matching the ER diagram (FR-016). Open http://localhost:8022/voyager.
voyager_app = create_use_case_voyager(
    services=[CatalogService],
    er_manager=handler._er_manager,
    name="Fed demo — composed graph",
)
app.mount("/voyager", voyager_app)


# Expose the UseCase service as REST alongside the GraphQL surface.
app.include_router(
    create_use_case_router(UseCaseAppConfig(name="catalog", services=[CatalogService]))
)
