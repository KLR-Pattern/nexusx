"""Python → GraphQL type mapping for UseCase compose schemas.

Forked from ``nexusx.type_converter`` (see specs/001-usecase-graphql-mcp/
research.md R2 for rationale). The general-purpose ``type_converter`` is
SQLModel/SQLAlchemy-aware (``is_mapped_wrapper()``, ``is_relationship()``);
UseCase compose schemas only ever see Pydantic models + Python scalars + enums,
and dragging SQLAlchemy coupling into that path would violate the
"two modes are orthogonal" principle.

Naming conventions (``Int``, ``[T!]!``, ``Boolean`` etc.) intentionally match
``type_converter`` so users moving between SQLModel-driven GraphQL and
UseCase-driven GraphQL don't encounter surprises.

Public surface:
- ``ComposeTypeMapper`` — accumulates ``TypeInfo`` definitions as it maps
  Python types; call ``.map_python_type(...)`` for each method parameter /
  return type, then read ``.registry``.
- ``is_from_context_annotation(annotation)`` — detect
  ``Annotated[T, FromContext(...)]`` so the schema builder can filter these
  parameters out of the public schema.
"""

from __future__ import annotations

import dataclasses
import datetime
import enum
import types
import uuid
from typing import Annotated, Any, Union, get_args, get_origin, get_type_hints

from pydantic import BaseModel
from pydantic.fields import FieldInfo as PydanticFieldInfo

from nexusx.use_case.compose_schema import (
    ArgumentInfo,
    DuplicateTypeError,
    EnumValueInfo,
    FieldInfo,
    SQLModelInDtoFieldError,
    TypeInfo,
    TypeRef,
    UnsupportedTypeError,
    list_of,
    non_null,
)

__all__ = ["ComposeTypeMapper", "is_from_context_annotation"]


# Custom scalars emitted to SDL as ``scalar <Name>``. Kept aligned with the
# existing ``type_converter.py`` scalar naming so cross-mode queries behave
# consistently. ``DateTime`` / ``Date`` / ``Time`` mirror graphql-core's
# built-in scalar names where one exists.
_SCALAR_NAMES: dict[type, str] = {
    int: "Int",
    float: "Float",
    str: "String",
    bool: "Boolean",
    uuid.UUID: "UUID",
    datetime.datetime: "DateTime",
    datetime.date: "Date",
    datetime.time: "Time",
}

_SCALAR_DESCRIPTIONS: dict[str, str] = {
    "Int": "32-bit integer scalar.",
    "Float": "Double-precision floating-point scalar.",
    "String": "UTF-8 string scalar.",
    "Boolean": "true / false boolean scalar.",
    "ID": "Unique identifier scalar (serialized as string).",
    "UUID": "RFC 4122 UUID scalar (serialized as canonical string).",
    "DateTime": "ISO-8601 datetime scalar.",
    "Date": "ISO-8601 date scalar.",
    "Time": "ISO-8601 time scalar.",
}

# Built-in types we deliberately refuse to map. ``bytes`` / ``Decimal`` /
# ``dict`` / ``set`` etc. could plausibly be added later but are intentionally
# out of scope for v1; raising now produces a clearer message than silently
# falling through to a wrong GraphQL type.
_UNSUPPORTED_BUILTIN_TYPES: tuple[type, ...] = (bytes,)


def is_from_context_annotation(annotation: Any) -> bool:
    """Return ``True`` when ``annotation`` is ``Annotated[T, FromContext(...)]``.

    Migrated from the legacy ``use_case/server.py`` inline check. Kept as a
    standalone helper so the schema builder and the executor share one source
    of truth for the ``FromContext`` detection rule.
    """
    # Local import keeps the marker class out of the module-import graph for
    # callers that only want scalar mapping.
    from nexusx.use_case.context import FromContext

    if get_origin(annotation) is not Annotated:
        return False
    metadata = get_args(annotation)[1:]
    return any(isinstance(meta, FromContext) for meta in metadata)


