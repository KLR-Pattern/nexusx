"""Shared helper functions for GraphQL schema generation.

This module provides common utilities used by both SDLGenerator and IntrospectionGenerator
to eliminate code duplication.
"""

from __future__ import annotations

import types
from typing import Any, Union, get_args, get_origin

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


