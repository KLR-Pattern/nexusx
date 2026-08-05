"""Dynamic Pydantic response model builder.

This module provides functionality to dynamically build Pydantic models
based on GraphQL field selection, enabling automatic filtering of
unwanted fields (like foreign keys) during serialization.
"""

from __future__ import annotations

from typing import Any, get_args, get_origin

from pydantic import BaseModel, create_model

from nexusx.loader.pagination import create_result_type
from nexusx.utils.type_utils import get_field_type


def build_response_model(
    entity: type,
    field_tree: dict[str, Any] | None,
    model_name: str = "Response",
    federation_namespace: dict[str, type] | None = None,
) -> type[BaseModel]:
    """Build a Pydantic model dynamically based on field selection tree.

    Args:
        entity: SQLModel entity class.
        field_tree: Field selection tree from GraphQL query.
            - None: Include all scalar fields
            - {"field": None}: Scalar field
            - {"field": {...}}: Nested relationship field
            - {"field": {"items": {...}, "pagination": {...}}}: Paginated package
              (renders as ``{items: list[nested], pagination: Pagination}``),
              specs/018 T003.
        model_name: Suffix for generated model name.
        federation_namespace: Optional map of federation-materialized remote
            types (keyed by ``__name__``). When resolving string forward refs,
            checked BEFORE local SQLModel subclasses — federation types don't
            appear in ``all_subclasses`` because they're pydantic ``create_model``
            products, not SQLModel children. specs/018 T004.

    Returns:
        Dynamically created Pydantic model class.
    """
    if field_tree is None:
        return _build_scalar_model(entity, model_name)

    fields = {}
    for field_name, nested in field_tree.items():
        if nested is None:
            # Scalar field - get type from entity
            field_type = get_field_type(entity, field_name)
            fields[field_name] = (field_type, ...)
            continue

        # Relationship field - build nested model
        relation_entity = get_relation_entity(
            entity, field_name, federation_namespace=federation_namespace
        )
        if relation_entity is None:
            # Fallback to Any if relation type cannot be determined
            fields[field_name] = (Any, ...)
            continue

        # Paginated package: {items: {...}, pagination: {...}} (specs/018 T003).
        # Reuses pagination.create_result_type to assemble the {items, pagination}
        # shape so behavior matches _serialize_paginated_package in query_executor.
        if _is_paginated_package(nested):
            items_tree = nested.get("items") or {}
            pagination_tree = nested.get("pagination") or {}
            nested_item_model = build_response_model(
                relation_entity, items_tree,
                f"{field_name.capitalize()}ItemResponse",
                federation_namespace=federation_namespace,
            )
            pag_selection = set(pagination_tree.keys()) if pagination_tree else None
            result_type = create_result_type(
                item_type=nested_item_model,
                pagination_selection=pag_selection,
            )
            fields[field_name] = (result_type, ...)
            continue

        nested_model = build_response_model(
            relation_entity, nested, f"{field_name.capitalize()}Response",
            federation_namespace=federation_namespace,
        )

        # Check if it's a list relationship
        if _is_list_relationship(entity, field_name):
            fields[field_name] = (list[nested_model], ...)  # type: ignore[valid-type]
        else:
            fields[field_name] = (nested_model | None, ...)

    return create_model(f"{entity.__name__}{model_name}", **fields)


def _is_paginated_package(nested: Any) -> bool:
    """True if ``nested`` field_tree represents a paginated package.

    A paginated package carries both ``items`` and ``pagination`` sub-keys —
    matching the ``{items, pagination}`` shape produced by ``page_by_<key>_in``
    gql roots or paginated relationship fields. Mirrors the runtime detection
    in ``query_executor._serialize_paginated_package`` (the dict-based path):
    "items" in pkg and "pagination" in pkg.
    """
    return (
        isinstance(nested, dict)
        and "items" in nested
        and "pagination" in nested
    )


def serialize_with_model(
    value: Any,
    entity: type,
    field_tree: dict[str, Any] | None,
) -> Any:
    """Serialize data using dynamically built Pydantic model.

    Args:
        value: Data to serialize (SQLModel instance or list).
        entity: SQLModel entity class.
        field_tree: Field selection tree.

    Returns:
        Serialized dictionary or list of dictionaries.
    """
    if value is None:
        return None

    model = build_response_model(entity, field_tree)

    if isinstance(value, list):
        return [_validate_and_dump(model, item, field_tree) for item in value]

    return _validate_and_dump(model, value, field_tree)


