"""Shared type conversion utilities for GraphQL schema generation."""

from __future__ import annotations

import types
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from nexusx import annotation_utils

# The single Python-type → GraphQL-scalar-name table (module-level so
# compose-side consumers can share it without importing the SQLModel-aware
# TypeConverter class — specs/001 R2 keeps that coupling out of compose).
SCALAR_TYPE_MAP: dict[Any, str] = {
    int: "Int",
    str: "String",
    bool: "Boolean",
    float: "Float",
    datetime: "DateTime",
    date: "Date",
    time: "Time",
    uuid.UUID: "UUID",
    # spec 026 / issue #160 DESIGN_1: a named custom scalar on BOTH paths.
    # Compose used to reject Decimal with a generic UnsupportedTypeError while
    # entity-first silently mapped it to String. Wire value is unchanged —
    # pydantic's model_dump(mode="json") already serialised Decimal as a string.
    Decimal: "Decimal",
}


# ---------------------------------------------------------------------------
# Scalar Literal support — single source for both GraphQL paths.
#
# GraphQL has no constrained-scalar kind, so ``Literal[X, ...]`` maps to the
# GraphQL scalar shared by its values; Pydantic stays responsible for
# enforcing the allowed values at runtime. The compose ``ComposeTypeMapper``
# (a fork of this module's behavior) and the entity-first SDL/introspection
# generators both consume these helpers so the mapping rules cannot drift
# between the two paths (nexusx #153).
# ---------------------------------------------------------------------------


def is_literal_annotation(annotation: Any) -> bool:
    """Return ``True`` when ``annotation`` is a ``Literal[...]`` leaf.

    Classification only, no validation — use :func:`literal_scalar_type`
    when the mapping (and its errors) is needed.
    """
    return get_origin(annotation) is Literal


def literal_scalar_type(annotation: Any) -> tuple[type, bool] | None:
    """Map a scalar ``Literal`` annotation to ``(scalar type, has_none)``.

    Returns ``None`` for non-Literal annotations. Raises ``ValueError`` for
    Literals that cannot map to a single GraphQL scalar: mixed value types,
    enum members (use the enum class directly), or all-``None`` — callers on
    the compose path translate this into ``UnsupportedTypeError`` verbatim so
    error messages stay identical on both paths.

    ``has_none`` is ``True`` when a ``None`` member inside the ``Literal``
    (or an ``Optional`` wrapper around it) makes the value nullable.
    """
    core = annotation
    if get_origin(core) is Annotated:
        args = get_args(core)
        core = args[0] if args else core
    origin = get_origin(core)
    if origin is Union or origin is types.UnionType:
        raw_args = get_args(core)
        non_none = [arg for arg in raw_args if arg is not type(None)]
        if len(non_none) != 1:  # a real union has no Literal leaf
            return None
        inner = literal_scalar_type(non_none[0])
        if inner is None:
            return None
        return inner[0], inner[1] or type(None) in raw_args
    if origin is not Literal:
        return None

    all_values = get_args(core)
    values = [value for value in all_values if value is not None]
    if not values:
        raise ValueError(f"Literal annotations must contain a non-None value; got {core!r}.")
    value_types = {type(value) for value in values}
    if len(value_types) != 1:
        names = ", ".join(sorted(value_type.__name__ for value_type in value_types))
        raise ValueError(f"Literal values must share one Python type; got {names} in {core!r}.")
    literal_type = next(iter(value_types))
    if literal_type not in SCALAR_TYPE_MAP:
        hint = (
            " Use the enum class directly instead of Literal[enum_member]."
            if issubclass(literal_type, Enum)
            else ""
        )
        raise ValueError(
            f"Literal values must use a supported scalar type; got "
            f"{literal_type.__name__} in {core!r}.{hint}"
        )
    return literal_type, len(values) != len(all_values)


def literal_allowed_values(annotation: Any) -> tuple[Any, ...] | None:
    """Return the allowed values of a scalar ``Literal`` annotation.

    Unwraps ``Annotated`` / ``Optional`` / ``list`` wrappers so field and
    argument descriptions can mention the constraint even though the GraphQL
    type is the plain underlying scalar — SDL has no constrained-scalar kind,
    so the description is where the values live for agents.
    """
    constraint = literal_constraint(annotation)
    return constraint[0] if constraint is not None else None


def literal_constraint(annotation: Any) -> tuple[tuple[Any, ...], bool] | None:
    """Return ``(non-None values, has_none)`` for a scalar ``Literal`` leaf.

    ``has_none`` tracks nullability from any layer: a ``None`` member inside
    the ``Literal`` itself, or an ``Optional``/``| None`` wrapper around it.
    The type mapper surfaces the same fact as a nullable TypeRef; descriptions
    need it so agents learn ``null`` is a legal input, not a violation.

    Lenient by design (unlike :func:`literal_scalar_type`): shapes without a
    Literal leaf — or with an unusable one — return ``None`` so description
    routing can call it unconditionally.
    """
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        if args:
            annotation = args[0]
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        raw_args = get_args(annotation)
        args = [arg for arg in raw_args if arg is not type(None)]
        if len(args) != 1:  # Optional[X] only — a real union has no Literal leaf
            return None
        inner = literal_constraint(args[0])
        if inner is None:
            return None
        return inner[0], inner[1] or type(None) in raw_args
    if origin is list:
        args = get_args(annotation)
        if args:
            return literal_constraint(args[0])
        return None
    if origin is Literal:
        values = get_args(annotation)
        non_none = tuple(value for value in values if value is not None)
        if not non_none:
            return None
        return non_none, None in values
    return None


