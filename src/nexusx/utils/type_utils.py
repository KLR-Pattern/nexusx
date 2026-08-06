"""Type utility functions for nexusx."""

from __future__ import annotations

import typing
from collections.abc import Callable
from typing import Any, ParamSpec, get_args, get_origin, get_type_hints

from nexusx.type_converter import TypeConverter

P = ParamSpec("P")


def is_list_annotation(annotation: Any) -> bool:
    """True if ``annotation`` is a list type, unwrapping common wrappers.

    Handles ``Annotated[...]``, SQLModel's ``Mapped[...]`` (table=True models
    rewrite relationship annotations to ``Mapped[list['X']]``), ``Optional`` /
    unions, and ``list`` generics. Shared by entity-first (response_builder)
    and UseCase (selection) paths — specs/021 convergence.
    """
    if isinstance(annotation, str):
        return False
    origin = get_origin(annotation)
    if origin is None:
        return False
    args = get_args(annotation)
    if origin is typing.Annotated or getattr(origin, "__name__", "") == "Mapped":
        return is_list_annotation(args[0]) if args else False
    if origin is list or str(origin).startswith("list"):
        return True
    if args:
        return any(
            is_list_annotation(arg)
            for arg in args
            if arg is not type(None)
        )
    return False


def get_field_type(entity: type, field_name: str) -> type:
    """Get the type of a field from an entity.

    Args:
        entity: SQLModel entity class.
        field_name: Name of the field.

    Returns:
        Field type or Any if not found.
    """
    if hasattr(entity, "model_fields"):
        field_info = entity.model_fields.get(field_name)
        if field_info and field_info.annotation:
            return field_info.annotation

    # Fallback to annotations
    if hasattr(entity, "__annotations__"):
        return entity.__annotations__.get(field_name, Any)

    return Any


def get_return_entity_type(method: Callable[P, Any], entities: list[type]) -> type | None:
    """Get the return entity type if method returns an entity or list of entities.

    Args:
        method: The query/mutation method.
        entities: List of all entity classes.

    Returns:
        The entity class if return type is an entity, otherwise None.
    """
    try:
        func = method.__func__ if hasattr(method, "__func__") else method
        hints = get_type_hints(func)
        return_type = hints.get("return")
        if return_type is None:
            return None

        # Create a TypeConverter for type inspection
        entity_names = {e.__name__ for e in entities}
        converter = TypeConverter(entity_names)

        # Unwrap list type
        origin = get_origin(return_type)
        if origin is list:
            return_type = converter.get_list_inner_type(return_type)

        # Unwrap Optional
        if converter.is_optional(return_type):
            return_type = converter.unwrap_optional(return_type)

        # Check if it's an entity
        if isinstance(return_type, type) and return_type.__name__ in entity_names:
            return return_type

    except Exception:
        pass

    return None
