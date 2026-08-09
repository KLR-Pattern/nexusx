"""Federation demo — REVIEWS service (mounts users; mounted by catalog).

Run: uv run uvicorn demo.federation.reviews_app:app --port 8021

Hosts TWO levels: Review ── Comment (local one-to-many); Comment.author →
users.User (remote). A single nested query to reviews resolves reviews, their
comments, and each comment's author — reviews internally calls users, which in
turn resolves UserConfig locally.
"""

from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, Relationship, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from demo.federation._common import initialize_with_retry, make_app
from nexusx import (
    AutoQueryConfig,
    BatchPageConfig,
    DefineSubset,
    GraphQLHandler,
    OrderTerm,
    PageOrder,
    SubsetConfig,
)
from nexusx.federation import RemoteRelationship, RemoteService

USERS_URL = "http://localhost:8020"  # base URL of the users service

# Remote service root — declared once, referenced in the relationship below.
users = RemoteService("users", url=USERS_URL, color="#10b981")


class ReviewsBase(SQLModel):
    pass


class Comment(ReviewsBase, table=True):
    __tablename__ = "fed_demo_comment"
    id: int | None = Field(default=None, primary_key=True)
    review_id: int = Field(foreign_key="fed_demo_review.id")
    author_id: int
    text: str

    # Cross-service relationship: the comment's author is owned by the users service.
    __relationships__ = [
        RemoteRelationship(
            fk="author_id", target=users.User,
            name="author", join_remote="id",
        ),
    ]


class Review(ReviewsBase, table=True):
    __tablename__ = "fed_demo_review"
    __federation_keys__ = ["product_id"]
    id: int | None = Field(default=None, primary_key=True)
    product_id: int
    title: str
    rating: int
    created_at: int  # epoch seconds — backs the NEWEST order profile
    comments: list[Comment] = Relationship(
        # order_by is required for local pagination (enable_pagination below):
        # Review.comments becomes comments(limit, offset) on the member side.
        sa_relationship_kwargs={"order_by": "Comment.id"},
    )
    # specs/015: local pagination order profiles — callers can now query
    #   comments(order: NEWEST|OLDEST, direction: ASC|DESC)
    # order_by above stays as the fixed fallback when no profile/order is given.
    __pagination_orders__ = {
        "comments": BatchPageConfig(
            default_order="NEWEST",
            orders={
                "NEWEST": PageOrder([OrderTerm("id", "desc")]),
                "OLDEST": PageOrder([OrderTerm("id", "asc")]),
            },
        ),
        # specs/020: product_id is in __federation_keys__ → page_by_product_id_in
        # batch root; comments is a local relation → local paginated loader. One
        # carrier, routed by __federation_keys__.
        "product_id": BatchPageConfig(
            default_order="HIGHEST_RATING",
            orders={
                "HIGHEST_RATING": PageOrder(
                    [OrderTerm("rating", "desc")],
                    description="Highest rating first",
                ),
                "NEWEST": PageOrder(
                    [OrderTerm("created_at", "desc")],
                    description="Newest first",
                ),
            },
        ),
    }


class ReviewDTO(DefineSubset):
    """member public DTO: subset of Review + federation order profiles.

    Exposed via dto_classes below; catalog's ProductDTO.reviews references it
    (γ DTO federation). __pagination_orders__ drives the member batch root's
    ROW_NUMBER top-N when catalog sends order+limit via Paged.
    """

    __subset__ = SubsetConfig(
        kls=Review,
        fields=("title", "rating", "product_id"),
        federation_public=True,
        federation_join_key="product_id",
    )
    __pagination_orders__ = BatchPageConfig(
        default_order="HIGHEST_RATING",
        orders={"HIGHEST_RATING": PageOrder([OrderTerm("rating", "desc")])},
    )


engine = create_async_engine(f"sqlite+aiosqlite:///{Path(__file__).parent / 'fed_reviews.db'}")
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with async_session() as s:
        if not (await s.exec(select(Review))).first():
            s.add(Review(id=1, product_id=1, title="Great widget", rating=5, created_at=300))
            s.add(Review(id=2, product_id=1, title="Works okay", rating=3, created_at=100))
            s.add(Review(id=3, product_id=2, title="Mediocre", rating=2, created_at=200))
            # review 1 gets 4 comments so callers can paginate them inside the
            # reviews page: comments(limit: 2) → C1,C2 + has_more + total_count 4.
            s.add(Comment(id=1, review_id=1, author_id=1, text="Loved it"))
            s.add(Comment(id=2, review_id=1, author_id=2, text="Solid build"))
            s.add(Comment(id=3, review_id=1, author_id=1, text="Works great"))
            s.add(Comment(id=4, review_id=1, author_id=2, text="Fast delivery"))
            s.add(Comment(id=5, review_id=2, author_id=1, text="Fair enough"))
            s.add(Comment(id=6, review_id=3, author_id=2, text="Expected more"))
            await s.commit()


handler = GraphQLHandler(
    base=ReviewsBase,
    session_factory=async_session,
    # `by_product_id_in` is the batch root catalog drives (Product → Review).
    # Comment.author → users.User is driven against users' `by_id_in`.
    auto_query_config=AutoQueryConfig(),
    service_name="reviews",
    dto_classes=[ReviewDTO],
    # reviews is itself mounted by catalog AND mounts users — opting in lets
    # catalog discover users' endpoint transitively through reviews. Leaf
    # services (users) and root services (catalog) don't need this. In production
    # also guard /nexusx/er-introspection with auth (build_federable_app(dependencies=...)).
    expose_mounted_endpoints=True,
    # Member-side local pagination: Review.comments renders as
    # comments(limit, offset) { items pagination }. Composes with catalog's
    # federation pagination on Product.reviews (supported since 5.0.1).
    enable_pagination=True,
)


async def on_startup() -> None:
    await init_db()
    # reviews mounts users — relative composition (every nexusx service can mount).
    await initialize_with_retry(handler)


app = make_app(handler, on_startup=on_startup, title="Fed demo — reviews (mounts users)")
