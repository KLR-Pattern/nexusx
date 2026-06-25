"""ErManager — inspects ORM metadata, creates DataLoaders, produces Resolvers.

Central hub for entity-relationship management. Accepts a SQLModel base class
or explicit entity list, auto-discovers relationships, and provides
``create_resolver()`` for building request-scoped Resolver instances.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiodataloader import DataLoader
from pydantic import BaseModel
from sqlmodel import SQLModel

from nexusx.loader.factories import (
    create_many_to_many_loader,
    create_many_to_one_loader,
    create_one_to_many_loader,
    create_page_many_to_many_loader,
    create_page_one_to_many_loader,
)
from nexusx.relationship import Relationship, get_custom_relationships

logger = logging.getLogger(__name__)


@dataclass
class RelationshipInfo:
    """Metadata for a single ORM relationship, including its DataLoader."""

    name: str  # relationship field name on the entity
    direction: str  # MANYTOONE | ONETOMANY | MANYTOMANY
    fk_field: str  # FK field on the *source* entity used as loader key
    target_entity: type[SQLModel]  # target entity class
    is_list: bool  # True for one-to-many / many-to-many lists
    loader: type[DataLoader]  # regular DataLoader class
    page_loader: type[DataLoader] | None = None  # paginated loader (list only)
    sort_field: str | None = None  # sort column for pagination
    default_page_size: int = 20
    max_page_size: int = 100


def _expect_single_pair(pairs: Any, message: str) -> tuple[Any, Any]:
    pair_list = list(pairs)
    if len(pair_list) != 1:
        raise NotImplementedError(message)
    return pair_list[0]


def _extract_sort_field(order_by: Any) -> str:
    """Extract column name from a SQLAlchemy order_by clause.

    Handles plain column references (Column.key), as well as
    desc(Column) / asc(Column) UnaryExpression wrappers.
    """
    if isinstance(order_by, (list, tuple)):
        if len(order_by) == 0:
            raise ValueError("order_by cannot be empty")
        if len(order_by) > 1:
            raise ValueError(
                f"Only single-column sorting is supported, got {len(order_by)} columns"
            )
        order_by = order_by[0]

    # Handle UnaryExpression: desc(Column), asc(Column)
    if hasattr(order_by, "element"):
        inner = order_by.element
        if hasattr(inner, "key"):
            return inner.key

    if hasattr(order_by, "key"):
        return order_by.key

    raise ValueError(
        f"Unable to extract sort field from order_by clause: {order_by}. "
        f"Please use a simple column reference like Post.id or desc(Post.id)"
    )


def _inspect_relationships(
    entity_kls: type[SQLModel],
    all_entities: set[type[SQLModel]],
    session_factory: Callable,
) -> list[RelationshipInfo]:
    """Inspect a single entity's ORM relationships and create loaders."""
    from sqlalchemy import inspect
    from sqlalchemy.orm import MANYTOMANY, MANYTOONE, ONETOMANY

    try:
        mapper = inspect(entity_kls)
    except Exception:
        # Not a mapped entity (no table=True)
        return []

    # Only process entities with actual table mappings
    if not hasattr(mapper, "relationships"):
        return []

    results: list[RelationshipInfo] = []

    for rel in mapper.relationships:
        target_entity = rel.mapper.class_

        # Only process relationships to known entities
        if target_entity not in all_entities:
            logger.debug(
                "Skipping %s.%s: target %s not in entity list",
                entity_kls.__name__,
                rel.key,
                target_entity.__name__,
            )
            continue

        direction = rel.direction
        rel_name = rel.key

        if direction is MANYTOONE:
            local_col, remote_col = _expect_single_pair(
                rel.local_remote_pairs,
                f"Composite FK not supported for MANYTOONE: {entity_kls.__name__}.{rel_name}",
            )
            fk_field = local_col.key
            loader = create_many_to_one_loader(
                source_kls=entity_kls,
                rel_name=rel_name,
                target_kls=target_entity,
                target_remote_col_name=remote_col.key,
                session_factory=session_factory,
            )
            results.append(
                RelationshipInfo(
                    name=rel_name,
                    direction="MANYTOONE",
                    fk_field=fk_field,
                    target_entity=target_entity,
                    is_list=False,
                    loader=loader,
                )
            )

        elif direction is ONETOMANY:
            local_col, remote_col = _expect_single_pair(
                rel.local_remote_pairs,
                f"Composite FK not supported for ONETOMANY: {entity_kls.__name__}.{rel_name}",
            )
            fk_field = local_col.key

            if rel.uselist is False:
                # Reverse one-to-one (treated as scalar)
                from nexusx.loader.factories import (
                    create_many_to_one_loader as _m2o,
                )

                loader = _m2o(
                    source_kls=entity_kls,
                    rel_name=rel_name,
                    target_kls=target_entity,
                    target_remote_col_name=remote_col.key,
                    session_factory=session_factory,
                )
                results.append(
                    RelationshipInfo(
                        name=rel_name,
                        direction="ONETOMANY_SCALAR",
                        fk_field=fk_field,
                        target_entity=target_entity,
                        is_list=False,
                        loader=loader,
                    )
                )
            else:
                # List relationship — create regular + optional paginated loader
                sort_field = None
                page_loader = None

                order_by = rel.order_by
                if order_by and order_by is not False:
                    sort_field = _extract_sort_field(order_by)
                    target_mapper = inspect(target_entity)
                    pk_col_name = target_mapper.primary_key[0].name

                    page_loader = create_page_one_to_many_loader(
                        source_kls=entity_kls,
                        rel_name=rel_name,
                        target_kls=target_entity,
                        target_fk_col_name=remote_col.key,
                        sort_field=sort_field,
                        pk_col_name=pk_col_name,
                        session_factory=session_factory,
                    )

                loader = create_one_to_many_loader(
                    source_kls=entity_kls,
                    rel_name=rel_name,
                    target_kls=target_entity,
                    target_fk_col_name=remote_col.key,
                    session_factory=session_factory,
                )

                results.append(
                    RelationshipInfo(
                        name=rel_name,
                        direction="ONETOMANY",
                        fk_field=fk_field,
                        target_entity=target_entity,
                        is_list=True,
                        loader=loader,
                        page_loader=page_loader,
                        sort_field=sort_field,
                    )
                )

        elif direction is MANYTOMANY:
            secondary = rel.secondary
            if secondary is None:
                raise NotImplementedError(
                    f"MANYTOMANY without secondary table: {entity_kls.__name__}.{rel_name}"
                )

            source_col, secondary_local_col = _expect_single_pair(
                rel.synchronize_pairs,
                f"Composite source pair not supported: {entity_kls.__name__}.{rel_name}",
            )
            target_col, secondary_remote_col = _expect_single_pair(
                rel.secondary_synchronize_pairs,
                f"Composite target pair not supported: {entity_kls.__name__}.{rel_name}",
            )
            fk_field = source_col.key

            sort_field = None
            page_loader = None

            order_by = rel.order_by
            if order_by and order_by is not False:
                sort_field = _extract_sort_field(order_by)
                target_mapper = inspect(target_entity)
                pk_col_name = target_mapper.primary_key[0].name

                page_loader = create_page_many_to_many_loader(
                    source_kls=entity_kls,
                    rel_name=rel_name,
                    target_kls=target_entity,
                    secondary_table=secondary,
                    secondary_local_col_name=secondary_local_col.key,
                    secondary_remote_col_name=secondary_remote_col.key,
                    target_match_col_name=target_col.key,
                    sort_field=sort_field,
                    pk_col_name=pk_col_name,
                    session_factory=session_factory,
                )

            loader = create_many_to_many_loader(
                source_kls=entity_kls,
                rel_name=rel_name,
                target_kls=target_entity,
                secondary_table=secondary,
                secondary_local_col_name=secondary_local_col.key,
                secondary_remote_col_name=secondary_remote_col.key,
                target_match_col_name=target_col.key,
                session_factory=session_factory,
            )

            results.append(
                RelationshipInfo(
                    name=rel_name,
                    direction="MANYTOMANY",
                    fk_field=fk_field,
                    target_entity=target_entity,
                    is_list=True,
                    loader=loader,
                    page_loader=page_loader,
                    sort_field=sort_field,
                )
            )

    return results


