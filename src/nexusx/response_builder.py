"""Dynamic Pydantic response model builder.

This module provides functionality to dynamically build Pydantic models
based on GraphQL field selection, enabling automatic filtering of
unwanted fields (like foreign keys) during serialization.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from typing import Any, ForwardRef, get_args, get_origin

from pydantic import BaseModel, create_model

from nexusx.core_builder import FieldResolution, build_model, is_paginated_package
from nexusx.query_parser import FieldSelection
from nexusx.utils.type_utils import coerce_to_dict, get_field_type, is_list_annotation

# Resolver callable injected by QueryExecutor so build_response_model can find
# federation-materialized relationships (which live in ErManager._registry, not
# on the entity's SQLAlchemy mapper / __annotations__). Returns a duck-typed
# RelationshipInfo-like object with ``.target_entity`` (type) and ``.is_list``
# (bool); None when no federation relationship matches. specs/018 T002b.
RelationshipEntityResolver = Callable[[type, str], Any]


class ERFieldResolver:
    """FieldResolver for entity-first gql (specs/021 path-merge).

    Wraps the relationship-resolution logic the old builder used inline
    (federation ``__relationships__`` → SQLAlchemy mapper →
    ``__sqlmodel_relationships__`` → ``__annotations__`` fallback) into the
    ``FieldResolver`` protocol so ``core_builder.build_model`` can consume it.
    """

    def __init__(
        self,
        relation_entity_resolver: RelationshipEntityResolver | None = None,
        federation_namespace: dict[str, type] | None = None,
    ):
        self._rel_resolver = relation_entity_resolver
        self._fed_ns = federation_namespace

    def resolve_field(self, entity: type, field_name: str) -> FieldResolution | None:
        # Federation registry first (source of truth for __relationships__).
        fed_rel = (
            self._rel_resolver(entity, field_name)
            if self._rel_resolver is not None
            else None
        )
        if fed_rel is not None:
            return FieldResolution(
                annotation=get_field_type(entity, field_name),
                nested_type=getattr(fed_rel, "target_entity", None),
                nested_shape=_list_shape(
                    bool(getattr(fed_rel, "is_list", False))
                ),
            )
        # SQLAlchemy / SQLModel / annotations fallback. ``get_relation_entity``
        # also returns scalar field types (str/int, extracted from annotations),
        # so only a BaseModel target counts as a nested relationship — the
        # builder would otherwise recurse into ``str`` and mint a bogus model
        # (specs/021 strTitle bug: MPPost.title became a strTitle class).
        rel_entity = get_relation_entity(
            entity, field_name, federation_namespace=self._fed_ns
        )
        if not (isinstance(rel_entity, type) and issubclass(rel_entity, BaseModel)):
            rel_entity = None
        annotation = get_field_type(entity, field_name)
        if (
            rel_entity is None
            and _is_declared_relationship(entity, field_name)
            and _contains_unresolved_forward_ref(annotation)
        ):
            annotation = Any
        return FieldResolution(
            annotation=annotation,
            nested_type=rel_entity,
            nested_shape=_list_shape(
                _is_list_relationship(entity, field_name)
            ),
        )


def _list_shape(is_list: bool) -> Callable[[type[BaseModel]], Any] | None:
    """``nested_shape`` for an entity-first relationship.

    ``True`` → ``list[nested]`` (to-many); ``False`` → None, which keeps the
    builder's lenient default: nullable single (``nested | None``).
    """
    if is_list:
        return lambda nested_model: list[nested_model]  # type: ignore[valid-type]
    return None


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
    selection: FieldSelection | None,
    model_name: str,
    federation_namespace: dict[str, type] | None,
) -> tuple:
    """Stable hashable key capturing every input that shapes the built model.

    ``relation_entity_resolver`` is a callable (not hashable) and intentionally
    excluded — its result is determined by the ErManager's stable relationship
    registry. ``federation_namespace`` types are keyed by ``id()``.

    paged values are NOT in the key (specs/020): the model is a pure shape
    container (paged fields are plain ``result_type``, no marker); paged params
    flow through a ``paged_provider`` closure at resolve time. The structure
    repr distinguishes paged fields (they carry ``items``/``pagination``
    sub-keys), so no separate paged dimension is needed — and it excludes
    ``FieldSelection.name/alias/arguments`` so caller page args (limit/...)
    never fragment the cache (specs/021 P0-2).
    """
    ns = federation_namespace or {}
    ns_key = tuple(sorted((k, id(v)) for k, v in ns.items()))
    return (entity, model_name, _selection_structure_repr(selection), ns_key)


def _selection_structure_repr(selection: FieldSelection | None) -> str:
    """Structure-only repr of a FieldSelection tree (sub_fields only).

    Excludes ``name`` / ``alias`` / ``arguments``. Dict and FieldSelection
    inputs for the same query produce the same key (both normalize to a
    FieldSelection before keying).
    """
    if selection is None:
        return "None"
    return "{" + ",".join(
        f"{name}:{_selection_structure_repr(child)}"
        for name, child in (selection.sub_fields or {}).items()
    ) + "}"


def build_response_model(
    entity: type,
    field_tree: dict[str, Any] | None,
    model_name: str = "Response",
    federation_namespace: dict[str, type] | None = None,
    relation_entity_resolver: RelationshipEntityResolver | None = None,
    _selection: FieldSelection | None = None,
) -> type[BaseModel]:
    """Build a Pydantic model dynamically based on field selection tree.

    The model is a pure shape container (scalar / nested / paginated-package);
    paged params (limit/offset/order/direction) are NOT baked in — they flow
    through a ``paged_provider`` closure at resolve time (specs/019). Paged
    detection at dispatch uses ``rel_info.page_loader``, not model metadata.

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
            types (keyed by ``__name__``), checked before local SQLModel
            subclasses when resolving forward refs. specs/018 T004.
        relation_entity_resolver: Optional callable injected by QueryExecutor
            to look up federation-materialized relationships in
            ``ErManager._registry``. specs/018 T002b.
        _selection: Internal — a parsed ``FieldSelection`` tree, passed by
            QueryExecutor to skip the dict round-trip (specs/021 P0-2). Mutually
            exclusive with ``field_tree``. An empty ``sub_fields`` keeps the
            dict-API semantics of ``field_tree=None`` (all scalar fields).

    Returns:
        Dynamically created Pydantic model class.
    """
    if _selection is not None:
        selection = _selection if _selection.sub_fields else None
    elif field_tree is None:
        selection = None
    else:
        selection = _field_tree_to_selection(field_tree)

    key = _cache_key(
        entity, selection, model_name, federation_namespace,
    )
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        _MODEL_CACHE.move_to_end(key)  # LRU: mark most-recently-used
        return cached
    model = _build_model_uncached(
        entity, selection, model_name, federation_namespace,
        relation_entity_resolver,
    )
    _MODEL_CACHE[key] = model
    if len(_MODEL_CACHE) > _MODEL_CACHE_MAX:
        _MODEL_CACHE.popitem(last=False)  # evict least-recently-used
    return model


def _build_model_uncached(
    entity: type,
    selection: FieldSelection | None,
    model_name: str,
    federation_namespace: dict[str, type] | None,
    relation_entity_resolver: RelationshipEntityResolver | None,
) -> type[BaseModel]:
    """Build the model (cache-miss path).

    specs/021: delegates to ``core_builder.build_model`` with an
    ``ERFieldResolver`` — the relationship/annotation resolution this function
    did inline now lives in the resolver. ``selection=None`` keeps its
    "all scalar fields" meaning.
    """
    if selection is None:
        return _build_scalar_model(entity, model_name)

    return build_model(
        entity, selection,
        resolver=ERFieldResolver(relation_entity_resolver, federation_namespace),
        model_name=model_name,
    )


def _field_tree_to_selection(field_tree: dict[str, Any]) -> FieldSelection:
    """Convert a response field_tree dict into a ``FieldSelection`` tree.

    specs/021: ``core_builder.build_model`` consumes ``FieldSelection``; the
    entity-first shell converts its dict-shaped selection (``{"field": None}``
    scalar, ``{"field": {...}}`` nested, ``{"items": ..., "pagination": ...}``
    paginated package) before delegating.
    """
    root = FieldSelection()
    root.sub_fields = {
        name: _sub_tree_to_selection(nested)
        for name, nested in field_tree.items()
    }
    return root


def _sub_tree_to_selection(nested: Any) -> FieldSelection:
    sel = FieldSelection()
    if isinstance(nested, dict):
        sel.sub_fields = {
            name: _sub_tree_to_selection(sub)
            for name, sub in nested.items()
        }
    return sel


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
    _selection: FieldSelection | None = None,
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
        _selection: Internal — parsed ``FieldSelection`` passed by
            QueryExecutor to skip the dict round-trip (specs/021 P0-2).
            ``_validate_and_dump``'s recursive serialization still consumes a
            dict tree, so it is materialized once here.

    Returns:
        Serialized dictionary or list of dictionaries.
    """
    if value is None:
        return None

    # The recursive serializer consumes a dict tree; materialize it once from
    # the internal FieldSelection (specs/021 P0-2).
    if _selection is not None:
        field_tree = _selection_to_tree(_selection)

    model = build_response_model(
        entity, field_tree,
        federation_namespace=federation_namespace,
        relation_entity_resolver=relation_entity_resolver,
        _selection=_selection,
    )

    if isinstance(value, list):
        return [
            _validate_and_dump(
                model, item, field_tree,
                entity=entity,
                federation_namespace=federation_namespace,
                value_accessor=value_accessor,
                relation_entity_resolver=relation_entity_resolver,
            )
            for item in value
        ]

    return _validate_and_dump(
        model, value, field_tree,
        entity=entity,
        federation_namespace=federation_namespace,
        value_accessor=value_accessor,
        relation_entity_resolver=relation_entity_resolver,
    )


