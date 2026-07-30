"""Federated Resolver (γ): do post_* / Collector / SendTo / ExposeAs work?

These context primitives live on LOCALLY-DEFINED DTO classes, so the catalog
Resolver runs them locally; federation only changes where the raw field VALUES
come from. They should therefore work unchanged in a federated Resolver query —
DefineSubset is not special (it merely sources fields remotely; the DTO class
itself is local).

Design rule (why there's no "remote entity post_*" test below): ER/SQLModel
entities — including materialized remote types — are resource-oriented and carry
only data (scalars + relationships). All resolve_*/post_*/Collector/ExposeAs
live on the DTO layer and run in the consuming service's Resolver. So a computed
field over remote data is always a post_* on a LOCAL DTO, never on the remote
entity.

Topology (2 services):

    catalog.CtxProduct ──reviews──► ctxreviews.CtxReview  (resource: id/title)

Probes (all on LOCAL DTOs whose data is partly remote-sourced):
  1. local post_* on the root DefineSubset DTO (review_count).
  2. Collector + SendTo where the sent value is remote-sourced (titles).
  3. post_* on a remote-sourced CHILD DTO (title_len) — regression for the
     deferred-subset rebuild that used to strip user methods.
  4. ExposeAs from a parent DTO down to a remote-sourced child DTO (label).
  5. post_default_handler (reserved finalizer) on a remote-sourced child DTO.
"""

from typing import Annotated

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.applications import Starlette
from starlette.routing import Mount

from nexusx import AutoQueryConfig, Collector, DefineSubset, ExposeAs, GraphQLHandler, SendTo
from nexusx.federation import RemoteRelationship, RemoteService
from nexusx.federation.http import GraphQLTransport
from nexusx.federation.introspect import build_federable_app

# Distinct service name to avoid cross-test pending-subset clashes.
ctxreviews = RemoteService("ctxreviews", url="http://test/ctxreviews")


# ── ctxreviews service: Review (resource: id/product_id/title) ────────────
class _ReviewsBase(SQLModel):
    pass


class CtxReview(_ReviewsBase, table=True):
    __tablename__ = "ctx_fed_review"
    id: int | None = Field(default=None, primary_key=True)
    product_id: int
    title: str


# ── catalog service: Product ── Review (remote) ────────────────────────────
class _CatalogBase(SQLModel):
    pass


class CtxProduct(_CatalogBase, table=True):
    __tablename__ = "ctx_fed_product"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[ctxreviews.CtxReview],
            name="reviews", join_remote="product_id",
        ),
    ]


# ── DefineSubset DTO tree (catalog-side; the classes are LOCAL) ────────────
class CtxReviewDTO(DefineSubset):
    __subset__ = (ctxreviews.CtxReview, ("title",))

    # Redeclare the subset field with SendTo — the value is remote-sourced,
    # but the annotation is scanned locally by the catalog Resolver.
    title: Annotated[str, SendTo("titles")] = ""
    label: str = ""
    title_len: int = 0
    finalize_marker: str = ""

    def post_label(self, ancestor_context) -> str:
        # ExposeAs('product_name') on the parent DTO should flow down here.
        pname = (ancestor_context or {}).get("product_name")
        return f"[{pname}] {self.title}"

    def post_title_len(self) -> int:
        # Isolation probe: does ANY post_* run on a remote-sourced child DTO?
        return len(self.title)

    def post_default_handler(self) -> None:
        # Reserved finalizer: runs after all post_* at this node. Verifies the
        # deferred-rebuild fix also preserves this reserved name.
        object.__setattr__(self, "finalize_marker", f"done:{self.title}")


class CtxProductDTO(DefineSubset):
    __subset__ = (CtxProduct, ("id", "name"))

    name: Annotated[str, ExposeAs("product_name")] = ""
    reviews: list[CtxReviewDTO] = Field(default_factory=list)

    def post_review_count(self) -> int:
        return len(self.reviews)

    def post_titles(self, collector: Collector = Collector("titles")) -> list[str]:
        return sorted(collector.values())