def describe_literal_values(description: str | None, annotation: Any) -> str | None:
    """Append ``Allowed values: ...`` to a description for ``Literal`` annotations.

    No-op for annotations without a ``Literal`` leaf, so callers can route
    every field/argument description through it unconditionally. Booleans
    render lower-case (``true``/``false``) to match GraphQL literals, and a
    nullable constraint gains an ``(or null)`` tail.
    """
    constraint = literal_constraint(annotation)
    if constraint is None:
        return description
    values, has_none = constraint
    suffix = "Allowed values: " + ", ".join(_format_literal_value(v) for v in values)
    if has_none:
        suffix += " (or null)"
    if description:
        return f"{description} {suffix}"
    return suffix


def _format_literal_value(value: Any) -> str:
    """Render one allowed value the way GraphQL spells its literal."""
    return str(value).lower() if isinstance(value, bool) else str(value)


class TypeConverter:
    """Converts Python types to GraphQL type information.

    Used by both SDLGenerator and IntrospectionGenerator to eliminate
    code duplication in type inspection logic.
    """

    # Mapping from Python types to GraphQL scalar names — THE single source
    # (issue: type-mapping had 4 parallel implementations / 3 scalar tables;
    # compose_type_mapper and use_case/introspector now import this one).
    SCALAR_TYPE_MAP: dict[Any, str] = SCALAR_TYPE_MAP

    def __init__(self, entity_names: set[str]):
        """Initialize the type converter.

        Args:
            entity_names: Set of known entity class names.
        """
        self._entity_names = entity_names

    # Structural annotation predicates live in the leaf module
    # ``nexusx.annotation_utils`` (spec 026 R1 — one implementation for every
    # path); these methods stay as the entity-first-facing names.

    def is_optional(self, type_hint: Any) -> bool:
        """Check if type hint is Optional[T] (Union with None)."""
        return annotation_utils.is_optional(type_hint)

    def unwrap_optional(self, type_hint: Any) -> Any:
        """Extract T from Optional[T] (first non-None arm of a union)."""
        return annotation_utils.unwrap_optional(type_hint)

    def is_list_type(self, type_hint: Any) -> bool:
        """Check if type is list[T]."""
        return annotation_utils.is_list(type_hint)

    def get_list_inner_type(self, type_hint: Any) -> Any:
        """Extract T from list[T], handling Optional inside list."""
        return annotation_utils.list_inner(type_hint)

    def is_mapped_wrapper(self, type_hint: Any) -> bool:
        """Check if type is SQLAlchemy Mapped wrapper."""
        return annotation_utils.is_mapped_wrapper(type_hint)

    def unwrap_mapped(self, type_hint: Any) -> Any:
        """Extract inner type from Mapped[T]."""
        return annotation_utils.unwrap_mapped(type_hint)

    def get_scalar_type_name(self, type_hint: Any) -> str | None:
        """Get GraphQL scalar name (Int, String, etc.) or None if not a scalar."""
        return self.SCALAR_TYPE_MAP.get(type_hint)

    def is_enum_type(self, type_hint: Any) -> bool:
        """Check if type is an Enum subclass."""
        return isinstance(type_hint, type) and issubclass(type_hint, Enum)

    def is_entity_type(self, type_hint: Any) -> bool:
        """Check if type refers to a known entity."""
        # Handle forward reference (string)
        if isinstance(type_hint, str):
            return type_hint in self._entity_names

        # Handle class reference
        type_name = getattr(type_hint, "__name__", None)
        return type_name is not None and type_name in self._entity_names

    def get_entity_name(self, type_hint: Any) -> str | None:
        """Get entity name from type hint, or None if not an entity."""
        if isinstance(type_hint, str):
            return type_hint if type_hint in self._entity_names else None

        type_name = getattr(type_hint, "__name__", None)
        if type_name and type_name in self._entity_names:
            return type_name
        return None

    def is_relationship(self, type_hint: Any) -> bool:
        """Check if type is a relationship (single or list of entities).

        This handles:
        - Single entity: User
        - Optional entity: Optional[User]
        - List of entities: list[User]
        - List with optional: list[Optional[User]]
        - Mapped wrapper: Mapped[User], Mapped[list[User]]
        """
        # Unwrap Mapped wrapper first
        if self.is_mapped_wrapper(type_hint):
            type_hint = self.unwrap_mapped(type_hint)

        # Handle list of entities
        if self.is_list_type(type_hint):
            inner = self.get_list_inner_type(type_hint)
            return self.is_entity_type(inner)

        # Handle Optional[Entity] (Union or UnionType)
        if self.is_optional(type_hint):
            inner = self.unwrap_optional(type_hint)
            return self.is_entity_type(inner)

        # Handle single entity
        return self.is_entity_type(type_hint)

    def unwrap_to_base_type(self, type_hint: Any) -> Any:
        """Unwrap all wrappers (Optional, Mapped, list) to get base type.

        For list types, returns the inner element type.
        For Optional types, returns the non-None type.
        For Mapped types, returns the unwrapped type.
        """
        # Unwrap Mapped wrapper
        if self.is_mapped_wrapper(type_hint):
            type_hint = self.unwrap_mapped(type_hint)

        # Unwrap list
        if self.is_list_type(type_hint):
            type_hint = self.get_list_inner_type(type_hint)

        # Unwrap Optional
        if self.is_optional(type_hint):
            type_hint = self.unwrap_optional(type_hint)

        return type_hint
