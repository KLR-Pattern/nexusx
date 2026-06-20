"""Executor for UseCase compose GraphQL queries.

Receives a standard GraphQL query string and returns ``{data, errors}`` per
graphql convention. Layered strictly on top of ``ComposeSchema`` and the
existing ``QueryParser`` / ``subset.build_subset_model`` — no new infrastructure.

Execution contract (spec FR-004a, research.md R5):
- Service methods are invoked directly with kwargs derived from GraphQL args
  plus ``FromContext`` values pulled from the caller-supplied ``context`` dict.
- The executor does **NOT** wrap results in ``Resolver()``. Service methods
  own that responsibility (they call ``Resolver().resolve(dtos)`` themselves
  when they want auto-load / post_* / Collector semantics).
- After each method returns, results are projected via
  ``subset.build_subset_model`` so only the requested fields are serialized.

Introspection queries (``__schema``, ``__type``, ``__typename``) are rejected
with a hint pointing to ``describe_compose_schema`` /
``describe_compose_method`` (spec FR-008). Rejection happens at AST level
before any service method is invoked.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from graphql import DocumentNode, FieldNode, OperationDefinitionNode, parse
from pydantic import BaseModel, TypeAdapter

from nexusx.query_parser import FieldSelection, QueryParser
from nexusx.use_case.business import UseCaseService
from nexusx.use_case.compose_schema import ComposeSchema
from nexusx.use_case.compose_type_mapper import is_from_context_annotation
from nexusx.use_case.selection import build_subset_model
from nexusx.use_case.types import UseCaseAppConfig

__all__ = [
    "execute_compose_query",
    "is_introspection_query",
    "compose_introspect",
]


_INTROSPECTION_REJECTION_HINT = (
    "GraphQL introspection is not available via compose_query. "
    "Use describe_compose_schema(app_name=...) and "
    "describe_compose_method(app_name=..., service_name=..., method_name=...) "
    "to discover the schema."
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_introspection_query(query: str) -> bool:
    """Return True if the query references any GraphQL introspection field.

    Detection is AST-level (post ``graphql.parse``) so it survives comments
    and string literals that merely contain ``__schema`` as text.
    """
    try:
        document = parse(query)
    except Exception:  # noqa: BLE001 — invalid query will be re-reported by the executor
        return False
    return _document_uses_introspection(document)


async def execute_compose_query(
    app: UseCaseAppConfig,
    schema: ComposeSchema,
    query: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a UseCase compose query, returning graphql-standard ``{data, errors}``.

    Layer-3 entry point of the 4-layer progressive-disclosure MCP. ``app`` and
    ``schema`` are pre-built by the MCP server factory (eager construction at
    startup); ``context`` is the dict returned by ``app.context_extractor``.

    Args:
        app: The ``UseCaseAppConfig`` the query targets.
        schema: The ``ComposeSchema`` derived from ``app``.
        query: Standard GraphQL query string.
        context: ``FromContext`` parameter values, keyed by parameter name.

    Returns:
        ``{"data": <nested service→method→result>, "errors": []}`` on success;
        ``{"data": null, "errors": [...]}`` on any failure (parse, introspection
        rejection, service exception, missing context, etc.).
    """
    # 1. Parse query → AST.
    try:
        document = parse(query)
    except Exception as exc:  # noqa: BLE001 — graphql parse errors vary in shape
        return _error_response(f"Failed to parse query: {exc}")

    # 2. Reject introspection (FR-008) before any service call.
    if _document_uses_introspection(document):
        return _error_response(_INTROSPECTION_REJECTION_HINT)

    # 3. Convert AST → FieldSelection tree (reuses existing QueryParser).
    parser = QueryParser()
    selections = parser.parse_document(document)
    if not selections:
        return _error_response("Query has no operations.")

    # 4. For each operation, plan + execute.
    try:
        data = await _execute_operations(app, schema, selections, context or {})
    except _ComposeExecutionError as exc:
        return _error_response(str(exc), exc.service_method)
    except Exception as exc:  # noqa: BLE001 — surface as graphql error, not 500
        return _error_response(f"{type(exc).__name__}: {exc}")

    return {"data": data, "errors": []}


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


class _ComposeExecutionError(Exception):
    """Internal control-flow exception carrying service/method context."""

    def __init__(self, message: str, service_method: str | None = None) -> None:
        super().__init__(message)
        self.service_method = service_method


