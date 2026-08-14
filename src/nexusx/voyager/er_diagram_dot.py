"""ErDiagramDotBuilder — build DOT graph from ErManager entity/relationship data.

Converts ErManager's SQLModel entity classes and RelationshipInfo
into SchemaNode/Link graph data for the DiagramRenderer.
"""
from __future__ import annotations

import typing

from nexusx.federation.relationship import parse_qualified_name
from nexusx.loader.registry import ErManager, RelationshipInfo
from nexusx.relationship import is_virtual_entity
from nexusx.voyager.render import DiagramRenderer
from nexusx.voyager.type import (
    PK,
    FieldInfo,
    FieldType,
    Link,
    MethodInfo,
    SchemaNode,
)
from nexusx.voyager.type_helper import (
    full_class_name,
    get_type_name,
    update_forward_refs,
)

ARROW = "=>"


def _is_model_like_target(target: type) -> bool:
    """Return True if target can be rendered as a schema node in ER diagram."""
    return hasattr(target, 'model_fields') and hasattr(target, '__name__')


def _get_return_type_name(func) -> str:
    """Extract return type annotation as a readable string."""
    try:
        hints = typing.get_type_hints(func)
        ret = hints.get('return')
        if ret is not None:
            return get_type_name(ret)
    except Exception:
        pass
    return 'Unknown'


def _discover_methods(entity_kls: type) -> tuple[list[MethodInfo], list[MethodInfo]]:
    """Scan entity for @query/@mutation methods, return (queries, mutations)."""
    queries: list[MethodInfo] = []
    mutations: list[MethodInfo] = []
    for attr_name in dir(entity_kls):
        try:
            attr = getattr(entity_kls, attr_name)
        except Exception:
            continue
        if not callable(attr):
            continue
        func = getattr(attr, '__func__', attr)
        if getattr(attr, '_graphql_query', False):
            queries.append(MethodInfo(
                name=func.__name__,
                return_type=_get_return_type_name(func),
            ))
        elif getattr(attr, '_graphql_mutation', False):
            mutations.append(MethodInfo(
                name=func.__name__,
                return_type=_get_return_type_name(func),
            ))
    return queries, mutations


def _is_list_relationship(rel: RelationshipInfo) -> bool:
    """Check if a relationship targets a list."""
    return rel.is_list


