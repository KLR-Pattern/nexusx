"""Selection projection for UseCase MCP responses.

This module implements a lightweight, DTO-only projection layer for
``call_use_case(selection=...)``.  It intentionally reuses the
``QueryParser``/``FieldSelection`` structures while avoiding ERD-specific
response building behavior such as relationships, pagination, and FK fields.
"""

from __future__ import annotations

import inspect
import typing
from functools import partial
from types import UnionType as _UnionType
from typing import Any, get_args, get_origin

from pydantic import BaseModel, Field, TypeAdapter
from pydantic_core import PydanticUndefined

from nexusx.core_builder import FieldResolution, SelectionError, build_model
from nexusx.query_parser import FieldSelection, QueryParser
from nexusx.utils.type_utils import map_annotation

_UNION_ORIGINS = (typing.Union, _UnionType)
_RESULT_FIELD = "__result"


def apply_selection(result: Any, return_annotation: Any, selection: str) -> Any:
    """Project a UseCase result into a dynamic Pydantic subset model.

    The returned value remains a Pydantic model/list of Pydantic models/None;
    final serialization is still handled by the existing MCP response layer.
    """
    field_selection = parse_selection(selection)
    root_model, root_annotation = _extract_root_model(return_annotation, result)
    subset_model = build_subset_model(root_model, field_selection)

    if result is None:
        return None

    try:
        selected_annotation = _replace_model_type(root_annotation, subset_model)
        return TypeAdapter(selected_annotation).validate_python(result)
    except Exception as e:  # pragma: no cover - exact pydantic errors vary
        raise SelectionError(f"Failed to apply selection: {e}") from e


def parse_selection(selection: str) -> FieldSelection:
    """Parse a rootless GraphQL-like selection into a FieldSelection tree.

    Accepts both a bare field list (``"name"`` / ``"id tasks { title }"``)
    and an already-braced fragment (``"{ name }"``); a bare list is wrapped
    automatically so callers don't have to supply outer braces.
    """
    if not selection or not selection.strip():
        raise SelectionError("selection cannot be empty")

    sel = selection.strip()
    if not sel.startswith("{"):
        sel = "{ " + sel + " }"
    query = f"{{ {_RESULT_FIELD} {sel} }}"
    try:
        parsed = QueryParser().parse(query)
    except Exception as e:
        raise SelectionError(str(e)) from e

    root = parsed.get(_RESULT_FIELD)
    if root is None:
        raise SelectionError("selection could not be parsed")
    if root.arguments:
        raise SelectionError("selection arguments are not supported")
    if not root.sub_fields:
        raise SelectionError("selection must include at least one field")

    _reject_arguments(root)
    return root


class DTOFieldResolver:
    """FieldResolver for UseCase compose (specs/021 path-merge).

    Wraps the annotation-unwrapping logic that ``build_subset_model`` used
    inline (``_get_pydantic_core_type`` to detect nested BaseModel) into the
    ``FieldResolver`` protocol so ``core_builder.build_model`` can consume it.

    Nullability / default preservation are pinned explicitly here (vs the
    entity-first resolver's lenient defaults): ``is_optional`` honors the DTO
    annotation (``Optional[X]`` / ``X | None``), ``default`` carries the
    original field's default / default_factory / description.
    """

    def resolve_field(self, dto_type: type, field_name: str) -> FieldResolution | None:
        if field_name not in dto_type.model_fields:
            return None
        field_info = dto_type.model_fields[field_name]
        field_type = field_info.annotation
        nested_type = _get_pydantic_core_type(field_type)
        return FieldResolution(
            annotation=field_type,
            nested_type=nested_type,
            default=_field_default(field_info),
            # Exact wrapper reconstruction (list[DTO | None] etc.) — subsumes
            # the old is_list/is_optional pair (specs/021).
            nested_shape=(
                partial(_replace_model_type, field_type)
                if nested_type is not None
                else None
            ),
        )


def build_subset_model(
    model_type: type[BaseModel],
    field_selection: FieldSelection,
    path: str = "",
) -> type[BaseModel]:
    """Recursively build a dynamic Pydantic model for selected DTO fields.

    specs/021: thin shell over ``core_builder.build_model`` with the UseCase
    semantics — strict validation (unknown fields / malformed sub-selections
    raise ``SelectionError``) and DTO default preservation (via
    ``DTOFieldResolver``). ``allow_paginated=False`` because DTO land never
    produces ``{items, pagination}`` packages.
    """
    if not field_selection.sub_fields:
        raise SelectionError(f"Selection for '{model_type.__name__}' cannot be empty")

    name_suffix = "Selection_" + "_".join(sorted(field_selection.sub_fields.keys()))
    return build_model(
        model_type,
        field_selection,
        resolver=DTOFieldResolver(),
        model_name=name_suffix,
        strict=True,
        allow_paginated=False,
        path=path,
    )


