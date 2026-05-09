"""RpcVoyager — analyze RPC services and build Tag/Route/SchemaNode/Link graph data.

Converts ServiceIntrospector data into the graph data structures
used by the DOT renderer, following the mapping:
  Service → Tag, Method → Route, DTO → SchemaNode.
"""
from __future__ import annotations

from pydantic import BaseModel

from sqlmodel_nexus.rpc.business import RPC_METHODS_ATTR, RpcService  # noqa: F401
from sqlmodel_nexus.rpc.introspector import ServiceIntrospector
from sqlmodel_nexus.subset import SUBSET_REFERENCE  # noqa: F401
from sqlmodel_nexus.voyager.filter import filter_graph
from sqlmodel_nexus.voyager.render import Renderer
from sqlmodel_nexus.voyager.type import (
    PK,
    CoreData,
    FieldType,
    Link,
    Route,
    SchemaNode,
    Tag,
)
from sqlmodel_nexus.voyager.type_helper import (
    full_class_name,
    get_bases_fields,
    get_core_types,
    get_pydantic_fields,
    get_type_name,
    is_inheritance_of_pydantic_base,
    is_non_pydantic_type,
    update_forward_refs,
)


class RpcVoyager:
    """Analyze RPC services and build graph data structures for DOT rendering.

    Follows the same pattern as fastapi-voyager's Voyager class, but sources
    data from RPC service introspection instead of FastAPI route introspection.
    """

    def __init__(
        self,
        services: list[type[RpcService]],
        *,
        schema: str | None = None,
        schema_field: str | None = None,
        show_fields: FieldType = 'single',
        include_tags: list[str] | None = None,
        module_color: dict[str, str] | None = None,
        route_name: str | None = None,
        hide_primitive_route: bool = False,
        show_module: bool = True,
        theme_color: str | None = None,
    ):
        self.services = services
        self.introspector = ServiceIntrospector(services)

        self.routes: list[Route] = []
        self.nodes: list[SchemaNode] = []
        self.node_set: dict[str, SchemaNode] = {}

        self.link_set: set[tuple[str, str]] = set()
        self.links: list[Link] = []

        self.tag_set: dict[str, Tag] = {}
        self.tags: list[Tag] = []

        self.include_tags = include_tags
        self.schema = schema
        self.schema_field = schema_field
        self.show_fields = show_fields if show_fields in ('single', 'object', 'all') else 'object'
        self.module_color = module_color or {}
        self.route_name = route_name
        self.hide_primitive_route = hide_primitive_route
        self.show_module = show_module
        self.theme_color = theme_color

    def analysis(self) -> None:
        """Analyze all RPC services and build graph data."""
        schemas: list[type[BaseModel]] = []

        for service_cls in self.services:
            service_name = service_cls.__name__
            tag_id = f'tag__{service_name}'
            tag_obj = Tag(id=tag_id, name=service_name, routes=[])
            self.tags.append(tag_obj)
            self.tag_set[tag_id] = tag_obj

            for method_name in getattr(service_cls, RPC_METHODS_ATTR):
                route_id = f'{service_name}.{method_name}'

                if self.route_name is not None and route_id != self.route_name:
                    continue

                method_info = self.introspector._extract_method_info(service_cls, method_name)
                return_anno = method_info.get("_return_anno")

                is_primitive = is_non_pydantic_type(return_anno)
                if self.hide_primitive_route and is_primitive:
                    continue

                # Link: tag → route
                self.links.append(Link(
                    source=tag_id,
                    source_origin=tag_id,
                    target=route_id,
                    target_origin=route_id,
                    type='tag_route',
                ))

                response_schema = get_type_name(return_anno) if return_anno else ''
                route_obj = Route(
                    id=route_id,
                    name=method_name,
                    module=service_cls.__module__,
                    unique_id=method_name,
                    response_schema=response_schema,
                    is_primitive=is_primitive,
                )
                self.routes.append(route_obj)
                tag_obj.routes.append(route_obj)

                # Link: route → response schema (DTO)
                if not is_primitive and return_anno is not None:
                    core_types = get_core_types(return_anno)
                    for anno in core_types:
                        if anno and isinstance(anno, type) and issubclass(anno, BaseModel):
                            target_name = full_class_name(anno)
                            self.links.append(Link(
                                source=route_id,
                                source_origin=route_id,
                                target=self._generate_node_head(target_name),
                                target_origin=target_name,
                                type='route_to_schema',
                            ))
                            schemas.append(anno)

        for s in schemas:
            self._analysis_schemas(s)

        self.nodes = list(self.node_set.values())

    def _generate_node_head(self, link_name: str) -> str:
        return f'{link_name}::{PK}'

    def _add_to_node_set(self, schema: type[BaseModel]) -> str:
        full_name = full_class_name(schema)
        bases_fields = get_bases_fields(
            [s for s in schema.__bases__ if is_inheritance_of_pydantic_base(s)]
        )

        if full_name not in self.node_set:
            self.node_set[full_name] = SchemaNode(
                id=full_name,
                module=schema.__module__,
                name=schema.__name__,
                fields=get_pydantic_fields(schema, bases_fields),
            )
        return full_name

    def _add_to_link_set(
        self,
        source: str,
        source_origin: str,
        target: str,
        target_origin: str,
        type: str,
    ) -> bool:
        pair = (source, target)
        if result := pair not in self.link_set:
            self.link_set.add(pair)
            self.links.append(Link(
                source=source,
                source_origin=source_origin,
                target=target,
                target_origin=target_origin,
                type=type,
            ))
        return result

    def _analysis_schemas(self, schema: type[BaseModel]) -> None:
        """Recursively analyze DTO types and their field relationships."""
        update_forward_refs(schema)
        self._add_to_node_set(schema)

        base_fields: set[str] = set()

        # Handle bases
        for base_class in schema.__bases__:
            if is_inheritance_of_pydantic_base(base_class):
                try:
                    base_fields.update(getattr(base_class, 'model_fields', {}).keys())
                except Exception:
                    pass
                self._add_to_node_set(base_class)
                self._add_to_link_set(
                    source=self._generate_node_head(full_class_name(schema)),
                    source_origin=full_class_name(schema),
                    target=self._generate_node_head(full_class_name(base_class)),
                    target_origin=full_class_name(base_class),
                    type='parent',
                )
                self._analysis_schemas(base_class)

        # Handle DefineSubset source entity
        subset_source = getattr(schema, SUBSET_REFERENCE, None)
        if subset_source is not None:
            self._add_to_node_set(subset_source)
            self._add_to_link_set(
                source=self._generate_node_head(full_class_name(schema)),
                source_origin=full_class_name(schema),
                target=self._generate_node_head(full_class_name(subset_source)),
                target_origin=full_class_name(subset_source),
                type='subset',
            )
            self._analysis_schemas(subset_source)

        # Handle fields
        for k, v in schema.model_fields.items():
            if k in base_fields:
                continue
            annos = get_core_types(v.annotation)
            for anno in annos:
                if anno and isinstance(anno, type) and issubclass(anno, BaseModel):
                    self._add_to_node_set(anno)
                    source_name = f'{full_class_name(schema)}::f{k}'
                    if self._add_to_link_set(
                        source=source_name,
                        source_origin=full_class_name(schema),
                        target=self._generate_node_head(full_class_name(anno)),
                        target_origin=full_class_name(anno),
                        type='schema',
                    ):
                        self._analysis_schemas(anno)

    def dump_core_data(self) -> CoreData:
        _tags, _routes, _nodes, _links = filter_graph(
            schema=self.schema,
            schema_field=self.schema_field,
            tags=self.tags,
            routes=self.routes,
            nodes=self.nodes,
            links=self.links,
            node_set=self.node_set,
        )
        return CoreData(
            tags=_tags,
            routes=_routes,
            nodes=_nodes,
            links=_links,
            show_fields=self.show_fields,
            module_color=self.module_color,
            schema=self.schema,
        )

    def calculate_filtered_tag_and_route(self) -> list[Tag]:
        _tags, _routes, _, _ = filter_graph(
            schema=self.schema,
            schema_field=self.schema_field,
            tags=self.tags,
            routes=self.routes,
            nodes=self.nodes,
            links=self.links,
            node_set=self.node_set,
        )
        route_ids = {r.id for r in _routes}
        for t in _tags:
            t.routes = [r for r in t.routes if r.id in route_ids]
        return _tags

    def render_dot(self) -> str:
        _tags, _routes, _nodes, _links = filter_graph(
            schema=self.schema,
            schema_field=self.schema_field,
            tags=self.tags,
            routes=self.routes,
            nodes=self.nodes,
            links=self.links,
            node_set=self.node_set,
        )

        renderer = Renderer(
            show_fields=self.show_fields,
            module_color=self.module_color,
            schema=self.schema,
            show_module=self.show_module,
            theme_color=self.theme_color,
        )

        _tags, _routes, _links = self._handle_hide(_tags, _routes, _links)
        return renderer.render_dot(_tags, _routes, _nodes, _links)

    def _handle_hide(self, tags, routes, links):
        if self.include_tags:
            return [], routes, [lk for lk in links if lk.type != 'tag_route']
        else:
            return tags, routes, links
