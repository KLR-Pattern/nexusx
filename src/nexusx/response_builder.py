"""Dynamic Pydantic response model builder.

This module provides functionality to dynamically build Pydantic models
based on GraphQL field selection, enabling automatic filtering of
unwanted fields (like foreign keys) during serialization.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from typing import Annotated, Any, get_args, get_origin

from pydantic import BaseModel, create_model

from nexusx.loader.pagination import Paged, create_result_type
from nexusx.utils.type_utils import get_field_type

# Resolver callable injected by QueryExecutor so build_response_model can find
# federation-materialized relationships (which live in ErManager._registry, not
# on the entity's SQLAlchemy mapper / __annotations__). Returns a duck-typed
# RelationshipInfo-like object with ``.target_entity`` (type) and ``.is_list``
# (bool); None when no federation relationship matches. specs/018 T002b.
RelationshipEntityResolver = Callable[[type, str], Any]


# Process-level LRU cache of built response models (specs/018 T026 mitigation).
# Without it, per-entity ``create_model`` dominates flag-on latency — cProfile
# showed it at 73% of Q2's flag-on time (10–30× slower than legacy _serialize).
# gql selections are discrete, so the key space is normally small; the first
# build pays the create_model cost and identical subsequent selections reuse the
# class. ``_MODEL_CACHE_MAX`` bounds it so a malicious/looping caller passing
# arbitrary gql args (e.g. ``limit``) cannot grow it without bound.
_MODEL_CACHE_MAX = 1024
_MODEL_CACHE: OrderedDict[tuple, type[BaseModel]] = OrderedDict()


def _cache_key(
    entity: type,
    field_tree: dict[str, Any] | None,
    model_name: str,
    federation_namespace: dict[str, type] | None,
    pagination_metadata: dict[str, Paged] | None,
) -> tuple:
    """Stable hashable key capturing every input that shapes the built model.

    ``relation_entity_resolver`` is a callable (not hashable) and intentionally
    excluded — its result (``target_entity`` / ``is_list``) is determined by the
    ErManager's stable relationship registry, so the same ``(entity, field_tree)``
    always yields the same model shape within a process. Assumption: an entity
    class has one consistent relationship configuration across the process
    (the normal single-ErManager case). ``federation_namespace`` types are keyed
    by ``id()`` (stable for long-lived registered materialized types).

    ``pagination_metadata`` Paged values are keyed by ``repr`` (frozen dataclass,
    stable). Different limit/order/direction combos yield distinct models because
    ``build_response_model`` stamps the value onto the field's
    ``Annotated[..., Paged(...)]`` metadata (specs/018 US2); the cache is bounded
    by ``_MODEL_CACHE_MAX`` (LRU eviction) so arbitrary gql args cannot grow it
    without bound.
    """
    ns = federation_namespace or {}
    ns_key = tuple(sorted((k, id(v)) for k, v in ns.items()))
    pm = pagination_metadata or {}
    pm_key = tuple(sorted((k, repr(v)) for k, v in pm.items()))
    return (entity, model_name, repr(field_tree), ns_key, pm_key)


def build_response_model(
    entity: type,
    field_tree: dict[str, Any] | None,
    model_name: str = "Response",
    federation_namespace: dict[str, type] | None = None,
    relation_entity_resolver: RelationshipEntityResolver | None = None,
    pagination_metadata: dict[str, Paged] | None = None,
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
        relation_entity_resolver: Optional callable injected by QueryExecutor
            to look up federation-materialized relationships in
            ``ErManager._registry`` (the source of truth for fields declared
            via ``__relationships__ = [RemoteRelationship(...)]`` — these don't
            appear on the entity's SQLAlchemy mapper or ``__annotations__``).
            Without it, ``reviews`` on ``Product`` is invisible to the builder.
            specs/018 T002b.
        pagination_metadata: Optional map of gql field args (``limit`` / ``offset``
            / ``order`` / ``direction``) packed as ``Paged`` per field name,
            derived from the gql selection (e.g. ``reviews(limit: 5)`` →
            ``{"reviews": Paged(limit=5)}``). When a paginated-package field
            appears in this map, the field type is upgraded to
            ``Annotated[{items, pagination} shape, Paged(...)]`` so Resolver can
            read the metadata and trigger page_loader (specs/018 US2). Absent
            for a field → plain ``{items, pagination}`` shape (US1 behavior,
            backward compatible).

    Returns:
        Dynamically created Pydantic model class.
    """
    key = _cache_key(
        entity, field_tree, model_name, federation_namespace, pagination_metadata,
    )
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        _MODEL_CACHE.move_to_end(key)  # LRU: mark most-recently-used
        return cached
    model = _build_response_model_uncached(
        entity, field_tree, model_name, federation_namespace,
        relation_entity_resolver, pagination_metadata,
    )
    _MODEL_CACHE[key] = model
    if len(_MODEL_CACHE) > _MODEL_CACHE_MAX:
        _MODEL_CACHE.popitem(last=False)  # evict least-recently-used
    return model


