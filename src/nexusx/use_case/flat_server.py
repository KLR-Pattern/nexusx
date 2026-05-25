"""Flat MCP Server — one tool per UseCase method, resources for type definitions.

Unlike the progressive-disclosure server (list_apps → list_services →
describe_service → call_use_case), this server exposes each @query/@mutation
method as its own MCP tool with parameters mapped directly from the Python
signature.  Type definitions are available via MCP resources.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from nexusx.mcp.types.errors import (
    MCPErrors,
    create_error_response,
    create_success_response,
)
from nexusx.use_case.business import USE_CASE_METHODS_ATTR
from nexusx.use_case.context import FromContext
from nexusx.use_case.manager import UseCaseManager
from nexusx.use_case.selection import SelectionError, apply_selection
from nexusx.use_case.server import (
    _coerce_kwargs,
    _get_return_annotation,
    _serialize_result,
)
from nexusx.use_case.types import UseCaseAppConfig

try:
    from fastmcp.server.context import Context
except ImportError:
    Context = None  # type: ignore[assignment, misc]


def create_flat_mcp_server(
    apps: list[UseCaseAppConfig],
    name: str = "nexusx UseCase API",
) -> Any:
    """Create a flat MCP server exposing each UseCase method as a separate tool.

    Each ``@query``/``@mutation`` method becomes its own MCP tool named
    ``{ServiceName}_{method_name}``.  Method parameters are mapped directly
    from the Python signature (excluding ``cls`` and ``FromContext`` params).
    SDL type definitions are available via MCP resources.

    Args:
        apps: List of UseCaseAppConfig instances.
        name: MCP server name.

    Returns:
        A configured FastMCP server instance.
    """
    from fastmcp import FastMCP

    if not apps:
        raise ValueError("apps list cannot be empty")

    manager = UseCaseManager(apps)
    mcp = FastMCP(name)

    _register_resources(mcp, manager)
    _register_tools(mcp, manager)

    return mcp


# ──────────────────────────────────────────────────
# Resource registration
# ──────────────────────────────────────────────────


def _register_resources(mcp: Any, manager: UseCaseManager) -> None:
    """Register per-app and per-service MCP resources."""
    for app_name, app in manager.apps.items():
        _register_app_resource(mcp, app, app_name)
        for service_name in app.services:
            _register_service_resource(mcp, app, app_name, service_name)


def _register_app_resource(
    mcp: Any, app: Any, app_name: str
) -> None:
    """Register a resource describing an app's services."""

    def _make_resource(_app: Any = app, _name: str = app_name) -> Callable[[], str]:
        def _app_resource() -> str:
            services_info = _app.introspector.list_services()
            lines = [f"# {_name}", ""]
            if _app.description:
                lines.append(_app.description)
                lines.append("")
            lines.append("## Services")
            for svc in services_info:
                lines.append(
                    f"- **{svc['name']}** ({svc['methods_count']} methods): "
                    f"{svc['description']}"
                )
            lines.append("")
            lines.append(
                f"Read `nexusx://{_name}/{{service_name}}` for method signatures "
                f"and type definitions."
            )
            return "\n".join(lines)
        return _app_resource

    mcp.resource(f"nexusx://{app_name}")(_make_resource())  # type: ignore[misc]


