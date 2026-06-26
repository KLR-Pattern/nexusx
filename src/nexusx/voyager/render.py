"""Render application structure to DOT format using Jinja2 templates.

Migrated from fastapi-voyager, with DiagramRenderer included.
"""
import logging
from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader, select_autoescape

from nexusx.voyager.module import build_module_route_tree, build_module_schema_tree
from nexusx.voyager.render_style import RenderConfig
from nexusx.voyager.type import (
    PK,
    FieldInfo,
    FieldType,
    Link,
    MethodInfo,
    ModuleNode,
    ModuleRoute,
    Route,
    SchemaNode,
    Tag,
)

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"


class TemplateRenderer:
    """Jinja2-based template renderer for DOT and HTML templates."""

    def __init__(self, template_dir: Path = TEMPLATE_DIR):
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render_template(self, template_name: str, **context) -> str:
        """Render a template with the given context."""
        template = self.env.get_template(template_name)
        return template.render(**context)


class Renderer:
    """Render application structure to DOT format.

    Handles the conversion of tags, routes, schemas, and links
    into Graphviz DOT format.
    """

    def __init__(
        self,
        *,
        show_fields: FieldType = 'single',
        module_color: dict[str, str] | None = None,
        schema: str | None = None,
        show_module: bool = True,
        show_pydantic_resolve_meta: bool = False,
        config: RenderConfig | None = None,
        theme_color: str | None = None,
        show_methods: bool = True,
    ) -> None:
        self.show_fields = show_fields if show_fields in ('single', 'object', 'all') else 'single'
        self.module_color = module_color or {}
        self.schema = schema
        self.show_module = show_module
        self.show_pydantic_resolve_meta = show_pydantic_resolve_meta
        self.show_methods = show_methods

        self.config = config or RenderConfig()
        self.colors = self.config.colors
        self.style = self.config.style

        self.theme_color = theme_color or self.colors.primary

        self.template_renderer = TemplateRenderer()

    def _render_pydantic_meta_parts(self, field: FieldInfo) -> list[str]:
        """Render pydantic-resolve metadata as HTML parts."""
        if not self.show_pydantic_resolve_meta:
            return []

        parts = []
        if field.is_resolve:
            parts.append(
                self.template_renderer.render_template(
                    'html/colored_text.j2',
                    text='● resolve',
                    color=self.colors.resolve
                )
            )
        if field.is_post:
            parts.append(
                self.template_renderer.render_template(
                    'html/colored_text.j2',
                    text='● post',
                    color=self.colors.post
                )
            )
        if field.expose_as_info:
            parts.append(
                self.template_renderer.render_template(
                    'html/colored_text.j2',
                    text=f'● expose as: {field.expose_as_info}',
                    color=self.colors.expose_as
                )
            )
        if field.send_to_info:
            to_collectors = ', '.join(field.send_to_info)
            parts.append(
                self.template_renderer.render_template(
                    'html/colored_text.j2',
                    text=f'● send to: {to_collectors}',
                    color=self.colors.send_to
                )
            )
        if field.collect_info:
            defined_collectors = ', '.join(field.collect_info)
            parts.append(
                self.template_renderer.render_template(
                    'html/colored_text.j2',
                    text=f'● collectors: {defined_collectors}',
                    color=self.colors.collector
                )
            )

        return parts

    def _render_schema_field(
        self,
        field: FieldInfo,
        max_type_length: int | None = None
    ) -> str:
        """Render a single schema field."""
        max_len = max_type_length or self.config.max_type_length

        type_name = field.type_name
        if len(type_name) > max_len:
            type_name = type_name[:max_len] + self.config.type_suffix

        field_text = f'{field.name}: {type_name}'

        meta_parts = self._render_pydantic_meta_parts(field)
        meta_html = self.template_renderer.render_template(
            'html/pydantic_meta.j2',
            meta_parts=meta_parts
        )

        text_html = self.template_renderer.render_template(
            'html/colored_text.j2',
            text=field_text,
            color='#000',
            strikethrough=field.is_exclude
        )

        content = f'<font>  {text_html}  </font> {meta_html}'

        return self.template_renderer.render_template(
            'html/schema_field_row.j2',
            port=field.name,
            align='left',
            content=content
        )

    def _render_schema_method(self, method: MethodInfo, type: Literal['query', 'mutation']) -> str:
        """Render a single method row."""
        prefix = '[Q]' if type == 'query' else '[M]'
        color = self.colors.query if type == 'query' else self.colors.mutation

        return_type = method.return_type
        if len(return_type) > self.config.max_type_length:
            return_type = return_type[:self.config.max_type_length] + self.config.type_suffix

        method_text = f'{prefix} {method.name}: {return_type}'

        text_html = self.template_renderer.render_template(
            'html/colored_text.j2',
            text=method_text,
            color=color
        )

        content = f'<font>  {text_html}  </font>'

        return self.template_renderer.render_template(
            'html/schema_field_row.j2',
            port=None,
            align='left',
            content=content
        )

    def _get_filtered_fields(self, node: SchemaNode) -> list[FieldInfo]:
        """Get fields filtered by show_fields setting."""
        if self.show_pydantic_resolve_meta:
            fields = [n for n in node.fields if n.has_pydantic_resolve_meta or not n.from_base]
        else:
            fields = [n for n in node.fields if not n.from_base]

        if self.show_fields == 'all':
            return fields
        elif self.show_fields == 'object':
            if self.show_pydantic_resolve_meta:
                return [f for f in fields if f.is_object or f.has_pydantic_resolve_meta]
            else:
                return [f for f in fields if f.is_object]
        else:  # 'single'
            return []

    def render_schema_label(self, node: SchemaNode, color: str | None = None) -> str:
        """Render a schema node's label as an HTML table."""
        fields = self._get_filtered_fields(node)

        rows = []
        has_base_fields = any(f.from_base for f in node.fields)

        if self.show_fields == 'all' and has_base_fields:
            notice = self.template_renderer.render_template(
                'html/colored_text.j2',
                text='  Inherited Fields ... ',
                color=self.colors.text_gray
            )
            rows.append(
                self.template_renderer.render_template(
                    'html/schema_field_row.j2',
                    content=notice,
                    align='left'
                )
            )

        for field in fields:
            rows.append(self._render_schema_field(field))

        if self.show_methods and (node.queries or node.mutations):
            for method in node.queries:
                rows.append(self._render_schema_method(method, type='query'))
            for method in node.mutations:
                rows.append(self._render_schema_method(method, type='mutation'))

        default_color = self.theme_color if color is None else color
        header_color = self.colors.highlight if node.id == self.schema else default_color
        header_text = node.name
        text_color = 'white'

        # Contract 3 visual distinction for non-SQLModel (virtual) roots:
        # yellow fill, «virtual» UML stereotype prefix, dark text (yellow is
        # too light for white text to remain legible).
        if getattr(node, 'is_virtual', False):
            header_color = self.colors.virtual_fill
            header_text = f'«virtual»\\n{node.name}'
            text_color = '#000'

        header = self.template_renderer.render_template(
            'html/schema_header.j2',
            text=header_text,
            bg_color=header_color,
            text_color=text_color,
            port=PK,
            is_entity=node.is_entity
        )

        return self.template_renderer.render_template(
            'html/schema_table.j2',
            header=header,
            rows=''.join(rows)
        )

    def _handle_schema_anchor(self, source: str) -> str:
        """Handle schema anchor for DOT links."""
        if '::' in source:
            a, b = source.split('::', 1)
            return f'"{a}":{b}'
        return f'"{source}"'

    def _format_link_attributes(self, attrs: dict) -> str:
        """Format link attributes for DOT format."""
        return ', '.join(f'{k}="{v}"' for k, v in attrs.items())

    def render_link(self, link: Link) -> str:
        """Render a link in DOT format."""
        source = self._handle_schema_anchor(link.source)
        target = self._handle_schema_anchor(link.target)

        if link.style is not None:
            attrs = {'style': link.style}
            if link.label:
                attrs['label'] = link.label
        else:
            attrs = self.style.get_link_attributes(link.type)
            if link.label:
                attrs['label'] = link.label

        return self.template_renderer.render_template(
            'dot/link.j2',
            source=source,
            target=target,
            attributes=self._format_link_attributes(attrs)
        )

    def render_schema_node(self, node: SchemaNode, color: str | None = None) -> str:
        """Render a schema node in DOT format."""
        label = self.render_schema_label(node, color)

        return self.template_renderer.render_template(
            'dot/schema_node.j2',
            id=node.id,
            label=label,
            margin=self.style.node_margin
        )

    def render_tag_node(self, tag: Tag) -> str:
        """Render a tag node in DOT format."""
        return self.template_renderer.render_template(
            'dot/tag_node.j2',
            id=tag.id,
            name=tag.name,
            margin=self.style.node_margin
        )

    def render_route_node(self, route: Route) -> str:
        """Render a route node in DOT format."""
        response_schema = route.response_schema
        if len(response_schema) > self.config.max_type_length:
            response_schema = (
                response_schema[:self.config.max_type_length]
                + self.config.type_suffix
            )

        return self.template_renderer.render_template(
            'dot/route_node.j2',
            id=route.id,
            name=route.name,
            response_schema=response_schema,
            margin=self.style.node_margin
        )

    def _render_module_schema(
        self,
        mod: ModuleNode,
        module_color_flag: set[str],
        inherit_color: str | None = None,
        show_cluster: bool = True
    ) -> str:
        """Render a module schema tree."""
        color = inherit_color
        cluster_color: str | None = None

        for k in module_color_flag:
            if mod.fullname.startswith(k):
                module_color_flag.remove(k)
                color = self.module_color[k]
                cluster_color = color if color != inherit_color else None
                break

        inner_nodes = [
            self.render_schema_node(node, color)
            for node in mod.schema_nodes
        ]
        inner_nodes_str = '\n'.join(inner_nodes)

        child_str = '\n'.join(
            self._render_module_schema(
                m,
                module_color_flag=module_color_flag,
                inherit_color=color,
                show_cluster=show_cluster
            )
            for m in mod.modules
        )

        if show_cluster:
            cluster_id = f'module_{mod.fullname.replace(".", "_")}'
            pen_style = ''

            if cluster_color:
                pen_style = f'pencolor = "{cluster_color}"'
                pen_style += '\n' + 'penwidth = 3' if color else ''
            else:
                pen_style = 'pencolor="#ccc"'

            return self.template_renderer.render_template(
                'dot/cluster.j2',
                cluster_id=cluster_id,
                label=mod.name,
                tooltip=mod.fullname,
                border_color=self.colors.border,
                pen_color=cluster_color,
                pen_width=3 if color and not cluster_color else None,
                content=f'{inner_nodes_str}\n{child_str}'
            )
        else:
            return f'{inner_nodes_str}\n{child_str}'

    def render_module_schema_content(self, nodes: list[SchemaNode]) -> str:
        """Render all module schemas."""
        module_schemas = build_module_schema_tree(nodes)
        module_color_flag = set(self.module_color.keys())

        return '\n'.join(
            self._render_module_schema(
                m,
                module_color_flag=module_color_flag,
                show_cluster=self.show_module
            )
            for m in module_schemas
        )

    def _render_module_route(self, mod: ModuleRoute, show_cluster: bool = True) -> str:
        """Render a module route tree."""
        inner_nodes = [self.render_route_node(r) for r in mod.routes]
        inner_nodes_str = '\n'.join(inner_nodes)

        child_str = '\n'.join(
            self._render_module_route(m, show_cluster=show_cluster)
            for m in mod.modules
        )

        if show_cluster:
            cluster_id = f'route_module_{mod.fullname.replace(".", "_")}'

            return self.template_renderer.render_template(
                'dot/cluster.j2',
                cluster_id=cluster_id,
                label=mod.name,
                tooltip=mod.fullname,
                border_color=self.colors.border,
                pen_color=None,
                pen_width=None,
                content=f'{inner_nodes_str}\n{child_str}'
            )
        else:
            return f'{inner_nodes_str}\n{child_str}'

    def render_module_route_content(self, routes: list[Route]) -> str:
        """Render all module routes."""
        module_routes = build_module_route_tree(routes)

        return '\n'.join(
            self._render_module_route(m, show_cluster=self.show_module)
            for m in module_routes
        )

    def _render_cluster_container(
        self,
        name: str,
        label: str,
        content: str,
        fontsize: str | None = None
    ) -> str:
        """Render a cluster container."""
        return self.template_renderer.render_template(
            'dot/cluster_container.j2',
            name=name,
            label=label,
            content=content,
            border_color=self.colors.border,
            margin=self.style.cluster_margin,
            fontsize=fontsize or self.style.cluster_fontsize
        )

    def render_service_clusters(self, tags: list[Tag]) -> str:
        """Render each tag (service) as a cluster containing its routes.

        When multiple services are present (no tag filter), wrap them in a
        parent "Services" cluster. Service clusters are always rendered and
        are not affected by the show_module toggle.
        """
        parts = []
        for tag in tags:
            route_strs = '\n'.join(self.render_route_node(r) for r in tag.routes)
            cluster = self._render_cluster_container(
                name=f'service_{tag.name}',
                label=tag.name,
                content=route_strs,
            )
            parts.append(cluster)

        inner = '\n'.join(parts)
        if len(tags) > 1:
            return self._render_cluster_container(
                name='services',
                label='Services',
                content=inner,
            )
        return inner

    def render_dot(
        self,
        tags: list[Tag],
        routes: list[Route],
        nodes: list[SchemaNode],
        links: list[Link],
        spline_line: bool = False
    ) -> str:
        """Render the complete DOT graph.

        Layout: each service (tag) is rendered as a cluster containing its
        methods (routes), followed by a schema cluster. Service clusters are
        always present regardless of the show_module setting.
        """
        service_clusters = self.render_service_clusters(tags)

        module_schemas_str = self.render_module_schema_content(nodes)
        schemas_cluster = self._render_cluster_container(
            name='schema',
            label='Schema',
            content=module_schemas_str
        )

        link_str = '\n'.join(self.render_link(link) for link in links)

        return self.template_renderer.render_template(
            'dot/digraph.j2',
            pad=self.style.pad,
            nodesep=self.style.nodesep,
            spline='line' if spline_line else '',
            font=self.style.font,
            node_fontsize=self.style.node_fontsize,
            tags_cluster=service_clusters,
            routes_cluster='',
            schemas_cluster=schemas_cluster,
            links=link_str
        )


