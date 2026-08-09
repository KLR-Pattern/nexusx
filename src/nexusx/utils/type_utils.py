"""Type utility functions for nexusx."""

from __future__ import annotations

import types
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


def map_annotation(annotation: Any, leaf_fn: Callable[[Any], Any]) -> Any:
    """Recursively rebuild a generic annotation, replacing leaves via
    ``leaf_fn`` (specs/021 P1-10).

    ``leaf_fn(node)`` returns a replacement for the node or the node itself
    (unchanged). Containers are rebuilt: ``list[X]``, unions (``X | Y`` /
    ``typing.Union``), and other generic containers (``origin[new_args]``).
    Returns the original object when nothing changed. Shared by the UseCase
    subset projection (``_replace_model_type``) and federation deferred-ref
    resolution (``_replace_classes_in_annotation`` / ``_replace_remote_ref``),
    which previously duplicated this skeleton verbatim.
    """
    leaf = leaf_fn(annotation)
    if leaf is not annotation:
        return leaf

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is None or not args:
        return annotation

    new_args = tuple(map_annotation(a, leaf_fn) for a in args)
    if new_args == args:
        return annotation

    if origin is list and len(new_args) == 1:
        return list[new_args[0]]
    if origin is types.UnionType:
        result = new_args[0]
        for a in new_args[1:]:
            result = result | a
        return result
    try:
        return origin[new_args] if len(new_args) > 1 else origin[new_args[0]]
    except Exception:
        return annotation


def get_fk_fields(entity: type) -> set[str]:
    """Foreign-key field names on an entity (specs/021 P1-7).

    Detects ``field_info.foreign_key`` (str) and ``metadata`` entries carrying
    a str ``foreign_key`` — SQLModel/SQLAlchemy column FK markers. Shared by
    query_executor (output filtering), subset (FK auto-include into
    DTO subset fields) and standard_queries (PK-vs-FK filtering).
    """
    fks: set[str] = set()
    if not hasattr(entity, "model_fields"):
        return fks
    for fname, fi in entity.model_fields.items():
        if hasattr(fi, "foreign_key") and isinstance(fi.foreign_key, str):
            fks.add(fname)
        if hasattr(fi, "metadata"):
            for meta in fi.metadata:
                if hasattr(meta, "foreign_key") and isinstance(
                    meta.foreign_key, str
                ):
                    fks.add(fname)
    return fks


def coerce_to_dict(value: Any, mode: str | None = None) -> Any:
    """Coerce a value to a plain dict when possible (specs/021 P1-12).

    pydantic ``model_dump`` (``mode`` passed through, e.g. ``"json"``) / plain
    dict / iterable-of-pairs. Returns None for values that can't be coerced
    (None, scalars). Unifies response_builder's ``_coerce_to_dict`` and
    remote_loader's ``_to_dict``.
    """
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump() if mode is None else value.model_dump(mode=mode)
    if isinstance(value, dict):
        return value
    if hasattr(value, "__iter__"):
        try:
            return dict(value)
        except Exception:
            return None
    return None


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
