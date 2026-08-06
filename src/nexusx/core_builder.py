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
``build_model``). Migrating the two existing builders to call ``build_model``
is the next step — they currently still work independently (zero risk).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, create_model

from nexusx.loader.pagination import create_result_type
from nexusx.query_parser import FieldSelection


@dataclass
class FieldResolution:
    """Result of resolving one field's type (specs/021).

    - ``annotation``: the field's type for scalar fields (e.g. ``int``, ``str``).
    - ``nested_type``: the target model type if this is a nested relationship;
      ``None`` for scalar fields.
    - ``is_list``: whether the field is a to-many (``list[X]``) relationship.
    """

    annotation: Any
    nested_type: type[BaseModel] | None
    is_list: bool


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


def _is_paginated_package_sel(selection: FieldSelection) -> bool:
    """True if selection represents a paginated package (``{items, pagination}``).

    Mirrors ``response_builder._is_paginated_package`` but works on
    ``FieldSelection`` (not field_tree dict). Entity-first gql produces this
    shape when the query selects ``field { items { ... } pagination { ... } }``;
    UseCase never does (no paginated package in DTO land).
    """
    return (
        selection.sub_fields is not None
        and "items" in selection.sub_fields
        and "pagination" in selection.sub_fields
    )


def build_model(
    owner_type: type,
    selection: FieldSelection,
    *,
    resolver: FieldResolver,
    model_name: str = "Response",
) -> type[BaseModel]:
    """Recursively build a dynamic pydantic model from a gql selection tree.

    Unified builder for entity-first gql (SQLModel + ER relationships) and
    UseCase compose (pydantic DTO + annotations). The ``FieldResolver``
    abstracts the only real difference: where nested field types come from.

    Field handling:
    - **scalar**: resolver returns ``nested_type=None`` → keep ``annotation``
      (or ``Any`` if unresolved, mirroring entity-first's fallback).
    - **nested**: resolver returns ``nested_type`` → recurse ``build_model``.
      ``is_list`` determines ``list[nested]`` vs ``nested | None``.
    - **paginated package**: selection has ``{items, pagination}`` sub-fields →
      ``create_result_type({items: list[nested], pagination})``. Entity-first
      only; UseCase never produces this tree shape.

    Config: ``from_attributes=True`` (absorbed from UseCase's ``build_subset_model``
    — enables pydantic validate from object attributes, not just dict; safe for
    both paths since pydantic falls back to dict path for dict input).

    Note: this is the framework. LRU caching, federation_namespace, forward-ref
    resolution, and strict validation (SelectionError) will be added when
    migrating the two existing builders (they carry those concerns today).
    """
    fields: dict[str, tuple[Any, Any]] = {}
    for field_name, child_sel in (selection.sub_fields or {}).items():
        resolution = resolver.resolve_field(owner_type, field_name)

        if resolution is None or resolution.nested_type is None:
            # Scalar field — keep the annotation (or Any if unresolved).
            annotation = resolution.annotation if resolution else Any
            fields[field_name] = (annotation, ...)
            continue

        if _is_paginated_package_sel(child_sel):
            # Paginated package: {items, pagination} shape (entity-first only).
            items_sel = child_sel.sub_fields.get("items")
            pagination_sel = child_sel.sub_fields.get("pagination")
            items_model = build_model(
                resolution.nested_type,
                items_sel,
                resolver=resolver,
                model_name=f"{field_name.capitalize()}Item",
            )
            pag_selection = (
                set(pagination_sel.sub_fields.keys())
                if pagination_sel and pagination_sel.sub_fields
                else None
            )
            result_type = create_result_type(
                item_type=items_model, pagination_selection=pag_selection,
            )
            fields[field_name] = (result_type, ...)
        else:
            # Nested relationship — recurse.
            nested_model = build_model(
                resolution.nested_type,
                child_sel,
                resolver=resolver,
                model_name=f"{field_name.capitalize()}",
            )
            if resolution.is_list:
                fields[field_name] = (list[nested_model], ...)  # type: ignore[valid-type]
            else:
                fields[field_name] = (nested_model | None, ...)

    return create_model(
        f"{owner_type.__name__}{model_name}",
        __config__=ConfigDict(from_attributes=True, arbitrary_types_allowed=True),
        **fields,
    )
