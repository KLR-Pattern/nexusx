"""Auto-generate FastAPI routers from UseCaseService definitions.

Provides ``create_router()`` to generate POST routes for all ``@query``/``@mutation``
methods in a ``UseCaseAppConfig``, with proper OpenAPI documentation and
``FromContext`` parameter injection via FastAPI ``Depends``.
"""

import inspect
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, create_model

from nexusx.use_case.business import USE_CASE_METHODS_ATTR, UseCaseService, get_return_type
from nexusx.use_case.context import FromContext
from nexusx.use_case.types import UseCaseAppConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CAMEL_TO_SNAKE_RE = re.compile(r"(?<!^)(?=[A-Z])")

# Keys ``create_router`` always passes explicitly to ``add_api_route``; letting
# callers override them via ``route_options`` would raise a confusing
# "multiple values for keyword argument" TypeError.
_RESERVED_ROUTE_KEYS = frozenset({"endpoint", "methods"})


def _camel_to_snake(name: str) -> str:
    """PascalCase / camelCase -> snake_case."""
    return _CAMEL_TO_SNAKE_RE.sub("_", name).lower()


def _service_to_url_segment(service_cls: type[UseCaseService]) -> str:
    """UserService -> user_service."""
    return _camel_to_snake(service_cls.__name__)


def _is_from_context(annotation: Any) -> bool:
    """Return True if the annotation is Annotated[..., FromContext()]."""
    if get_origin(annotation) is Annotated:
        for arg in get_args(annotation):
            if isinstance(arg, FromContext):
                return True
    return False


def _unwrap_from_context_type(annotation: Any) -> Any:
    """Extract the inner type from Annotated[T, FromContext()]."""
    args = get_args(annotation)
    return args[0] if args else annotation


def _classify_params(
    sig: inspect.Signature,
    hints: dict[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    """Split method parameters into body params and FromContext params.

    Returns:
        (body_param_names, {context_param_name: unwrapped_type})
    """
    body_params: list[str] = []
    context_params: dict[str, Any] = {}

    for name, param in sig.parameters.items():
        if name == "cls":
            continue
        hint = hints.get(name, param.annotation)
        if _is_from_context(hint):
            context_params[name] = _unwrap_from_context_type(hint)
        else:
            body_params.append(name)

    return body_params, context_params


def _build_request_model(
    service_cls: type[UseCaseService],
    method_name: str,
    body_params: list[str],
    hints: dict[str, Any],
    sig: inspect.Signature,
) -> type[BaseModel]:
    """Dynamically create a Pydantic model for the POST body."""
    fields: dict[str, Any] = {}
    for pname in body_params:
        anno = hints.get(pname, sig.parameters[pname].annotation)
        if anno is inspect.Parameter.empty:
            anno = Any

        default = sig.parameters[pname].default
        if default is inspect.Parameter.empty:
            fields[pname] = (anno, ...)
        else:
            fields[pname] = (anno, default)

    snake = _camel_to_snake(method_name)
    model_name = f"{service_cls.__name__}{snake.title().replace('_', '')}Request"
    return create_model(model_name, **fields)


def _get_from_context_params(method: Any) -> set[str]:
    """Return parameter names annotated with FromContext."""
    params: set[str] = set()
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
                    params.add(name)
                    break
    return params


# ---------------------------------------------------------------------------
# Handler factory
# ---------------------------------------------------------------------------


def _make_context_extractor_dep(
    context_extractor: Callable[[Any], dict[str, Any] | Awaitable[dict[str, Any]]],
) -> Callable[..., Any]:
    """Create a FastAPI dependency that calls context_extractor with Request."""

    async def extract_context(request: Request) -> dict[str, Any]:
        result = context_extractor(request)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, dict):
            raise HTTPException(
                status_code=500,
                detail="context_extractor must return a dict",
            )
        return result

    return extract_context


def _merge_context_params(
    kwargs: dict[str, Any],
    context_params: dict[str, Any],
    ctx: dict[str, Any],
) -> None:
    """Resolve ``FromContext`` parameters from *ctx* into *kwargs* in place.

    Raises HTTP 400 if a required context parameter is missing from *ctx*.
    ``body_params`` and ``context_params`` are disjoint by construction (see
    ``_classify_params``), so context params never collide with body params.
    """
    for pname in context_params:
        if pname in ctx:
            kwargs[pname] = ctx[pname]
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Required context parameter '{pname}' not provided",
            )