def _reject_arguments(selection: FieldSelection, path: str = "") -> None:
    if selection.arguments:
        location = path or _RESULT_FIELD
        raise SelectionError(f"selection arguments are not supported at '{location}'")
    if not selection.sub_fields:
        return
    for field_name, sub_selection in selection.sub_fields.items():
        child_path = f"{path}.{field_name}" if path else field_name
        _reject_arguments(sub_selection, child_path)


def _extract_root_model(
    return_annotation: Any,
    result: Any,
) -> tuple[type[BaseModel], Any]:
    core_type = _get_pydantic_core_type(return_annotation)
    if core_type is not None:
        return core_type, return_annotation

    runtime_annotation = _infer_runtime_annotation(result)
    runtime_core_type = _get_pydantic_core_type(runtime_annotation)
    if runtime_core_type is not None:
        return runtime_core_type, runtime_annotation

    raise SelectionError(
        "selection is only supported for Pydantic return types "
        "(BaseModel, list[BaseModel], or optional variants)"
    )


def _infer_runtime_annotation(result: Any) -> Any:
    if isinstance(result, BaseModel):
        return result.__class__

    if not isinstance(result, list):
        return None

    item_type = None
    saw_none = False
    for item in result:
        if item is None:
            saw_none = True
            continue

        if not isinstance(item, BaseModel):
            return None

        current_type = item.__class__
        if item_type is None:
            item_type = current_type
        elif current_type is not item_type:
            return None

    if item_type is None:
        return None

    if saw_none:
        return list[item_type | None]

    return list[item_type]


def _get_pydantic_core_type(annotation: Any) -> type[BaseModel] | None:
    """Extract the Pydantic BaseModel type from a possibly-wrapped annotation."""
    if annotation is None or annotation is inspect.Parameter.empty:
        return None
    core_types = _get_core_types(annotation)
    pydantic_types = [tp for tp in core_types if _safe_issubclass(tp, BaseModel)]
    if len(pydantic_types) == 1:
        return pydantic_types[0]
    return None


def _get_core_types(tp: Any) -> list[type]:
    """Extract all concrete types from a possibly-wrapped annotation."""
    if tp is None or tp is inspect.Parameter.empty:
        return []
    if isinstance(tp, str):
        return []
    if isinstance(tp, type):
        return [tp]

    origin = get_origin(tp)

    # Annotated[X, ...]
    if origin is typing.Annotated:
        args = get_args(tp)
        return _get_core_types(args[0]) if args else []

    # list[X]
    if origin is list:
        args = get_args(tp)
        return _get_core_types(args[0]) if args else []

    # Union / Optional
    if origin in _UNION_ORIGINS:
        results: list[type] = []
        for arg in get_args(tp):
            results.extend(_get_core_types(arg))
        return results

    return [tp] if isinstance(tp, type) else []


def _safe_issubclass(kls: Any, classinfo: type) -> bool:
    try:
        return issubclass(kls, classinfo)
    except TypeError:
        return False


def _replace_model_type(annotation: Any, nested_model: type[BaseModel]) -> Any:
    annotation = _strip_annotated(annotation)

    if annotation is None or annotation is inspect.Parameter.empty:
        return nested_model

    def leaf(a: Any) -> Any:
        # Bare BaseModel (possibly the core of a wrapper) → nested model.
        # list / union nodes are rebuilt by map_annotation, not replaced.
        if (
            _get_pydantic_core_type(a) is not None
            and not _is_list_annotation(a)
            and get_origin(a) not in _UNION_ORIGINS
        ):
            return nested_model
        return a

    return map_annotation(annotation, leaf)


def _field_default(field_info: Any) -> Any:
    description = getattr(field_info, "description", None)
    default_factory = getattr(field_info, "default_factory", None)
    if default_factory is not None:
        return Field(default_factory=default_factory, description=description)

    default = getattr(field_info, "default", PydanticUndefined)
    if default is PydanticUndefined:
        return Field(default=..., description=description)

    return Field(default=default, description=description)


def _strip_annotated(annotation: Any) -> Any:
    while get_origin(annotation) is typing.Annotated:
        args = get_args(annotation)
        if not args:
            break
        annotation = args[0]
    return annotation


def _is_list_annotation(annotation: Any) -> bool:
    return get_origin(annotation) is list