def _build_response_model_uncached(
    entity: type,
    field_tree: dict[str, Any] | None,
    model_name: str,
    federation_namespace: dict[str, type] | None,
    relation_entity_resolver: RelationshipEntityResolver | None,
    pagination_metadata: dict[str, Paged] | None,
) -> type[BaseModel]:
    """Build the model (cache-miss path). Split out so ``build_response_model``
    can memoize the result (specs/018 T026)."""
    if field_tree is None:
        return _build_scalar_model(entity, model_name)

    fields = {}
    for field_name, nested in field_tree.items():
        if nested is None:
            # Scalar field - get type from entity
            field_type = get_field_type(entity, field_name)
            fields[field_name] = (field_type, ...)
            continue

        # Federation registry first (source of truth for __relationships__
        # fields): carries both target_entity and is_list. specs/018 T002b.
        fed_rel = (
            relation_entity_resolver(entity, field_name)
            if relation_entity_resolver is not None
            else None
        )
        if fed_rel is not None:
            relation_entity = getattr(fed_rel, "target_entity", None)
            is_list = bool(getattr(fed_rel, "is_list", False))
        else:
            relation_entity = get_relation_entity(
                entity, field_name, federation_namespace=federation_namespace
            )
            is_list = _is_list_relationship(entity, field_name)

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
                relation_entity_resolver=relation_entity_resolver,
                pagination_metadata=_restrict_metadata(pagination_metadata, items_tree),
            )
            pag_selection = set(pagination_tree.keys()) if pagination_tree else None
            result_type = create_result_type(
                item_type=nested_item_model,
                pagination_selection=pag_selection,
            )
            # specs/018 US2: when gql args provided a Paged for this field,
            # wrap the result_type in Annotated so Resolver can read metadata
            # and dispatch to page_loader. Absent → plain shape (US1 path).
            paged_meta = pagination_metadata.get(field_name) if pagination_metadata else None
            if paged_meta is not None:
                fields[field_name] = (Annotated[result_type, paged_meta], ...)
            else:
                fields[field_name] = (result_type, ...)
            continue

        nested_model = build_response_model(
            relation_entity, nested, f"{field_name.capitalize()}Response",
            federation_namespace=federation_namespace,
            relation_entity_resolver=relation_entity_resolver,
            pagination_metadata=_restrict_metadata(pagination_metadata, nested),
        )

        if is_list:
            fields[field_name] = (list[nested_model], ...)  # type: ignore[valid-type]
        else:
            fields[field_name] = (nested_model | None, ...)

    return create_model(f"{entity.__name__}{model_name}", **fields)


def _restrict_metadata(
    pagination_metadata: dict[str, Paged] | None,
    nested_tree: dict[str, Any],
) -> dict[str, Paged] | None:
    """Trim ``pagination_metadata`` to keys that appear in ``nested_tree``.

    A field's Paged metadata applies at its own level; nested fields' metadata
    travels with them under their own keys. Restricting the dict before
    recursing into build_response_model keeps the lookup scoped to the child
    tree (and prevents accidental cross-branch matches when sibling fields
    share names with descendants).
    """
    if pagination_metadata is None:
        return None
    if not nested_tree:
        return None
    restricted = {
        k: v for k, v in pagination_metadata.items() if k in nested_tree
    }
    return restricted or None


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


def _coerce_to_dict(value: Any) -> Any:
    """Coerce a value to a plain dict if possible (model_dump / dict / iter).

    Returns ``None`` when the value can't be reasonably coerced. Used by
    paginated package serialization (specs/018 T005) where the package may
    arrive as a pydantic model or a plain dict.
    """
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return value
    if hasattr(value, "__iter__"):
        try:
            return dict(value)
        except Exception:
            return None
    return None


def _default_value_accessor(value: Any, field_name: str) -> Any:
    """Default ``value_accessor``: plain attribute lookup."""
    return getattr(value, field_name, None)


def serialize_with_model(
    value: Any,
    entity: type,
    field_tree: dict[str, Any] | None,
    federation_namespace: dict[str, type] | None = None,
    value_accessor: Any = None,
    relation_entity_resolver: RelationshipEntityResolver | None = None,
    pagination_metadata: dict[str, Paged] | None = None,
) -> Any:
    """Serialize data using dynamically built Pydantic model.

    Args:
        value: Data to serialize (SQLModel instance or list).
        entity: SQLModel entity class.
        field_tree: Field selection tree.
        federation_namespace: Optional map of federation-materialized remote types
            (specs/018 T004 / T005).
        value_accessor: Optional callable ``(value, field_name) -> nested_value``
            used to read nested relationship values. Defaults to ``getattr``.
            QueryExecutor passes a wrapper that checks its BFS-resolved
            ``_results`` cache first (avoiding SQLAlchemy DetachedInstanceError
            when the session is closed post-query); specs/018 T007.
        relation_entity_resolver: Optional callable to look up
            federation-materialized relationships in ErManager._registry
            (specs/018 T002b).
        pagination_metadata: Optional gql-args-derived ``{field_name: Paged}``;
            forwarded to ``build_response_model`` to stamp ``Annotated[..., Paged]``
            on paginated-package fields (specs/018 US2 / T014).

    Returns:
        Serialized dictionary or list of dictionaries.
    """
    if value is None:
        return None

    model = build_response_model(
        entity, field_tree,
        federation_namespace=federation_namespace,
        relation_entity_resolver=relation_entity_resolver,
        pagination_metadata=pagination_metadata,
    )

    if isinstance(value, list):
        return [
            _validate_and_dump(
                model, item, field_tree,
                federation_namespace=federation_namespace,
                value_accessor=value_accessor,
                relation_entity_resolver=relation_entity_resolver,
            )
            for item in value
        ]

    return _validate_and_dump(
        model, value, field_tree,
        federation_namespace=federation_namespace,
        value_accessor=value_accessor,
        relation_entity_resolver=relation_entity_resolver,
    )


