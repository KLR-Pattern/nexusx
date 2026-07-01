"""VoyagerContext — shared business logic for UseCase voyager API endpoints.

Simplified from fastapi-voyager's VoyagerContext, removing framework
detection and pydantic-resolve dependencies.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

from nexusx.loader.registry import ErManager
from nexusx.use_case.business import UseCaseService
from nexusx.voyager.er_diagram_dot import ErDiagramDotBuilder
from nexusx.voyager.render import Renderer
from nexusx.voyager.render_style import DEFAULT_PRIMARY
from nexusx.voyager.type import CoreData, SchemaNode, Tag
from nexusx.voyager.type_helper import get_source, get_vscode_link
from nexusx.voyager.use_case_voyager import UseCaseVoyager  # noqa: F401

WEB_DIR = Path(__file__).parent / "web"

STATIC_FILES_PATH = "/nexusx-voyager-static"

VERSION_PLACEHOLDER = "<!-- VERSION_PLACEHOLDER -->"
STATIC_PATH_PLACEHOLDER = "<!-- STATIC_PATH -->"
THEME_COLOR_PLACEHOLDER = "<!-- THEME_COLOR -->"
VOYAGER_PATH_PLACEHOLDER = "<!-- VOYAGER_PATH -->"


class VoyagerContext:
    """Context object that holds configuration and provides business logic methods."""

    def __init__(
        self,
        services: list[type[UseCaseService]],
        er_manager: ErManager | None = None,
        name: str = "UseCase API",
        module_color: dict[str, str] | None = None,
        initial_page_policy: str = 'first',
        online_repo_url: str | None = None,
        version: str = "1.0.0",
    ):
        self.services = services
        self.er_manager = er_manager
        self.name = name
        self.module_color = module_color or {}
        self.initial_page_policy = initial_page_policy
        self.online_repo_url = online_repo_url
        self.version = version
        self.theme_color = DEFAULT_PRIMARY

    def _get_voyager(self, **kwargs) -> UseCaseVoyager:
        """Create a UseCaseVoyager instance with common configuration."""
        config = {
            "module_color": self.module_color,
            "theme_color": self.theme_color,
        }
        config.update(kwargs)
        return UseCaseVoyager(self.services, **config)

    def analyze_and_get_dot(self) -> tuple[str, list[Tag], list[SchemaNode]]:
        """Analyze UseCase services and return dot graph, tags, and schemas."""
        voyager = self._get_voyager()
        voyager.analysis()
        dot = voyager.render_dot()

        tags = voyager.tags
        for t in tags:
            t.routes.sort(key=lambda r: r.name)
        tags.sort(key=lambda t: t.name)

        schemas = voyager.nodes[:]
        schemas.sort(key=lambda s: s.name)

        return dot, tags, schemas

    def get_option_param(self) -> dict:
        """Get the option parameter for the voyager UI."""
        dot, tags, schemas = self.analyze_and_get_dot()

        has_resolve_meta = any(
            f.has_pydantic_resolve_meta
            for s in schemas
            for f in s.fields
        )

        return {
            "tags": tags,
            "schemas": schemas,
            "dot": dot,
            "enable_brief_mode": bool(self.module_color),
            "version": self.version,
            "swagger_url": None,
            "initial_page_policy": self.initial_page_policy,
            "has_er_diagram": self.er_manager is not None,
            "enable_pydantic_resolve_meta": has_resolve_meta,
            "framework_name": self.name,
        }

    def get_search_dot(self, payload: dict) -> list[Tag]:
        """Get filtered tags for search."""
        voyager = self._get_voyager(
            schema=payload.get("schema_name"),
            schema_field=payload.get("schema_field"),
            show_fields=payload.get("show_fields", "object"),
            hide_primitive_route=payload.get("hide_primitive_route", False),
            show_module=payload.get("show_module", True),
        )
        voyager.analysis()
        tags = voyager.calculate_filtered_tag_and_route()

        for t in tags:
            t.routes.sort(key=lambda r: r.name)
        tags.sort(key=lambda t: t.name)

        return tags

    def get_filtered_dot(self, payload: dict) -> str:
        """Get filtered dot graph."""
        voyager = self._get_voyager(
            include_tags=payload.get("tags"),
            schema=payload.get("schema_name"),
            schema_field=payload.get("schema_field"),
            show_fields=payload.get("show_fields", "object"),
            route_name=payload.get("route_name"),
            hide_primitive_route=payload.get("hide_primitive_route", False),
            show_module=payload.get("show_module", True),
        )
        voyager.analysis()
        return voyager.render_dot(
            show_pydantic_resolve_meta=payload.get("show_pydantic_resolve_meta", False),
        )

    def get_core_data(self, payload: dict) -> CoreData:
        """Get core data for the graph."""
        voyager = self._get_voyager(
            include_tags=payload.get("tags"),
            schema=payload.get("schema_name"),
            schema_field=payload.get("schema_field"),
            show_fields=payload.get("show_fields", "object"),
            route_name=payload.get("route_name"),
        )
        voyager.analysis()
        return voyager.dump_core_data(
            show_pydantic_resolve_meta=payload.get("show_pydantic_resolve_meta", False),
        )

    def render_dot_from_core_data(self, core_data: CoreData) -> str:
        """Render dot graph from core data."""
        renderer = Renderer(
            show_fields=core_data.show_fields,
            module_color=core_data.module_color,
            schema=core_data.schema,
            theme_color=self.theme_color,
            show_pydantic_resolve_meta=core_data.show_pydantic_resolve_meta,
        )
        return renderer.render_dot(
            core_data.tags, core_data.routes, core_data.nodes, core_data.links
        )

    def get_er_diagram_data(self, payload: dict) -> dict:
        """Get ER diagram dot graph and link metadata."""
        if not self.er_manager:
            return {"dot": "", "links": [], "schemas": []}

        edge_minlen = max(3, min(10, payload.get("edge_minlen", 3)))
        builder = ErDiagramDotBuilder(
            self.er_manager,
            show_fields=payload.get("show_fields", "object"),
            show_module=payload.get("show_module", True),
            better_cluster_display=payload.get("better_cluster_display", False),
            theme_color=self.theme_color,
            edge_minlen=edge_minlen,
            show_methods=payload.get("show_methods", True),
        )
        builder.analysis()
        dot = builder.render_dot()

        links_meta = [
            {
                "source_origin": link.source_origin,
                "target_origin": link.target_origin,
                "label": link.label,
                "loader_fullname": link.loader_fullname,
            }
            for link in builder.links
        ]
        schemas_meta = [
            {
                "id": node.id,
                "name": node.name,
                "module": node.module,
                "fields": [
                    {
                        "name": f.name,
                        "type_name": f.type_name,
                        "from_base": f.from_base,
                        "is_object": f.is_object,
                        "is_exclude": f.is_exclude,
                        "desc": f.desc,
                    }
                    for f in node.fields
                ],
            }
            for node in builder.node_set.values()
        ]
        return {"dot": dot, "links": links_meta, "schemas": schemas_meta}

    def get_er_diagram_subgraph(self, payload: dict) -> dict:
        """Get a focused ER sub-graph for one entity + its direct neighbors.

        Spec 005 — backs the "Related Entities" sidebar tab. Reuses the same
        ``ErDiagramDotBuilder`` rendering path as :meth:`get_er_diagram_data`
        (so show_module / show_methods / edge_minlen / show_fields have identical
        effect), with one extra ``filter_to_neighborhood`` step after analysis.

        Response shape is identical to :meth:`get_er_diagram_data`:
        ``{"dot": str, "links": list, "schemas": list}``.
        """
        if not self.er_manager:
            return {"dot": "", "links": [], "schemas": []}

        schema_name = payload.get("schema_name") or ""
        edge_minlen = max(3, min(10, payload.get("edge_minlen", 3)))
        builder = ErDiagramDotBuilder(
            self.er_manager,
            show_fields=payload.get("show_fields", "object"),
            show_module=payload.get("show_module", True),
            better_cluster_display=payload.get("better_cluster_display", False),
            theme_color=self.theme_color,
            edge_minlen=edge_minlen,
            show_methods=payload.get("show_methods", True),
        )
        builder.analysis()
        # Unknown anchor → observably empty result (contracts/api.md).
        if schema_name not in builder.node_set:
            return {"dot": "", "links": [], "schemas": []}
        builder.filter_to_neighborhood(schema_name)
        dot = builder.render_dot()

        links_meta = [
            {
                "source_origin": link.source_origin,
                "target_origin": link.target_origin,
                "label": link.label,
                "loader_fullname": link.loader_fullname,
            }
            for link in builder.links
        ]
        schemas_meta = [
            {
                "id": node.id,
                "name": node.name,
                "module": node.module,
                "fields": [
                    {
                        "name": f.name,
                        "type_name": f.type_name,
                        "from_base": f.from_base,
                        "is_object": f.is_object,
                        "is_exclude": f.is_exclude,
                        "desc": f.desc,
                    }
                    for f in node.fields
                ],
            }
            for node in builder.node_set.values()
        ]
        return {"dot": dot, "links": links_meta, "schemas": schemas_meta}

    def get_index_html(self) -> str:
        """Get the index HTML content."""
        index_file = WEB_DIR / "index.html"
        if index_file.exists():
            content = index_file.read_text(encoding="utf-8")
            content = content.replace(VERSION_PLACEHOLDER, f"?v={self.version}")
            content = content.replace(STATIC_PATH_PLACEHOLDER, STATIC_FILES_PATH.lstrip("/"))
            content = content.replace(THEME_COLOR_PLACEHOLDER, self.theme_color)
            return content
        return """
        <!doctype html>
        <html>
        <head><meta charset="utf-8"><title>Voyager</title></head>
        <body>
          <p>index.html not found.</p>
        </body>
        </html>
        """

    def _resolve_object(self, schema_name: str):
        """Resolve a schema_name to a Python object.

        Handles two formats:
          - Route ID: "service_name.method_name" (looked up from RPC configs)
          - Full class name: "module.path.ClassName" (imported directly)
        """
        # Try RPC route ID first: "service_name.method_name"
        service_map = {svc.__name__: svc for svc in self.services}
        dot_idx = schema_name.find(".")
        if dot_idx > 0:
            svc_name = schema_name[:dot_idx]
            method_name = schema_name[dot_idx + 1:]
            if svc_name in service_map:
                svc_cls = service_map[svc_name]
                method = getattr(svc_cls, method_name, None)
                if method is not None:
                    return method

        # Fall back to module.ClassName import.
        #
        # Voyager/ER UI uses fully-qualified names from the analyzed graph, which
        # may point at DTO/entity/loader classes living outside service modules
        # (for example ``src.models.WorkspaceKnowledgeBinding``). Restricting
        # resolution to service modules makes those valid graph nodes fail with
        # a misleading "Invalid schema name format." even though the name is
        # structurally correct and already imported by the running app.
        #
        # Prefer already-loaded modules for safety and only import as a fallback.
        components = schema_name.split(".")
        if len(components) < 2:
            return None
        module_name = ".".join(components[:-1])
        class_name = components[-1]
        mod = sys.modules.get(module_name)
        if mod is None:
            try:
                mod = __import__(module_name, fromlist=[class_name])
            except ImportError:
                return None
        return getattr(mod, class_name)

    def get_source_code(self, schema_name: str) -> dict:
        """Get source code for a schema or RPC method."""
        try:
            obj = self._resolve_object(schema_name)
            if obj is None:
                return {"error": "Invalid schema name format."}
            source_code = get_source(obj)
            return {"source_code": source_code}
        except ImportError as e:
            return {"error": f"Module not found: {e}"}
        except AttributeError as e:
            return {"error": f"Class not found: {e}"}
        except Exception as e:
            return {"error": f"Internal error: {str(e)}"}

    def get_docstring(self, schema_name: str) -> dict:
        """spec 006 — Get the Python ``__doc__`` of a schema class.

        Used by the About tab to render the entity's docstring as Markdown +
        Mermaid. Returns ``{"docstring": ""}`` (empty string, not null) when
        ``__doc__`` is missing so the frontend can distinguish "no docstring"
        from "loading" / "error". Mirrors ``get_source_code`` error shape.
        """
        try:
            obj = self._resolve_object(schema_name)
            if obj is None:
                return {"error": "Invalid schema name format."}
            return {"docstring": inspect.cleandoc(obj.__doc__ or "")}
        except ImportError as e:
            return {"error": f"Module not found: {e}"}
        except AttributeError as e:
            return {"error": f"Class not found: {e}"}
        except Exception as e:
            return {"error": f"Internal error: {str(e)}"}

    def get_vscode_link(self, schema_name: str) -> dict:
        """Get VSCode link for a schema or RPC method."""
        try:
            obj = self._resolve_object(schema_name)
            if obj is None:
                return {"error": "Invalid schema name format."}
            link = get_vscode_link(obj, online_repo_url=self.online_repo_url)
            return {"link": link}
        except ImportError as e:
            return {"error": f"Module not found: {e}"}
        except AttributeError as e:
            return {"error": f"Class not found: {e}"}
        except Exception as e:
            return {"error": f"Internal error: {str(e)}"}