class ErDiagramDotBuilder:
    """Build DOT graph data from ErManager's entity registry.

    Usage::

        builder = ErDiagramDotBuilder(er_manager)
        builder.analysis()
        dot = builder.render_dot()
    """

    def __init__(
        self,
        er_manager: ErManager,
        *,
        show_fields: FieldType = 'single',
        show_module: bool = False,
        better_cluster_display: bool = False,
        theme_color: str | None = None,
        edge_minlen: int = 3,
        show_methods: bool = True,
        hide_reverse_relationships: bool = False,
    ):
        self.er_manager = er_manager
        self.nodes: list[SchemaNode] = []
        self.node_set: dict[str, SchemaNode] = {}
        self.links: list[Link] = []
        self.link_set: set[tuple[str, str, str | None]] = set()
        self.rel_name_set: dict[str, dict[str, RelationshipInfo]] = {}

        self.show_field = show_fields
        self.show_module = show_module
        self.better_cluster_display = better_cluster_display
        self.theme_color = theme_color
        self.edge_minlen = edge_minlen
        self.show_methods = show_methods
        self.hide_reverse_relationships = hide_reverse_relationships
        # ComposedErManager member grouping (specs/022): cls → (service_name,
        # color). Duck-typed probe — a standalone ErManager has no such
        # attribute, so member grouping stays inactive (FR-008).
        self._member_styling: dict[type, tuple[str, str | None]] | None = (
            getattr(er_manager, "_member_styling", None)
        )

    def _generate_node_head(self, link_name: str) -> str:
        return f'{link_name}::{PK}'

    def analysis(self) -> None:
        """Analyze all entities and relationships from ErManager."""
        entities = self.er_manager.get_all_entities()
        all_relationships = self.er_manager.get_all_relationships()

        # Build relationship map per entity (replaces fk_set)
        self.rel_name_set: dict[str, dict[str, RelationshipInfo]] = {}
        for entity_kls in entities:
            entity_name = full_class_name(entity_kls)
            rels = all_relationships.get(entity_kls, {})
            self.rel_name_set[entity_name] = rels

        # Create SchemaNodes for each entity
        for entity_kls in entities:
            update_forward_refs(entity_kls)
            self._add_to_node_set(entity_kls)

        # Create Links for each relationship
        for entity_kls, rels in all_relationships.items():
            for _rel_name, rel_info in rels.items():
                self._add_relationship_link(entity_kls, rel_info)

    def _add_to_node_set(self, entity_kls: type) -> str:
        full_name = full_class_name(entity_kls)

        if full_name not in self.node_set:
            # Extract fields from model_fields
            fields = self._get_entity_fields(entity_kls)
            queries, mutations = _discover_methods(entity_kls)
            # Federation ownership: a materialized remote type has a qualified
            # name ("srv.TypeName") in the fed_registry; local SQLModel and
            # genuine virtual entities resolve to None.
            fed_reg = getattr(self.er_manager, "_fed_registry", None)
            fed_qn = fed_reg.qualified_of(entity_kls) if fed_reg is not None else None
            # A materialized remote type is a REAL entity (its table lives in
            # another service), so it must never render as virtual. Genuine
            # virtuals (qualified_of is None) keep is_virtual_entity's verdict.
            is_virtual = is_virtual_entity(entity_kls) and not fed_qn
            # module = cluster key. Priority (specs/022 FR-003):
            #   1. federation qualified name → owning remote service (FR-016)
            #   2. ComposedErManager member grouping → service_name (FR-002)
            #   3. Python __module__ (pre-change default)
            if fed_qn:
                module = parse_qualified_name(fed_qn)[0]
            elif self._member_styling and entity_kls in self._member_styling:
                module = self._member_styling[entity_kls][0]
            else:
                module = entity_kls.__module__

            self.node_set[full_name] = SchemaNode(
                id=full_name,
                module=module,
                name=entity_kls.__name__,
                fields=fields,
                queries=queries,
                mutations=mutations,
                is_virtual=is_virtual,
                is_federated=bool(fed_qn),
            )
        return full_name

    def _get_entity_fields(self, entity_kls: type) -> list[FieldInfo]:
        """Extract fields from an entity class's model_fields and relationships."""
        full_name = full_class_name(entity_kls)
        rels = self.rel_name_set.get(full_name, {})
        rel_names = set(rels.keys())

        fields: list[FieldInfo] = []

        # 1. Add regular model fields (skip relationship field names)
        for k, v in entity_kls.model_fields.items():
            if k in rel_names:
                continue
            anno = v.annotation
            fields.append(FieldInfo(
                is_object=False,
                name=k,
                from_base=False,
                type_name=get_type_name(anno),
                is_exclude=bool(v.exclude),
                desc=getattr(v, 'description', None) or '',
            ))

        # 2. Add relationship fields (name + target type)
        for rel_name, rel_info in rels.items():
            if not _is_model_like_target(rel_info.target_entity):
                continue
            target_type = rel_info.target_entity.__name__
            type_name = f'list[{target_type}]' if rel_info.is_list else target_type
            fields.append(FieldInfo(
                is_object=True,
                name=rel_name,
                from_base=False,
                type_name=type_name,
                is_exclude=False,
                desc=getattr(rel_info, 'description', None) or '',
            ))

        return fields

    def _add_relationship_link(
        self,
        entity_kls: type,
        rel_info: RelationshipInfo,
    ) -> None:
        """Add a Link for a single relationship."""
        if not _is_model_like_target(rel_info.target_entity):
            return

        # Spec 007 — Hide Reverse Relationships mode: skip ONETOMANY reverse
        # mirrors. MANYTOONE (FK-holder side) and MANYTOMANY (through table)
        # are preserved. See specs/007-voyager-er-pure-fk/spec.md FR-005/FR-006.
        if self.hide_reverse_relationships and rel_info.direction == 'ONETOMANY':
            return

        source_name = full_class_name(entity_kls)
        target_name = full_class_name(rel_info.target_entity)

        # Ensure target node exists
        self._add_to_node_set(rel_info.target_entity)

        # Build label with cardinality
        cardinality = f'1 {ARROW} N' if rel_info.is_list else f'1 {ARROW} 1'
        label = f'{rel_info.name}\n{cardinality}'

        # Build source anchor from relationship name field
        source_anchor = f'{source_name}::f{rel_info.name}'

        # Check for duplicates
        biz = rel_info.name
        pair = (source_anchor, self._generate_node_head(target_name), biz)
        if pair in self.link_set:
            return
        self.link_set.add(pair)

        self.links.append(Link(
            source=source_anchor,
            source_origin=source_name,
            target=self._generate_node_head(target_name),
            target_origin=target_name,
            type='schema',
            label=label,
            style='solid',
            loader_fullname=None,
        ))

    def _federation_styling(self) -> tuple[dict[str, str], set[str]]:
        """Derive (module_color, federated_modules) for remote-service clusters.

        Colors come ONLY from declared ``RemoteService(color=...)`` (collected
        into the fed_registry during federate) — opt-in, no auto-palette. A
        service without a declared color renders dashed but uncolored.
        ``federated_modules`` is the set of ALL remote service names — every
        remote cluster is dashed to mark the service boundary.

        specs/022: member colors (``ErManager(color=...)`` via
        ``ComposedErManager._member_styling``) merge underneath — a member
        name colliding with a remote service name keeps the federation color
        (remote ownership wins, mirroring FR-003's module priority).
        """
        fed_reg = getattr(self.er_manager, "_fed_registry", None)
        services: set[str] = set()
        if fed_reg is not None:
            for cls in fed_reg.all_classes():
                qn = fed_reg.qualified_of(cls)
                if qn:
                    services.add(parse_qualified_name(qn)[0])

        module_color = fed_reg.service_colors() if fed_reg is not None else {}
        if self._member_styling:
            member_colors: dict[str, str] = {}
            for name, color in self._member_styling.values():
                if color:
                    member_colors[name] = color
            module_color = {**member_colors, **module_color}
        return module_color, services

    def render_dot(self) -> str:
        """Render the ER diagram as DOT format."""
        module_color, federated_modules = self._federation_styling()
        renderer = DiagramRenderer(
            show_fields=self.show_field,
            show_module=self.show_module,
            better_cluster_display=self.better_cluster_display,
            theme_color=self.theme_color,
            edge_minlen=self.edge_minlen,
            show_methods=self.show_methods,
            module_color=module_color,
            federated_modules=federated_modules,
        )
        return renderer.render_dot(
            list(self.node_set.values()),
            self.links,
        )

    def filter_to_neighborhood(self, schema_name: str) -> None:
        """Narrow the built graph to ``schema_name`` + its direct neighbors + the
        edges incident to ``schema_name``. Call this AFTER :meth:`analysis`.

        Spec 005 FR-002 / FR-014 — the result is the "Related Entities" sub-graph
        rendered in the sidebar tab. Mutates ``node_set`` / ``links`` / ``link_set``
        in place.

        - Unknown ``schema_name`` (not in ``node_set``): everything is cleared so
          the caller produces an observably empty result.
        - Isolated entity (no incident edges): ``node_set`` keeps only
          ``schema_name`` itself; ``links`` becomes empty. (FR-005.)
        - Self-references (``X → X``) and parallel edges are preserved. (FR-010.)
        - Edges between two *neighbors* (neither endpoint is ``schema_name``) are
          excluded — the sub-graph shows relationships OF the selected entity, not
          relationships among its neighborhood.
        """
        if schema_name not in self.node_set:
            self.node_set = {}
            self.links = []
            self.link_set = set()
            return

        kept_links: list[Link] = []
        for link in self.links:
            if link.source_origin == schema_name or link.target_origin == schema_name:
                kept_links.append(link)

        neighbor_ids: set[str] = {schema_name}
        for link in kept_links:
            neighbor_ids.add(link.source_origin)
            neighbor_ids.add(link.target_origin)

        self.node_set = {
            nid: node for nid, node in self.node_set.items() if nid in neighbor_ids
        }
        self.links = kept_links
        # link_set is only consulted during analysis() for dedup; reset to stay consistent.
        self.link_set = set()
