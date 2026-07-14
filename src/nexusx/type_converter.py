"""Shared type conversion utilities for GraphQL schema generation."""

from __future__ import annotations

import types
import uuid
from datetime import date, datetime, time
from enum import Enum
from typing import Any, Union, get_args, get_origin


class TypeConverter:
    """Converts Python types to GraphQL type information.

    Used by both SDLGenerator and IntrospectionGenerator to eliminate
    code duplication in type inspection logic.
    """

    # Mapping from Python types to GraphQL scalar names
    SCALAR_TYPE_MAP: dict[Any, str] = {
        int: "Int",
        str: "String",
        bool: "Boolean",
        float: "Float",
        datetime: "DateTime",
        date: "Date",
        time: "Time",
        uuid.UUID: "UUID",
    }

    def __init__(self, entity_names: set[str]):
        """Initialize the type converter.

        Args:
            entity_names: Set of known entity class names.
        """
        self._entity_names = entity_names

    def is_optional(self, type_hint: Any) -> bool:
        """Check if type hint is Optional[T] (Union with None)."""
        origin = get_origin(type_hint)
        # Handle both Union (typing module) and UnionType (| syntax in Python 3.10+)
        if origin is Union or origin is types.UnionType:
            args = get_args(type_hint)
            return type(None) in args
        return False

    def unwrap_optional(self, type_hint: Any) -> Any:
        """Extract T from Optional[T]."""
        origin = get_origin(type_hint)
        # Handle both Union (typing module) and UnionType (| syntax in Python 3.10+)
        if origin is Union or origin is types.UnionType:
            args = get_args(type_hint)
            non_none = [a for a in args if a is not type(None)]
            return non_none[0] if non_none else type_hint
        return type_hint

    def is_list_type(self, type_hint: Any) -> bool:
        """Check if type is list[T]."""
        return get_origin(type_hint) is list

    def get_list_inner_type(self, type_hint: Any) -> Any:
        """Extract T from list[T], handling Optional inside list."""
        args = get_args(type_hint)
        if not args:
            return type_hint

        inner = args[0]
        # Handle list[Optional[T]]
        if self.is_optional(inner):
            inner = self.unwrap_optional(inner)
        return inner

    def is_mapped_wrapper(self, type_hint: Any) -> bool:
        """Check if type is SQLAlchemy Mapped wrapper."""
        origin = get_origin(type_hint)
        if origin is None:
            return False

        origin_name = getattr(origin, "__name__", "") or getattr(origin, "_name", "")
        return origin_name == "Mapped" or str(origin).endswith("Mapped")

    def unwrap_mapped(self, type_hint: Any) -> Any:
        """Extract inner type from Mapped[T]."""
        args = get_args(type_hint)
        return args[0] if args else type_hint

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

        origin = get_origin(type_hint)

        # Handle list of entities
        if origin is list:
            inner = self.get_list_inner_type(type_hint)
            return self.is_entity_type(inner)

        # Handle Optional[Entity] (Union or UnionType)
        if origin is Union or origin is types.UnionType:
            args = get_args(type_hint)
            non_none = [a for a in args if a is not type(None)]
            if non_none:
                return self.is_entity_type(non_none[0])
            return False

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
