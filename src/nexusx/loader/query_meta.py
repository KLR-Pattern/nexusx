"""Query meta generation for SQL column pruning.

Analyzes response models or GraphQL field selections to determine
which SQL columns each loader actually needs, then attaches this
metadata to loader instances for use in batch_load_fn.

Adapted from pydantic-resolve's loader_manager._generate_query_meta.
"""
from __future__ import annotations

from typing import Any, TypedDict

from pydantic import BaseModel


class LoaderQueryMeta(TypedDict):
    """Metadata attached to a DataLoader instance for column pruning."""
    fields: list[str]  # Union of all needed SQL column names
    request_types: list[dict[str, Any]]  # Per-type field breakdowns


def generate_query_meta_from_dto(dto_class: type[BaseModel]) -> LoaderQueryMeta:
    """Generate query_meta from a DefineSubset DTO class.

    Extracts all Pydantic field names that correspond to SQL columns.
    """
    fields = list(dto_class.model_fields.keys())
    return {
        'fields': fields,
        'request_types': [{'name': dto_class, 'fields': fields}],
    }


def generate_query_meta_from_selection(
    field_selection: Any,
    entity_kls: type[BaseModel],
    fk_lookup: dict[str, str] | None = None,
) -> LoaderQueryMeta:
    """Generate query_meta from a GraphQL FieldSelection + entity class.

    Only includes scalar fields that exist on the entity's model_fields.
    Relationship fields (those with sub_fields) are excluded from SQL column
    list since they're loaded via separate DataLoaders, but their FK columns
    are preserved.

    Args:
        field_selection: Parsed GraphQL field selection.
        entity_kls: Target entity class.
        fk_lookup: Optional mapping of relationship_name -> fk_field_name
            from LoaderRegistry. When provided, uses actual FK names instead
            of the ``{rel_name}_id`` naming convention fallback.
    """
    if field_selection is None or not field_selection.sub_fields:
        return {
            'fields': list(entity_kls.model_fields.keys()),
            'request_types': [],
        }

    fields: list[str] = []
    for fname, child_sel in field_selection.sub_fields.items():
        if not child_sel.sub_fields:
            # Scalar field: directly maps to a SQL column
            if fname in entity_kls.model_fields:
                fields.append(fname)
        else:
            # Relationship field: preserve the FK column
            if fk_lookup and fname in fk_lookup:
                fk_name = fk_lookup[fname]
            else:
                # Fallback to naming convention
                fk_name = f"{fname}_id"
            if fk_name in entity_kls.model_fields and fk_name not in fields:
                fields.append(fk_name)

    return {
        'fields': fields,
        'request_types': [],
    }


def merge_query_meta(loader: Any, meta: LoaderQueryMeta) -> None:
    """Merge _query_meta onto a loader instance.

    If _query_meta already exists, merges fields (union) to handle the case
    where the same loader is used for multiple relationships requesting
    different fields within a single request.
    """
    existing = getattr(loader, "_query_meta", None)
    if existing is None:
        loader._query_meta = meta
    else:
        existing_fields = set(existing.get('fields', []))
        new_fields = set(meta.get('fields', []))
        merged = existing_fields | new_fields
        existing['fields'] = list(merged)


def set_query_meta(loader: Any, meta: LoaderQueryMeta) -> None:
    """Directly set _query_meta on a loader instance (no merge).

    Used in split mode where each loader instance is dedicated to one type_key.
    """
    loader._query_meta = meta


def generate_type_key_from_selection(
    field_selection: Any,
    entity_kls: type[BaseModel],
    fk_lookup: dict[str, str] | None = None,
) -> frozenset[str] | None:
    """Generate a hashable type_key from a GraphQL FieldSelection.

    Returns frozenset of scalar field names, or None if selection is empty
    (meaning no column pruning is possible).

    Args:
        field_selection: Parsed GraphQL field selection.
        entity_kls: Target entity class.
        fk_lookup: Optional mapping of relationship_name -> fk_field_name.
    """
    if field_selection is None or not field_selection.sub_fields:
        return None

    fields: set[str] = set()
    for fname, child_sel in field_selection.sub_fields.items():
        if not child_sel.sub_fields:
            if fname in entity_kls.model_fields:
                fields.add(fname)
        else:
            if fk_lookup and fname in fk_lookup:
                fk_name = fk_lookup[fname]
            else:
                fk_name = f"{fname}_id"
            if fk_name in entity_kls.model_fields:
                fields.add(fk_name)

    return frozenset(fields) if fields else None


def generate_type_key_from_dto(
    dto_class: type[BaseModel],
    entity_kls: type[BaseModel] | None = None,
) -> frozenset[str] | None:
    """Generate a hashable type_key from a DefineSubset DTO.

    Returns frozenset of field names that correspond to SQL columns.
    Filters out non-SQL fields (post_* computed fields, relationship fields).

    Returns None if no SQL-column fields can be identified.
    """
    subset_fields = getattr(dto_class, "__subset_fields__", None)
    if subset_fields is not None:
        # DefineSubset: __subset_fields__ lists the SQL column names
        return frozenset(subset_fields)

    # Fallback: use all model_fields, filter to SQL columns if entity is known
    all_fields = set(dto_class.model_fields.keys())
    if entity_kls is not None:
        sql_fields = set(entity_kls.model_fields.keys())
        all_fields &= sql_fields

    return frozenset(all_fields) if all_fields else None