def _make_handler(
    method: Any,
    request_model: type[BaseModel] | None,
    body_params: list[str],
    context_extractor: Callable[[Any], dict[str, Any] | Awaitable[dict[str, Any]]]
    | None,
    context_params: dict[str, Any],
) -> Callable[..., Any]:
    """Create an async route handler for a single use case method."""
    # NOTE: This function dynamically creates handlers with varying signatures
    # depending on whether the use case method has body params and/or FromContext
    # params.  mypy cannot verify the conditional branches, hence the coarse
    # ``type: ignore`` comments below.

    # Build context dependency if needed
    if context_params and context_extractor is not None:
        extract_ctx = _make_context_extractor_dep(context_extractor)
        ctx_dep: Any = Depends(extract_ctx)
    else:
        ctx_dep = None

    if request_model is not None and ctx_dep is not None:
        # Case 1: body + FromContext
        async def handler(
            body: request_model,  # type: ignore[valid-type]
            ctx: dict[str, Any] = ctx_dep,
        ) -> Any:
            # Use attribute access instead of body.model_dump() so nested
            # BaseModel instances are preserved (issue #107).
            kwargs: dict[str, Any] = {p: getattr(body, p) for p in body_params}
            _merge_context_params(kwargs, context_params, ctx)
            return await method(**kwargs)

    elif request_model is not None:
        # Case 2: body only
        async def handler(  # type: ignore[misc]
            body: request_model,  # type: ignore[valid-type]
        ) -> Any:
            # Use attribute access instead of body.model_dump() so nested
            # BaseModel instances are preserved (issue #107).
            kwargs = {p: getattr(body, p) for p in body_params}
            return await method(**kwargs)

    elif ctx_dep is not None:
        # Case 3: FromContext only
        async def handler(  # type: ignore[misc]
            ctx: dict[str, Any] = ctx_dep,
        ) -> Any:
            kwargs: dict[str, Any] = {}
            _merge_context_params(kwargs, context_params, ctx)
            return await method(**kwargs)

    else:
        # Case 4: no parameters
        async def handler() -> Any:  # type: ignore[misc]
            return await method()

    return handler


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_router(
    config: UseCaseAppConfig,
    prefix: str = "/api",
    url_mapper: Callable[[type[UseCaseService]], str] | None = None,
    *,
    dependencies: Sequence[Any] | None = None,
    route_options: dict[str, dict[str, Any]] | None = None,
    **router_kwargs: Any,
) -> APIRouter:
    """Create a FastAPI APIRouter from a UseCaseAppConfig.

    Generates one POST route per ``@query``/``@mutation`` method discovered
    on each service in *config.services*. Routes are grouped by service
    name (snake_case by default) under *prefix*.

    Args:
        config: A ``UseCaseAppConfig`` with services, context_extractor, etc.
        prefix: URL prefix for all generated routes (default ``"/api"``).
        url_mapper: Optional callable to customize per-service URL segment.
            Receives the service class, returns a string.
            Defaults to snake_case of the class name.
        dependencies: Router-level dependencies applied to **all** routes
            (e.g. ``[Depends(require_auth)]``). Passed directly to
            ``APIRouter(dependencies=...)``.
        route_options: Per-route overrides keyed by
            ``"ServiceName.method_name"``. Values are merged into
            ``add_api_route()`` kwargs, so you can set ``status_code``,
            ``dependencies``, ``response_model``, ``responses``, etc.
            Example::

                {
                    "UserService.create_user": {
                        "status_code": 201,
                        "dependencies": [Depends(require_admin)],
                    },
                }
        **router_kwargs: Additional keyword arguments forwarded to the
            ``APIRouter()`` constructor (e.g. ``default_response_class``,
            ``responses``, ``deprecated``).

    Returns:
        A ``fastapi.APIRouter`` ready to be included in a FastAPI app.

    Example::

        router = create_router(
            UseCaseAppConfig(
                name="project",
                services=[UserService, TaskService],
            ),
        )
        app.include_router(router)
    """
    router = APIRouter(dependencies=dependencies, **router_kwargs)

    for service_cls in config.services:
        tag = service_cls.get_tag_name()
        service_url = (
            url_mapper(service_cls)
            if url_mapper
            else _service_to_url_segment(service_cls)
        )

        methods = getattr(service_cls, USE_CASE_METHODS_ATTR, {})
        for method_name, meta in methods.items():
            kind = meta.get("kind", "query") if isinstance(meta, dict) else "query"
            description = (
                meta.get("description", "") if isinstance(meta, dict) else ""
            )

            # Skip mutations when disabled
            if not config.enable_mutation and kind == "mutation":
                continue

            method = getattr(service_cls, method_name)

            # Introspect method signature
            try:
                hints = get_type_hints(method, include_extras=True)
            except Exception:
                hints = {}

            sig = inspect.signature(method)

            # Classify parameters
            body_params, context_params = _classify_params(sig, hints)

            # Build request model if there are body parameters
            request_model = (
                _build_request_model(
                    service_cls, method_name, body_params, hints, sig
                )
                if body_params
                else None
            )

            # Create handler
            handler = _make_handler(
                method=method,
                request_model=request_model,
                body_params=body_params,
                context_extractor=config.context_extractor,
                context_params=context_params,
            )

            # Set handler metadata. The closures above are all named ``handler``;
            # give them meaningful names so tracebacks, logs, and FastAPI's
            # generated operation_ids reflect the originating use case.
            handler.__doc__ = description or method_name
            handler.__name__ = method_name
            handler.__qualname__ = f"{service_cls.__name__}.{method_name}"

            # Determine return type
            return_type = get_return_type(method)

            # Build path
            path = f"{prefix}/{service_url}/{method_name}"

            # Register route
            route_kwargs: dict[str, Any] = {
                "path": path,
                "tags": [tag],
                "summary": description or method_name,
            }
            if return_type is not None:
                route_kwargs["response_model"] = return_type

            # Merge per-route overrides from route_options
            route_key = f"{service_cls.__name__}.{method_name}"
            overrides = (route_options or {}).get(route_key)
            if overrides:
                reserved = _RESERVED_ROUTE_KEYS & overrides.keys()
                if reserved:
                    raise ValueError(
                        f"route_options[{route_key!r}] cannot override "
                        f"reserved keys (set by the router itself): "
                        f"{sorted(reserved)}"
                    )
                route_kwargs.update(overrides)

            router.add_api_route(
                endpoint=handler,
                methods=["POST"],
                **route_kwargs,
            )

    return router
