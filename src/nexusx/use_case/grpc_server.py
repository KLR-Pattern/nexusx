"""gRPC Server — expose UseCaseService methods as unary RPCs over gRPC.

Uses JSON-over-gRPC: request/response bodies are JSON-encoded bytes.
This avoids protobuf code generation while leveraging gRPC's transport layer
(retry, load balancing, TLS, interceptors).

Usage::

    from nexusx import UseCaseAppConfig, create_use_case_grpc_server

    server = create_use_case_grpc_server(
        UseCaseAppConfig(name="project", services=[UserService]),
        port=50051,
    )
    await server.start()
"""

from __future__ import annotations

import inspect
import json
from typing import Annotated, Any, get_args, get_origin, get_type_hints

try:
    import grpc
    from grpc import aio as grpc_aio
except ImportError as exc:
    raise ImportError(
        "grpcio is required for gRPC support: pip install nexusx[grpc]"
    ) from exc

from nexusx.use_case.business import USE_CASE_METHODS_ATTR
from nexusx.use_case.context import FromContext
from nexusx.use_case.manager import UseCaseManager
from nexusx.use_case.server import _coerce_kwargs, _serialize_result
from nexusx.use_case.types import UseCaseAppConfig


def _get_from_context_params(method: Any) -> set[str]:
    from_context_params: set[str] = set()
    try:
        hints = get_type_hints(method, include_extras=True)
    except Exception:
        hints = {}
    sig = inspect.signature(method)
    for name in sig.parameters:
        annotation = hints.get(name)
        if annotation is not None and get_origin(annotation) is Annotated:
            for arg in get_args(annotation):
                if isinstance(arg, FromContext):
                    from_context_params.add(name)
                    break
    return from_context_params


class _GrpcContextAdapter:
    """Adapts gRPC ServicerContext metadata to dict-like access for context_extractor."""

    def __init__(self, context: grpc_aio.ServicerContext):
        metadata = context.invocation_metadata() or []
        self._metadata = dict(metadata)

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._metadata.get(key, default)

    def __getitem__(self, key: str) -> str:
        return self._metadata[key]

    def __contains__(self, key: str) -> bool:
        return key in self._metadata

    @property
    def headers(self) -> dict[str, str]:
        return self._metadata


async def _extract_context(
    app: Any,
    grpc_context: grpc_aio.ServicerContext,
) -> dict[str, Any]:
    if app.context_extractor is None:
        return {}
    adapter = _GrpcContextAdapter(grpc_context)
    result = app.context_extractor(adapter)
    if inspect.isawaitable(result):
        result = await result
    return result if isinstance(result, dict) else {}


async def _handle_rpc(
    app: Any,
    service_name: str,
    method_name: str,
    request_bytes: bytes,
    grpc_context: grpc_aio.ServicerContext,
) -> bytes:
    # Deserialize
    try:
        params = json.loads(request_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        await grpc_context.abort(
            grpc.StatusCode.INVALID_ARGUMENT,
            f"Invalid JSON: {e}",
        )
        return b""  # unreachable, but helps type checker

    if not isinstance(params, dict):
        await grpc_context.abort(
            grpc.StatusCode.INVALID_ARGUMENT,
            "Request body must be a JSON object",
        )
        return b""

    # Service lookup
    service_cls = app.services.get(service_name)
    if service_cls is None:
        available = list(app.services.keys())
        await grpc_context.abort(
            grpc.StatusCode.NOT_FOUND,
            f"Service '{service_name}' not found. Available: {available}",
        )
        return b""

    # Method lookup
    methods = getattr(service_cls, USE_CASE_METHODS_ATTR)
    if method_name not in methods:
        available = list(methods.keys())
        await grpc_context.abort(
            grpc.StatusCode.NOT_FOUND,
            f"Method '{method_name}' not found. Available: {available}",
        )
        return b""

    # Mutation check
    method_meta = methods.get(method_name, {})
    method_kind = method_meta.get("kind", "query") if isinstance(method_meta, dict) else "query"
    if not app.enable_mutation and method_kind == "mutation":
        await grpc_context.abort(
            grpc.StatusCode.PERMISSION_DENIED,
            f"Method '{method_name}' is a mutation and mutations are disabled",
        )
        return b""

    # Execute
    method = getattr(service_cls, method_name)
    func = method.__func__ if isinstance(method, classmethod) else method

    kwargs = _coerce_kwargs(func, dict(params))

    # FromContext injection
    from_context_params = _get_from_context_params(method)
    if from_context_params:
        context = await _extract_context(app, grpc_context)
        sig = inspect.signature(method)
        for param_name in from_context_params:
            if param_name in context:
                kwargs[param_name] = context[param_name]
            elif (
                param_name not in kwargs
                and sig.parameters[param_name].default is inspect.Parameter.empty
            ):
                await grpc_context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    f"Required FromContext parameter '{param_name}' not found",
                )
                return b""

    try:
        result = await method(**kwargs)
    except Exception as e:
        await grpc_context.abort(
            grpc.StatusCode.INTERNAL,
            f"Error executing {service_name}.{method_name}: {e}",
        )
        return b""

    serialized = _serialize_result(result)
    return json.dumps({"result": serialized}, ensure_ascii=False).encode("utf-8")


