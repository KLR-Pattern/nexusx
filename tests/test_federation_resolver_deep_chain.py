"""Resolver (γ) over a federated deep chain — member-local edges via β fetch.

Mirror of test_federation_deep_chain.py, but entered through the Resolver
(``catalog.er.create_resolver().resolve([ProductDTO])``) instead of a gql query.
Proves the two paths now share one fetch primitive (``fetch_remote_subtree``):
the Resolver fetches the whole sub-tree with ONE nested gql per service, so
edges LOCAL to a member (Review→Comment, User→UserConfig) resolve too — the
case that used to break (per-edge flat fetch, wrong join key).

    RCProduct → RCReview → RCComment → RCUser → RCUserConfig
      (catalog)  (rcreviews)  (rcreviews local)  (rcusers)  (rcusers local)

Uses distinct service names (rcusers / rcreviews) so the module-level
DefineSubset DTOs don't collide with other tests' federate (their pending
subsets are skipped when their service isn't mounted).
"""

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, Relationship, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.applications import Starlette
from starlette.routing import Mount

from nexusx import AutoQueryConfig, DefineSubset, GraphQLHandler
from nexusx.federation import RemoteRelationship, RemoteService
from nexusx.federation.http import GraphQLTransport
from nexusx.federation.introspect import build_federable_app

# Remote service roots — distinct names to avoid cross-test pending-subset clashes.
rcusers = RemoteService("rcusers", url="http://test/rcusers")
rcreviews = RemoteService("rcreviews", url="http://test/rcreviews")


# ── rcusers service: User ── UserConfig (local one-to-one) ────────────────
class _UsersBase(SQLModel):
    pass


class RCUserConfig(_UsersBase, table=True):
    __tablename__ = "rc_resolver_userconfig"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="rc_resolver_user.id")
    value: str


class RCUser(_UsersBase, table=True):
    __tablename__ = "rc_resolver_user"
    __federation_keys__ = ["id"]
    id: int | None = Field(default=None, primary_key=True)
    name: str
    config: RCUserConfig | None = Relationship(sa_relationship_kwargs={"uselist": False})


# ── rcreviews service: Review ── Comment (local); Comment.author → rcusers.User
class _ReviewsBase(SQLModel):
    pass


class RCComment(_ReviewsBase, table=True):
    __tablename__ = "rc_resolver_comment"
    id: int | None = Field(default=None, primary_key=True)
    review_id: int = Field(foreign_key="rc_resolver_review.id")
    author_id: int
    text: str
    __relationships__ = [
        RemoteRelationship(
            fk="author_id", target=rcusers.RCUser,
            name="author", join_remote="id",
        ),
    ]


class RCReview(_ReviewsBase, table=True):
    __tablename__ = "rc_resolver_review"
    __federation_keys__ = ["product_id"]
    id: int | None = Field(default=None, primary_key=True)
    product_id: int
    title: str
    rating: int
    comments: list[RCComment] = Relationship()


# ── catalog service: Product ── Review (remote) ───────────────────────────
class _CatalogBase(SQLModel):
    pass


class RCProduct(_CatalogBase, table=True):
    __tablename__ = "rc_resolver_product"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[rcreviews.RCReview],
            name="reviews", join_remote="product_id",
        ),
    ]


# ── Deep DefineSubset DTO tree over the federated graph ───────────────────
class RCUserConfigDTO(DefineSubset):
    __subset__ = (rcusers.RCUserConfig, ("value",))


class RCUserDTO(DefineSubset):
    __subset__ = (rcusers.RCUser, ("name",))
    config: RCUserConfigDTO | None = None


class RCCommentDTO(DefineSubset):
    __subset__ = (rcreviews.RCComment, ("text",))
    author: RCUserDTO | None = None


class RCReviewDTO(DefineSubset):
    __subset__ = (rcreviews.RCReview, ("title", "rating"))
    comments: list[RCCommentDTO] = Field(default_factory=list)