def _selection_to_tree(field_sel: FieldSelection | None) -> dict[str, Any] | None:
    """Convert a ``FieldSelection`` to the dict ``field_tree`` shape.

    Mapping (mirrors query_executor's old ``_field_sel_to_tree``, moved here
    as the inverse of ``_field_tree_to_selection`` for the serializer):
      - ``field_sel = None`` → ``None`` (all scalar fields)
      - sub_field with no children → ``{name: None}`` (scalar)
      - sub_field with children → ``{name: <recurse>}`` (nested relationship)
    """
    if field_sel is None or not field_sel.sub_fields:
        return None
    tree: dict[str, Any] = {}
    for name, child in field_sel.sub_fields.items():
        if not child.sub_fields:
            tree[name] = None
        else:
            tree[name] = _selection_to_tree(child)
    return tree


def _validate_and_dump(
    model: type[BaseModel],
    value: Any,
    field_tree: dict[str, Any] | None,
    *,
    entity: type,
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

    ``entity`` is the declared SQLModel type — used for relationship lookup
    instead of ``type(value)`` because local paged loaders return SQLAlchemy
    ``RowMapping`` (not entity instances), and the registry keys on entity
    classes (specs/020 nested-paged fix).
    """
    if value is None:
        return None

    if value_accessor is None:
        value_accessor = _default_value_accessor

    # Convert to dict if it's a model instance
    if hasattr(value, "model_dump"):
        data = value.model_dump()
    elif isinstance(value, dict):
        data = value
    else:
        data = dict(value) if hasattr(value, "__iter__") else value

    # If we have nested field_tree, recursively serialize relationships.
    # Use ``entity`` (declared type), NOT type(value) — paged loaders return
    # RowMapping; relationship lookup must key on the entity class.
    if field_tree and isinstance(data, dict):
        for field_name, nested_tree in field_tree.items():
            if nested_tree is None:
                continue

            nested_entity = get_relation_entity(
                entity, field_name,
                federation_namespace=federation_namespace,
                relation_entity_resolver=relation_entity_resolver,
            )
            if nested_entity is None:
                continue

            nested_value = value_accessor(value, field_name)
            if nested_value is None:
                data[field_name] = None
                continue

            # Paginated package: nested_value is {items: [...], pagination: {...}}
            # or a pydantic model with items/pagination. Mirror the runtime
            # handling in _serialize_paginated_package: recursively serialize
            # items, filter pagination to the requested sub-keys (specs/018 T005).
            if is_paginated_package(nested_tree):
                pkg = coerce_to_dict(nested_value)
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
                pagination_value = coerce_to_dict(pkg.get("pagination")) or {}
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
            return is_list_annotation(annotation)
    return False


def _is_declared_relationship(entity: type, field_name: str) -> bool:
    if field_name in get_relationship_names(entity):
        return True
    return any(
        getattr(rel, "name", None) == field_name
        for rel in getattr(entity, "__relationships__", ())
    )


def _contains_unresolved_forward_ref(annotation: Any) -> bool:
    if isinstance(annotation, (str, ForwardRef)):
        return True
    return any(
        _contains_unresolved_forward_ref(arg)
        for arg in get_args(annotation)
    )


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
