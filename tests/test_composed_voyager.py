"""specs/022 — Voyager member clusters & colors for ComposedErManager.

Members that declare ``service_name`` cluster by that name on the ER diagram
and the UseCase page; ``ErManager(color=...)`` (opt-in) fills the cluster
background. Ownership priority: fed qualified-name service > member
service_name > Python ``__module__``. A standalone ErManager must keep
byte-identical output (FR-008).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx import ComposedErManager, ErManager, Relationship
from nexusx.voyager.er_diagram_dot import ErDiagramDotBuilder


def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ── Shared fixture models (both members' entities in ONE Python module —
# exactly the demo situation where Python-module grouping cannot tell the
# engines apart) ────────────────────────────────────────────────────────


class CvBlogBase(SQLModel):
    pass


class CvUser(CvBlogBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str


class CvPost(CvBlogBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    user_id: int | None = Field(default=None, foreign_key="cvuser.id")


class CvShopBase(SQLModel):
    pass


class CvOrder(CvShopBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    total: float = 0.0
    user_id: int | None = Field(default=None, foreign_key="cvuser.id")


# Standalone-baseline entities (FR-008 golden file) — module-level so the
# baseline generator (specs/022-voyager-composed-clusters/make_baseline.py)
# imports the exact same classes and the __module__ context matches.
class CvTb(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str


class CvHr(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str


async def _orders_by_user(user_ids: list[int]) -> list[list[CvOrder]]:
    return [[] for _ in user_ids]


def _composed(
    blog_name: str | None = "blog",
    shop_name: str | None = "shop",
    blog_color: str | None = None,
    shop_color: str | None = None,
) -> ComposedErManager:
    blog_er = ErManager(
        session_factory=_session_factory(),
        base=CvBlogBase,
        service_name=blog_name,
        color=blog_color,
    )
    shop_er = ErManager(
        session_factory=_session_factory(),
        base=CvShopBase,
        service_name=shop_name,
        color=shop_color,
    )
    cross = [
        (
            CvUser,
            Relationship(
                name="orders",
                fk="id",
                target=list[CvOrder],
                loader=_orders_by_user,
            ),
        ),
    ]
    return ComposedErManager(members=[blog_er, shop_er], cross_relationships=cross)


# ── Foundational (FR-009 / FR-008) ─────────────────────────────────────


class TestServiceNameUniqueness:
    def test_duplicate_service_name_raises(self):
        with pytest.raises(ValueError, match="service_name 'blog' is used by multiple"):
            _composed(blog_name="blog", shop_name="blog")

    def test_all_unnamed_members_are_fine(self):
        composed = _composed(blog_name=None, shop_name=None)
        assert composed._member_styling == {}


class TestMemberStylingMapping:
    def test_mapping_covers_entities_with_names_and_colors(self):
        composed = _composed(blog_color="#E3F2FD")
        styling = composed._member_styling
        assert styling[CvUser] == ("blog", "#E3F2FD")
        assert styling[CvPost] == ("blog", "#E3F2FD")
        assert styling[CvOrder] == ("shop", None)  # no color declared

    def test_color_without_service_name_is_ignored(self):
        # color depends on service_name: silently dropped, no error (contract §1)
        composed = _composed(shop_name=None, shop_color="#FF0000")
        styling = composed._member_styling
        assert styling[CvUser][0] == "blog"
        assert CvOrder not in styling


class TestStandaloneManagerUnchanged:
    """FR-008/SC-004 — a standalone ErManager (with or without color) must
    produce byte-identical ER DOT output vs the pre-change baseline."""

    BASELINE = (
        Path(__file__).parent.parent
        / "specs/022-voyager-composed-clusters/baseline_single_er.dot"
    ).read_text()

    def _render(self, color: str | None) -> str:
        er = ErManager(
            session_factory=_session_factory(),
            entities=[CvTb, CvHr],
            color=color,
        )
        builder = ErDiagramDotBuilder(er, show_module=True)
        builder.analysis()
        return builder.render_dot()

    def test_plain_manager_matches_baseline(self):
        assert self._render(None) == self.BASELINE

    def test_colored_manager_also_matches_baseline(self):
        # color is stored but never consumed on the standalone path
        assert self._render("#E3F2FD") == self.BASELINE


# ── US1 — ER diagram clusters by member (FR-003) ──────────────────────


class TestErDiagramMemberClusters:
    def _build(self, composed: ComposedErManager) -> ErDiagramDotBuilder:
        builder = ErDiagramDotBuilder(composed, show_module=True)
        builder.analysis()
        return builder

    def test_entities_cluster_by_service_name(self):
        builder = self._build(_composed())
        by_name = {n.name: n for n in builder.node_set.values()}
        # Both members' entities share one Python module (this test module);
        # member grouping must override it with service_name.
        assert by_name["CvUser"].module == "blog"
        assert by_name["CvPost"].module == "blog"
        assert by_name["CvOrder"].module == "shop"

    def test_dot_contains_two_member_clusters(self):
        dot = self._build(_composed()).render_dot()
        # cluster labels + ids derived from service_name
        assert 'label = "  blog"' in dot
        assert 'label = "  shop"' in dot
        assert "module_blog" in dot
        assert "module_shop" in dot

    def test_cross_engine_edge_spans_two_clusters(self):
        builder = self._build(_composed())
        edge = [
            l for l in builder.links
            if l.source_origin.endswith("CvUser") and l.target_origin.endswith("CvOrder")
        ]
        assert edge, "cross-boundary edge CvUser→CvOrder missing"
        dot = builder.render_dot()
        # the edge source anchor lives in the blog cluster, target in shop
        src_mod = next(n.module for n in builder.node_set.values() if n.name == "CvUser")
        dst_mod = next(n.module for n in builder.node_set.values() if n.name == "CvOrder")
        assert src_mod != dst_mod

    def test_unnamed_members_fall_back_to_python_module(self):
        composed = _composed(blog_name=None, shop_name=None)
        builder = self._build(composed)
        by_name = {n.name: n for n in builder.node_set.values()}
        # Pre-change behavior: Python __module__ grouping
        assert by_name["CvUser"].module == "tests.test_composed_voyager"
        assert by_name["CvOrder"].module == "tests.test_composed_voyager"


# ── US2 — cluster color & background fill (FR-004, opt-in) ─────────────


class TestMemberClusterColors:
    def test_colored_member_cluster_has_fillcolor_and_pencolor(self):
        composed = _composed(blog_color="#E3F2FD")
        builder = ErDiagramDotBuilder(composed, show_module=True)
        builder.analysis()
        dot = builder.render_dot()
        # cluster background fill + border color, same tone
        assert 'fillcolor = "#E3F2FD"' in dot
        assert 'pencolor = "#E3F2FD"' in dot
        # filled style on the member cluster (not dashed — local grouping)
        assert 'style="rounded,filled"' in dot

    def test_uncolored_member_cluster_has_no_fillcolor(self):
        builder = ErDiagramDotBuilder(_composed(), show_module=True)
        builder.analysis()
        dot = builder.render_dot()
        # Opt-in guard: neither member declared a color — no fill anywhere
        assert "fillcolor" not in dot
        assert "pencolor" not in dot

    def test_only_the_colored_member_is_filled(self):
        composed = _composed(blog_color="#E3F2FD")
        builder = ErDiagramDotBuilder(composed, show_module=True)
        builder.analysis()
        dot = builder.render_dot()
        assert dot.count('fillcolor = "#E3F2FD"') == 1  # exactly the blog cluster


# ── US2 (cont.) — composed + federation stacking stays orthogonal ──────

# Materialized remote type (module-level so relationship annotations resolve),
# built the same lightweight way as test_federation_voyager.py.
from nexusx.federation.contract import EntityFragment, FieldDescriptor  # noqa: E402
from nexusx.federation.registry import FederatedTypeRegistry  # noqa: E402

_stacked_reg = FederatedTypeRegistry()
_stacked_reg.record_service_color("reviews", "#3b82f6")
_stacked_reg.materialize({
    "reviews.Review": EntityFragment(
        typename="Review",
        pk_field="id",
        scalar_fields=[
            FieldDescriptor(name="id", type_name="int"),
            FieldDescriptor(name="title", type_name="str"),
        ],
    ),
})
StackedReview = _stacked_reg.get("reviews.Review")


async def _reviews_by_post(post_ids: list[int]) -> list[list[BaseModel]]:
    return [[] for _ in post_ids]


class TestComposedPlusFederationStacking:
    def test_remote_type_and_members_keep_separate_clusters(self):
        # Real federation order: member federates FIRST (remote type
        # materializes into its entity set), THEN gets composed.
        blog_er = ErManager(
            session_factory=_session_factory(),
            base=CvBlogBase,
            service_name="blog",
            color="#E3F2FD",
        )
        blog_er._fed_registry = _stacked_reg
        blog_er.add_virtual_entities([StackedReview])
        shop_er = ErManager(
            session_factory=_session_factory(),
            base=CvShopBase,
            service_name="shop",
        )
        composed = ComposedErManager(members=[blog_er, shop_er])

        builder = ErDiagramDotBuilder(composed, show_module=True)
        builder.analysis()
        by_name = {n.name: n for n in builder.node_set.values()}
        # Remote type keeps federation ownership (service, dashed, its color)…
        assert by_name["Review"].module == "reviews"
        assert by_name["Review"].is_federated is True
        # …member locals keep member grouping — no cross-talk.
        assert by_name["CvUser"].module == "blog"
        assert by_name["CvOrder"].module == "shop"

        dot = builder.render_dot()
        assert 'style="rounded,dashed,filled"' in dot   # reviews (remote)
        assert 'style="rounded,filled"' in dot          # blog (member local)
        assert 'fillcolor = "#3b82f6"' in dot           # reviews color
        assert 'fillcolor = "#E3F2FD"' in dot           # blog color


# ── US3 — UseCase page clusters registered DTOs by member (FR-005) ─────

from nexusx.use_case.business import UseCaseService  # noqa: E402
from nexusx.voyager.use_case_voyager import UseCaseVoyager  # noqa: E402
from nexusx.voyager.voyager_context import VoyagerContext  # noqa: E402
from nexusx import query  # noqa: E402


class CvSummary(BaseModel):
    title: str


class CvMiscSummary(BaseModel):
    label: str


class _CvBlogService(UseCaseService):
    @query
    async def list_posts(cls) -> list[CvSummary]:
        """Registered DTO — owned by the blog member."""

    @query
    async def list_misc(cls) -> list[CvMiscSummary]:
        """Unregistered DTO — keeps Python-module grouping."""


def _member_styling_world():
    member_styling = {
        CvSummary: ("blog", "#E3F2FD"),
        CvUser: ("blog", "#E3F2FD"),
    }
    return member_styling


class TestUseCasePageMemberClusters:
    def test_registered_dto_clusters_by_member(self):
        voyager = UseCaseVoyager(
            [_CvBlogService],
            member_styling=_member_styling_world(),
            show_module=True,
        )
        voyager.analysis()
        by_name = {n.name: n for n in voyager.nodes}
        assert by_name["CvSummary"].module == "blog"
        assert by_name["CvMiscSummary"].module == "tests.test_composed_voyager"

        dot = voyager.render_dot()
        assert 'fillcolor = "#E3F2FD"' in dot  # member color reaches the cluster

    def test_route_nodes_keep_python_module(self):
        voyager = UseCaseVoyager(
            [_CvBlogService],
            member_styling=_member_styling_world(),
            show_module=True,
        )
        voyager.analysis()
        # Routes are service-layer, not data-layer: never member-grouped
        for route in voyager.routes:
            assert route.module == _CvBlogService.__module__

    def test_voyager_context_passes_member_styling_through(self):
        # End-to-end wiring: VoyagerContext probes the composed manager and
        # forwards member_styling into UseCaseVoyager just like fed_registry.
        composed = _composed(blog_color="#E3F2FD")
        composed._members[0]._dto_classes.append(CvSummary)
        ctx = VoyagerContext(services=[_CvBlogService], er_manager=composed)
        voyager = ctx._get_voyager()
        assert voyager._member_styling is not None
        assert voyager._member_styling[CvSummary] == ("blog", "#E3F2FD")


# ── US4 — neighborhood subgraph inherits grouping & colors (FR-007) ────


class TestSubgraphInheritsStyling:
    def test_neighborhood_keeps_both_clusters(self):
        composed = _composed(blog_color="#E3F2FD")
        builder = ErDiagramDotBuilder(composed, show_module=True)
        builder.analysis()
        anchor = next(
            n.id for n in builder.node_set.values() if n.name == "CvUser"
        )
        builder.filter_to_neighborhood(anchor)
        # CvUser + its cross-engine neighbor CvOrder survive the filter —
        # both member clusters and colors must survive with them.
        dot = builder.render_dot()
        assert 'label = "  blog"' in dot
        assert 'label = "  shop"' in dot
        assert 'fillcolor = "#E3F2FD"' in dot
        # the cross-engine edge itself is kept (FR spec US4 scenario)
        assert "CvOrder" in dot and "CvUser" in dot
