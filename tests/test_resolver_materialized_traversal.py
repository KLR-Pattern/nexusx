"""Resolver traversal over materialized remote types (β supplement branches).

Existing federation tests (deep chain etc.) convert materialized instances to
DefineSubset DTOs at the load boundary (``_orm_to_dto``), so the materialized
classes themselves never enter traversal as NODES. These tests resolve nodes
whose source IS the materialized class — the supplement-scan branches that
discover relationships in the ErManager (not model_fields):

  - ``Resolver._scan_auto_load_fields`` supplement loop (rels not in
    model_fields; REMOTE_COALESCED skipped there)
  - ``Resolver._get_traversable_fields`` supplement append
  - ``Resolver._compute_should_traverse`` registry-rels branch (a class with
    no resolve/post/expose config but ErManager rels is traversable)
  - ``Resolver._build_nested_selection`` materialized-type-without-DTO branch
    (include ErManager rels so the member resolves those edges too)

Plus two local (non-federation) branch tests: the ``Loader("<name>")`` global
name fallback and ExposeAs on a non-root level (``_init_level_nodes`` branch).

Graph (mirrors test_federation_resolver_deep_chain with distinct names):

    MTProduct → MTReview → MTComment → MTUser → MTUserConfig
      (catalog)  (mtreviews) (mtreviews local)  (mtusers)  (mtusers local)
"""

from typing import Annotated

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, Relationship, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.applications import Starlette
from starlette.routing import Mount

from nexusx import AutoQueryConfig, DefineSubset, ErManager, ExposeAs, GraphQLHandler, Loader
from nexusx.federation import RemoteRelationship, RemoteService
from nexusx.federation.http import GraphQLTransport
from nexusx.federation.introspect import build_federable_app

# Remote service roots — distinct names to avoid cross-test pending-subset clashes.
mtusers = RemoteService("mtusers", url="http://test/mtusers")
mtreviews = RemoteService("mtreviews", url="http://test/mtreviews")


# ── mtusers service: MTUser ── MTUserConfig (local one-to-one) ─────────────
class _MtUsersBase(SQLModel):
    pass


class MTUserConfig(_MtUsersBase, table=True):
    __tablename__ = "mt_userconfig"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="mt_user.id")
    value: str


class MTUser(_MtUsersBase, table=True):
    __tablename__ = "mt_user"
    __federation_keys__ = ["id"]
    id: int | None = Field(default=None, primary_key=True)
    name: str
    config: MTUserConfig | None = Relationship(sa_relationship_kwargs={"uselist": False})


# ── mtreviews service: MTReview ── MTComment (local); Comment.author → mtusers
class _MtReviewsBase(SQLModel):
    pass


class MTComment(_MtReviewsBase, table=True):
    __tablename__ = "mt_comment"
    id: int | None = Field(default=None, primary_key=True)
    review_id: int = Field(foreign_key="mt_review.id")
    author_id: int
    text: str
    __relationships__ = [
        RemoteRelationship(
            fk="author_id", target=mtusers.MTUser,
            name="author", join_remote="id",
        ),
    ]


class MTReview(_MtReviewsBase, table=True):
    __tablename__ = "mt_review"
    __federation_keys__ = ["product_id"]
    id: int | None = Field(default=None, primary_key=True)
    product_id: int
    title: str
    comments: list[MTComment] = Relationship()


# ── catalog service: MTProduct ── MTReview (remote) ────────────────────────
class _MtCatalogBase(SQLModel):
    pass


class MTProduct(_MtCatalogBase, table=True):
    __tablename__ = "mt_product"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[mtreviews.MTReview],
            name="reviews", join_remote="product_id",
        ),
    ]


async def _setup_stack():
    """Build the 3-service in-process stack; return (handlers, transport)."""
    engines = {
        k: create_async_engine("sqlite+aiosqlite:///:memory:")
        for k in ("mtusers", "mtreviews", "catalog")
    }
    for e in engines.values():
        async with e.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    def sf(k):
        return async_sessionmaker(engines[k], class_=AsyncSession, expire_on_commit=False)

    async with sf("mtusers")() as s:
        s.add(MTUser(id=1, name="Alice"))
        s.add(MTUser(id=2, name="Bob"))
        s.add(MTUserConfig(id=1, user_id=1, value="dark"))
        s.add(MTUserConfig(id=2, user_id=2, value="light"))
        await s.commit()
    async with sf("mtreviews")() as s:
        s.add(MTReview(id=1, product_id=1, title="R1"))
        s.add(MTComment(id=1, review_id=1, author_id=1, text="C1"))
        s.add(MTComment(id=2, review_id=1, author_id=2, text="C2"))
        await s.commit()
    async with sf("catalog")() as s:
        s.add(MTProduct(id=1, name="Widget"))
        await s.commit()

    users_h = GraphQLHandler(
        base=_MtUsersBase, session_factory=sf("mtusers"),
        auto_query_config=AutoQueryConfig(),
        service_name="mtusers",
    )
    reviews_h = GraphQLHandler(
        base=_MtReviewsBase, session_factory=sf("mtreviews"),
        auto_query_config=AutoQueryConfig(),
        service_name="mtreviews", expose_mounted_endpoints=True,
    )
    catalog_h = GraphQLHandler(
        base=_MtCatalogBase, session_factory=sf("catalog"),
        auto_query_config=AutoQueryConfig(), service_name="catalog",
    )

    composite = Starlette(routes=[
        Mount("/mtusers", app=build_federable_app(users_h)),
        Mount("/mtreviews", app=build_federable_app(reviews_h)),
    ])
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=composite), base_url="http://test",
    )
    transport = GraphQLTransport(client=client)

    await reviews_h.er.initialize(transport=transport)
    await catalog_h.er.initialize(transport=transport)
    return catalog_h, transport, engines