class ComposeTypeMapper:
    """Accumulates ``TypeInfo`` definitions while mapping Python types.

    Usage:
        mapper = ComposeTypeMapper()
        ref = mapper.map_python_type(SomePydanticModel)  # registers TypeInfo
        mapper.map_python_type(list[int])                 # no registration needed
        registry = mapper.registry                        # all collected TypeInfos

    The same Python class referenced from multiple method signatures is
    registered exactly once (dedup by ``id(cls)``). Two distinct Python
    classes that produce the same GraphQL name raise ``DuplicateTypeError``.
    """

    def __init__(self) -> None:
        self._registry: dict[str, TypeInfo] = {}
        self._by_python_id: dict[int, TypeInfo] = {}

    @property
    def registry(self) -> dict[str, TypeInfo]:
        """Read-only snapshot of accumulated TypeInfo definitions."""
        return dict(self._registry)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def map_python_type(self, py_type: Any) -> TypeRef:
        """Map a Python type to a ``TypeRef``.

        Wraps non-Optional / non-list types in NON_NULL (i.e. ``T`` → ``T!``).
        Callers wanting nullable semantics must pass ``Optional[T]`` or
        ``T | None``.

        Raises:
            UnsupportedTypeError: for bytes/Decimal/Any/dict/tuple/etc.
            SQLModelInDtoFieldError: if a Pydantic field type is a SQLModel
                entity (``__table__`` set). Also fires if a SQLModel entity is
                used directly as a method return type — by convention services
                return DTOs (DefineSubset subclasses), not entities.
            DuplicateTypeError: if two distinct Python classes produce the
                same GraphQL name.
        """
        return self._map(py_type, force_nullable=False)

    def map_python_type_as_input(self, py_type: Any) -> TypeRef:
        """Map a Python type for use as a method-argument (input) type ref.

        Same wrapping / nullability rules as ``map_python_type``, but a
        ``BaseModel`` leaf registers as ``INPUT_OBJECT`` (with ``input_fields``
        populated and pydantic defaults surfaced as literals) instead of
        ``OBJECT``. Use this for ``@query`` / ``@mutation`` argument type
        refs — never for return types.

        When the same BaseModel class is also registered as ``OBJECT`` from a
        return type, the input version is renamed ``{Name}Input`` so the
        GraphQL spec's "type name uniquely identifies kind" rule holds.
        Scalars, enums, and container wrappers (``list``/``Optional``) are
        unaffected by the input flag.
        """
        return self._map(py_type, force_nullable=False, is_input=True)

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    def _map(self, py_type: Any, force_nullable: bool, *, is_input: bool = False) -> TypeRef:
        """Recursive mapper.

        ``force_nullable=True`` means we are inside an ``Optional`` and must
        NOT wrap the result in NON_NULL. Propagates down through containers
        so e.g. ``Optional[list[T]]`` produces ``[T!]`` (nullable list,
        non-null elements), matching the rules in data-model.md D3.

        ``is_input=True`` propagates to ``_map_leaf`` so a BaseModel leaf
        registers as INPUT_OBJECT instead of OBJECT (use this for method-arg
        type refs, not return types). Scalars and enums are unaffected.
        """
        py_type = _strip_annotated(py_type)
        origin = get_origin(py_type)

        # Optional[T] / T | None  (PEP 604 union or typing.Union[T, None])
        if origin is Union or isinstance(py_type, types.UnionType):
            return self._map_optional(py_type, is_input=is_input)

        # list[T] / typing.List[T]
        if origin is list:
            return self._map_list(py_type, force_nullable=force_nullable, is_input=is_input)

        # tuple — reject, fixed-size tuples aren't idiomatic GraphQL
        if origin is tuple:
            raise UnsupportedTypeError(
                f"Tuple types are not supported; got {py_type!r}. Use list[T]."
            )

        # Other typing generics (dict, set, frozenset, etc.)
        if origin is not None:
            raise UnsupportedTypeError(
                f"Generic type {py_type!r} is not supported in compose schemas. "
                "Supported containers: list[T], Optional[T]."
            )

        # Leaf type (scalar / enum / Pydantic)
        leaf_ref = self._map_leaf(py_type, is_input=is_input)
        return leaf_ref if force_nullable else non_null(leaf_ref)

    def _map_optional(self, py_type: Any, *, is_input: bool = False) -> TypeRef:
        """Map ``Optional[T]`` / ``T | None`` to a nullable ``TypeRef``.

        Multiple non-None args (e.g. ``Union[A, B]``) are rejected — only
        ``Optional`` / ``X | None`` is supported.
        """
        args = [a for a in get_args(py_type) if a is not type(None)]
        if len(args) != 1:
            raise UnsupportedTypeError(
                f"Union types beyond Optional[T] are not supported; got {py_type!r}"
            )
        return self._map(args[0], force_nullable=True, is_input=is_input)

    def _map_list(self, py_type: Any, force_nullable: bool, *, is_input: bool = False) -> TypeRef:
        """Map ``list[T]`` / ``typing.List[T]`` to ``[T!]!``.

        The list itself is NON_NULL by default. ``Optional[list[T]]`` produces
        ``[T!]`` (caller passes ``force_nullable=True``). Elements follow the
        nullability of ``T`` itself: ``list[T]`` → ``[T!]!``,
        ``list[Optional[T]]`` → ``[T]!``.
        """
        args = get_args(py_type)
        if not args:
            raise UnsupportedTypeError(
                f"Bare ``list`` without a parameter type is not supported; got {py_type!r}"
            )
        inner_ref = self._map(args[0], force_nullable=False, is_input=is_input)
        list_ref = list_of(inner_ref)
        return list_ref if force_nullable else non_null(list_ref)

    def _map_leaf(self, py_type: Any, *, is_input: bool = False) -> TypeRef:
        """Map a leaf Python type to a TypeRef, registering TypeInfo as needed."""
        # ``None`` / ``type(None)`` should never reach here from well-formed
        # signatures, but be defensive rather than crashing deep inside _register.
        if py_type is None or py_type is type(None):
            raise UnsupportedTypeError(
                "None is not a valid GraphQL type; did you forget a return annotation?"
            )

        # ``Any`` / ``object`` — explicit reject to avoid silent String fallback
        if py_type is Any or py_type is object:
            raise UnsupportedTypeError(
                "``Any`` / ``object`` are not supported; specify a concrete type."
            )

        if not isinstance(py_type, type):
            raise UnsupportedTypeError(
                f"Type {py_type!r} is not a class and cannot be mapped to GraphQL."
            )

        # Unsupported builtins
        if issubclass(py_type, _UNSUPPORTED_BUILTIN_TYPES):
            raise UnsupportedTypeError(
                f"{py_type.__name__} is not supported in compose schemas."
            )

        # SQLModel entity (table=True) — forbidden by project convention.
        # DTOs (DefineSubset subclasses) are plain BaseModel and pass.
        self._reject_sqlmodel_entity(py_type)

        # Scalars
        if py_type in _SCALAR_NAMES:
            name = _SCALAR_NAMES[py_type]
            self._register_scalar(name)
            return TypeRef(kind="SCALAR", name=name)

        # Enums
        if issubclass(py_type, enum.Enum):
            return TypeRef(kind="ENUM", name=self._register_enum(py_type))

        # Pydantic models — dispatch on is_input so arg-side BaseModel leaves
        # register as INPUT_OBJECT (with input_fields populated) instead of OBJECT.
        if issubclass(py_type, BaseModel):
            if is_input:
                return TypeRef(
                    kind="INPUT_OBJECT", name=self._register_input_object(py_type)
                )
            return TypeRef(kind="OBJECT", name=self._register_object(py_type))

        raise UnsupportedTypeError(
            f"Type {py_type!r} is not supported in compose schemas. "
            "Supported: scalars (int/float/str/bool/UUID/datetime), enums, "
            "Pydantic BaseModel subclasses, and list/Optional wrappers."
        )

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def _register_scalar(self, name: str) -> None:
        if name in self._registry:
            return
        self._registry[name] = TypeInfo(
            name=name, kind="SCALAR", description=_SCALAR_DESCRIPTIONS.get(name)
        )

    def _register_enum(self, cls: type[enum.Enum]) -> str:
        name = cls.__name__
        existing = self._by_python_id.get(id(cls))
        if existing is not None:
            return existing.name
        if name in self._registry:
            raise DuplicateTypeError(
                f"Two distinct enum classes share the GraphQL name '{name}'. "
                "Rename one of them so each GraphQL type maps to one Python class."
            )
        info = TypeInfo(
            name=name,
            kind="ENUM",
            description=_clean_docstring(cls.__doc__),
            enum_values=tuple(
                EnumValueInfo(
                    name=member.name,
                    description=_clean_docstring(member.__doc__),
                )
                for member in cls
            ),
        )
        self._registry[name] = info
        self._by_python_id[id(cls)] = info
        return name

    def _register_object(self, cls: type[BaseModel]) -> str:
        name = cls.__name__
        existing = self._by_python_id.get(id(cls))
        if existing is not None:
            return existing.name
        if name in self._registry:
            raise DuplicateTypeError(
                f"Two distinct Pydantic classes share the GraphQL name '{name}'. "
                "Rename one of them so each GraphQL type maps to one Python class."
            )
        # Pre-register a stub so self-references (``parent: Self | None``) and
        # mutual references (``A.b: B`` / ``B.a: A``) short-circuit at the
        # ``_by_python_id`` memo above instead of recursing forever. Fields are
        # filled in after the walk via ``dataclasses.replace`` — TypeInfo is frozen.
        stub = TypeInfo(
            name=name,
            kind="OBJECT",
            description=_clean_docstring(cls.__doc__),
            fields=(),
            python_class=cls,
        )
        self._registry[name] = stub
        self._by_python_id[id(cls)] = stub
        fields = tuple(
            self._build_field_info(fname, ftype, cls)
            for fname, ftype in _iter_field_types(cls)
        )
        finalized = dataclasses.replace(stub, fields=fields)
        self._registry[name] = finalized
        self._by_python_id[id(cls)] = finalized
        return name

    def _register_input_object(self, cls: type[BaseModel]) -> str:
        """Register ``cls`` as a GraphQL INPUT_OBJECT and return its registry name.

        Mirrors ``_register_object`` but produces ``kind="INPUT_OBJECT"`` with
        ``input_fields`` populated from the pydantic model's fields (each as an
        ``ArgumentInfo`` carrying pydantic defaults as GraphQL literals).

        Rename-on-conflict: if ``cls.__name__`` is already taken in ``_registry``
        AND the existing entry has ``python_class is cls`` AND ``kind == "OBJECT"``,
        the existing entry is the return-side registration of the SAME class —
        rename the input version to ``{Name}Input`` so both can coexist per the
        GraphQL spec's "type name uniquely identifies kind" rule. Two distinct
        classes sharing a name still raise ``DuplicateTypeError`` (existing
        guard preserved).

        Idempotency for the input codepath is scan-based (linear lookup of
        ``python_class is cls`` among INPUT_OBJECTs) rather than keyed on
        ``_by_python_id`` — that map tracks OBJECT registrations only, so the
        same class can be referenced from both kinds without one clobbering
        the other's id slot. Input registrations are rare (only method args),
        so the scan cost is negligible.

        Load-bearing: callers MUST ensure all return-side OBJECT registrations
        happen before any arg-side INPUT_OBJECT registration — otherwise the
        bare name is still free when the input registers, no rename fires, and
        the subsequent return registration raises ``DuplicateTypeError``.
        ``build_compose_schema`` enforces this via its two-phase structure.
        """
        # Idempotency: same class already registered as INPUT_OBJECT.
        for existing in self._registry.values():
            if existing.kind == "INPUT_OBJECT" and existing.python_class is cls:
                return existing.name

        name = cls.__name__
        bare_collision = self._registry.get(name)
        if bare_collision is not None:
            if bare_collision.python_class is cls and bare_collision.kind == "OBJECT":
                # Same class already registered as OBJECT (return-side) — rename
                # the input version so both can coexist per the GraphQL spec.
                name = f"{name}Input"
            else:
                # Two distinct classes share __name__, OR the bare name was
                # already won by an INPUT_OBJECT (return-phase wasn't run first).
                # Either way, keep the existing guard.
                raise DuplicateTypeError(
                    f"Two distinct Pydantic classes share the GraphQL name "
                    f"'{cls.__name__}'. Rename one of them so each GraphQL "
                    f"type maps to one Python class."
                )

        # Pre-register a stub so self/mutual references on the input side
        # (e.g. a tree-filter INPUT_OBJECT with a ``children: Self`` field)
        # short-circuit at the idempotency scan at the top of this method.
        stub = TypeInfo(
            name=name,
            kind="INPUT_OBJECT",
            description=_clean_docstring(cls.__doc__),
            input_fields=(),
            python_class=cls,
        )
        self._registry[name] = stub
        input_fields = tuple(
            self._build_input_field_info(fname, ftype, cls)
            for fname, ftype in _iter_field_types(cls)
        )
        finalized = dataclasses.replace(stub, input_fields=input_fields)
        self._registry[name] = finalized
        # Intentionally NOT updating _by_python_id — it tracks OBJECT only.
        return name

    def _build_input_field_info(
        self, field_name: str, field_type: Any, cls: type[BaseModel]
    ) -> ArgumentInfo:
        """Build an ``ArgumentInfo`` for one pydantic field of an INPUT_OBJECT.

        ``has_default`` / ``default_value`` come from the pydantic FieldInfo.
        Mutable defaults (``default_factory``) are treated as "no static
        literal" (same as ``PydanticUndefined``) — they're not representable
        as a GraphQL literal.
        """
        from pydantic_core import PydanticUndefined  # late import — module-load cycle guard

        description = _field_description(field_type)
        pydantic_field = cls.model_fields.get(field_name)
        if pydantic_field is None:
            has_default = False
            default_value = None
        else:
            has_default = (
                not pydantic_field.is_required()
                and pydantic_field.default is not PydanticUndefined
                # default_factory means "computed per-call" — no static literal.
                and pydantic_field.default_factory is None
            )
            default_value = pydantic_field.default if has_default else None

        return ArgumentInfo(
            name=field_name,
            type_ref=self.map_python_type_as_input(field_type),
            has_default=has_default,
            default_value=default_value,
            description=description,
        )

    def _build_field_info(
        self, field_name: str, field_type: Any, cls: type[BaseModel]
    ) -> FieldInfo:
        # Description can come from two sources in Pydantic v2:
        #   - Annotated metadata: ``x: Annotated[int, Field(description="...")]``
        #   - Default value FieldInfo: ``x: int = Field(description="...")``
        # Prefer Annotated (explicit); fall back to model_fields[fname].description.
        description = _field_description(field_type)
        if description is None:
            pydantic_field = cls.model_fields.get(field_name)
            if pydantic_field is not None and pydantic_field.description:
                description = pydantic_field.description
        return FieldInfo(
            name=field_name,
            type_ref=self.map_python_type(field_type),
            description=description,
        )

    def _reject_sqlmodel_entity(self, py_type: type) -> None:
        """Reject SQLModel entities (``table=True`` classes) in compose schemas.

        DTOs created via ``DefineSubset`` are plain ``BaseModel`` subclasses
        and pass through. SQLModel entities are forbidden by project convention
        #7 (see CLAUDE.md); a service that returns entities should return DTOs
        instead.
        """
        try:
            from sqlmodel import SQLModel
        except ImportError:  # pragma: no cover — sqlmodel is a hard dep
            return
        if not issubclass(py_type, SQLModel):
            return
        if getattr(py_type, "__table__", None) is not None:
            raise SQLModelInDtoFieldError(
                f"{py_type.__name__} is a SQLModel entity (table=True). "
                "Compose schemas only accept Pydantic DTO types (BaseModel "
                "subclasses, e.g. DefineSubset DTOs). Define a DTO that "
                "subsets the entity and use it as the return / field type."
            )


