"""Leaf module: type-annotation reflection shared by every nexusx path.

Pure functions over ``typing`` objects with **zero** nexusx imports — the one
place all paths (entity-first SDL/introspection, UseCase compose, Resolver,
DefineSubset, voyager) unwrap ``Optional`` / ``list`` / ``Annotated`` /
``Mapped``. Before spec 026 each path carried a private copy (20+ in total);
two of them had already drifted from their own "shared" docstrings.

Two deliberately different predicates live here, named for what they do:

- :func:`unwrap_optional` — return the **first** non-``None`` arm of a union
  (``A | B | None`` → ``A``). The historical ``TypeConverter`` semantics the
  SDL / introspection / argument builders rely on.
- :func:`unwrap_optional_strict` — return the single non-``None`` arm **only
  when it is the only one** (``A | B | None`` stays a union). Used where a
  union would be invalid input anyway (primary / federation keys, DTO field
  types) and silently taking the first arm would hide the mistake.
"""

from __future__ import annotations

import types
import typing
from collections.abc import Callable
from typing import Any, cast

__all__ = [
    "is_union",
    "is_optional",
    "unwrap_optional",
    "unwrap_optional_strict",
    "is_list",
    "is_list_annotation",
    "list_inner",
    "strip_annotated",
    "is_mapped_wrapper",
    "unwrap_mapped",
    "core_types",
    "is_pydantic",
    "safe_issubclass",
    "unwrap_func",
    "map_annotation",
]

_NoneType = type(None)


def _is_union(anno: Any) -> bool:
    origin = typing.get_origin(anno)
    return origin is typing.Union or origin is types.UnionType


# ──────────────────────────────────────────────────────────
# Optional / Union
# ──────────────────────────────────────────────────────────


def is_union(anno: Any) -> bool:
    """True for any union — ``typing.Union[...]`` or PEP 604 ``X | Y`` — Optional or not."""
    return _is_union(anno)


def is_optional(anno: Any) -> bool:
    """True for ``Optional[X]`` / ``X | None`` (a union that contains ``None``).

    Does not look through ``Annotated`` — :func:`strip_annotated` first if
    needed. ``Annotated[Optional[X], ...]`` therefore reports ``False``.
    """
    if not _is_union(anno):
        return False
    return any(a is _NoneType for a in typing.get_args(anno))


def unwrap_optional(anno: Any) -> Any:
    """Drop ``None`` from a union, keeping the **first** remaining arm.

    ``Optional[X]`` → ``X``; ``A | B | None`` → ``A`` (first arm — see the
    module docstring for why this is kept distinct from
    :func:`unwrap_optional_strict`); anything that is not an Optional union is
    returned unchanged.
    """
    if not _is_union(anno):
        return anno
    non_none = [a for a in typing.get_args(anno) if a is not _NoneType]
    return non_none[0] if non_none else anno


def unwrap_optional_strict(anno: Any) -> Any:
    """``Optional[X]`` → ``X`` **only** when ``X`` is the single non-``None`` arm.

    ``A | B | None`` is returned unchanged: a real union is not an Optional,
    and callers in this module's contract treat it as invalid input rather
    than silently picking ``A``. Non-unions are returned unchanged.
    """
    if not _is_union(anno):
        return anno
    args = typing.get_args(anno)
    non_none = [a for a in args if a is not _NoneType]
    if len(non_none) == 1 and len(args) > 1:
        return non_none[0]
    return anno


# ──────────────────────────────────────────────────────────
# list
# ──────────────────────────────────────────────────────────


def is_list(anno: Any) -> bool:
    """Strict: ``origin is list``. ``Optional[list[X]]`` / ``Annotated[list[X], …]``
    / ``Mapped[list[X]]`` are all ``False`` — unwrap those first."""
    return typing.get_origin(anno) is list


def is_list_annotation(anno: Any) -> bool:
    """Lenient: does this annotation *contain* a list anywhere?

    Handles ``Annotated[...]``, SQLAlchemy ``Mapped[...]``, ``Optional`` /
    unions, and bare ``list[...]``. Historically ``utils.type_utils``
    .is_list_annotation`` (shared by entity-first ``response_builder`` and
    UseCase ``selection`` per its docstring — which had its own private copy).
    """
    if isinstance(anno, str):
        return False
    origin = typing.get_origin(anno)
    if origin is None:
        return False
    args = typing.get_args(anno)
    if origin is typing.Annotated or getattr(origin, "__name__", "") == "Mapped":
        return is_list_annotation(args[0]) if args else False
    if origin is list or str(origin).startswith("list"):
        return True
    if args:
        return any(is_list_annotation(a) for a in args if a is not _NoneType)
    return False


