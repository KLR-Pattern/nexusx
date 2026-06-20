"""UseCase GraphQL compose schema — type definitions, errors, builder, and renderer.

This module hosts the data primitives shared by the schema builder
(`build_compose_schema`), the SDL/introspection renderers, and the executor.

Design rationale (see specs/001-usecase-graphql-mcp/research.md R1):
- We model the schema as a custom `dict[str, TypeInfo]` registry, NOT a
  graphql-core `GraphQLSchema`. The registry is isomorphic to graphql
  introspection's `__schema` payload, so `render_introspection()` is a near
  trivial transformation, and the resulting JSON round-trips through
  graphql-core's `build_client_schema(...)` for GraphiQL compatibility.
- `TypeRef` matches graphql introspection `__Type`'s recursive shape: leaf
  kinds (SCALAR/OBJECT/ENUM/INPUT_OBJECT) carry a `name`; wrapper kinds
  (NON_NULL/LIST) carry `of_type`.

All dataclasses here are frozen + slotted: a `ComposeSchema` is built once at
server startup and treated as readonly thereafter.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Literal, get_type_hints

__all__ = [
    "TypeRef",
    "TypeInfo",
    "FieldInfo",
    "ArgumentInfo",
    "EnumValueInfo",
    "ComposeSchema",
    "non_null",
    "list_of",
    "nullable",
    "TypeKind",
    "WrapperKind",
    "LeafKind",
    "build_compose_schema",
    "ComposeSchemaError",
    "DuplicateServiceError",
    "DuplicateMethodError",
    "DuplicateTypeError",
    "UnsupportedTypeError",
    "SQLModelInDtoFieldError",
    "MissingReturnAnnotationError",
]


LeafKind = Literal["SCALAR", "OBJECT", "ENUM", "INPUT_OBJECT"]
WrapperKind = Literal["NON_NULL", "LIST"]
TypeKind = Literal["SCALAR", "OBJECT", "ENUM", "INPUT_OBJECT", "NON_NULL", "LIST"]


@dataclass(frozen=True, slots=True)
class TypeRef:
    """Reference to a GraphQL type.

    Mirrors graphql introspection ``__Type``. Leaf kinds (SCALAR/OBJECT/ENUM/
    INPUT_OBJECT) set ``name``; wrapper kinds (NON_NULL/LIST) set ``of_type``.
    """

    kind: TypeKind
    name: str | None = None
    of_type: TypeRef | None = None


def non_null(t: TypeRef) -> TypeRef:
    """Wrap ``t`` in a NON_NULL type reference."""
    return TypeRef(kind="NON_NULL", of_type=t)


def list_of(t: TypeRef) -> TypeRef:
    """Wrap ``t`` in a LIST type reference."""
    return TypeRef(kind="LIST", of_type=t)


def nullable(t: TypeRef) -> TypeRef:
    """Identity helper for symmetry with ``non_null``."""
    return t


@dataclass(frozen=True, slots=True)
class ArgumentInfo:
    """A method parameter surfaced as a GraphQL field argument.

    ``is_from_context=True`` marks parameters that are ``Annotated[T, FromContext()]``
    — these are **not** exposed in the GraphQL schema; the value is injected at
    execution time via ``context_extractor``. The flag is kept here for
    internal bookkeeping so the executor can re-derive the mapping without
    re-introspecting the Python signature.
    """

    name: str
    type_ref: TypeRef
    has_default: bool = False
    default_value: Any = None
    description: str | None = None
    is_from_context: bool = False


@dataclass(frozen=True, slots=True)
class FieldInfo:
    """A GraphQL OBJECT field.

    For UseCase compose schemas, fields are either:
    - Root Query/Mutation service entry points (e.g. ``TaskService: TaskServiceQuery!``)
    - Service-type method entry points (e.g. ``list_tasks: [TaskSummary!]!``)
    - DTO data fields (e.g. ``id: Int!``)
    """

    name: str
    type_ref: TypeRef
    description: str | None = None
    args: tuple[ArgumentInfo, ...] = field(default_factory=tuple)
    deprecation_reason: str | None = None


@dataclass(frozen=True, slots=True)
class EnumValueInfo:
    """A single value of a GraphQL ENUM type."""

    name: str
    description: str | None = None
    deprecation_reason: str | None = None


@dataclass(frozen=True, slots=True)
class TypeInfo:
    """Definition of a leaf GraphQL type (SCALAR / OBJECT / ENUM / INPUT_OBJECT)."""

    name: str
    kind: LeafKind
    description: str | None = None
    fields: tuple[FieldInfo, ...] = field(default_factory=tuple)
    enum_values: tuple[EnumValueInfo, ...] = field(default_factory=tuple)
    input_fields: tuple[ArgumentInfo, ...] = field(default_factory=tuple)
    specified_by_url: str | None = None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ComposeSchemaError(Exception):
    """Base for all ComposeSchema construction errors."""


class DuplicateServiceError(ComposeSchemaError):
    """Two services in the same app share a name."""


class DuplicateMethodError(ComposeSchemaError):
    """Two methods in the same service share a name."""


class DuplicateTypeError(ComposeSchemaError):
    """Two distinct Python classes produced the same GraphQL type name."""


class UnsupportedTypeError(ComposeSchemaError):
    """A Python type in a method signature cannot be mapped to GraphQL."""


class SQLModelInDtoFieldError(ComposeSchemaError):
    """A DTO field is annotated with a SQLModel entity class."""


class MissingReturnAnnotationError(ComposeSchemaError):
    """A ``@query`` / ``@mutation`` method lacks a return type annotation."""


# ---------------------------------------------------------------------------
# ComposeSchema + build_compose_schema
# ---------------------------------------------------------------------------


class ComposeSchema:
    """UseCaseService-derived GraphQL schema artifact.

    Built once (eagerly at server startup), treated as readonly thereafter.
    Renders three views over the same registry:
    - ``render_introspection()`` — graphql introspection ``__schema`` payload
      (GraphiQL-compatible, round-trips through graphql-core).
    - ``render_sdl()`` — full SDL string.
    - ``render_method_sdl(service, method)`` — single-method SDL fragment
      with transitive closure of the return type.
    """

    __slots__ = ("_app_name", "_registry", "_has_mutation")

    def __init__(
        self,
        app_name: str,
        registry: dict[str, TypeInfo],
        has_mutation: bool,
    ) -> None:
        self._app_name = app_name
        # Defensive copy so callers can't mutate us via the dict they passed in.
        self._registry: dict[str, TypeInfo] = dict(registry)
        self._has_mutation = has_mutation

    @property
    def app_name(self) -> str:
        return self._app_name

    @property
    def registry(self) -> dict[str, TypeInfo]:
        """Read-only snapshot of TypeInfo definitions."""
        return dict(self._registry)

    @property
    def has_mutation(self) -> bool:
        """True if the schema has a root Mutation type."""
        return self._has_mutation

    def render_sdl(self) -> str:
        """Full SDL string covering the entire registry."""
        return _render_sdl(self._registry, self._has_mutation)

    def render_introspection(self) -> dict[str, Any]:
        """graphql introspection ``__schema`` payload (no outer ``data`` wrap).

        The returned structure is what graphql-core's ``build_client_schema``
        expects under ``data.__schema``.
        """
        return _render_introspection(self._registry, self._has_mutation)

    def render_method_sdl(self, service_name: str, method_name: str) -> str | None:
        """Single-method SDL fragment (method field + return type transitive closure).

        Returns ``None`` when the service or method is not found, so callers
        can produce a friendly "not found" error without try/except.
        """
        return _render_method_sdl(
            self._registry, service_name, method_name, self._has_mutation
        )


def build_compose_schema(app: Any) -> ComposeSchema:
    """Derive a ``ComposeSchema`` from a ``UseCaseAppConfig``.

    Walks each ``UseCaseService`` subclass in ``app.services`` and constructs:
    - ``{Service}Query`` OBJECT type with one field per ``@query`` method
    - ``{Service}Mutation`` OBJECT type (when mutations exist) with one field
      per ``@mutation`` method
    - Root ``Query`` OBJECT type with one field per service
    - Root ``Mutation`` OBJECT type (only when at least one service has a
      mutation method AND ``app.enable_mutation`` is True)

    Failures surface eagerly (startup, not query time):
    - duplicate service names → ``DuplicateServiceError``
    - duplicate method names within a service → ``DuplicateMethodError``
    - methods missing return annotation → ``MissingReturnAnnotationError``
    - DTO fields referencing SQLModel entities → ``SQLModelInDtoFieldError``
    - unsupported Python types → ``UnsupportedTypeError`` (via mapper)
    - distinct classes sharing a GraphQL name → ``DuplicateTypeError``
    """
    # Local imports keep this module's import graph small at module load.
    from nexusx.use_case.business import UseCaseService
    from nexusx.use_case.compose_type_mapper import ComposeTypeMapper

    mapper = ComposeTypeMapper()

    seen_service_names: set[str] = set()
    seen_method_signatures: set[tuple[str, str]] = set()
    service_query_fields: list[FieldInfo] = []
    service_mutation_fields: list[FieldInfo] = []
    has_mutation = False

    for service_cls in app.services:
        if not isinstance(service_cls, type) or not issubclass(service_cls, UseCaseService):
            raise ComposeSchemaError(
                f"Service {service_cls!r} is not a UseCaseService subclass."
            )

        service_name = service_cls.__name__
        if service_name in seen_service_names:
            raise DuplicateServiceError(
                f"Service name '{service_name}' appears more than once in "
                f"app '{app.name}'. Rename one of the service classes."
            )
        seen_service_names.add(service_name)

        query_fields, mutation_fields = _build_service_fields(
            service_cls=service_cls,
            mapper=mapper,
            seen_signatures=seen_method_signatures,
            enable_mutation=app.enable_mutation,
        )

        if query_fields:
            service_query_type = TypeInfo(
                name=f"{service_name}Query",
                kind="OBJECT",
                description=f"Query entry points for {service_name}.",
                fields=tuple(query_fields),
            )
            mapper._registry[service_query_type.name] = service_query_type
            service_query_fields.append(
                FieldInfo(
                    name=service_name,
                    type_ref=non_null(
                        TypeRef(kind="OBJECT", name=service_query_type.name)
                    ),
                    description=service_cls.__doc__,
                )
            )

        if mutation_fields:
            has_mutation = True
            service_mutation_type = TypeInfo(
                name=f"{service_name}Mutation",
                kind="OBJECT",
                description=f"Mutation entry points for {service_name}.",
                fields=tuple(mutation_fields),
            )
            mapper._registry[service_mutation_type.name] = service_mutation_type
            service_mutation_fields.append(
                FieldInfo(
                    name=service_name,
                    type_ref=non_null(
                        TypeRef(kind="OBJECT", name=service_mutation_type.name)
                    ),
                    description=service_cls.__doc__,
                )
            )

    root_query = TypeInfo(
        name="Query",
        kind="OBJECT",
        description="Root of the UseCase compose schema.",
        fields=tuple(service_query_fields),
    )
    mapper._registry["Query"] = root_query

    if has_mutation and service_mutation_fields:
        root_mutation = TypeInfo(
            name="Mutation",
            kind="OBJECT",
            description="Root Mutation type.",
            fields=tuple(service_mutation_fields),
        )
        mapper._registry["Mutation"] = root_mutation

    return ComposeSchema(
        app_name=app.name,
        registry=mapper._registry,
        has_mutation=bool(service_mutation_fields),
    )


def _build_service_fields(
    service_cls: type,
    mapper: Any,
    seen_signatures: set[tuple[str, str]],
    enable_mutation: bool,
) -> tuple[list[FieldInfo], list[FieldInfo]]:
    """Walk ``service_cls.__use_case_methods__`` and build (query_fields, mutation_fields).

    Filters mutations when ``enable_mutation`` is False. Validates return
    annotations. Detects duplicate (service, method) signatures.
    """
    from nexusx.use_case.compose_type_mapper import is_from_context_annotation

    methods = getattr(service_cls, "__use_case_methods__", {})
    query_fields: list[FieldInfo] = []
    mutation_fields: list[FieldInfo] = []

    for method_name, meta in methods.items():
        kind = meta.get("kind", "query")
        method = meta["method"]
        unwrapped = inspect.unwrap(method)
        func = unwrapped.__func__ if hasattr(unwrapped, "__func__") else unwrapped

        signature_key = (service_cls.__name__, method_name)
        if signature_key in seen_signatures:
            raise DuplicateMethodError(
                f"Method '{method_name}' appears twice on service "
                f"'{service_cls.__name__}'."
            )
        seen_signatures.add(signature_key)

        if kind == "mutation" and not enable_mutation:
            continue

        return_type = _get_return_type(func, service_cls, method_name)
        if return_type is None:
            raise MissingReturnAnnotationError(
                f"Method '{service_cls.__name__}.{method_name}' has no return "
                "type annotation. All @query/@mutation methods must declare "
                "their return type so it can be surfaced in the GraphQL schema."
            )

        return_ref = mapper.map_python_type(return_type)
        args = _build_method_arguments(func, mapper, is_from_context_annotation)

        field_info = FieldInfo(
            name=method_name,
            type_ref=return_ref,
            description=meta.get("description"),
            args=tuple(args),
        )
        if kind == "mutation":
            mutation_fields.append(field_info)
        else:
            query_fields.append(field_info)

    return query_fields, mutation_fields


def _get_return_type(func: Any, service_cls: type, method_name: str) -> Any:
    """Extract the return annotation of ``func``.

    Returns ``None`` when no annotation is present or annotation is ``type(None)``.
    Uses ``get_type_hints`` to resolve forward references.
    """
    try:
        hints = get_type_hints(func, include_extras=True)
    except Exception:  # noqa: BLE001 — fall back to raw __annotations__
        hints = getattr(func, "__annotations__", {}) or {}
    return_type = hints.get("return")
    if return_type is type(None):
        return None
    return return_type


def _build_method_arguments(
    func: Any,
    mapper: Any,
    is_from_context_annotation: Any,
) -> list[ArgumentInfo]:
    """Build ``ArgumentInfo`` per parameter.

    Skips:
    - ``cls`` (classmethod receiver)
    - ``*args`` / ``**kwargs`` (no GraphQL representation; raises UnsupportedTypeError)
    - ``Annotated[T, FromContext()]`` parameters (not surfaced in the public
      schema — the executor re-introspects the method signature at query
      time to know which params need context injection)

    The remaining parameters become public GraphQL field arguments.
    """
    sig = inspect.signature(func)
    args: list[ArgumentInfo] = []
    try:
        hints = get_type_hints(func, include_extras=True)
    except Exception:  # noqa: BLE001
        hints = {}

    for name, param in sig.parameters.items():
        if name == "cls":
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            raise UnsupportedTypeError(
                f"Method '{func.__qualname__}' uses *args / **kwargs which are "
                "not supported in compose schemas."
            )
        annotation = hints.get(name, param.annotation)
        if annotation is inspect.Parameter.empty:
            raise UnsupportedTypeError(
                f"Parameter '{name}' of '{func.__qualname__}' has no type "
                "annotation. Compose schema requires all parameters to be "
                "annotated."
            )
        # FromContext params are not part of the public schema. The executor
        # re-discovers them at query time via is_from_context_annotation.
        if is_from_context_annotation(annotation):
            continue
        has_default = param.default is not inspect.Parameter.empty
        type_ref = mapper.map_python_type(annotation)
        args.append(
            ArgumentInfo(
                name=name,
                type_ref=type_ref,
                has_default=has_default,
                default_value=param.default if has_default else None,
                description=None,
            )
        )
    return args


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _type_ref_to_sdl(ref: TypeRef) -> str:
    """Render a TypeRef as an SDL type expression (e.g. ``[Int!]!``)."""
    if ref.kind == "NON_NULL":
        assert ref.of_type is not None
        return f"{_type_ref_to_sdl(ref.of_type)}!"
    if ref.kind == "LIST":
        assert ref.of_type is not None
        return f"[{_type_ref_to_sdl(ref.of_type)}]"
    # Leaf
    assert ref.name is not None
    return ref.name


def _render_sdl(registry: dict[str, TypeInfo], has_mutation: bool) -> str:
    """Full SDL covering the entire registry."""
    lines: list[str] = []
    # Order: scalars → enums → DTOs (alphabetical) → service types → root Query → root Mutation
    scalars = sorted(
        (t for t in registry.values() if t.kind == "SCALAR"),
        key=lambda t: t.name,
    )
    enums = sorted(
        (t for t in registry.values() if t.kind == "ENUM"),
        key=lambda t: t.name,
    )
    reserved = {"Query", "Mutation"}
    service_type_suffixes = ("Query", "Mutation")
    dto_types = sorted(
        (
            t
            for t in registry.values()
            if t.kind == "OBJECT"
            and t.name not in reserved
            and not any(
                t.name.endswith(suffix) and t.name[: -len(suffix)].isidentifier()
                for suffix in service_type_suffixes
            )
        ),
        key=lambda t: t.name,
    )
    service_types = sorted(
        (
            t
            for t in registry.values()
            if t.kind == "OBJECT"
            and t.name not in reserved
            and any(t.name.endswith(suffix) for suffix in service_type_suffixes)
            and not t.name.startswith("Query")
            and not t.name.startswith("Mutation")
        ),
        key=lambda t: t.name,
    )

    for scalar in scalars:
        lines.append(f'scalar {scalar.name}')
        if scalar.description:
            lines.insert(-1, f'"""{scalar.description}"""')
    for en in enums:
        if en.description:
            lines.append(f'"""{en.description}"""')
        lines.append(f'enum {en.name} {{')
        for v in en.enum_values:
            lines.append(f'  {v.name}')
        lines.append('}')
        lines.append('')
    for obj in dto_types + service_types:
        if obj.description:
            lines.append(f'"""{obj.description}"""')
        lines.append(f'type {obj.name} {{')
        for f in obj.fields:
            arg_str = ""
            if f.args:
                arg_str = '(' + ", ".join(
                    f"{a.name}: {_type_ref_to_sdl(a.type_ref)}"
                    + (f" = {_sdl_literal(a.default_value)}" if a.has_default else "")
                    for a in f.args
                ) + ")"
            lines.append(f'  {f.name}{arg_str}: {_type_ref_to_sdl(f.type_ref)}')
        lines.append('}')
        lines.append('')
    root_query = registry.get("Query")
    if root_query is not None:
        lines.append('type Query {')
        for f in root_query.fields:
            lines.append(f'  {f.name}: {_type_ref_to_sdl(f.type_ref)}')
        lines.append('}')
        lines.append('')
    if has_mutation:
        root_mutation = registry.get("Mutation")
        if root_mutation is not None:
            lines.append('type Mutation {')
            for f in root_mutation.fields:
                lines.append(f'  {f.name}: {_type_ref_to_sdl(f.type_ref)}')
            lines.append('}')
            lines.append('')
    return "\n".join(lines).rstrip() + "\n"


def _sdl_literal(value: Any) -> str:
    """Render a Python value as an SDL literal (``"x"``, ``5``, ``true``, ``null``)."""
    import enum
    import json

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, enum.Enum):
        return value.name
    if isinstance(value, (int, float, str)):
        return json.dumps(value)
    return json.dumps(repr(value))


def _json_default(value: Any) -> Any:
    """``json.dumps`` ``default`` hook for values graphql introspection can't natively encode.

    Handles enum members (by name — graphql expects the ENUM value name) and
    falls back to ``str()`` for anything else exotic.
    """
    import enum

    if isinstance(value, enum.Enum):
        return value.name
    return str(value)


def _render_introspection(registry: dict[str, TypeInfo], has_mutation: bool) -> dict[str, Any]:
    """graphql introspection ``__schema`` payload."""
    types_payload = [_type_info_to_introspection(t) for t in registry.values()]
    return {
        "queryType": {"name": "Query"},
        "mutationType": {"name": "Mutation"} if has_mutation else None,
        "subscriptionType": None,
        "types": types_payload,
        "directives": [],
    }


def _type_info_to_introspection(t: TypeInfo) -> dict[str, Any]:
    """Convert one TypeInfo to the graphql introspection ``__Type`` shape."""
    payload: dict[str, Any] = {
        "kind": t.kind,
        "name": t.name,
        "description": t.description,
        "specifiedByURL": t.specified_by_url,
    }
    if t.kind == "OBJECT":
        payload["fields"] = [_field_to_introspection(f) for f in t.fields]
        payload["inputFields"] = None
        payload["enumValues"] = None
        payload["interfaces"] = []
    elif t.kind == "INPUT_OBJECT":
        payload["fields"] = None
        payload["inputFields"] = [
            _arg_to_introspection(a) for a in t.input_fields
        ]
        payload["enumValues"] = None
        payload["interfaces"] = []
    elif t.kind == "ENUM":
        payload["fields"] = None
        payload["inputFields"] = None
        payload["enumValues"] = [
            {
                "name": v.name,
                "description": v.description,
                "isDeprecated": v.deprecation_reason is not None,
                "deprecationReason": v.deprecation_reason,
            }
            for v in t.enum_values
        ]
        payload["interfaces"] = None
    else:  # SCALAR
        payload["fields"] = None
        payload["inputFields"] = None
        payload["enumValues"] = None
        payload["interfaces"] = None
    return payload


def _field_to_introspection(f: FieldInfo) -> dict[str, Any]:
    return {
        "name": f.name,
        "description": f.description,
        "args": [_arg_to_introspection(a) for a in f.args],
        "type": _type_ref_to_introspection(f.type_ref),
        "isDeprecated": f.deprecation_reason is not None,
        "deprecationReason": f.deprecation_reason,
    }


def _arg_to_introspection(a: ArgumentInfo) -> dict[str, Any]:
    import json

    return {
        "name": a.name,
        "description": a.description,
        "type": _type_ref_to_introspection(a.type_ref),
        "defaultValue": (
            json.dumps(a.default_value, default=_json_default) if a.has_default else None
        ),
    }


def _type_ref_to_introspection(ref: TypeRef) -> dict[str, Any]:
    """Recursive TypeRef → graphql introspection __Type (with ofType nesting)."""
    if ref.kind in ("NON_NULL", "LIST"):
        assert ref.of_type is not None
        return {
            "kind": ref.kind,
            "name": None,
            "ofType": _type_ref_to_introspection(ref.of_type),
        }
    assert ref.name is not None
    return {
        "kind": ref.kind,
        "name": ref.name,
        "ofType": None,
    }


def _render_method_sdl(
    registry: dict[str, TypeInfo],
    service_name: str,
    method_name: str,
    has_mutation: bool,
) -> str | None:
    """Single-method SDL: {Service}Query (or Mutation) with just the method,
    plus the transitive closure of the return type's OBJECT/ENUM/SCALAR types."""
    # Try Query first, then Mutation.
    query_type_name = f"{service_name}Query"
    mutation_type_name = f"{service_name}Mutation"

    method_field: FieldInfo | None = None
    owning_type_name: str | None = None

    query_type = registry.get(query_type_name)
    if query_type is not None:
        for f in query_type.fields:
            if f.name == method_name:
                method_field = f
                owning_type_name = query_type_name
                break

    if method_field is None:
        mutation_type = registry.get(mutation_type_name)
        if mutation_type is not None:
            for f in mutation_type.fields:
                if f.name == method_name:
                    method_field = f
                    owning_type_name = mutation_type_name
                    break

    if method_field is None or owning_type_name is None:
        return None

    # Collect transitive closure of types reachable from method_field.type_ref.
    closure_names: set[str] = set()
    _collect_closure(method_field.type_ref, registry, closure_names)

    # Build the filtered service-type (only the one method).
    owning_type = registry[owning_type_name]
    filtered_service_type = TypeInfo(
        name=owning_type.name,
        kind="OBJECT",
        description=owning_type.description,
        fields=(method_field,),
    )

    # Render: service type first, then closure types (excluding the service type
    # itself, and excluding the root Query/Mutation).
    excluded = {"Query", "Mutation", owning_type_name}
    closure_types = sorted(
        (registry[n] for n in closure_names if n not in excluded),
        key=lambda t: t.name,
    )

    lines: list[str] = []
    _emit_type_sdl(filtered_service_type, lines)
    lines.append("")
    for t in closure_types:
        _emit_type_sdl(t, lines)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _collect_closure(
    ref: TypeRef,
    registry: dict[str, TypeInfo],
    visited: set[str],
) -> None:
    """Walk the TypeRef, registering all reachable type names in ``visited``."""
    if ref.kind in ("NON_NULL", "LIST"):
        assert ref.of_type is not None
        _collect_closure(ref.of_type, registry, visited)
        return
    assert ref.name is not None
    if ref.name in visited:
        return
    info = registry.get(ref.name)
    if info is None:
        return
    visited.add(ref.name)
    if info.kind == "OBJECT":
        for f in info.fields:
            _collect_closure(f.type_ref, registry, visited)
        # Also walk arg types (rare for DTOs but correct)
        for f in info.fields:
            for arg in f.args:
                _collect_closure(arg.type_ref, registry, visited)
    # SCALAR / ENUM / INPUT_OBJECT: leaf, no further recursion needed.


def _emit_type_sdl(t: TypeInfo, lines: list[str]) -> None:
    """Append one type's SDL block to ``lines``."""
    if t.description:
        lines.append(f'"""{t.description}"""')
    if t.kind == "SCALAR":
        lines.append(f'scalar {t.name}')
        return
    if t.kind == "ENUM":
        lines.append(f'enum {t.name} {{')
        for v in t.enum_values:
            lines.append(f'  {v.name}')
        lines.append('}')
        return
    keyword = "type" if t.kind == "OBJECT" else "input"
    lines.append(f'{keyword} {t.name} {{')
    for f in t.fields:
        arg_str = ""
        if f.args:
            arg_str = '(' + ", ".join(
                f"{a.name}: {_type_ref_to_sdl(a.type_ref)}"
                + (f" = {_sdl_literal(a.default_value)}" if a.has_default else "")
                for a in f.args
            ) + ")"
        lines.append(f'  {f.name}{arg_str}: {_type_ref_to_sdl(f.type_ref)}')
    lines.append('}')