async def _execute_operations(
    app: UseCaseAppConfig,
    schema: ComposeSchema,
    selections: dict[str, FieldSelection],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Run every operation in ``selections`` and return the nested data dict.

    For v1 simplicity: operations are executed sequentially. Within an
    operation, ``@query`` methods run concurrently via ``asyncio.gather`` and
    ``@mutation`` methods run serially in query-declaration order. This mirrors
    pydantic-resolve's compose executor.
    """
    services_by_name: dict[str, type[UseCaseService]] = {
        cls.__name__: cls for cls in app.services
    }

    data: dict[str, Any] = {}
    for _op_name, root_sel in selections.items():
        # Each root FieldSelection's sub_fields are the service selections.
        for service_name, service_sel in root_sel.sub_fields.items():
            service_cls = services_by_name.get(service_name)
            if service_cls is None:
                raise _ComposeExecutionError(
                    f"Service '{service_name}' not found in app '{app.name}'. "
                    f"Available: {sorted(services_by_name)}.",
                    service_method=service_name,
                )
            method_results = await _execute_service_methods(
                app=app,
                schema=schema,
                service_cls=service_cls,
                service_sel=service_sel,
                context=context,
            )
            data[service_name] = method_results
    return data


async def _execute_service_methods(
    app: UseCaseAppConfig,
    schema: ComposeSchema,
    service_cls: type[UseCaseService],
    service_sel: FieldSelection,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Run each method selection under one service and return {method: result}."""
    methods = getattr(service_cls, "__use_case_methods__", {})

    # Bucket methods by kind so we can run queries concurrently and mutations serially.
    query_tasks: list[tuple[str, Awaitable[Any]]] = []
    mutation_specs: list[tuple[str, FieldSelection]] = []
    for method_name, method_sel in service_sel.sub_fields.items():
        meta = methods.get(method_name)
        if meta is None:
            raise _ComposeExecutionError(
                f"Method '{service_cls.__name__}.{method_name}' not found.",
                service_method=f"{service_cls.__name__}.{method_name}",
            )
        kind = meta.get("kind", "query")
        if kind == "mutation" and not app.enable_mutation:
            raise _ComposeExecutionError(
                f"Method '{service_cls.__name__}.{method_name}' is a mutation, "
                f"but app '{app.name}' has enable_mutation=False.",
                service_method=f"{service_cls.__name__}.{method_name}",
            )
        if kind == "mutation":
            mutation_specs.append((method_name, method_sel))
        else:
            query_tasks.append(
                (method_name, _invoke_and_project(
                    app=app,
                    schema=schema,
                    service_cls=service_cls,
                    method_name=method_name,
                    method_sel=method_sel,
                    context=context,
                ))
            )

    results: dict[str, Any] = {}

    # Queries: concurrent.
    if query_tasks:
        names = [n for n, _ in query_tasks]
        awaitables = [a for _, a in query_tasks]
        values = await asyncio.gather(*awaitables)
        for name, value in zip(names, values, strict=True):
            results[name] = value

    # Mutations: serial in declaration order.
    for method_name, method_sel in mutation_specs:
        results[method_name] = await _invoke_and_project(
            app=app,
            schema=schema,
            service_cls=service_cls,
            method_name=method_name,
            method_sel=method_sel,
            context=context,
        )

    return results


async def _invoke_and_project(
    app: UseCaseAppConfig,
    schema: ComposeSchema,
    service_cls: type[UseCaseService],
    method_name: str,
    method_sel: FieldSelection,
    context: dict[str, Any],
) -> Any:
    """Invoke one method, then project its result via subset.build_subset_model."""
    # ``service_cls.__use_case_methods__[name]["method"]`` is the raw
    # classmethod descriptor captured during BusinessMeta — calling it
    # directly raises ``TypeError: 'classmethod' object is not callable``.
    # ``getattr(service_cls, method_name)`` returns the class-bound method
    # whose ``cls`` is already supplied, so the kwargs we build (which omit
    # ``cls``) match the signature exactly.
    method = getattr(service_cls, method_name)

    kwargs = _build_kwargs(
        method=method,
        graphql_args=method_sel.arguments,
        context=context,
        qualname=f"{service_cls.__name__}.{method_name}",
    )

    try:
        result = await method(**kwargs)
    except Exception as exc:  # noqa: BLE001 — surface as graphql error
        raise _ComposeExecutionError(
            f"{service_cls.__name__}.{method_name} raised "
            f"{type(exc).__name__}: {exc}",
            service_method=f"{service_cls.__name__}.{method_name}",
        ) from exc

    return _project_result(
        schema=schema,
        service_name=service_cls.__name__,
        method_name=method_name,
        result=result,
        method_sel=method_sel,
    )


def _build_kwargs(
    method: Callable[..., Any],
    graphql_args: dict[str, Any],
    context: dict[str, Any],
    qualname: str,
) -> dict[str, Any]:
    """Combine GraphQL args + FromContext values into the method's kwargs."""
    unwrapped = inspect.unwrap(method)
    func = unwrapped.__func__ if hasattr(unwrapped, "__func__") else unwrapped
    sig = inspect.signature(func)
    hints = _safe_hints(func)

    kwargs: dict[str, Any] = {}
    for name, param in sig.parameters.items():
        if name == "cls":
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        annotation = hints.get(name, param.annotation)
        if annotation is not inspect.Parameter.empty and is_from_context_annotation(annotation):
            # FromContext parameter — source value from context dict.
            if name in context:
                kwargs[name] = context[name]
            elif param.default is not inspect.Parameter.empty:
                # Leave default in place by not setting kwargs[name].
                pass
            else:
                raise _ComposeExecutionError(
                    f"Required FromContext parameter '{name}' on '{qualname}' "
                    f"not found in MCP context. Provide it via context_extractor.",
                    service_method=qualname,
                )
            continue
        # Regular GraphQL argument.
        if name in graphql_args:
            raw_value = graphql_args[name]
            kwargs[name] = _coerce_strict(raw_value, annotation, name, qualname)
        elif param.default is not inspect.Parameter.empty:
            pass  # leave default
        else:
            raise _ComposeExecutionError(
                f"Required argument '{name}' on '{qualname}' was not provided.",
                service_method=qualname,
            )

    # FromContext values also get coerced — extractors can return JSON-native
    # values (e.g. {"user_id": "42"} from a header) that need promotion to the
    # method's declared type.
    for name, value in list(kwargs.items()):
        annotation = hints.get(name, inspect.Parameter.empty)
        if annotation is inspect.Parameter.empty or value is None:
            continue
        if is_from_context_annotation(annotation):
            kwargs[name] = _coerce_strict(value, annotation, name, qualname)
    return kwargs


def _coerce_strict(
    value: Any, annotation: Any, arg_name: str, qualname: str
) -> Any:
    """Defensive type coercion via Pydantic TypeAdapter.

    ``QueryParser`` already converts graphql value nodes to native Python
    values (IntValueNode→int, etc.), but two gaps remain:
    - Custom scalars declared as Python types (``datetime``, ``UUID``, ``Decimal``)
      come through as strings from the GraphQL side and need promotion.
    - Pydantic ``BaseModel`` parameters: GraphQL object literals become dicts
      and need to be rebuilt as model instances.

    The coercion is best-effort: on failure we surface a graphql ``errors``
    entry naming the offending argument, rather than letting the method
    receive a mistyped value and crash deeper in the stack.

    Mirrors pydantic-resolve's ``_coerce_strict``.
    """
    if value is None:
        return None
    if annotation is inspect.Parameter.empty or annotation is None:
        return value
    try:
        return TypeAdapter(annotation).validate_python(value)
    except Exception as exc:  # noqa: BLE001 — re-surface as graphql error
        raise _ComposeExecutionError(
            f"Failed to coerce argument '{arg_name}' on '{qualname}' "
            f"to {annotation!r}: {exc}",
            service_method=qualname,
        ) from exc


def _safe_hints(func: Any) -> dict[str, Any]:
    """Best-effort type-hint resolution; tolerates forward-ref failures."""
    from typing import get_type_hints

    try:
        return get_type_hints(func, include_extras=True)
    except Exception:  # noqa: BLE001
        return dict(getattr(func, "__annotations__", {}) or {})


def _project_result(
    schema: ComposeSchema,
    service_name: str,
    method_name: str,
    result: Any,
    method_sel: FieldSelection,
) -> Any:
    """Project ``result`` to only the requested fields via subset.build_subset_model.

    Derives the leaf Pydantic model class from the live result (rather than
    from the schema registry) — simpler and avoids the registry needing to
    carry Python types alongside the GraphQL view.
    """
    if result is None:
        return None
    if not method_sel.sub_fields:
        # Scalar return (no sub-fields requested); nothing to project.
        return result

    leaf_model = _leaf_model_from_result(result)
    if leaf_model is None:
        return result

    subset_model = build_subset_model(leaf_model, method_sel)
    try:
        if isinstance(result, list):
            return [
                TypeAdapter(subset_model).validate_python(item)
                for item in result
            ]
        return TypeAdapter(subset_model).validate_python(result)
    except Exception:  # noqa: BLE001 — projection failure: return raw, don't crash
        return result


def _leaf_model_from_result(result: Any) -> type[BaseModel] | None:
    """Derive the leaf BaseModel class from a live result.

    Handles single instance, list of instances, and Optional. Returns None
    for non-BaseModel results (scalars, dicts).
    """
    if isinstance(result, BaseModel):
        return type(result)
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, BaseModel):
            return type(first)
    return None