def _build_custom_relationship_info(rel: Relationship) -> RelationshipInfo:
    """Convert a custom Relationship to a RelationshipInfo with a DataLoader class."""
    loader_fn = rel.loader

    class _CustomLoader(DataLoader):
        async def batch_load_fn(self, keys):
            return await loader_fn(keys)

    _CustomLoader.__name__ = f"CustomLoader_{rel.name}"
    _CustomLoader.__qualname__ = f"CustomLoader_{rel.name}"

    return RelationshipInfo(
        name=rel.name,
        direction="CUSTOM",
        fk_field=rel.fk,
        target_entity=rel.target_entity,
        is_list=rel.is_list,
        loader=_CustomLoader,
    )


class ErManager:
    """Entity-Relationship manager — the central hub for nexusx.

    Inspects SQLModel ORM metadata to auto-discover relationships,
    creates DataLoaders, and produces request-scoped Resolver instances.

    Usage::

        er = ErManager(base=SQLModel, session_factory=async_session)
        resolver = er.create_resolver(context={"user_id": 1})
        result = await resolver.resolve(dtos)
    """

    def __init__(
        self,
        session_factory: Callable,
        base: type | None = None,
        entities: list[type[SQLModel]] | None = None,
        enable_pagination: bool = False,
        split_loader_by_type: bool = False,
    ):
        if base is not None and entities is not None:
            raise ValueError("base and entities are mutually exclusive")
        if base is None and entities is None:
            raise ValueError("Either base or entities must be provided")

        if base is not None:
            from nexusx.discovery import EntityDiscovery
            entities = EntityDiscovery(base).discover(include_all=True)

        self._session_factory = session_factory
        self._enable_pagination = enable_pagination
        self._split_mode = split_loader_by_type
        # entity -> {rel_name -> RelationshipInfo}. Keys may be SQLModel
        # classes (registered via __init__) OR plain BaseModel classes
        # (registered via add_virtual_entities). The dict shape is uniform;
        # downstream code is source-type-agnostic.
        self._registry: dict[type, dict[str, RelationshipInfo]] = {}
        # Cache of instantiated loaders.
        # Default mode: {loader_cls: instance}
        # Split mode: {loader_cls: {type_key: instance}}
        self._loader_instances: dict = {}
        # Frozen flag: set True on first create_resolver(). After that,
        # add_virtual_entities() raises RuntimeError — the registry and
        # loader wiring cannot be safely mutated once a Resolver exists.
        self._frozen: bool = False

        all_entities = set(entities)
        for entity in entities:
            rels = _inspect_relationships(entity, all_entities, session_factory)
            self._registry[entity] = {r.name: r for r in rels}

        # Register custom relationships from __relationships__
        for entity in entities:
            custom_rels = get_custom_relationships(entity)
            entity_rels = self._registry.setdefault(entity, {})
            for rel in custom_rels:
                if rel.name in entity_rels:
                    raise ValueError(
                        f"Custom relationship '{rel.name}' on {entity.__name__} "
                        f"conflicts with an existing relationship name"
                    )
                entity_rels[rel.name] = _build_custom_relationship_info(rel)

        if enable_pagination:
            self._validate_pagination()

    def add_virtual_entities(self, entities: list[type[BaseModel]]) -> None:
        """Register plain ``BaseModel`` subclasses as non-SQLModel virtual entities.

        Each entry becomes a first-class member of the ER graph: a valid
        Resolver root, a participant in custom relationships (declared via
        ``__relationships__``), and a virtual node in ER diagrams / Voyager.

        Must be called **before** the first ``create_resolver()`` — the
        registry is frozen at that point and subsequent calls raise
        ``RuntimeError``.

        Args:
            entities: A list of BaseModel subclasses. Each MUST NOT be a
                SQLModel subclass (those go in ``__init__``'s ``entities=``
                or via ``base=``).

        Raises:
            RuntimeError: If called after ``create_resolver()``.
            TypeError: If an entry is not a class, not a BaseModel subclass,
                or is a SQLModel subclass.
            ValueError: If an entry is already registered.
        """
        if self._frozen:
            raise RuntimeError(
                "ErManager registry is frozen after first create_resolver() "
                "call. Call add_virtual_entities() before any "
                "create_resolver()."
            )

        seen_in_this_call: set[type] = set()
        for entity in entities:
            if not isinstance(entity, type):
                raise TypeError(
                    f"add_virtual_entities entries must be classes; got "
                    f"{type(entity).__name__} value {entity!r}."
                )
            if issubclass(entity, SQLModel):
                raise TypeError(
                    f"{entity.__name__} is a SQLModel subclass; SQLModel "
                    f"entities must be passed to ErManager.__init__'s "
                    f"entities= or base=, not add_virtual_entities()."
                )
            if not issubclass(entity, BaseModel):
                raise TypeError(
                    f"{entity.__name__} must be a subclass of "
                    f"pydantic.BaseModel."
                )
            if entity in self._registry or entity in seen_in_this_call:
                raise ValueError(
                    f"{entity.__name__} is already registered."
                )
            seen_in_this_call.add(entity)

            # Wire relationships from __relationships__ (no _inspect_relationships
            # call — virtual entities have no SQLAlchemy mapper to inspect).
            custom_rels = get_custom_relationships(entity)
            entity_rels: dict[str, RelationshipInfo] = {}
            for rel in custom_rels:
                if rel.name in entity_rels:
                    raise ValueError(
                        f"Custom relationship '{rel.name}' on "
                        f"{entity.__name__} conflicts with another "
                        f"relationship name on the same class."
                    )
                entity_rels[rel.name] = _build_custom_relationship_info(rel)
            self._registry[entity] = entity_rels

    @property
    def frozen(self) -> bool:
        """True after the first ``create_resolver()`` call."""
        return self._frozen

    def _validate_pagination(self) -> None:
        """Warn about list relationships that lack order_by (no page_loader).

        Relationships without ``order_by`` fall back to the regular (non-
        paginated) loader at runtime — downstream SDL/introspection/executor
        already treat ``page_loader is None`` per-relationship, so skipping
        is safe. We log a WARNING once at startup so the omission is visible
        without blocking app startup. Custom relationships are skipped — they
        always use the regular loader.
        """
        skipped = []
        for entity_kls, rels in self._registry.items():
            for rel in rels.values():
                if not rel.is_list:
                    continue
                if rel.page_loader is not None:
                    continue
                if rel.direction == "CUSTOM":
                    continue
                skipped.append(f"  {entity_kls.__name__}.{rel.name}")
        if skipped:
            logger.warning(
                "enable_pagination=True but the following list relationships "
                "have no order_by — they will fall back to non-paginated "
                "loaders:\n%s\nSet order_by on the SQLModel Relationship to "
                "enable pagination for these lists.",
                "\n".join(skipped),
            )

    def get_relationships(self, entity: type[SQLModel]) -> dict[str, RelationshipInfo]:
        """Get all registered relationships for an entity."""
        return self._registry.get(entity, {})

    def has_entity(self, entity: type) -> bool:
        """Return True if ``entity`` is registered in this ErManager.

        Covers both SQLModel entities (registered via ``__init__``'s
        ``base=`` / ``entities=``) and plain BaseModel virtual entities
        (registered via ``add_virtual_entities()``). Used by the Resolver's
        unified source-resolution fallback to decide whether a plain
        BaseModel root should be treated as its own source.
        """
        return entity in self._registry

    def get_all_entities(self) -> list[type[SQLModel]]:
        """Get all registered entity classes."""
        return list(self._registry.keys())

    def get_all_relationships(self) -> dict[type[SQLModel], dict[str, RelationshipInfo]]:
        """Get the complete relationship registry."""
        return dict(self._registry)

    def get_relationship(
        self, entity: type[SQLModel], name: str
    ) -> RelationshipInfo | None:
        """Get a specific relationship by entity and name."""
        rels = self._registry.get(entity, {})
        return rels.get(name)

    def get_loader(
        self,
        loader_cls: type[DataLoader],
        type_key: frozenset[str] | None = None,
    ) -> DataLoader:
        """Get or create a DataLoader instance (cached per request).

        In split mode, creates separate instances per type_key so each
        can have its own _query_meta for column pruning.
        """
        if not self._split_mode or type_key is None:
            # Default mode / no type_key: shared instance per loader_cls
            if loader_cls not in self._loader_instances:
                self._loader_instances[loader_cls] = loader_cls()
            return self._loader_instances[loader_cls]

        # Split mode: per-type_key instances
        if loader_cls not in self._loader_instances:
            self._loader_instances[loader_cls] = {}
        inner: dict[frozenset[str], DataLoader] = self._loader_instances[loader_cls]
        if type_key not in inner:
            inner[type_key] = loader_cls()
        return inner[type_key]

    def clear_cache(self) -> None:
        """Clear cached loader instances (call at start of each request)."""
        self._loader_instances.clear()

    def get_loader_by_name(
        self,
        name: str,
        type_key: frozenset[str] | None = None,
    ) -> DataLoader | None:
        """Get a DataLoader by relationship name.

        Searches all registered entities for a relationship with the given name.
        Returns the first match, or None if not found.
        Raises ValueError if multiple entities have the same relationship name.

        Used by Resolver for Core API mode Loader() parameter injection.
        Prefer get_loader_for_entity() when the source entity is known.
        """
        matches: list[tuple[type[SQLModel], RelationshipInfo]] = []
        for entity_kls, entity_rels in self._registry.items():
            rel_info = entity_rels.get(name)
            if rel_info is not None:
                matches.append((entity_kls, rel_info))

        if not matches:
            return None

        if len(matches) > 1:
            entity_names = [e.__name__ for e, _ in matches]
            raise ValueError(
                f"Ambiguous loader lookup: relationship '{name}' found on "
                f"{entity_names}. Use a DefineSubset DTO or "
                f"get_loader_for_entity() for precision."
            )

        _, rel_info = matches[0]
        return self.get_loader(rel_info.loader, type_key=type_key)

    def get_loader_for_entity(
        self,
        entity: type[SQLModel],
        rel_name: str,
        type_key: frozenset[str] | None = None,
    ) -> DataLoader | None:
        """Get a DataLoader for a specific entity's relationship.

        Returns None if the entity or relationship is not registered.
        """
        entity_rels = self._registry.get(entity)
        if entity_rels is None:
            return None
        rel_info = entity_rels.get(rel_name)
        if rel_info is None:
            return None
        return self.get_loader(rel_info.loader, type_key=type_key)

    def create_resolver(self) -> type:
        """Create a Resolver class pre-wired with this ErManager.

        Returns a Resolver **class** (not instance). Instantiate it
        per-request with an optional ``context`` dict::

            # App startup — once
            Resolver = er.create_resolver()

            # Per request
            resolver = Resolver(context={"user_id": current_user.id})
            result = await resolver.resolve(dtos)

        Each instance holds its own DataLoader cache and contextvar state,
        so concurrent requests are isolated.

        The first call to ``create_resolver()`` **freezes** the registry —
        subsequent ``add_virtual_entities()`` calls raise ``RuntimeError``.
        This keeps loader wiring and relationship registry immutable at
        runtime, so all Resolvers built from this ErManager see a
        consistent entity set.

        Returns:
            A Resolver subclass bound to this ErManager.
        """
        self._frozen = True
        from nexusx.resolver import Resolver as _Resolver

        er_manager = self

        class BoundResolver(_Resolver):
            def __init__(
                self,
                context: dict[str, Any] | None = None,
                loader_instances: dict[type[DataLoader], DataLoader] | None = None,
            ):
                super().__init__(
                    loader_registry=er_manager,
                    context=context,
                    loader_instances=loader_instances,
                )

        BoundResolver.__name__ = "Resolver"
        BoundResolver.__qualname__ = "Resolver"
        return BoundResolver


# Backward-compatible alias
LoaderRegistry = ErManager