class DiagramRenderer(Renderer):
    """Renderer for Entity-Relationship diagrams.

    Inherits from Renderer to reuse template system and styling.
    ER diagrams have simpler structure (no tags/routes).
    """

    def __init__(
        self,
        *,
        show_fields: FieldType = 'single',
        show_module: bool = True,
        theme_color: str | None = None,
        edge_minlen: int = 3,
        show_methods: bool = True,
    ) -> None:
        super().__init__(
            show_fields=show_fields,
            show_module=show_module,
            config=RenderConfig(),
            theme_color=theme_color,
            show_methods=show_methods,
        )
        self.edge_minlen = edge_minlen

    def render_link(self, link: Link) -> str:
        """Override link rendering for ER diagrams."""
        source = self._handle_schema_anchor(link.source)
        target = self._handle_schema_anchor(link.target)

        if link.style is not None:
            attrs = {'style': link.style}
            if link.label:
                attrs['label'] = link.label
            attrs['minlen'] = self.edge_minlen
        else:
            attrs = self.style.get_link_attributes(link.type)
            if link.label:
                attrs['label'] = link.label

        return self.template_renderer.render_template(
            'dot/link.j2',
            source=source,
            target=target,
            attributes=self._format_link_attributes(attrs)
        )

    def render_dot(
        self, nodes: list[SchemaNode], links: list[Link],
        spline_line: bool = False,
    ) -> str:
        """Render ER diagram as DOT format.

        Virtual nodes (``SchemaNode.is_virtual=True``, set by
        ``ErDiagramDotBuilder`` for plain BaseModel classes registered via
        ``ErManager.add_virtual_entities()``) are grouped into a separate
        ``cluster_virtual`` subgraph with a dashed border and yellow fill,
        per Contract 3 of specs/004-non-sqlmodel-roots.
        """
        real_nodes = [n for n in nodes if not getattr(n, 'is_virtual', False)]
        virtual_nodes = [n for n in nodes if getattr(n, 'is_virtual', False)]

        module_schemas_str = self.render_module_schema_content(real_nodes)
        virtual_cluster_str = self._render_virtual_cluster(virtual_nodes)

        er_cluster = module_schemas_str
        if virtual_cluster_str:
            er_cluster = f'{module_schemas_str}\n{virtual_cluster_str}'

        link_str = '\n'.join(self.render_link(link) for link in links)

        return self.template_renderer.render_template(
            'dot/er_diagram.j2',
            pad=self.style.pad,
            nodesep=self.style.nodesep,
            font=self.style.font,
            node_fontsize=self.style.node_fontsize,
            spline='line' if spline_line else None,
            er_cluster=er_cluster,
            links=link_str
        )

    def _render_virtual_cluster(self, virtual_nodes: list[SchemaNode]) -> str:
        """Render virtual-entity nodes inside a dashed ``cluster_virtual``.

        Returns an empty string when there are no virtual nodes — so the
        zero-virtual-entities case is byte-identical to pre-feature output.
        """
        if not virtual_nodes:
            return ''

        inner = self.render_module_schema_content(virtual_nodes)
        return self.template_renderer.render_template(
            'dot/cluster_container.j2',
            name='virtual',
            label='Virtual Entities',
            content=inner,
            border_color=self.colors.virtual_cluster,
            margin=self.style.cluster_margin,
            fontsize=self.style.cluster_fontsize,
        )
