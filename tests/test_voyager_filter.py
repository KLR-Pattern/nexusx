"""Tests for voyager graph-filtering pure functions (filter.py).

``filter_graph`` focuses the tag/route/schema graph on one schema node and its
reachable neighborhood; ``filter_subgraph_by_module_prefix`` (and its
tag-to-schema variant) collapse the graph so routes/tags link directly to
nodes whose module matches a prefix. All are pure list-in/list-out functions
migrated from fastapi-voyager — these tests pin their mechanical behavior.

Graph shape used across the tests (unless noted):

    Tag T ──tag_route──> Route R ──route_to_schema──> A
    A ──schema──> B ──parent──> C        (D is isolated)

``parent``/``subset`` links flow source → target where the TARGET is the
more general node: the schema_field walk climbs from targets to sources.
"""

from nexusx.voyager.filter import (
    filter_graph,
    filter_subgraph_by_module_prefix,
    filter_subgraph_from_tag_to_schema_by_module_prefix,
)
from nexusx.voyager.type import FieldInfo, Link, Route, SchemaNode, Tag


def _node(nid: str, module: str = "m", field_names: tuple[str, ...] = ("id",)) -> SchemaNode:
    return SchemaNode(
        id=nid,
        name=nid,
        module=module,
        fields=[FieldInfo(name=n, type_name="String") for n in field_names],
    )


def _link(src: str, tgt: str, type_: str) -> Link:
    return Link(
        source=f"{src}::PK",
        target=f"{tgt}::PK",
        source_origin=src,
        target_origin=tgt,
        type=type_,  # type: ignore[arg-type]
    )


def _base_graph():
    """Tag → Route → A → B → C, plus isolated D and a Tag sharing A's id-space."""
    nodes = [
        _node("A", module="app.models"),
        _node("B", module="app.models", field_names=("id", "owner")),
        _node("C", module="app.core", field_names=("id", "owner", "base")),
        _node("D", module="app.other"),
    ]
    routes = [Route(id="R", name="list_a", module="app.routes")]
    tags = [Tag(id="T", name="tag_t", routes=routes)]
    links = [
        _link("T", "R", "tag_route"),
        _link("R", "A", "route_to_schema"),
        _link("A", "B", "schema"),
        _link("B", "C", "parent"),
        _link("D", "D", "schema"),
    ]
    node_set = {n.id: n for n in nodes}
    return tags, routes, nodes, links, node_set


class TestFilterGraph:
    def test_schema_none_passthrough(self):
        tags, routes, nodes, links, node_set = _base_graph()
        out = filter_graph(
            schema=None, schema_field=None,
            tags=tags, routes=routes, nodes=nodes, links=links, node_set=node_set,
        )
        assert out == (tags, routes, nodes, links)

    def test_unknown_schema_passthrough(self):
        tags, routes, nodes, links, node_set = _base_graph()
        out = filter_graph(
            schema="NOPE", schema_field=None,
            tags=tags, routes=routes, nodes=nodes, links=links, node_set=node_set,
        )
        assert out == (tags, routes, nodes, links)

    def test_seed_keeps_reachable_neighborhood(self):
        """Seed A: downstream B, C; upstream reaches R (via route_to_schema
        R→A) even though R is a Route — the closure works on ids, while
        out_nodes only re-filters the INPUT nodes list."""
        tags, routes, nodes, links, node_set = _base_graph()
        out_tags, out_routes, out_nodes, out_links = filter_graph(
            schema="A", schema_field=None,
            tags=tags, routes=routes, nodes=nodes, links=links, node_set=node_set,
        )
        node_ids = {n.id for n in out_nodes}
        # A + downstream (B, C); D excluded (isolated). The closure is
        # transitive: R joins via R→A, then T joins via T→R — but out_nodes
        # only re-filters the INPUT nodes list (R/T are Route/Tag).
        assert node_ids == {"A", "B", "C"}
        # links kept only when BOTH endpoints are in the closure — the whole
        # T→R→A chain survives; only D's self-link is dropped.
        kept = {(lk.source_origin, lk.target_origin, lk.type) for lk in out_links}
        assert ("A", "B", "schema") in kept
        assert ("B", "C", "parent") in kept
        assert ("T", "R", "tag_route") in kept
        assert ("R", "A", "route_to_schema") in kept
        assert ("D", "D", "schema") not in kept
        # routes/tags filtered by membership in the closure (R and T both in)
        assert [r.id for r in out_routes] == ["R"]
        assert [t.id for t in out_tags] == ["T"]

    def test_schema_field_climbs_parents_having_the_field(self):
        """With schema_field, the parent/subset walk only accepts sources that
        actually declare the field — C (has `base`) is reached, a field-less
        chain stops early."""
        tags, routes, nodes, links, node_set = _base_graph()
        out_tags, out_routes, out_nodes, out_links = filter_graph(
            schema="C", schema_field="owner",
            tags=tags, routes=routes, nodes=nodes, links=links, node_set=node_set,
        )
        node_ids = {n.id for n in out_nodes}
        # parent link B→C: B declares `owner` → accepted and traversed up.
        # B→C is parent; A→B is `schema` type — NOT in the parent/subset walk.
        assert "B" in node_ids
        assert "C" in node_ids
        # non-parent/subset links pass through the neighborhood filter
        kept = {(lk.source_origin, lk.target_origin) for lk in out_links}
        assert ("B", "C") in kept

    def test_schema_field_missing_on_source_stops_walk(self):
        """Same graph, but the field exists nowhere on B → B stays out."""
        tags, routes, nodes, links, node_set = _base_graph()
        # B declares ("id", "owner") — use a field no node declares.
        out_tags, out_routes, out_nodes, out_links = filter_graph(
            schema="C", schema_field="nonexistent",
            tags=tags, routes=routes, nodes=nodes, links=links, node_set=node_set,
        )
        node_ids = {n.id for n in out_nodes}
        assert node_ids == {"C"}
        assert out_links == []