def _register_service_resource(
    mcp: Any, app: Any, app_name: str, service_name: str
) -> None:
    """Register a resource with method signatures and SDL types for a service."""

    def _make_resource(
        _app: Any = app, _app_name: str = app_name, _svc_name: str = service_name
    ) -> Callable[[], str]:
        def _service_resource() -> str:
            info = _app.introspector.describe_service(_svc_name)
            if info is None:
                return f"Service '{_svc_name}' not found."

            if not _app.enable_mutation:
                info["methods"] = [
                    m for m in info.get("methods", []) if m.get("kind") != "mutation"
                ]

            lines = [f"# {_svc_name}", ""]
            desc = info.get("description", "")
            if desc:
                lines.append(desc)
                lines.append("")

            lines.append("## Methods")
            for m in info.get("methods", []):
                kind_tag = " [MUTATION]" if m.get("kind") == "mutation" else ""
                lines.append(f"### {m['name']}{kind_tag}")
                if m.get("description"):
                    lines.append(m["description"])
                sig = m.get("signature_sdl") or m.get("signature", "")
                if sig:
                    lines.append(f"Signature: `{sig}`")
                if m.get("selection_supported"):
                    lines.append(f"Selection example: `{m.get('selection_example', '')}`")
                lines.append("")

            types_str = info.get("types", "")
            if types_str:
                lines.append("## Type Definitions (SDL)")
                lines.append("```graphql")
                lines.append(types_str)
                lines.append("```")

            return "\n".join(lines)

        return _service_resource

    mcp.resource(f"nexusx://{app_name}/{service_name}")(_make_resource())  # type: ignore[misc]


# ──────────────────────────────────────────────────
# Tool registration
# ──────────────────────────────────────────────────


def _register_tools(mcp: Any, manager: UseCaseManager) -> None:
    """Register one MCP tool per UseCase method."""
    # Collect all tool names first for collision detection
    tool_names: dict[str, tuple[str, str, str]] = {}  # name → (app, svc, method)

    for app_name, app in manager.apps.items():
        for service_name, service_cls in app.services.items():
            methods = getattr(service_cls, USE_CASE_METHODS_ATTR, {})
            for method_name, method_meta in methods.items():
                if not isinstance(method_meta, dict):
                    continue
                kind = method_meta.get("kind", "query")
                if not app.enable_mutation and kind == "mutation":
                    continue

                tool_name = f"{service_name}_{method_name}"
                if tool_name in tool_names:
                    # Collision: prefix with app name
                    tool_name = f"{app_name}_{service_name}_{method_name}"
                tool_names[tool_name] = (app_name, service_name, method_name)

    # Register each tool
    for tool_name, (app_name, service_name, method_name) in tool_names.items():
        app = manager.apps[app_name]
        service_cls = app.services[service_name]
        methods = getattr(service_cls, USE_CASE_METHODS_ATTR, {})
        method_meta = methods[method_name]

        handler = _build_tool_handler(
            app=app,
            app_name=app_name,
            service_cls=service_cls,
            service_name=service_name,
            method_name=method_name,
            method_meta=method_meta,
        )
        mcp.tool(name=tool_name)(handler)


def _build_tool_handler(
    app: Any,
    app_name: str,
    service_cls: type,
    service_name: str,
    method_name: str,
    method_meta: dict,
) -> Any:
    """Build a flat tool handler for a single use case method."""
    method = getattr(service_cls, method_name)
    func = method.__func__ if isinstance(method, classmethod) else method

    # Get type hints and signature
    try:
        hints = get_type_hints(func, include_extras=True)
    except Exception:
        hints = {}

    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError):
        sig = inspect.Signature()

    from_context_params = _get_from_context_params(method, hints, sig)

    # Build parameter list, skipping cls and FromContext params
    tool_params: list[inspect.Parameter] = []
    for param_name, param in sig.parameters.items():
        if param_name == "cls" or param_name in from_context_params:
            continue
        tool_params.append(param)

    # Add selection parameter
    tool_params.append(
        inspect.Parameter(
            "selection",
            inspect.Parameter.KEYWORD_ONLY,
            default=None,
            annotation=str | None,
        )
    )

    # Add Context parameter (FastMCP auto-injects, excluded from schema)
    if Context is not None:
        tool_params.append(
            inspect.Parameter(
                "ctx",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=Context,
            )
        )

    new_sig = sig.replace(parameters=tool_params, return_annotation=dict[str, Any])

    # Build annotations dict for FastMCP schema generation
    annotations = {}
    for p in tool_params:
        anno = p.annotation
        if anno is inspect.Parameter.empty:
            anno = Any
        annotations[p.name] = anno

    # Description
    description = method_meta.get("description", "") or ""
    if not description:
        try:
            description = inspect.getdoc(func) or ""
        except Exception:
            pass

    # Append resource hint
    resource_hint = (
        f"\n\nFor type definitions, read resource "
        f"`nexusx://{app_name}/{service_name}`."
    )
    full_description = description + resource_hint if description else resource_hint.strip()

    # Capture values for closure
    _app = app
    _service_cls = service_cls
    _method_name = method_name
    _method = method
    _func = func
    _from_context_params = from_context_params

    async def handler(**kwargs: Any) -> dict[str, Any]:
        return await _execute_flat_method(
            app=_app,
            app_name=app_name,
            service_name=service_name,
            method_name=_method_name,
            method=_method,
            func=_func,
            from_context_params=_from_context_params,
            kwargs=kwargs,
        )

    handler.__signature__ = new_sig  # type: ignore[attr-defined]
    handler.__annotations__ = annotations
    handler.__doc__ = full_description

    return handler