def list_inner(anno: Any) -> Any:
    """``list[X]`` → ``X`` (unwrapping an ``Optional`` element); otherwise unchanged."""
    args = typing.get_args(anno)
    if not args:
        return anno
    inner = args[0]
    if is_optional(inner):
        inner = unwrap_optional(inner)
    return inner


# ──────────────────────────────────────────────────────────
# Annotated / Mapped
# ──────────────────────────────────────────────────────────


def strip_annotated(anno: Any) -> Any:
    """Peel every ``Annotated[T, ...]`` layer down to ``T``; else unchanged."""
    while typing.get_origin(anno) is typing.Annotated:
        args = typing.get_args(anno)
        if not args:
            break
        anno = args[0]
    return anno


def is_mapped_wrapper(anno: Any) -> bool:
    """True for SQLAlchemy's ``Mapped[T]`` (``table=True`` models rewrite
    relationship annotations to ``Mapped[list['X']]``)."""
    origin = typing.get_origin(anno)
    if origin is None:
        return False
    origin_name = getattr(origin, "__name__", "") or getattr(origin, "_name", "")
    return origin_name == "Mapped" or str(origin).endswith("Mapped")


def unwrap_mapped(anno: Any) -> Any:
    """``Mapped[T]`` → ``T``; otherwise unchanged."""
    args = typing.get_args(anno)
    return args[0] if args else anno


# ──────────────────────────────────────────────────────────
# Core types / classes
# ──────────────────────────────────────────────────────────


def core_types(tp: Any) -> list[type]:
    """Concrete classes reachable from an annotation, unwrapping ``Optional`` /
    unions / ``list`` / ``Annotated``. ``None`` / ``NoneType``, ``Ellipsis``,
    string forward references and non-type leaves (``Literal[...]``,
    ``dict[...]``, ``Mapped[...]``) yield ``[]``. (The former
    ``introspector._collect_core_types`` kept ``NoneType`` in its result — a
    drift against ``schema_helpers.get_core_types``; the skip-``None`` rule is
    the one every caller actually wants.)"""
    if tp is None or tp is _NoneType or tp is Ellipsis or isinstance(tp, str):
        return []
    if isinstance(tp, type):
        return [tp]
    origin = typing.get_origin(tp)
    if origin is list:
        args = typing.get_args(tp)
        return core_types(args[0]) if args else []
    if _is_union(tp) or origin is typing.Annotated:
        results: list[type] = []
        for arg in typing.get_args(tp):
            results.extend(core_types(arg))
        return results
    return []


def is_pydantic(tp: Any) -> bool:
    """True when ``tp`` is a ``pydantic.BaseModel`` subclass."""
    from pydantic import BaseModel

    return safe_issubclass(tp, BaseModel)


def safe_issubclass(kls: Any, classinfo: type) -> bool:
    """``issubclass`` that answers ``False`` instead of raising for
    non-classes (``ForwardRef``, string annotations, generic aliases)."""
    return isinstance(kls, type) and issubclass(kls, classinfo)


# ──────────────────────────────────────────────────────────
# Callables
# ──────────────────────────────────────────────────────────


def unwrap_func(obj: Any) -> Callable[..., Any]:
    """The plain function behind a ``classmethod`` / bound method; anything
    else is returned as-is. Replaces the 21 inline
    ``x.__func__ if hasattr(x, "__func__") else x`` sites."""
    func = getattr(obj, "__func__", None)
    return cast(Callable[..., Any], func) if func is not None else cast(Callable[..., Any], obj)


# ──────────────────────────────────────────────────────────
# Rebuilding annotations
# ──────────────────────────────────────────────────────────


def map_annotation(annotation: Any, leaf_fn: Callable[[Any], Any]) -> Any:
    """Recursively rebuild a generic annotation, replacing leaves via
    ``leaf_fn`` (specs/021 P1-10).

    ``leaf_fn(node)`` returns a replacement for the node or the node itself
    (unchanged). Containers are rebuilt: ``list[X]``, unions (``X | Y`` /
    ``typing.Union``), and other generic containers (``origin[new_args]``).
    Returns the original object when nothing changed. Shared by the UseCase
    subset projection (``_replace_model_type``) and federation deferred-ref
    resolution (``_replace_classes_in_annotation`` / ``_replace_remote_ref``).
    Moved here from ``utils.type_utils`` (spec 026 R1) so every annotation
    helper has one home.
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
        return cast(Any, list)[new_args[0]]
    if origin is types.UnionType:
        result = new_args[0]
        for a in new_args[1:]:
            result = result | a
        return result
    origin_alias = cast(Any, origin)
    try:
        return origin_alias[new_args] if len(new_args) > 1 else origin_alias[new_args[0]]
    except Exception:
        return annotation
