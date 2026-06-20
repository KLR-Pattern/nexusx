"""4-layer progressive-disclosure MCP server on top of UseCase compose schemas.

Entry point: ``create_use_case_graphql_mcp_server(apps, name) -> FastMCP``.

Layer 0 ``list_apps`` — discover apps.
Layer 1 ``describe_compose_schema`` — service + method overview (compact).
Layer 2 ``describe_compose_method`` — single method detail (args + return type + SDL fragment).
Layer 3 ``compose_query`` — execute GraphQL query, return ``{data, errors}``.

Response envelope split (spec FR-007):
- Layers 0–2 return ``{success, data}`` / ``{success, error, error_type}``
  (matches existing ``mcp/types/errors.py`` helpers).
- Layer 3 returns graphql-standard ``{data, errors}``.

Note: This module builds its own internal app registry (``_ComposeAppEntry``)
rather than reusing ``UseCaseManager``. The legacy manager is shared with
the direct-call MCP / JSON-RPC / Voyager surfaces; coupling the new GraphQL
MCP's eager ``ComposeSchema`` construction to it would force every legacy
service (whose method signatures may use types ComposeTypeMapper doesn't
yet support, e.g. ``Decimal``) through schema validation at startup.
Keeping the registries separate lets users adopt the GraphQL MCP only for
apps whose types are ready.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nexusx.mcp.types.errors import (
    MCPErrors,
    create_error_response,
    create_success_response,
)
from nexusx.use_case.compose_executor import execute_compose_query
from nexusx.use_case.compose_schema import ComposeSchema, build_compose_schema
from nexusx.use_case.types import UseCaseAppConfig

if TYPE_CHECKING:
    from fastmcp import FastMCP

__all__ = ["create_use_case_graphql_mcp_server"]


@dataclass
class _ComposeAppEntry:
    """Internal per-app bundle for the compose GraphQL MCP."""

    config: UseCaseAppConfig
    schema: ComposeSchema


def create_use_case_graphql_mcp_server(
    apps: list[UseCaseAppConfig],
    name: str = "nexusx UseCase GraphQL API",
) -> FastMCP:
    """Create a 4-layer progressive-disclosure MCP server.

    Args:
        apps: One or more ``UseCaseAppConfig``. Each app's ``ComposeSchema`` is
            built eagerly at this call, so schema errors surface here (not at
            query time).
        name: MCP server name (shown in protocol handshake).

    Returns:
        ``FastMCP`` instance.

    Raises:
        ComposeSchemaError: If any app's schema fails to build.
        ValueError: If two apps share a name.
    """
    from fastmcp import FastMCP

    registry: dict[str, _ComposeAppEntry] = {}
    for app_config in apps:
        if app_config.name in registry:
            raise ValueError(f"App with name '{app_config.name}' already exists")
        registry[app_config.name] = _ComposeAppEntry(
            config=app_config,
            schema=build_compose_schema(app_config),
        )

    mcp: FastMCP = FastMCP(name)
    _register_list_apps(mcp, registry)
    _register_describe_compose_schema(mcp, registry)
    _register_describe_compose_method(mcp, registry)
    _register_compose_query(mcp, registry)
    return mcp


def _get_app(registry: dict[str, _ComposeAppEntry], name: str) -> _ComposeAppEntry | None:
    """Lookup with case-insensitive fallback. Returns None if not found."""
    if name in registry:
        return registry[name]
    name_lower = name.lower()
    for key, entry in registry.items():
        if key.lower() == name_lower:
            return entry
    return None


# ---------------------------------------------------------------------------
# Layer 0 — list_apps
# ---------------------------------------------------------------------------


def _register_list_apps(mcp: FastMCP, registry: dict[str, _ComposeAppEntry]) -> None:
    @mcp.tool()
    def list_apps() -> dict[str, Any]:
        """List all available UseCase applications registered on this server.

        Returns a compact app directory. For per-app schema discovery, call
        ``describe_compose_schema(app_name=...)`` next.
        """
        apps_payload = [
            {
                "name": entry.config.name,
                "description": entry.config.description or "",
                "services_count": len(entry.config.services),
            }
            for entry in registry.values()
        ]
        return create_success_response({
            "apps": apps_payload,
            "hint": (
                "Call describe_compose_schema(app_name=...) to see services "
                "and methods for an app."
            ),
        })


# ---------------------------------------------------------------------------
# Layer 1 — describe_compose_schema
# ---------------------------------------------------------------------------


def _register_describe_compose_schema(
    mcp: FastMCP, registry: dict[str, _ComposeAppEntry]
) -> None:
    @mcp.tool()
    def describe_compose_schema(app_name: str) -> dict[str, Any]:
        """List services and methods for an app.

        Compact: only name / kind (query|mutation) / description per method.
        For parameter and return type details, call
        ``describe_compose_method(app_name=..., service_name=..., method_name=...)``.
        """
        entry = _get_app(registry, app_name)
        if entry is None:
            return create_error_response(
                f"App '{app_name}' not found. Available: {list(registry.keys())}.",
                MCPErrors.APP_NOT_FOUND,
            )

        services_payload: list[dict[str, Any]] = []
        for service_cls in entry.config.services:
            service_name = service_cls.__name__
            query_type = entry.schema.registry.get(f"{service_name}Query")
            mutation_type = entry.schema.registry.get(f"{service_name}Mutation")
            methods: list[dict[str, Any]] = []
            if query_type is not None:
                for f in query_type.fields:
                    methods.append({
                        "name": f.name,
                        "kind": "query",
                        "description": f.description,
                    })
            if mutation_type is not None:
                for f in mutation_type.fields:
                    methods.append({
                        "name": f.name,
                        "kind": "mutation",
                        "description": f.description,
                    })
            services_payload.append({
                "name": service_name,
                "description": service_cls.__doc__,
                "methods": methods,
            })
        return create_success_response({
            "app_name": entry.config.name,
            "services": services_payload,
            "hint": (
                "Call describe_compose_method(app_name=..., service_name=..., "
                "method_name=...) for parameter and return type details."
            ),
        })


# ---------------------------------------------------------------------------
# Layer 2 — describe_compose_method
# ---------------------------------------------------------------------------


def _register_describe_compose_method(
    mcp: FastMCP, registry: dict[str, _ComposeAppEntry]
) -> None:
    @mcp.tool()
    def describe_compose_method(
        app_name: str,
        service_name: str,
        method_name: str,
    ) -> dict[str, Any]:
        """Get detailed info for a single method: args, return type, and an SDL fragment.

        The SDL fragment contains the method field on its ``{Service}Query`` (or
        ``{Service}Mutation``) type plus the transitive closure of the return
        type's DTO / enum / scalar dependencies — enough to formulate a
        ``compose_query`` call without loading the full schema.
        """
        entry = _get_app(registry, app_name)
        if entry is None:
            return create_error_response(
                f"App '{app_name}' not found. Available: {list(registry.keys())}.",
                MCPErrors.APP_NOT_FOUND,
            )

        service_cls = next(
            (s for s in entry.config.services if s.__name__ == service_name),
            None,
        )
        if service_cls is None:
            return create_error_response(
                f"Service '{service_name}' not found in app '{entry.config.name}'.",
                MCPErrors.SERVICE_NOT_FOUND,
            )

        query_type = entry.schema.registry.get(f"{service_name}Query")
        mutation_type = entry.schema.registry.get(f"{service_name}Mutation")

        method_field = None
        kind: str | None = None
        if query_type is not None:
            for f in query_type.fields:
                if f.name == method_name:
                    method_field = f
                    kind = "query"
                    break
        if method_field is None and mutation_type is not None:
            for f in mutation_type.fields:
                if f.name == method_name:
                    method_field = f
                    kind = "mutation"
                    break
        if method_field is None or kind is None:
            return create_error_response(
                f"Method '{method_name}' not found on service '{service_name}'.",
                MCPErrors.METHOD_NOT_FOUND,
            )

        sdl = entry.schema.render_method_sdl(service_name, method_name) or ""
        return create_success_response({
            "app_name": entry.config.name,
            "service_name": service_name,
            "method": {
                "name": method_field.name,
                "kind": kind,
                "description": method_field.description,
                "args": [_arg_to_dict(a) for a in method_field.args],
                "return_type": _type_ref_to_str(method_field.type_ref),
            },
            "sdl": sdl,
        })


def _arg_to_dict(a: Any) -> dict[str, Any]:
    return {
        "name": a.name,
        "type": _type_ref_to_str(a.type_ref),
        "has_default": a.has_default,
        "default_value": a.default_value if a.has_default else None,
        "description": a.description,
    }


def _type_ref_to_str(ref: Any) -> str:
    """Render a TypeRef as an SDL type expression (e.g. ``[Int!]!``)."""
    if ref.kind == "NON_NULL":
        return f"{_type_ref_to_str(ref.of_type)}!"
    if ref.kind == "LIST":
        return f"[{_type_ref_to_str(ref.of_type)}]"
    return str(ref.name)


# ---------------------------------------------------------------------------
# Layer 3 — compose_query
# ---------------------------------------------------------------------------


def _register_compose_query(
    mcp: FastMCP, registry: dict[str, _ComposeAppEntry]
) -> None:
    @mcp.tool()
    async def compose_query(
        app_name: str,
        query: str,
    ) -> dict[str, Any]:
        """Execute a GraphQL query against an app's UseCase compose schema.

        Returns graphql-standard ``{data, errors}``. ``data`` is nested by
        service then method (e.g. ``{TaskService: {list_tasks: [...]}}``).
        Introspection queries (``__schema``, ``__type``, ``__typename``) are
        rejected — use ``describe_compose_schema`` and
        ``describe_compose_method`` for schema discovery.
        """
        entry = _get_app(registry, app_name)
        if entry is None:
            return {
                "data": None,
                "errors": [{
                    "message": (
                        f"App '{app_name}' not found. "
                        f"Available: {list(registry.keys())}."
                    ),
                }],
            }

        context: dict[str, Any] = {}
        if entry.config.context_extractor is not None:
            try:
                extracted = entry.config.context_extractor(None)
                if hasattr(extracted, "__await__"):
                    extracted = await extracted
                if isinstance(extracted, dict):
                    context = extracted
            except Exception as exc:  # noqa: BLE001 — context extraction failure shouldn't 500
                return {
                    "data": None,
                    "errors": [{
                        "message": (
                            f"context_extractor raised "
                            f"{type(exc).__name__}: {exc}"
                        ),
                    }],
                }

        return await execute_compose_query(
            app=entry.config,
            schema=entry.schema,
            query=query,
            context=context,
        )