async def _execute_flat_method(
    app: Any,
    app_name: str,
    service_name: str,
    method_name: str,
    method: Any,
    func: Any,
    from_context_params: set[str],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Execute a use case method and return the result."""
    # Extract selection and ctx from kwargs
    selection = kwargs.pop("selection", None)
    ctx = kwargs.pop("ctx", None)

    # Coerce parameter types
    kwargs = _coerce_kwargs(func, kwargs)

    # Extract context and inject FromContext params
    if from_context_params and app.context_extractor is not None and ctx is not None:
        context = await _extract_context(app, ctx)
        if context is None:
            context = {}
        for param_name in from_context_params:
            if param_name in context:
                kwargs[param_name] = context[param_name]
            elif (
                param_name not in kwargs
                and param_name in inspect.signature(method).parameters
                and inspect.signature(method).parameters[param_name].default
                is inspect.Parameter.empty
            ):
                return create_error_response(
                    f"Required FromContext parameter '{param_name}' "
                    f"not found in context for {service_name}.{method_name}",
                    MCPErrors.VALIDATION_ERROR,
                )

    # Execute
    try:
        result = await method(**kwargs)
    except TypeError as e:
        return create_error_response(
            f"Parameter error calling {service_name}.{method_name}: {e}",
            MCPErrors.VALIDATION_ERROR,
        )
    except Exception as e:
        return create_error_response(
            f"Error executing {service_name}.{method_name}: {e}",
            MCPErrors.QUERY_EXECUTION_ERROR,
        )

    # Apply selection if provided
    if selection is not None:
        try:
            return_anno = _get_return_annotation(method)
            result = apply_selection(result, return_anno, selection)
        except SelectionError as e:
            return create_error_response(
                f"Invalid selection for {service_name}.{method_name}: {e}",
                MCPErrors.VALIDATION_ERROR,
            )

    data = _serialize_result(result)
    return create_success_response(data)


def _get_from_context_params(
    method: Any, hints: dict[str, Any] | None = None, sig: inspect.Signature | None = None
) -> set[str]:
    """Return parameter names annotated with FromContext."""
    if hints is None:
        try:
            hints = get_type_hints(method, include_extras=True)
        except Exception:
            hints = {}
    if sig is None:
        try:
            sig = inspect.signature(method)
        except (ValueError, TypeError):
            return set()

    from_context_params: set[str] = set()
    for name in sig.parameters:
        annotation = hints.get(name)
        if annotation is not None and get_origin(annotation) is Annotated:
            for arg in get_args(annotation):
                if isinstance(arg, FromContext):
                    from_context_params.add(name)
                    break
    return from_context_params


async def _extract_context(app: Any, ctx: Any) -> dict | None:
    """Call the app's context_extractor if configured."""
    if app.context_extractor is None or ctx is None:
        return None
    result = app.context_extractor(ctx)
    if inspect.isawaitable(result):
        return await result
    return result
