"""Federation demo — REVIEWS service (mounts users; mounted by catalog).

Run: uv run uvicorn demo.federation.reviews_app:app --port 8021

Hosts TWO levels: Review ── Comment (local one-to-many); Comment.author →
users.User (remote). A single nested query to reviews resolves reviews, their
comments, and each comment's author — reviews internally calls users, which in
turn resolves UserConfig locally.
"""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, Relationship, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from demo.federation._common import initialize_with_retry, make_app
from nexusx import AutoQueryConfig, GraphQLHandler
from nexusx.federation import RemoteRelationship, RemoteService

USERS_URL = "http://localhost:8020"  # base URL of the users service

# Remote service root — declared once, referenced in the relationship below.
users = RemoteService("users", url=USERS_URL)


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
            name="author", target=users.User,
            join_local="author_id", join_remote="id", is_list=False,
        ),
    ]


class Review(ReviewsBase, table=True):
    __tablename__ = "fed_demo_review"
    id: int | None = Field(default=None, primary_key=True)
    product_id: int
    title: str
    rating: int
    comments: list[Comment] = Relationship()


engine = create_async_engine("sqlite+aiosqlite:///fed_reviews.db")
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with async_session() as s:
        if not (await s.exec(select(Review))).first():
            s.add(Review(id=1, product_id=1, title="Great widget", rating=5))
            s.add(Review(id=2, product_id=1, title="Works okay", rating=3))
            s.add(Review(id=3, product_id=2, title="Mediocre", rating=2))
            s.add(Comment(id=1, review_id=1, author_id=1, text="Loved it"))
            s.add(Comment(id=2, review_id=1, author_id=2, text="Solid build"))
            s.add(Comment(id=3, review_id=2, author_id=1, text="Fair enough"))
            s.add(Comment(id=4, review_id=3, author_id=2, text="Expected more"))
            await s.commit()


handler = GraphQLHandler(
    base=ReviewsBase,
    session_factory=async_session,
    # `by_product_id_in` is the batch root catalog drives (Product → Review).
    # Comment.author → users.User is driven against users' `by_id_in`.
    auto_query_config=AutoQueryConfig(batch_keys={"Review": ["product_id"]}),
    service_name="reviews",
    # reviews is itself mounted by catalog AND mounts users — opting in lets
    # catalog discover users' endpoint transitively through reviews. Leaf
    # services (users) and root services (catalog) don't need this. In production
    # also guard /nexusx/er-introspection with auth (build_federable_app(dependencies=...)).
    expose_mounted_endpoints=True,
)


async def on_startup() -> None:
    await init_db()
    # reviews mounts users — relative composition (every nexusx service can mount).
    await initialize_with_retry(handler)


app = make_app(handler, on_startup=on_startup, title="Fed demo — reviews (mounts users)")