@pytest.fixture(scope="module")
async def _federated():
    eng = {
        "ctxreviews": create_async_engine("sqlite+aiosqlite:///:memory:"),
        "catalog": create_async_engine("sqlite+aiosqlite:///:memory:"),
    }
    for e in eng.values():
        async with e.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
    sf = {k: async_sessionmaker(eng[k], class_=AsyncSession, expire_on_commit=False) for k in eng}

    async with sf["ctxreviews"]() as s:
        s.add(CtxReview(id=1, product_id=1, title="Alpha"))
        s.add(CtxReview(id=2, product_id=1, title="Beta"))
        await s.commit()
    async with sf["catalog"]() as s:
        s.add(CtxProduct(id=1, name="Widget"))
        await s.commit()

    reviews_h = GraphQLHandler(
        base=_ReviewsBase, session_factory=sf["ctxreviews"],
        auto_query_config=AutoQueryConfig(batch_keys={"CtxReview": ["product_id"]}),
        service_name="ctxreviews",
    )
    catalog_h = GraphQLHandler(
        base=_CatalogBase, session_factory=sf["catalog"],
        auto_query_config=AutoQueryConfig(), service_name="catalog",
    )

    composite = Starlette(routes=[Mount("/ctxreviews", app=build_federable_app(reviews_h))])
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=composite), base_url="http://test")
    transport = GraphQLTransport(client=client)

    await catalog_h.er.initialize(transport=transport)
    try:
        yield catalog_h
    finally:
        await client.aclose()
        for e in eng.values():
            await e.dispose()


async def _resolve(catalog_h) -> CtxProductDTO:
    Resolver = catalog_h.er.create_resolver()
    resolved = await Resolver().resolve([CtxProductDTO(id=1, name="Widget")])
    return resolved[0]


@pytest.mark.asyncio
async def test_local_post_method_on_dto(_federated):
    """1. A post_* on a local DefineSubset DTO runs in the federated Resolver."""
    product = await _resolve(_federated)
    assert product.review_count == 2


@pytest.mark.asyncio
async def test_collector_sendto_with_remote_sourced_value(_federated):
    """2. Collector+SendTo works when the sent value (title) is remote-sourced."""
    product = await _resolve(_federated)
    assert product.titles == ["Alpha", "Beta"]


@pytest.mark.asyncio
async def test_post_method_on_remote_sourced_child(_federated):
    """3a. A post_* on a remote-sourced CHILD DTO runs (regression: the deferred
    DefineSubset rebuild used to strip user methods, so this stayed 0)."""
    product = await _resolve(_federated)
    by_title = {r.title: r for r in product.reviews}
    assert by_title["Alpha"].title_len == len("Alpha")


@pytest.mark.asyncio
async def test_expose_as_flows_to_remote_sourced_child(_federated):
    """3b. ExposeAs on the parent DTO reaches a remote-sourced child DTO."""
    product = await _resolve(_federated)
    by_title = {r.title: r for r in product.reviews}
    assert by_title["Alpha"].label == "[Widget] Alpha"
    assert by_title["Beta"].label == "[Widget] Beta"


@pytest.mark.asyncio
async def test_post_default_handler_on_remote_sourced_child(_federated):
    """3c. The reserved post_default_handler finalizer also runs on a
    remote-sourced child DTO (after all post_* at that node)."""
    product = await _resolve(_federated)
    by_title = {r.title: r for r in product.reviews}
    assert by_title["Alpha"].finalize_marker == "done:Alpha"
    assert by_title["Beta"].finalize_marker == "done:Beta"


# Note: there is NO test for "post_* on the REMOTE service's own entity" — by
# design, ER/SQLModel entities (incl. materialized remote types) are
# resource-oriented and carry only data (scalars + relationships). All
# resolve_*/post_*/Collector/ExposeAs live on the DTO layer (DefineSubset /
# local pydantic DTOs) and run in the consuming service's Resolver. So a
# computed field over remote data is always a post_* on a LOCAL DTO, never on
# the remote entity.
