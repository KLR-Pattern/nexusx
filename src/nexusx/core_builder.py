"""Unified dynamic model builder for entity-first gql AND UseCase compose.

specs/021 path-merge: consolidates ``build_response_model`` (response_builder.py,
from SQLModel entity + field_tree dict) and ``build_subset_model`` (selection.py,
from pydantic DTO + FieldSelection) into one recursive builder, parameterized
by a ``FieldResolver`` that abstracts the "where does this field's type come
from" difference:

- **entity-first**: field types come from SQLModel relationships (SQLAlchemy
  mapper / federation ``__relationships__`` / forward-ref). The resolver
  implementation queries the ErManager registry.
- **UseCase**: field types come from pydantic DTO ``model_fields`` annotations.
  The resolver implementation unwraps the annotation.

This module provides the framework (``FieldResolution`` / ``FieldResolver`` /
``build_model``). The two existing builders (``build_response_model`` /
``build_subset_model``) are thin shells on top of ``build_model``; their
world-specific concerns (LRU caching, strictness, default-value preservation)
live in the shells or in the resolver implementations.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, create_model

from nexusx.loader.pagination import create_result_type
from nexusx.query_parser import FieldSelection


class SelectionError(ValueError):
    """Raised for invalid field selections in strict mode (UseCase semantics).

    specs/021: moved here from ``use_case.selection`` so ``build_model`` can
    raise it without importing the use_case layer. ``use_case.selection``
    re-exports it for backwards compatibility.
    """


@dataclass
class FieldResolution:
    """Result of resolving one field's type (specs/021).

    - ``annotation``: the field's type for scalar fields (e.g. ``int``, ``str``).
    - ``nested_type``: the target model type if this is a nested relationship;
      ``None`` for scalar fields.
    - ``default``: the pydantic field-definition second element — ``...``
      (required), a plain value, or a ``Field(...)`` object. entity-first
      leaves every field required; UseCase preserves the DTO's
      default / default_factory / description.
    - ``nested_shape``: how to wrap the nested model back into its field
      annotation — ``nested_model -> annotation``. UseCase uses
      ``partial(_replace_model_type, field_type)`` which preserves the exact
      wrapper (e.g. ``list[DTO | None]``); entity-first builds ``list[m]`` for
      to-many relationships. ``None`` → the builder's lenient default:
      nullable single model (``nested | None``), entity-first semantics.

    ``nested_shape`` subsumes the former ``is_list`` / ``is_optional`` /
    ``nested_annotation_factory`` triple — a single source of truth for "the
    field's annotation shape around the nested model".
    """

    annotation: Any
    nested_type: type[BaseModel] | None
    default: Any = ...
    nested_shape: Callable[[type[BaseModel]], Any] | None = None


class FieldResolver(Protocol):
    """Abstracts the source-of-truth difference between entity-first and UseCase.

    entity-first gql resolves field types from SQLModel relationships
    (SQLAlchemy mapper / federation ``__relationships__`` / forward-ref).

    UseCase compose resolves from pydantic DTO ``model_fields`` annotations.

    Both produce the same ``FieldResolution`` shape so ``build_model`` doesn't
    need to know which world it's in.
    """

    def resolve_field(
        self, owner_type: type, field_name: str
    ) -> FieldResolution | None:
        """Return the field's type info, or None if the field is unknown."""
        ...


def is_paginated_package(tree: Any) -> bool:
    """True if a field_tree dict (or dict value) is a paginated package.

    ``items`` is the marker key — ``pagination`` is optional (a client may
    select only ``{ items {...} }``; requiring both would silently treat such
    a query as a plain nested field and pass RowMappings through raw, leaking
    internal columns — specs/021 hardening). Shared by the build path (dict →
    FieldSelection), the recursive serializer (response_builder) and the
    resolver's duck-type checks.
    """
    return isinstance(tree, dict) and "items" in tree


def _is_paginated_package_sel(selection: FieldSelection) -> bool:
    """True if selection represents a paginated package (``{items, ...}``).

    FieldSelection variant of ``is_paginated_package`` — ``items`` is the
    marker, ``pagination`` optional (specs/021 hardening). entity-first gql
    produces this shape when the query selects ``field { items { ... } }``
    (with or without ``pagination``); UseCase never does (no paginated
    package in DTO land).
    """
    return (
        selection.sub_fields is not None
        and "items" in selection.sub_fields
    )


