"""JSON-RPC 2.0 router for UseCaseService.

Provides ``create_jsonrpc_router()`` to create a FastAPI endpoint that
exposes UseCaseService methods via JSON-RPC 2.0 protocol.

Method naming: ``ServiceName.method_name`` (e.g. ``SprintService.list_sprints``).
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any, get_type_hints

from fastapi import APIRouter, Request
from pydantic import TypeAdapter
from starlette.responses import JSONResponse

from nexusx.use_case.business import USE_CASE_METHODS_ATTR
from nexusx.use_case.introspector import ServiceIntrospector
from nexusx.use_case.manager import UseCaseManager
from nexusx.use_case.router import _get_from_context_params
from nexusx.use_case.serialization import coerce_kwargs as _coerce_kwargs
from nexusx.use_case.serialization import serialize_result as _serialize_result
from nexusx.use_case.types import UseCaseAppConfig

# ---------------------------------------------------------------------------
# JSON-RPC 2.0 error codes
# ---------------------------------------------------------------------------

INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
PARSE_ERROR = -32700

# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _make_result(result: Any, req_id: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "result": result, "id": req_id}


def _make_error(code: int, message: str, req_id: Any | None = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "error": {"code": code, "message": message}, "id": req_id}


# ---------------------------------------------------------------------------
# Method execution
# ---------------------------------------------------------------------------


async def _extract_context(
    context_extractor: Callable[[Any], dict[str, Any] | Awaitable[dict[str, Any]]] | None,
    request: Request,
) -> dict[str, Any] | None:
    if context_extractor is None:
        return None
    result = context_extractor(request)
    if inspect.isawaitable(result):
        result = await result
    return result


async def _execute_method(
    app: Any,
    service_name: str,
    method_name: str,
    params: dict[str, Any],
    context: dict[str, Any] | None,
) -> Any:
    """Look up and execute a use case method. Raises ValueError on lookup failure."""
    service_cls = app.services.get(service_name)
    if service_cls is None:
        available = list(app.services.keys())
        raise ValueError(f"Service '{service_name}' not found. Available: {available}")

    methods = getattr(service_cls, USE_CASE_METHODS_ATTR)
    if method_name not in methods:
        available = list(methods.keys())
        raise ValueError(f"Method '{method_name}' not found. Available: {available}")

    method_meta = methods.get(method_name, {})
    method_kind = method_meta.get("kind", "query") if isinstance(method_meta, dict) else "query"
    if not app.enable_mutation and method_kind == "mutation":
        raise ValueError(f"Method '{method_name}' is a mutation and mutations are disabled")

    method = getattr(service_cls, method_name)
    func = method.__func__ if isinstance(method, classmethod) else method

    # Coerce params
    kwargs = _coerce_kwargs(func, dict(params))

    # Inject FromContext params
    from_context_params = _get_from_context_params(method)
    if from_context_params:
        if context is None:
            context = {}
        sig = inspect.signature(method)
        for param_name in from_context_params:
            if param_name in context:
                kwargs[param_name] = context[param_name]
            elif (
                param_name not in kwargs
                and sig.parameters[param_name].default is inspect.Parameter.empty
            ):
                raise ValueError(
                    f"Required FromContext parameter '{param_name}' not found in context"
                )

    return await method(**kwargs)


# ---------------------------------------------------------------------------
# RPC introspection (rpc.discover / rpc.describe / rpc.schema)
# ---------------------------------------------------------------------------


def _build_full_schema(config: UseCaseAppConfig) -> dict[str, Any]:
    """Build complete JSON Schema for all methods and DTO types.

    Returns a dict with ``methods`` (per-method param/result schemas) and
    ``$defs`` (shared DTO type definitions).  Clients can feed this directly
    into codegen tools (datamodel-code-generator, json-schema-to-typescript, …).
    """
    methods: dict[str, Any] = {}
    defs: dict[str, Any] = {}

    for service_cls in config.services:
        service_methods = getattr(service_cls, USE_CASE_METHODS_ATTR, {})
        for method_name, meta in service_methods.items():
            kind = meta.get("kind", "query") if isinstance(meta, dict) else "query"
            if not config.enable_mutation and kind == "mutation":
                continue

            description = meta.get("description", "") if isinstance(meta, dict) else ""
            method = getattr(service_cls, method_name)
            func = method.__func__ if isinstance(method, classmethod) else method

            try:
                hints = get_type_hints(func, include_extras=True)
            except Exception:
                hints = {}

            try:
                sig = inspect.signature(func)
            except (ValueError, TypeError):
                continue

            # Params
            params_schema: dict[str, Any] = {}
            for pname, param in sig.parameters.items():
                if pname == "cls":
                    continue
                anno = hints.get(pname, param.annotation)
                if anno is inspect.Parameter.empty:
                    continue
                try:
                    ps = TypeAdapter(anno).json_schema()
                except Exception:
                    continue
                params_schema[pname] = {k: v for k, v in ps.items() if k != "$defs"}
                defs.update(ps.get("$defs", {}))

            # Result
            return_anno = hints.get("return")
            result_schema: dict[str, Any] = {}
            if return_anno:
                try:
                    rs = TypeAdapter(return_anno).json_schema()
                    result_schema = {k: v for k, v in rs.items() if k != "$defs"}
                    defs.update(rs.get("$defs", {}))
                except Exception:
                    pass

            methods[f"{service_cls.__name__}.{method_name}"] = {
                "description": description,
                "kind": kind,
                "params": params_schema,
                "result": result_schema,
            }

    return {"methods": methods, "$defs": defs}


def _handle_rpc_method(
    method_name: str,
    params: dict[str, Any],
    introspector: ServiceIntrospector,
    full_schema: dict[str, Any],
) -> Any | dict[str, Any]:
    """Dispatch ``rpc.*`` system methods.  Returns result or error dict."""
    if method_name == "discover":
        return introspector.list_services()

    if method_name == "describe":
        service = params.get("service") if isinstance(params, dict) else None
        if not service or not isinstance(service, str):
            return _make_error(INVALID_PARAMS, "'service' parameter required")
        info = introspector.describe_service(service)
        if info is None:
            return _make_error(
                METHOD_NOT_FOUND,
                f"Service '{service}' not found. "
                f"Available: {[s['name'] for s in introspector.list_services()]}",
            )
        return info

    if method_name == "schema":
        return full_schema

    return _make_error(
        METHOD_NOT_FOUND,
        f"Unknown rpc method '{method_name}'. "
        f"Available: rpc.discover, rpc.describe, rpc.schema",
    )


# ---------------------------------------------------------------------------
# Request handling
# ---------------------------------------------------------------------------


async def _handle_single_request(
    req: dict[str, Any],
    app: Any,
    context_extractor: Callable | None,
    request: Request,
    introspector: ServiceIntrospector | None = None,
    full_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Process a single JSON-RPC request dict and return a response dict."""
    req_id = req.get("id")

    # Validate JSON-RPC 2.0 format
    if req.get("jsonrpc") != "2.0":
        return _make_error(INVALID_REQUEST, "Invalid or missing 'jsonrpc' field", req_id)

    method_str = req.get("method")
    if not isinstance(method_str, str) or not method_str:
        return _make_error(INVALID_REQUEST, "Invalid or missing 'method' field", req_id)

    # Split method: "ServiceName.method_name"
    if "." not in method_str:
        return _make_error(
            METHOD_NOT_FOUND,
            f"Invalid method format: '{method_str}'. Expected 'ServiceName.method_name'",
            req_id,
        )

    service_name, method_name = method_str.split(".", 1)

    # System methods: rpc.discover / rpc.describe / rpc.schema
    if service_name == "rpc":
        if introspector is None or full_schema is None:
            return _make_error(INTERNAL_ERROR, "Introspection not available", req_id)
        result = _handle_rpc_method(method_name, req.get("params", {}), introspector, full_schema)
        # _handle_rpc_method may return an error dict
        if isinstance(result, dict) and "error" in result and "jsonrpc" in result:
            return {**result, "id": req_id}
        return _make_result(result, req_id)

    # Validate params
    params = req.get("params", {})
    if not isinstance(params, dict):
        return _make_error(INVALID_PARAMS, "params must be a JSON object", req_id)

    # Extract context
    try:
        context = await _extract_context(context_extractor, request)
    except Exception as e:
        return _make_error(INVALID_PARAMS, f"Context extraction failed: {e}", req_id)

    # Execute
    try:
        result = await _execute_method(app, service_name, method_name, params, context)
        serialized = _serialize_result(result)
        return _make_result(serialized, req_id)
    except ValueError as e:
        if "not found" in str(e) or "mutations are disabled" in str(e):
            return _make_error(METHOD_NOT_FOUND, str(e), req_id)
        return _make_error(INVALID_PARAMS, str(e), req_id)
    except TypeError as e:
        return _make_error(INVALID_PARAMS, str(e), req_id)
    except Exception as e:
        return _make_error(INTERNAL_ERROR, str(e), req_id)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_jsonrpc_router(
    config: UseCaseAppConfig,
    path: str = "/rpc",
    context_extractor: Callable[[Any], dict[str, Any] | Awaitable[dict[str, Any]]]
    | None = None,
) -> APIRouter:
    """Create a JSON-RPC 2.0 endpoint from UseCaseAppConfig.

    Generates a single POST endpoint that routes JSON-RPC methods to
    UseCaseService methods. Method naming: ``ServiceName.method_name``.

    Args:
        config: UseCaseAppConfig with services and optional defaults.
        path: URL path for the JSON-RPC endpoint (default ``"/rpc"``).
        context_extractor: Optional callable to extract context from Request.
            Overrides ``config.context_extractor`` if provided.

    Returns:
        A ``fastapi.APIRouter`` ready to be included in a FastAPI app.

    Example::

        router = create_jsonrpc_router(
            UseCaseAppConfig(
                name="project",
                services=[UserService, TaskService],
            ),
        )
        app.include_router(router)
    """
    router = APIRouter()
    manager = UseCaseManager([config])
    app = manager.get_app(config.name)
    ctx_extractor = context_extractor or config.context_extractor
    introspector = ServiceIntrospector(config.services)
    full_schema = _build_full_schema(config)

    @router.post(path)
    async def handle_rpc(request: Request) -> JSONResponse:
        # Parse body
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(_make_error(PARSE_ERROR, "Parse error"))

        # Batch request
        if isinstance(body, list):
            if not body:
                return JSONResponse(_make_error(INVALID_REQUEST, "Empty batch"))
            results = await asyncio.gather(
                *[
                    _handle_single_request(
                        r, app, ctx_extractor, request, introspector, full_schema
                    )
                    for r in body
                ]
            )
            return JSONResponse(list(results))

        # Single request
        if not isinstance(body, dict):
            return JSONResponse(_make_error(INVALID_REQUEST, "Request must be a JSON object"))

        result = await _handle_single_request(
            body, app, ctx_extractor, request, introspector, full_schema
        )
        return JSONResponse(result)

    return router