class _UseCaseServiceHandler(grpc.ServiceRpcHandler):
    """Routes /ServiceName/MethodName to UseCaseService methods."""

    def __init__(self, app: Any):
        self._app = app
        self._service_name: str | None = None
        self._methods: dict[str, Any] = {}

        services = app.services
        if len(services) == 1:
            svc_cls = list(services.values())[0]
            self._service_name = svc_cls.__name__
            self._methods = getattr(svc_cls, USE_CASE_METHODS_ATTR, {})
        else:
            # Multi-service: accept any registered service
            self._service_name = app.name
            for svc_cls in services.values():
                svc_methods = getattr(svc_cls, USE_CASE_METHODS_ATTR, {})
                for mname, meta in svc_methods.items():
                    qualified = f"{svc_cls.__name__}.{mname}"
                    self._methods[qualified] = (svc_cls, mname, meta)

    def service_name(self) -> str:
        return self._service_name or ""

    def service(
        self,
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler | None:
        # Format: /ServiceName/MethodName
        method_path = handler_call_details.method
        if not method_path:
            return None

        parts = method_path.strip("/").split("/")
        if len(parts) != 2:
            return None

        called_service = parts[0]
        called_method = parts[1]

        # Accept any registered service name
        if called_service not in self._app.services:
            return None

        app = self._app
        service_name = called_service
        method_name = called_method

        async def handler(
            request: bytes,
            context: grpc_aio.ServicerContext,
        ) -> bytes:
            return await _handle_rpc(app, service_name, method_name, request, context)

        return grpc.unary_unary_rpc_method_handler(
            handler,
            request_deserializer=lambda b: b,
            response_serializer=lambda r: r,
        )


def create_use_case_grpc_server(
    config: UseCaseAppConfig,
    host: str = "[::]",
    port: int = 50051,
) -> grpc_aio.Server:
    """Create an async gRPC server from UseCaseAppConfig.

    Each UseCaseService becomes a gRPC service, each ``@query``/``@mutation``
    method becomes a unary RPC. Request/response bodies are JSON-encoded bytes.

    Args:
        config: A ``UseCaseAppConfig`` with services.
        host: Bind address. Defaults to ``[::]`` (all interfaces).
        port: Listen port. Defaults to 50051.

    Returns:
        A ``grpc.aio.Server`` instance. Call ``await server.start()`` to start.

    Example::

        server = create_use_case_grpc_server(
            UseCaseAppConfig(name="project", services=[UserService]),
            port=50051,
        )
        await server.start()
        await server.wait_for_termination()
    """
    if not isinstance(config, UseCaseAppConfig):
        raise TypeError("config must be a UseCaseAppConfig")

    manager = UseCaseManager([config])
    app = manager.apps[config.name]

    server = grpc_aio.server()
    server.add_generic_rpc_handlers(
        (_UseCaseServiceHandler(app),)
    )
    server.add_insecure_port(f"{host}:{port}")

    return server
