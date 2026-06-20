"""UseCase GraphQL compose schema — type definitions and errors.

This module hosts the data primitives shared by the schema builder
(`build_compose_schema`), the SDL/introspection renderers, and the executor.

Design rationale (see specs/001-usecase-graphql-mcp/research.md R1):
- We model the schema as a custom `dict[str, TypeInfo]` registry, NOT a
  graphql-core `GraphQLSchema`. The registry is isomorphic to graphql
  introspection's `__schema` payload, so `render_introspection()` is a near
  trivial transformation, and the resulting JSON round-trips through
  `graphql.build_schema(...)` for GraphiQL compatibility.
- `TypeRef` matches graphql introspection `__Type`'s recursive shape: leaf
  kinds (SCALAR/OBJECT/ENUM/INPUT_OBJECT) carry a `name`; wrapper kinds
  (NON_NULL/LIST) carry `of_type`.

All dataclasses here are frozen + slotted: a `ComposeSchema` is built once at
server startup and treated as readonly thereafter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = [
    "TypeRef",
    "TypeInfo",
    "FieldInfo",
    "ArgumentInfo",
    "EnumValueInfo",
    "non_null",
    "list_of",
    "nullable",
    "TypeKind",
    "WrapperKind",
    "LeafKind",
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
    """Wrap ``t`` in a LIST type reference. The element type should already be
    NON_NULL for typical ``[T!]!`` semantics — callers handle that explicitly."""
    return TypeRef(kind="LIST", of_type=t)


def nullable(t: TypeRef) -> TypeRef:
    """Identity helper for symmetry with ``non_null``. Use to signal intent at
    call sites where a type is intentionally nullable."""
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
    """Definition of a leaf GraphQL type (SCALAR / OBJECT / ENUM / INPUT_OBJECT).

    Exactly one of ``fields`` / ``enum_values`` / ``input_fields`` is populated
    depending on ``kind``. SCALAR types have all three empty (they carry just a
    ``name`` + ``description`` + optional ``specified_by_url``).
    """

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
    """Base for all ComposeSchema construction errors.

    Raised eagerly at ``build_compose_schema(...)`` time so misconfigurations
    surface at server startup, not at query execution.
    """


class DuplicateServiceError(ComposeSchemaError):
    """Two services in the same app share a name."""


class DuplicateMethodError(ComposeSchemaError):
    """Two methods in the same service share a name."""


class DuplicateTypeError(ComposeSchemaError):
    """Two distinct Python classes produced the same GraphQL type name.

    The compose schema requires each named GraphQL type to map to exactly one
    Python class. Different classes with the same ``__name__`` (e.g. two DTOs
    both called ``Summary`` in different modules) cannot be disambiguated and
    fail at construction.
    """


class UnsupportedTypeError(ComposeSchemaError):
    """A Python type in a method signature cannot be mapped to GraphQL.

    Examples: ``bytes``, ``Decimal``, ``dict[str, Any]``, ``Any``, ``*args``,
    ``**kwargs``. v1 of the compose schema deliberately keeps the type language
    small (scalars + enums + Pydantic models + ``list``/``Optional`` wrappers).
    """


class SQLModelInDtoFieldError(ComposeSchemaError):
    """A DTO field is annotated with a SQLModel entity class.

    By long-standing nexusx convention (see project CLAUDE.md "常见陷阱 #7"),
    DTO fields must be DTO types (Pydantic models), not SQLModel entities.
    The compose schema enforces this at construction so the failure is loud.
    """


class MissingReturnAnnotationError(ComposeSchemaError):
    """A ``@query`` / ``@mutation`` method lacks a return type annotation.

    GraphQL requires every field to declare its output type; without a Python
    return annotation we cannot derive one and refuse to guess.
    """
