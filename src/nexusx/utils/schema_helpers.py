"""Shared helper functions for GraphQL schema generation.

This module provides common utilities used by both SDLGenerator and IntrospectionGenerator
to eliminate code duplication.
"""

from __future__ import annotations

import types
from collections.abc import Iterable
from enum import Enum
from typing import Any, Union, get_args, get_origin, get_type_hints

from pydantic import BaseModel
from sqlmodel import SQLModel


def get_core_types(python_type: Any) -> list[type]:
    """Extract core types from a type hint, unwrapping Optional, Union, list, etc.

    Args:
        python_type: A Python type hint (can be Optional, Union, list, etc.)

    Returns:
        List of base types extracted from the type hint.

    Examples:
        >>> get_core_types(Optional[int])
        [<class 'int'>]
        >>> get_core_types(Union[int, str])
        [<class 'int'>, <class 'str'>]
        >>> get_core_types(list[int])
        [<class 'int'>]
    """
    origin = get_origin(python_type)

    # Handle Union (including Optional)
    if origin is Union or origin is types.UnionType:
        args = get_args(python_type)
        result = []
        for arg in args:
            if arg is not type(None):
                result.extend(get_core_types(arg))
        return result

    # Handle list
    if origin is list:
        args = get_args(python_type)
        if args:
            return get_core_types(args[0])
        return []

    # Base type
    if isinstance(python_type, type):
        return [python_type]

    return []


def is_input_type(python_type: type) -> bool:
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


def collect_enum_types(
    entities: list[type[SQLModel]],
    type_converter: Any,  # TypeConverter type hint would cause circular import
) -> dict[str, type[Enum]]:
    """Collect all enum types used in entities.

    Args:
        entities: List of SQLModel entity classes.
        type_converter: TypeConverter instance for type inspection.

    Returns:
        Dictionary mapping enum name to enum class.

    Examples:
        >>> from enum import Enum
        >>> class Status(Enum):
        ...     ACTIVE = "active"
        >>> class User(SQLModel):
        ...     status: Status
        >>> enums = collect_enum_types([User], converter)
        >>> "Status" in enums
        True
    """
    root_types: list[Any] = []

    for entity in entities:
        try:
            hints = get_type_hints(entity)
        except Exception:
            continue
        root_types.extend(hints.values())

    return collect_reachable_enum_types(root_types, type_converter)


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