class RCProductDTO(DefineSubset):
    __subset__ = (RCProduct, ("id", "name"))
    reviews: list[RCReviewDTO] = Field(default_factory=list)


class _CountingTransport(GraphQLTransport):
    """Records gql POST urls (excludes introspection GETs)."""

    def __init__(self, client):
        super().__init__(client=client)
        self.posts: list[str] = []

    async def post_json(self, url, body):
        self.posts.append(url)
        return await super().post_json(url, body)


@pytest.fixture(scope="module")
async def _engines():
    eng = {
        "rcusers": create_async_engine("sqlite+aiosqlite:///:memory:"),
        "rcreviews": create_async_engine("sqlite+aiosqlite:///:memory:"),
        "catalog": create_async_engine("sqlite+aiosqlite:///:memory:"),
    }
    for e in eng.values():
        async with e.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
    yield eng
    for e in eng.values():
        await e.dispose()


@pytest.mark.asyncio
async def test_resolver_deep_chain_via_shared_fetch_primitive(_engines):
    def sf(k):
        return async_sessionmaker(_engines[k], class_=AsyncSession, expire_on_commit=False)

    async with sf("rcusers")() as s:
        s.add(RCUser(id=1, name="Alice"))
        s.add(RCUser(id=2, name="Bob"))
        s.add(RCUserConfig(id=1, user_id=1, value="dark"))
        s.add(RCUserConfig(id=2, user_id=2, value="light"))
        await s.commit()
    async with sf("rcreviews")() as s:
        s.add(RCReview(id=1, product_id=1, title="R1", rating=5))
        s.add(RCComment(id=1, review_id=1, author_id=1, text="C1"))
        s.add(RCComment(id=2, review_id=1, author_id=2, text="C2"))
        await s.commit()
    async with sf("catalog")() as s:
        s.add(RCProduct(id=1, name="Widget"))
        await s.commit()

    users_h = GraphQLHandler(
        base=_UsersBase, session_factory=sf("rcusers"),
        auto_query_config=AutoQueryConfig(),
        service_name="rcusers",
    )
    reviews_h = GraphQLHandler(
        base=_ReviewsBase, session_factory=sf("rcreviews"),
        auto_query_config=AutoQueryConfig(),
        service_name="rcreviews", expose_mounted_endpoints=True,
    )
    catalog_h = GraphQLHandler(
        base=_CatalogBase, session_factory=sf("catalog"),
        auto_query_config=AutoQueryConfig(), service_name="catalog",
    )

    composite = Starlette(routes=[
        Mount("/rcusers", app=build_federable_app(users_h)),
        Mount("/rcreviews", app=build_federable_app(reviews_h)),
    ])
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=composite), base_url="http://test")
    transport = _CountingTransport(client=client)

    await reviews_h.er.initialize(transport=transport)
    await catalog_h.er.initialize(transport=transport)

    try:
        Resolver = catalog_h.er.create_resolver()
        before = len(transport.posts)
        resolved = await Resolver().resolve([RCProductDTO(id=1, name="Widget")])
        gql_posts = transport.posts[before:]

        product = resolved[0]
        review = product.reviews[0]
        assert review.title == "R1" and review.rating == 5
        by_text = {c.text: c for c in review.comments}
        # member-LOCAL edge (Review→Comment) + cross-service (Comment→User)
        # + member-local to users (User→UserConfig) — all populated.
        assert by_text["C1"].author.name == "Alice"
        assert by_text["C1"].author.config.value == "dark"
        assert by_text["C2"].author.name == "Bob"
        assert by_text["C2"].author.config.value == "light"

        # ONE nested gql per service (β coalescing via fetch_remote_subtree),
        # not per-level flat fetches.
        reviews_hits = sum(1 for u in gql_posts if "/rcreviews/" in u)
        users_hits = sum(1 for u in gql_posts if "/rcusers/" in u)
        assert reviews_hits == 1, gql_posts
        assert users_hits == 1, gql_posts
    finally:
        await client.aclose()
