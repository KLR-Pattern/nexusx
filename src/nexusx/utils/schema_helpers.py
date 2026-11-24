"""Shared helper functions for GraphQL schema generation.

This module provides common utilities used by both SDLGenerator and IntrospectionGenerator
to eliminate code duplication. Structural annotation helpers live in
:mod:`nexusx.annotation_utils` (``core_types`` replaces the former
``get_core_types`` here — spec 026 R1).
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from typing import Any, get_type_hints

from pydantic import BaseModel
from sqlmodel import SQLModel

from nexusx.annotation_utils import (
    core_types as get_core_types,  # noqa: F401  (re-export for the two generators)
)

__all__ = ["get_core_types", "is_input_type", "collect_reachable_enum_types"]


def is_input_type(python_type: Any) -> bool:
    """Check if a type should be treated as a GraphQL Input type.

    Input types are SQLModel or BaseModel subclasses that are NOT in the entity list
    (i.e., they are used as mutation parameters, not as entity types).

    Args:
        python_type: A Python type to check.

    Returns:
        True if the type is an input type (SQLModel or BaseModel subclass).

    Examples:
        >>> class MyInput(SQLModel):
        ...     field: str
        >>> is_input_type(MyInput)
        True
        >>> is_input_type(int)
        False
    """
    if not isinstance(python_type, type):
        return False
    # Check if it's a SQLModel or Pydantic BaseModel
    try:
        if issubclass(python_type, SQLModel) or issubclass(python_type, BaseModel):
            return True
    except TypeError:
        pass
    return False


def collect_reachable_enum_types(
    root_types: Iterable[Any],
    type_converter: Any,  # TypeConverter type hint would cause circular import
) -> dict[str, type[Enum]]:
    """Collect enums reachable through nested input model fields."""
    enums: dict[str, type[Enum]] = {}
    visited_models: set[type] = set()

    def collect_from_type(python_type: Any) -> None:
        if type_converter.is_mapped_wrapper(python_type):
            python_type = type_converter.unwrap_mapped(python_type)

        for core_type in get_core_types(python_type):
            if type_converter.is_enum_type(core_type):
                enums[core_type.__name__] = core_type
                continue

            if not is_input_type(core_type) or core_type in visited_models:
                continue

            visited_models.add(core_type)
            try:
                hints = get_type_hints(core_type)
            except Exception:
                continue
            for field_type in hints.values():
                collect_from_type(field_type)

    for root_type in root_types:
        collect_from_type(root_type)

    return enums