class TestFilterSubgraphByModulePrefix:
    def test_empty_prefix_keeps_route_links_only(self):
        tags, routes, nodes, links, node_set = _base_graph()
        out_tags, out_routes, out_nodes, out_links = filter_subgraph_by_module_prefix(
            tags=tags, routes=routes, links=links, nodes=nodes, module_prefix="",
        )
        assert out_nodes == nodes  # unfiltered
        kept_types = {lk.type for lk in out_links}
        assert kept_types == {"tag_route", "route_to_schema"}

    def test_prefix_collapses_route_onto_matching_nodes(self):
        """Route R → A (module app.models): with prefix "app.models", R links
        directly to A; C (app.core) is dropped; module-internal links kept."""
        tags, routes, nodes, links, node_set = _base_graph()
        out_tags, out_routes, out_nodes, out_links = filter_subgraph_by_module_prefix(
            tags=tags, routes=routes, links=links, nodes=nodes,
            module_prefix="app.models",
        )
        assert {n.id for n in out_nodes} == {"A", "B"}  # module match only
        merged = [lk for lk in out_links if lk.type == "route_to_schema"]
        assert [(lk.source_origin, lk.target_origin) for lk in merged] == [("R", "A")]
        # tag_route links survive the merge
        assert any(lk.type == "tag_route" for lk in out_links)

    def test_prefix_traverses_through_non_matching_nodes(self):
        """R → A where A's module does NOT match, but A --schema--> B does:
        BFS through A lands on B, so R links directly to B."""
        nodes = [_node("A", module="outside"), _node("B", module="inside")]
        links = [
            _link("R", "A", "route_to_schema"),
            _link("A", "B", "schema"),
        ]
        _tags, _routes, out_nodes, out_links = filter_subgraph_by_module_prefix(
            tags=[], routes=[Route(id="R", name="r", module="m")],
            links=links, nodes=nodes, module_prefix="inside",
        )
        assert {n.id for n in out_nodes} == {"B"}
        merged = [lk for lk in out_links if lk.type == "route_to_schema"]
        assert [(lk.source_origin, lk.target_origin) for lk in merged] == [("R", "B")]

    def test_unreachable_route_endpoint_dropped(self):
        """Route pointing at a node absent from node_lookup → no merged link."""
        nodes = [_node("B", module="inside")]
        links = [
            _link("R", "GHOST", "route_to_schema"),  # GHOST not in nodes
        ]
        _tags, _routes, _out_nodes, out_links = filter_subgraph_by_module_prefix(
            tags=[], routes=[Route(id="R", name="r", module="m")],
            links=links, nodes=nodes, module_prefix="inside",
        )
        assert [lk for lk in out_links if lk.type == "route_to_schema"] == []


class TestFilterSubgraphFromTagToSchemaByModulePrefix:
    def test_empty_prefix_keeps_route_links_only(self):
        tags, routes, nodes, links, node_set = _base_graph()
        out_tags, out_routes, out_nodes, out_links = (
            filter_subgraph_from_tag_to_schema_by_module_prefix(
                tags=tags, routes=routes, links=links, nodes=nodes, module_prefix="",
            )
        )
        assert out_nodes == nodes
        assert out_routes == routes  # empty prefix keeps routes (non-brief shape)
        kept_types = {lk.type for lk in out_links}
        assert kept_types == {"tag_route", "route_to_schema"}

    def test_prefix_links_tag_directly_to_nodes(self):
        """Tag T → Route R → A: with matching prefix, T links STRAIGHT to A
        (type tag_to_schema); routes vanish from the result."""
        tags, routes, nodes, links, node_set = _base_graph()
        out_tags, out_routes, out_nodes, out_links = (
            filter_subgraph_from_tag_to_schema_by_module_prefix(
                tags=tags, routes=routes, links=links, nodes=nodes,
                module_prefix="app.models",
            )
        )
        assert out_routes == []
        assert {n.id for n in out_nodes} == {"A", "B"}
        merged = [lk for lk in out_links if lk.type == "tag_to_schema"]
        assert [(lk.source_origin, lk.target_origin) for lk in merged] == [("T", "A")]

    def test_prefix_traverses_route_then_schema_edges(self):
        """T → R (route) → A (outside) → B (inside): tag lands on B."""
        nodes = [_node("A", module="outside"), _node("B", module="inside")]
        routes = [Route(id="R", name="r", module="outside")]
        links = [
            _link("T", "R", "tag_route"),
            _link("R", "A", "route_to_schema"),
            _link("A", "B", "schema"),
        ]
        _tags, out_routes, out_nodes, out_links = (
            filter_subgraph_from_tag_to_schema_by_module_prefix(
                tags=[Tag(id="T", name="t", routes=routes)], routes=routes,
                links=links, nodes=nodes, module_prefix="inside",
            )
        )
        assert out_routes == []
        merged = [lk for lk in out_links if lk.type == "tag_to_schema"]
        assert [(lk.source_origin, lk.target_origin) for lk in merged] == [("T", "B")]
