"""create_use_case_voyager — public API for creating UseCase voyager visualization.

Creates a FastAPI ASGI sub-application that can be mounted on any
FastAPI/Starlette app to provide interactive visualization of
UseCase services and ER diagrams.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel as PydanticModel

from nexusx.loader.registry import ErManager
from nexusx.use_case.business import UseCaseService  # noqa: F401
from nexusx.voyager.type import CoreData, SchemaNode, Tag
from nexusx.voyager.voyager_context import (
    STATIC_FILES_PATH,
    WEB_DIR,
    VoyagerContext,
)

# ── Request/Response models ─────────────────────────────────────


class OptionParam(PydanticModel):
    tags: list[Tag]
    schemas: list[SchemaNode]
    dot: str
    enable_brief_mode: bool
    version: str
    initial_page_policy: Literal["first", "full", "empty"]
    swagger_url: str | None = None
    has_er_diagram: bool = False
    enable_pydantic_resolve_meta: bool = False
    framework_name: str = "UseCase API"


class Payload(PydanticModel):
    tags: list[str] | None = None
    schema_name: str | None = None
    schema_field: str | None = None
    route_name: str | None = None
    show_fields: str = "object"
    brief: bool = False
    hide_primitive_route: bool = False
    show_module: bool = True
    show_pydantic_resolve_meta: bool = False


class SearchResultOptionParam(PydanticModel):
    tags: list[Tag]


class SchemaSearchPayload(PydanticModel):
    schema_name: str | None = None
    schema_field: str | None = None
    show_fields: str = "object"
    brief: bool = False
    hide_primitive_route: bool = False
    show_module: bool = True
    show_pydantic_resolve_meta: bool = False


class ErDiagramPayload(PydanticModel):
    show_fields: str = "object"
    show_module: bool = True
    edge_minlen: int = 3
    show_methods: bool = True


class ErDiagramSubgraphPayload(PydanticModel):
    """Spec 005 — request body for POST /er-diagram-subgraph.

    Same rendering fields as :class:`ErDiagramPayload`, plus the required
    ``schema_name`` of the selected entity whose one-level neighborhood should
    be rendered as a focused read-only sub-graph in the sidebar.
    """

    schema_name: str
    show_fields: str = "object"
    show_module: bool = True
    edge_minlen: int = 3
    show_methods: bool = True


class SourcePayload(PydanticModel):
    schema_name: str


# ── Public API ───────────────────────────────────────────────────


def create_use_case_voyager(
    services: list[type[UseCaseService]],
    er_manager: ErManager | None = None,
    name: str = "UseCase API",
    module_color: dict[str, str] | None = None,
    initial_page_policy: Literal["first", "full", "empty"] = "first",
    online_repo_url: str | None = None,
    version: str = "1.0.0",
    gzip_minimum_size: int | None = 500,
) -> Any:
    """Create a voyager visualization ASGI app for UseCase services.

    Returns a FastAPI application that can be mounted on any
    FastAPI/Starlette app.

    Usage::

        from nexusx.voyager import create_use_case_voyager

        voyager_app = create_use_case_voyager(
            services=[UserService, TaskService],
            er_manager=er,
            name="My Project API",
        )
        app.mount("/voyager", voyager_app)

    Args:
        services: List of UseCaseService subclasses.
        er_manager: Optional ErManager for ER diagram visualization.
        name: Display name for the voyager UI.
        module_color: Optional color mapping for modules.
        initial_page_policy: Initial page display policy.
        online_repo_url: Optional online repository URL for source links.
        version: Version string for cache busting.
        gzip_minimum_size: Minimum size for gzip compression (set to <0 to disable).

    Returns:
        A FastAPI application that provides the voyager UI.
    """
    from fastapi import APIRouter, FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
    from fastapi.staticfiles import StaticFiles
    from starlette.middleware.gzip import GZipMiddleware

    ctx = VoyagerContext(
        services=services,
        er_manager=er_manager,
        name=name,
        module_color=module_color,
        initial_page_policy=initial_page_policy,
        online_repo_url=online_repo_url,
        version=version,
    )

    router = APIRouter(tags=["voyager"])

    @router.get("/dot", response_model=OptionParam)
    def get_dot() -> OptionParam:
        data = ctx.get_option_param()
        return OptionParam(**data)

    @router.post("/dot-search", response_model=SearchResultOptionParam)
    def get_search_dot(payload: SchemaSearchPayload) -> SearchResultOptionParam:
        tags = ctx.get_search_dot(payload.model_dump())
        return SearchResultOptionParam(tags=tags)

    @router.post("/dot", response_class=PlainTextResponse)
    def get_filtered_dot(payload: Payload) -> str:
        return ctx.get_filtered_dot(payload.model_dump())

    @router.post("/dot-core-data", response_model=CoreData)
    def get_filtered_dot_core_data(payload: Payload) -> CoreData:
        return ctx.get_core_data(payload.model_dump())

    @router.post("/dot-render-core-data", response_class=PlainTextResponse)
    def render_dot_from_core_data(core_data: CoreData) -> str:
        return ctx.render_dot_from_core_data(core_data)

    @router.post("/er-diagram")
    def get_er_diagram(payload: ErDiagramPayload):
        return ctx.get_er_diagram_data(payload.model_dump())

    @router.post("/er-diagram-subgraph")
    def get_er_diagram_subgraph(payload: ErDiagramSubgraphPayload):
        return ctx.get_er_diagram_subgraph(payload.model_dump())

    @router.get("/", response_class=HTMLResponse)
    def index() -> str:
        return ctx.get_index_html()

    @router.post("/source")
    def get_object_by_module_name(payload: SourcePayload) -> JSONResponse:
        result = ctx.get_source_code(payload.schema_name)
        status_code = 200 if "error" not in result else 400
        if "error" in result and "not found" in result["error"]:
            status_code = 404
        return JSONResponse(content=result, status_code=status_code)

    @router.post("/docstring")
    def get_docstring_endpoint(payload: SourcePayload) -> JSONResponse:
        # spec 006 — returns class __doc__ for the About tab. Mirrors /source:
        # 200 on success, 404 when module/class not found, 400 otherwise.
        result = ctx.get_docstring(payload.schema_name)
        status_code = 200 if "error" not in result else 400
        if "error" in result and "not found" in result["error"]:
            status_code = 404
        return JSONResponse(content=result, status_code=status_code)

    @router.post("/vscode-link")
    def get_vscode_link_by_module_name(payload: SourcePayload) -> JSONResponse:
        result = ctx.get_vscode_link(payload.schema_name)
        status_code = 200 if "error" not in result else 400
        if "error" in result and "not found" in result["error"]:
            status_code = 404
        return JSONResponse(content=result, status_code=status_code)

    app = FastAPI(title=f"{name} Voyager")

    if gzip_minimum_size is not None and gzip_minimum_size >= 0:
        app.add_middleware(GZipMiddleware, minimum_size=gzip_minimum_size)


    app.mount(STATIC_FILES_PATH, StaticFiles(directory=str(WEB_DIR)), name="static")
    app.include_router(router)

    return app