def build_model(
    owner_type: type,
    selection: FieldSelection,
    *,
    resolver: FieldResolver,
    model_name: str = "Response",
    strict: bool = False,
    allow_paginated: bool = True,
    path: str = "",
) -> type[BaseModel]:
    """Recursively build a dynamic pydantic model from a gql selection tree.

    Unified builder for entity-first gql (SQLModel + ER relationships) and
    UseCase compose (pydantic DTO + annotations). The ``FieldResolver``
    abstracts the only real difference: where nested field types come from.

    Field handling:
    - **scalar**: resolver returns ``nested_type=None`` → keep ``annotation``
      (or ``Any`` if unresolved, mirroring entity-first's fallback).
    - **nested**: resolver returns ``nested_type`` → recurse ``build_model``.
      ``nested_shape`` wraps the result (``list[nested]`` for to-many,
      UseCase's exact-wrapper reconstruction); ``None`` → nullable single
      (entity-first semantics).
    - **paginated package**: selection has ``{items, pagination}`` sub-fields →
      ``create_result_type({items: list[nested], pagination})``. entity-first
      only; UseCase passes ``allow_paginated=False`` (its DTOs never produce
      this tree shape).

    ``strict`` (UseCase semantics): unknown fields, nested fields without
    sub-selection, and scalar fields with sub-selection raise
    ``SelectionError`` (with ``path``-qualified field names); lenient mode
    (entity-first) ignores them. ``path`` carries the dotted field path for
    error messages; it is '' at the root.

    Config: ``from_attributes=True`` — enables pydantic validate from object
    attributes, not just dict; safe for both paths since pydantic falls back
    to the dict path for dict input.
    """
    fields: dict[str, tuple[Any, Any]] = {}
    for field_name, child_sel in (selection.sub_fields or {}).items():
        resolution = resolver.resolve_field(owner_type, field_name)
        field_path = f"{path}.{field_name}" if path else field_name

        if resolution is None:
            if strict:
                raise SelectionError(
                    f"Unknown field '{field_path}' on return type "
                    f"'{owner_type.__name__}'"
                )
            # Lenient fallback: Any (mirrors entity-first behavior).
            fields[field_name] = (Any, ...)
            continue

        if resolution.nested_type is None:
            # Scalar field — keep the annotation.
            if strict and child_sel.sub_fields:
                raise SelectionError(
                    f"Field '{field_path}' is not a Pydantic object and "
                    "cannot have sub-selection"
                )
            fields[field_name] = (resolution.annotation, resolution.default)
            continue

        if strict and not child_sel.sub_fields:
            raise SelectionError(
                f"Field '{field_path}' is a Pydantic object and requires "
                "sub-selection"
            )

        if allow_paginated and _is_paginated_package_sel(child_sel):
            # Paginated package: {items, pagination} shape (entity-first only).
            items_sel = child_sel.sub_fields.get("items")
            pagination_sel = child_sel.sub_fields.get("pagination")
            items_model = build_model(
                resolution.nested_type,
                items_sel,
                resolver=resolver,
                model_name=f"{field_name.capitalize()}Item{model_name}",
                strict=strict,
                allow_paginated=allow_paginated,
                path=field_path,
            )
            pag_selection = (
                set(pagination_sel.sub_fields.keys())
                if pagination_sel and pagination_sel.sub_fields
                else None
            )
            result_type = create_result_type(
                item_type=items_model, pagination_selection=pag_selection,
            )
            fields[field_name] = (result_type, resolution.default)
        else:
            # Nested relationship — recurse.
            nested_model = build_model(
                resolution.nested_type,
                child_sel,
                resolver=resolver,
                model_name=f"{field_name.capitalize()}{model_name}",
                strict=strict,
                allow_paginated=allow_paginated,
                path=field_path,
            )
            if resolution.nested_shape is not None:
                fields[field_name] = (
                    resolution.nested_shape(nested_model),
                    resolution.default,
                )
            else:
                # Lenient default (entity-first semantics): nullable single.
                fields[field_name] = (nested_model | None, resolution.default)

    return create_model(
        f"{owner_type.__name__}{model_name}",
        __config__=ConfigDict(from_attributes=True, arbitrary_types_allowed=True),
        **fields,
    )