@pytest.mark.asyncio
async def test_materialized_traversal_paths():
    """Two traversal shapes over ONE mounted stack (service names are global
    pending-subset keys — mount each service once per module):

    1. Resolve the raw local entity: the declared remote rel (reviews) is not
       a model_field — the supplement scan discovers it, fetches ONE β nested
       gql, and the materialized instances are traversed as nodes.
    2. Resolve a materialized instance as the ROOT: the class has no
       resolve_*/post_* of its own, so its (and its descendants')
       traversability is decided by the ErManager-registered relationships —
       the ``_compute_should_traverse`` registry branch.
    """
    catalog_h, transport, engines = await _setup_stack()
    try:
        Resolver = catalog_h.er.create_resolver()

        # ── 1. local entity root ──
        resolved = await Resolver().resolve([MTProduct(id=1, name="Widget")])

        product = resolved[0]
        # reviews auto-loaded via supplement scan → β fetch → materialized instances
        assert len(product.reviews) == 1
        review = product.reviews[0]
        assert type(review) is not MTReview  # catalog's materialized copy
        assert review.title == "R1"
        # materialized MTComment children arrived coalesced (populated by the
        # nested selection, skipped by auto-load via the COALESCED guard)
        by_text = {c.text: c for c in review.comments}
        assert set(by_text) == {"C1", "C2"}
        # cross-service coalesced hop (Comment.author → mtusers) + member-local
        # edge (User.config) both populated on the materialized instances
        assert by_text["C1"].author.name == "Alice"
        assert by_text["C1"].author.config.value == "dark"
        assert by_text["C2"].author.name == "Bob"
        assert by_text["C2"].author.config.value == "light"

        # ── 2. materialized instance root ──
        re_resolved = await Resolver().resolve([review])
        node = re_resolved[0]
        assert node.title == "R1"
        by_text = {c.text: c for c in node.comments}
        assert set(by_text) == {"C1", "C2"}
        assert by_text["C1"].author.name == "Alice"
        assert by_text["C1"].author.config.value == "dark"
    finally:
        for e in engines.values():
            await e.dispose()


# ── Local (non-federation) branch tests ────────────────────────────────────

@pytest.mark.asyncio
async def test_loader_by_name_global_fallback(test_db):
    """``Loader("<rel>")`` where the DTO's source entity lacks that rel falls
    through to the registry's global name lookup (get_loader_by_name)."""
    from tests.conftest import FixtureSprint, FixtureUser, get_test_session_factory

    class UserSprintGlimpse(DefineSubset):
        __subset__ = (FixtureUser, ("id", "name"))
        sprint_name: str = ""

        async def resolve_sprint_name(self, loader=Loader("sprint")):
            # FixtureUser has no "sprint" rel — the lookup must fall back to
            # the global name index and find FixtureTask.sprint's loader.
            sprint = await loader.load(self.id)
            return sprint.name if sprint is not None else "none"

    from tests.conftest import FixtureTask

    er = ErManager(
        entities=[FixtureUser, FixtureSprint, FixtureTask],
        session_factory=get_test_session_factory(),
    )
    resolver = er.create_resolver()()
    resolved = await resolver.resolve([UserSprintGlimpse(id=1, name="Alice")])
    # user 1 → sprint loader keyed by sprint_id → Sprint 1 (seed data)
    assert resolved[0].sprint_name == "Sprint 1"


@pytest.mark.asyncio
async def test_expose_on_child_level():
    """ExposeAs on a NON-root class: the ancestor-context merge happens in
    ``_init_level_nodes`` (level ≥ 1), not the inlined level-0 builder."""
    from nexusx.resolver import Resolver

    class Leaf(BaseModel):
        seen: str = ""

        def post_seen(self, ancestor_context=None):
            return (ancestor_context or {}).get("leaf_label", "missing")

    class Child(BaseModel):
        label: Annotated[str, ExposeAs("leaf_label")]
        leaves: list[Leaf] = []

    class Root(BaseModel):
        name: str
        children: list[Child] = []

    root = Root(
        name="R",
        children=[Child(label="L1", leaves=[Leaf()]), Child(label="L2", leaves=[Leaf()])],
    )
    result = await Resolver().resolve(root)
    assert result.children[0].leaves[0].seen == "L1"
    assert result.children[1].leaves[0].seen == "L2"
