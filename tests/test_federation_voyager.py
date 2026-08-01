"""US4 — Voyager renders the federated graph with ownership tags (FR-016).

Materialized remote types render as REAL entities (their table lives in another
service), tagged with the owning SERVICE, in a dashed per-service cluster — NOT
as virtual entities. Genuine virtual entities keep rendering as virtual.

Cluster COLOR is opt-in: declared on ``RemoteService(color=...)`` and carried to
the consumer's fed_registry along the same path as ``url``. A service with no
declared color renders dashed but uncolored. See specs/004 (virtual) +
specs/012 FR-016 (federation ownership).
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.applications import Starlette
from starlette.routing import Mount

from nexusx import AutoQueryConfig, GraphQLHandler
from nexusx.federation import RemoteRelationship, RemoteService
from nexusx.federation.http import GraphQLTransport
from nexusx.federation.introspect import build_federable_app
from nexusx.voyager.er_diagram_dot import ErDiagramDotBuilder
from tests.test_federation_e2e import _build_catalog_and_transport


class _GenuineVirtual(BaseModel):
    """Plain BaseModel with no table — a genuine virtual entity (spec 004)."""

    label: str = ""


@pytest.mark.asyncio
async def test_voyager_includes_and_tags_federated_nodes():
    catalog_handler, _transport, client = await _build_catalog_and_transport()
    try:
        er = catalog_handler._er_manager
        builder = ErDiagramDotBuilder(er, show_module=True)
        builder.analysis()

        names = {n.name for n in builder.node_set.values()}
        assert "FedProduct" in names
        assert "FedReview" in names  # remote (materialized)

        by_name = {n.name: n for n in builder.node_set.values()}
        review = by_name["FedReview"]
        assert review.module == "reviews"
        assert review.is_federated is True
        assert review.is_virtual is False

        product = by_name["FedProduct"]
        assert product.module != "reviews"
        assert product.is_federated is False
        assert product.is_virtual is False

        dot = builder.render_dot()
        # Federated cluster is dashed (boundary); local stays rounded.
        assert 'style="rounded,dashed"' in dot
        # Opt-in guard: e2e's `reviews` RemoteService declares NO color, so no
        # cluster is colored. Color is opt-in only (no auto-palette).
        assert "pencolor" not in dot
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_genuine_virtual_stays_virtual_alongside_federated():
    """Regression for the ``and not fed_qn`` carve-out.

    A genuine virtual entity (plain BaseModel, no table) registered via
    ``add_virtual_entities`` must stay virtual — the carve-out must NOT turn it
    federated, nor let a federated type leak into the virtual cluster.
    """
    catalog_handler, _transport, client = await _build_catalog_and_transport()
    try:
        er = catalog_handler._er_manager
        er.add_virtual_entities([_GenuineVirtual])

        builder = ErDiagramDotBuilder(er, show_module=True)
        builder.analysis()
        by_name = {n.name: n for n in builder.node_set.values()}

        virtual = by_name["_GenuineVirtual"]
        assert virtual.is_virtual is True
        assert virtual.is_federated is False

        assert by_name["FedReview"].is_virtual is False
        assert by_name["FedReview"].is_federated is True

        dot = builder.render_dot()
        assert "cluster_virtual" in dot
        assert 'style="rounded,dashed"' in dot
    finally:
        await client.aclose()


def test_remote_service_color_declaration_flows_to_relationship():
    """Unit: RemoteService(color=...) carries onto RemoteRef and into
    RemoteRelationship.target_color (mirrors ``url``). No color => None."""
    colored = RemoteService("svc", url="http://test/svc", color="#abc123")
    plain = RemoteService("plain", url="http://test/plain")

    assert colored.CReview.color == "#abc123"  # RemoteRef carries color
    assert plain.Thing.color is None  # default: no color

    rrel = RemoteRelationship(
        fk="id", target=list[colored.CReview],
        name="reviews", join_remote="product_id",
    )
    assert rrel.target_color == "#abc123"
    assert rrel.target_url == "http://test/svc"  # url still flows in parallel

    rrel_plain = RemoteRelationship(
        fk="id", target=plain.Thing, name="t", join_remote="id",
    )
    assert rrel_plain.target_color is None


# ── Full-path: a declared color renders in the ER DOT ────────────────────
# Module-level entities with unique tablenames so SQLModel's global registry
# sees each class once across the session (mirrors test_federation_resolver_context).
_color_reviews = RemoteService("creviews", url="http://test/creviews", color="#3b82f6")


class _ColorRevBase(SQLModel):
    pass


class ColorReview(_ColorRevBase, table=True):
    __tablename__ = "voyager_color_review"
    id: int | None = Field(default=None, primary_key=True)
    product_id: int
    title: str


class _ColorCatBase(SQLModel):
    pass


class ColorProduct(_ColorCatBase, table=True):
    __tablename__ = "voyager_color_product"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[_color_reviews.ColorReview],
            name="reviews", join_remote="product_id",
        ),
    ]


@pytest.mark.asyncio
async def test_declared_remote_service_color_renders():
    """End-to-end: RemoteService(color=...) → fed_registry → ER DOT.

    The declared service's cluster is dashed AND colored; the local cluster is
    uncolored.
    """
    eng = {
        "rev": create_async_engine("sqlite+aiosqlite:///:memory:"),
        "cat": create_async_engine("sqlite+aiosqlite:///:memory:"),
    }
    for e in eng.values():
        async with e.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
    sf = {
        k: async_sessionmaker(eng[k], class_=AsyncSession, expire_on_commit=False)
        for k in eng
    }

    rev_h = GraphQLHandler(
        base=_ColorRevBase, session_factory=sf["rev"],
        auto_query_config=AutoQueryConfig(batch_keys={"ColorReview": ["product_id"]}),
        service_name="creviews",
    )
    cat_h = GraphQLHandler(
        base=_ColorCatBase, session_factory=sf["cat"],
        auto_query_config=AutoQueryConfig(), service_name="ccatalog",
    )
    composite = Starlette(routes=[Mount("/creviews", app=build_federable_app(rev_h))])
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=composite), base_url="http://test",
    )
    transport = GraphQLTransport(client=client)
    await cat_h.er.initialize(transport=transport)
    try:
        er = cat_h._er_manager
        # Color collected from RemoteRelationship.target_color during federate.
        assert er._fed_registry.service_colors()["creviews"] == "#3b82f6"

        builder = ErDiagramDotBuilder(er, show_module=True)
        builder.analysis()
        dot = builder.render_dot()
        assert '#3b82f6' in dot  # the declared color reaches the cluster
        assert 'style="rounded,dashed"' in dot  # dashed
    finally:
        await client.aclose()
        for e in eng.values():
            await e.dispose()