def _validate_and_dump(
    model: type[BaseModel],
    value: Any,
    field_tree: dict[str, Any] | None,
    *,
    federation_namespace: dict[str, type] | None = None,
    value_accessor: Any = None,
    relation_entity_resolver: RelationshipEntityResolver | None = None,
) -> dict[str, Any]:
    """Validate value with model and dump to dict.

    Handles SQLModel instances by recursively serializing nested relationships.
    Recognizes paginated package field_tree (specs/018 T005): when the nested
    tree has ``items`` + ``pagination`` sub-keys, the corresponding value is
    treated as a ``{items, pagination}`` package — items are recursively
    serialized, pagination is filtered to the requested sub-keys.
    """
    if value is None:
        return None

    if value_accessor is None:
        value_accessor = _default_value_accessor

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
            if nested_tree is None:
                continue

            nested_entity = get_relation_entity(
                value_type, field_name,
                federation_namespace=federation_namespace,
                relation_entity_resolver=relation_entity_resolver,
            )
            if nested_entity is None:
                continue

            nested_value = value_accessor(value, field_name)
            if nested_value is None:
                continue

            # Paginated package: nested_value is {items: [...], pagination: {...}}
            # or a pydantic model with items/pagination. Mirror the runtime
            # handling in _serialize_paginated_package: recursively serialize
            # items, filter pagination to the requested sub-keys (specs/018 T005).
            if _is_paginated_package(nested_tree):
                pkg = _coerce_to_dict(nested_value)
                if not isinstance(pkg, dict):
                    continue
                pag_pkg: dict[str, Any] = {}
                items_value = pkg.get("items") or []
                items_tree = nested_tree.get("items") or {}
                pag_pkg["items"] = [
                    serialize_with_model(
                        it, nested_entity, items_tree,
                        federation_namespace=federation_namespace,
                        value_accessor=value_accessor,
                        relation_entity_resolver=relation_entity_resolver,
                    )
                    for it in items_value
                ]
                pagination_tree = nested_tree.get("pagination") or {}
                pagination_value = _coerce_to_dict(pkg.get("pagination")) or {}
                if pagination_tree:
                    pag_pkg["pagination"] = {
                        k: v for k, v in pagination_value.items()
                        if k in pagination_tree
                    }
                else:
                    pag_pkg["pagination"] = pagination_value
                data[field_name] = pag_pkg
            else:
                data[field_name] = serialize_with_model(
                    nested_value, nested_entity, nested_tree,
                    federation_namespace=federation_namespace,
                    value_accessor=value_accessor,
                    relation_entity_resolver=relation_entity_resolver,
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
    relation_entity_resolver: RelationshipEntityResolver | None = None,
) -> type | None:
    """Get the target entity type for a relationship field.

    Args:
        entity: SQLModel entity class.
        field_name: Name of the relationship field.
        all_subclasses: Optional set of all SQLModel subclasses for resolving forward references.
        federation_namespace: Optional map of federation-materialized remote types
            (specs/018 T004).
        relation_entity_resolver: Optional callable to look up
            federation-materialized relationships in ErManager._registry. Tried
            BEFORE the SQLAlchemy / SQLModel / annotations fallbacks because
            federation fields declared via ``__relationships__`` never appear
            on the SQLAlchemy mapper or ``__annotations__`` (specs/018 T002b).

    Returns:
        Target entity class or None if not found.
    """
    # Federation registry lookup (source of truth for __relationships__ fields).
    if relation_entity_resolver is not None:
        try:
            resolved = relation_entity_resolver(entity, field_name)
        except Exception:
            resolved = None
        if resolved is not None:
            # Resolver returns a RelationshipInfo-like object; callers of this
            # function want the target type. Unwrap defensively (specs/018 T002b).
            target = getattr(resolved, "target_entity", None)
            if target is not None:
                return target
            if isinstance(resolved, type):
                return resolved
            return None

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


def _is_list_relationship(
    entity: type,
    field_name: str,
) -> bool:
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