def _document_uses_introspection(document: DocumentNode) -> bool:
    """Walk every selection in the document, return True if any field name starts with __."""
    for definition in document.definitions:
        if isinstance(definition, OperationDefinitionNode):
            if _selection_set_uses_introspection(definition.selection_set):
                return True
    return False


def _selection_set_uses_introspection(selection_set: Any) -> bool:
    for selection in selection_set.selections:
        if isinstance(selection, FieldNode):
            field_name = selection.name.value
            if field_name.startswith("__"):
                return True
            if selection.selection_set is not None:
                if _selection_set_uses_introspection(selection.selection_set):
                    return True
    return False


def _error_response(message: str, service_method: str | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"message": message}
    if service_method is not None:
        error["extensions"] = {"service_method": service_method}
    return {"data": None, "errors": [error]}


# ---------------------------------------------------------------------------
# compose_introspect — GraphiQL-compatible introspection handler
# ---------------------------------------------------------------------------

import re  # noqa: E402 — local import keeps the top of the file clean

_TYPE_NAME_RE = re.compile(r'__type\s*\(\s*name\s*:\s*["\']([^"\']+)["\']')


def compose_introspect(
    schema: ComposeSchema,
    query: str | None = None,
) -> dict[str, Any]:
    """Handle a GraphQL introspection query against ``schema``.

    Unlike ``execute_compose_query`` (which **rejects** introspection in
    Layer 3 to keep MCP responses compact), this function **services**
    introspection queries. It's intended for HTTP endpoints that want to
    host GraphiQL — GraphiQL opens by sending the canonical ``__schema``
    query, and needs the full introspection payload back.

    Dispatch by keyword (substring match on the query string, matching
    pydantic-resolve's behavior):

    - ``__schema`` (or ``query is None``) → full introspection payload
    - ``__type(name: "X")`` → single-type lookup
    - ``__typename`` → literal ``"Query"``

    Field-level selection inside ``__schema { ... }`` is **not** honored —
    GraphiQL only ever sends the canonical full introspection query, so the
    entire schema is returned.

    Returns:
        Standard graphql response envelope ``{"data": {...}, "errors": None}``.

    Raises:
        ComposeSchemaError: If ``schema`` carries no registry.
    """
    actual_query = query if query is not None else "__schema"
    data: dict[str, Any] = {}

    if "__schema" in actual_query:
        data["__schema"] = schema.render_introspection()

    if "__type" in actual_query:
        type_name = _extract_type_name_from_query(actual_query)
        if type_name is None:
            data["__type"] = None
        else:
            data["__type"] = _render_type_by_name(schema, type_name)

    if "__typename" in actual_query:
        data["__typename"] = "Query"

    return {"data": data, "errors": None}


def _extract_type_name_from_query(query: str) -> str | None:
    """Extract the type name from a ``__type(name: "X")`` query."""
    match = _TYPE_NAME_RE.search(query)
    return match.group(1) if match else None


def _render_type_by_name(schema: ComposeSchema, name: str) -> dict[str, Any] | None:
    """Look up one TypeInfo by name and render it as a graphql ``__Type`` payload."""
    info = schema.registry.get(name)
    if info is None:
        return None
    # Reuse the introspection renderer by filtering the registry down to one
    # type. Cheaper than a parallel renderer and keeps the shape consistent.
    from nexusx.use_case.compose_schema import _type_info_to_introspection

    return _type_info_to_introspection(info)
