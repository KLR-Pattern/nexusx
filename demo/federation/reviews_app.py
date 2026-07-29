"""Federation demo — REVIEWS service (mounts users; mounted by catalog).

Run: uv run uvicorn demo.federation.reviews_app:app --port 8021

Demonstrates relative composition: reviews is itself a federating service — it
mounts `users` (Review.author → users.User) at startup. So a single nested
query to reviews resolves both reviews AND their authors (reviews internally
calls users).
"""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from demo.federation._common import initialize_with_retry, make_app
from nexusx import AutoQueryConfig, GraphQLHandler
from nexusx.federation import RemoteRelationship, RemoteService

USERS_URL = "http://localhost:8020"  # base URL of the users service

# Remote service root — declared once, referenced in the relationship below.
users = RemoteService("users", url=USERS_URL)


class ReviewsBase(SQLModel):
    pass


class Review(ReviewsBase, table=True):
    __tablename__ = "fed_demo_review"
    id: int | None = Field(default=None, primary_key=True)
    product_id: int
    author_id: int
    title: str
    rating: int

    # Cross-service relationship: author is owned by the users service.
    __relationships__ = [
        RemoteRelationship(
            name="author", target=users.User,
            join_local="author_id", join_remote="id", is_list=False,
        ),
    ]


engine = create_async_engine("sqlite+aiosqlite:///fed_reviews.db")
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with async_session() as s:
        if not (await s.exec(select(Review))).first():
            s.add(Review(product_id=1, author_id=1, title="Great widget", rating=5))
            s.add(Review(product_id=1, author_id=2, title="Works okay", rating=3))
            s.add(Review(product_id=2, author_id=1, title="Mediocre", rating=2))
            await s.commit()


handler = GraphQLHandler(
    base=ReviewsBase,
    session_factory=async_session,
    # `by_product_id_in` is the entry catalog drives; `by_author_id_in` is the
    # entry reviews itself drives when resolving `author` against users.
    auto_query_config=AutoQueryConfig(batch_keys={"Review": ["product_id", "author_id"]}),
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