# ---------------------------------------------------------------------------
# Module-private helpers
# ---------------------------------------------------------------------------


def _strip_annotated(py_type: Any) -> Any:
    """Peel one layer of ``Annotated[T, ...]`` if present."""
    if get_origin(py_type) is Annotated:
        return get_args(py_type)[0]
    return py_type


def _iter_field_types(cls: type[BaseModel]) -> list[tuple[str, Any]]:
    """Return ``[(field_name, annotation), ...]`` for a Pydantic model.

    Order follows ``cls.model_fields`` (Pydantic v2 preserves declaration
    order) so SDL field order matches user intent.
    """
    try:
        hints = get_type_hints(cls, include_extras=True)
    except Exception:  # noqa: BLE001 — fall back to Pydantic's own view
        hints = {fname: finfo.annotation for fname, finfo in cls.model_fields.items()}
    return [(fname, hints[fname]) for fname in cls.model_fields if fname in hints]


def _field_description(field_type: Any) -> str | None:
    """Extract a Pydantic ``Field(description=...)`` value from an Annotated hint."""
    if get_origin(field_type) is not Annotated:
        return None
    for meta in get_args(field_type)[1:]:
        if isinstance(meta, PydanticFieldInfo) and meta.description:
            return meta.description
    return None


def _clean_docstring(doc: str | None) -> str | None:
    """Trim leading/trailing whitespace from a class/member docstring.

    Returns None for empty/None input so TypeInfo.description stays None
    rather than carrying an empty string (cleaner SDL output).
    """
    if not doc:
        return None
    stripped = doc.strip()
    return stripped or None