def _validate_and_dump(
    model: type[BaseModel],
    value: Any,
    field_tree: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate value with model and dump to dict.

    Handles SQLModel instances by recursively serializing nested relationships.
    """
    if value is None:
        return None

    value_type = type(value)

    # Convert to dict if it's a model instance
    if hasattr(value, "model_dump"):
        data = value.model_dump()
    elif isinstance(value, dict):
        data = value
    else:
        data = dict(value) if hasattr(value, "__iter__") else value

    # If we have nested field_tree, recursively serialize relationships
    if field_tree and isinstance(data, dict):
        for field_name, nested_tree in field_tree.items():
            if nested_tree is not None:
                # Get nested entity type
                nested_entity = get_relation_entity(value_type, field_name)
                if nested_entity:
                    nested_value = getattr(value, field_name, None)
                    if nested_value is not None:
                        data[field_name] = serialize_with_model(
                            nested_value, nested_entity, nested_tree
                        )

    try:
        validated = model.model_validate(data)
        return validated.model_dump(mode="json")
    except Exception:
        # Fallback: return filtered data directly
        if isinstance(data, dict) and field_tree:
            return {k: v for k, v in data.items() if k in field_tree}
        return data


def _resolve_forward_reference(
    annotation: str,
    all_subclasses: set[type],
    federation_namespace: dict[str, type] | None = None,
) -> type | None:
    """Resolve a string forward reference to an actual entity class.

    Args:
        annotation: String annotation (e.g., "EntityName", "list[EntityName]").
        all_subclasses: Set of all SQLModel subclasses to search.
        federation_namespace: Optional map of federation-materialized remote types
            keyed by ``__name__``. Checked BEFORE ``all_subclasses`` so federation
            types (pydantic ``create_model`` products, not SQLModel children)
            resolve ahead of local entity classes of the same name.
            specs/018 T004.

    Returns:
        Entity class or None if not found.
    """
    # Simple case: "EntityName"
    if "[" not in annotation:
        if federation_namespace and annotation in federation_namespace:
            return federation_namespace[annotation]
        for subclass in all_subclasses:
            if subclass.__name__ == annotation:
                return subclass
        return None

    # Complex case: "list[EntityName]" or "list['EntityName']"
    import re

    # Try quoted format first: list['EntityName']
    match = re.search(r"'([^']+)'", annotation)
    if match:
        entity_name = match.group(1)
    else:
        # Try unquoted format: list[EntityName]
        match = re.search(r"\[([^\]]+)\]", annotation)
        if match:
            entity_name = match.group(1).strip("'\"")
        else:
            return None

    if federation_namespace and entity_name in federation_namespace:
        return federation_namespace[entity_name]
    for subclass in all_subclasses:
        if subclass.__name__ == entity_name:
            return subclass
    return None


def get_relation_entity(
    entity: type,
    field_name: str,
    all_subclasses: set[type] | None = None,
    federation_namespace: dict[str, type] | None = None,
) -> type | None:
    """Get the target entity type for a relationship field.

    Args:
        entity: SQLModel entity class.
        field_name: Name of the relationship field.
        all_subclasses: Optional set of all SQLModel subclasses for resolving forward references.
        federation_namespace: Optional map of federation-materialized remote types
            (specs/018 T004).

    Returns:
        Target entity class or None if not found.
    """
    # Check SQLAlchemy relationships first (more reliable for actual entity types)
    try:
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(entity)
        if mapper and hasattr(mapper, "relationships"):
            if field_name in mapper.relationships:
                rel = mapper.relationships[field_name]
                return rel.mapper.class_
    except Exception:
        pass

    # Check SQLModel relationships
    if hasattr(entity, "__sqlmodel_relationships__"):
        rel_info = entity.__sqlmodel_relationships__.get(field_name)
        if rel_info is not None and hasattr(entity, "__annotations__"):
            annotation = entity.__annotations__.get(field_name)
            if annotation:
                result = _extract_entity_from_annotation(
                    annotation, all_subclasses, federation_namespace=federation_namespace
                )
                if result:
                    return result
                # Handle string forward references
                if isinstance(annotation, str) and all_subclasses:
                    return _resolve_forward_reference(
                        annotation, all_subclasses,
                        federation_namespace=federation_namespace,
                    )

    # Fallback: try to get from annotations
    if hasattr(entity, "__annotations__"):
        annotation = entity.__annotations__.get(field_name)
        if annotation:
            result = _extract_entity_from_annotation(
                annotation, all_subclasses, federation_namespace=federation_namespace
            )
            if result:
                return result
            # Handle string forward references
            if isinstance(annotation, str) and all_subclasses:
                return _resolve_forward_reference(
                    annotation, all_subclasses,
                    federation_namespace=federation_namespace,
                )

    return None


def _extract_entity_from_annotation(
    annotation: Any,
    all_subclasses: set[type] | None = None,
    federation_namespace: dict[str, type] | None = None,
) -> type | None:
    """Extract entity class from type annotation.

    Handles: Optional[Entity], list[Entity], List[Entity], and string forward references.

    Args:
        annotation: Type annotation (can be string, ForwardRef, or actual type).
        all_subclasses: Set of all SQLModel subclasses for resolving string forward references.
        federation_namespace: Optional map of federation-materialized remote types
            (specs/018 T004).
    """
    origin = get_origin(annotation)

    # Handle Optional[Entity] (Union[Entity, None])
    if origin is not None:
        args = get_args(annotation)
        for arg in args:
            if arg is type(None):
                continue
            if isinstance(arg, type):
                return arg
            # Handle nested generics like list[Entity]
            nested = _extract_entity_from_annotation(
                arg, all_subclasses, federation_namespace=federation_namespace
            )
            if nested:
                return nested
            # Handle string forward references in generic args
            if isinstance(arg, str) and all_subclasses:
                result = _resolve_forward_reference(
                    arg, all_subclasses,
                    federation_namespace=federation_namespace,
                )
                if result:
                    return result

    # Direct type
    if isinstance(annotation, type):
        return annotation

    # Handle string forward references
    if isinstance(annotation, str) and all_subclasses:
        return _resolve_forward_reference(
            annotation, all_subclasses,
            federation_namespace=federation_namespace,
        )

    return None


def _is_list_relationship(entity: type, field_name: str) -> bool:
    """Check if a relationship field is a list type.

    Args:
        entity: SQLModel entity class.
        field_name: Name of the relationship field.

    Returns:
        True if the relationship returns a list.
    """
    if hasattr(entity, "__annotations__"):
        annotation = entity.__annotations__.get(field_name)
        if annotation:
            origin = get_origin(annotation)
            if origin is list:
                return True
            # Check for List from typing
            if origin is not None:
                origin_name = getattr(origin, "__name__", "")
                if origin_name == "list" or str(origin).startswith("list"):
                    return True
    return False


def _build_scalar_model(entity: type, model_name: str) -> type[BaseModel]:
    """Build a Pydantic model with only scalar fields.

    Args:
        entity: SQLModel entity class.
        model_name: Suffix for generated model name.

    Returns:
        Pydantic model with only scalar fields.
    """
    fields = {}

    # Get relationship field names
    rel_names = get_relationship_names(entity)

    # Get scalar fields from model_fields
    if hasattr(entity, "model_fields"):
        for name, field_info in entity.model_fields.items():
            # Skip relationship fields
            if name in rel_names:
                continue
            field_type = field_info.annotation or Any
            fields[name] = (field_type, ...)

    return create_model(f"{entity.__name__}{model_name}", **fields)


def get_relationship_names(entity: type) -> set[str]:
    """Get names of all relationship fields.

    Args:
        entity: SQLModel entity class.

    Returns:
        Set of relationship field names.
    """
    names: set[str] = set()

    # SQLModel relationships
    if hasattr(entity, "__sqlmodel_relationships__"):
        names.update(entity.__sqlmodel_relationships__.keys())

    # SQLAlchemy relationships
    try:
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(entity)
        if mapper and hasattr(mapper, "relationships"):
            names.update(mapper.relationships.keys())
    except Exception:
        pass

    return names
