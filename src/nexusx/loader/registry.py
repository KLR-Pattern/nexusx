"""ErManager — inspects ORM metadata, creates DataLoaders, produces Resolvers.

Central hub for entity-relationship management. Accepts a SQLModel base class
or explicit entity list, auto-discovers relationships, and provides
``create_resolver()`` for building request-scoped Resolver instances.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from aiodataloader import DataLoader
from pydantic import BaseModel
from sqlmodel import SQLModel

from nexusx.federation.relationship import RemoteRelationship, parse_qualified_name
from nexusx.federation.transport import FederationTransport
from nexusx.loader.factories import (
    create_many_to_many_loader,
    create_many_to_one_loader,
    create_one_to_many_loader,
    create_page_many_to_many_loader,
    create_page_one_to_many_loader,
)
from nexusx.relationship import Relationship, get_custom_relationships

logger = logging.getLogger(__name__)


class RelationshipKind:
    """Discriminator for how a relationship is loaded/resolved.

    Replaces the implicit ``(target_service × coalesced × pagination ×
    page_loader × loader)`` boolean matrix with one explicit value that
    consumers match on — see D1.

    - LOCAL: a local relationship. ``loader``/``page_loader`` drive it;
      ``page_loader`` set ⇒ local pagination.
    - REMOTE_COALESCED: a relationship on a materialized remote type, resolved
      by the owning service within the parent fetch (β coalescing). Not
      BFS-traversed; the serializer reads it off the instance attribute.
    - REMOTE_PAGED: a declared RemoteRelationship with ``pagination=True``
      (``page_by_<key>_in`` via ``fetch_remote_subtree(paged=True)``).
    - REMOTE_PLAIN: a declared RemoteRelationship without pagination
      (``by_<key>_in`` via ``fetch_remote_subtree()``).
    """

    LOCAL = "local"
    REMOTE_COALESCED = "remote_coalesced"
    REMOTE_PAGED = "remote_paged"
    REMOTE_PLAIN = "remote_plain"


@dataclass
class RelationshipInfo:
    """Metadata for a single ORM relationship, including its DataLoader."""

    name: str  # relationship field name on the entity
    direction: str  # MANYTOONE | ONETOMANY | MANYTOMANY
    fk_field: str  # FK field on the *source* entity used as loader key
    target_entity: type[SQLModel]  # target entity class
    is_list: bool  # True for one-to-many / many-to-many lists
    # DataLoader class for this relationship. None for coalesced federated rels
    # (resolved within the owning service's nested fetch — see
    # fetch_remote_subtree — not loaded per-edge).
    loader: type[DataLoader] | None = None
    page_loader: type[DataLoader] | None = None  # paginated loader (list only)
    sort_field: str | None = None  # sort column for pagination
    pagination: bool = False  # explicit remote pagination capability
    # Member-owned pagination capability for a federation REMOTE_PAGED relationship
    # (profile name set + default_order) — the single source the mounter uses to
    # render the schema's `order` enum and fall back when the caller omits `order`.
    # None for local / non-paginated / coalesced relationships. specs/014.
    page_capability: Any = None
    default_page_size: int = 20
    max_page_size: int = 100
    description: str | None = None  # documentation string surfaced in voyager/ER diagram
    # Owning service prefix for a remote (federated) relationship; None for local.
    target_service: str | None = None
    # Discriminator for the relationship kind — consumers match on this instead
    # of combining target_service/pagination booleans. See RelationshipKind.
    # Defaults to LOCAL; federation construction sets the remote variants.
    kind: str = RelationshipKind.LOCAL


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


def _resolve_local_page_capability(
    target_entity: type[SQLModel],
) -> tuple[Any, Any]:
    """Build a ``BatchPageCapability`` for a local paginated relationship.

    specs/020: the order profile belongs to the SORTED object — the
    relationship's TARGET (e.g. Comment), not the owner (Review). Comment's sort
    is declared once on Comment.__pagination_orders__ and reused by every owner
    that references it, so we read target_entity.__pagination_orders__ here.
    Profiles are validated with federation's ``_resolve_page_orders`` (enum-safe
    names, single-column, SQL column, direction, nullable nulls, default∈keys) —
    fail-fast at startup.

    Returns ``(capability, resolved_orders)`` — ``capability`` is the descriptor
    (names only) used for schema rendering; ``resolved_orders`` carries the
    physical ``OrderTerm``s the page_loader needs to build ORDER BY. Both None
    when the target has no profile (falls back to sort_field). specs/015.
    """
    cfg = getattr(target_entity, "__pagination_orders__", None)
    if cfg is None:
        return None, None
    from nexusx.federation.contract import BatchPageCapability, PageOrderDescriptor
    from nexusx.standard_queries import _resolve_page_orders

    resolved = _resolve_page_orders(target_entity, cfg)
    capability = BatchPageCapability(
        default_order=cfg.default_order,
        orders=[
            PageOrderDescriptor(name=n, description=o.description)
            for n, o in resolved.items()
        ],
    )
    return capability, resolved


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
                page_capability, page_orders_resolved = _resolve_local_page_capability(
                    target_entity
                )
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
                        page_orders_resolved=page_orders_resolved,
                        default_order=(
                            page_capability.default_order
                            if page_capability is not None
                            else None
                        ),
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
                        page_capability=page_capability,
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

            page_capability, m2m_orders_resolved = _resolve_local_page_capability(
                target_entity
            )
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
                    page_orders_resolved=m2m_orders_resolved,
                    default_order=(
                        page_capability.default_order
                        if page_capability is not None
                        else None
                    ),
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
                    page_capability=page_capability,
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
        description=rel.description,
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
        service_name: str | None = None,
        expose_mounted_endpoints: bool = False,
        dto_classes: list[type[BaseModel]] | None = None,
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
        # Federation state (no-op when federation is unused).
        self.service_name: str | None = service_name
        # When True, this member advertises the endpoints of services it itself
        # has mounted in its ER-introspection payload (enables transitive
        # discovery). Defaults to False: internal URLs are suppressed (they leak
        # network topology); the mounter resolves such services from its own
        # services= map instead.
        self._expose_mounted_endpoints: bool = expose_mounted_endpoints
        # Federation-public DTOs owned by this member (γ-path composition source,
        # specs/016). Explicit list (symmetric to entities=) — avoids scanning the
        # global _subset_registry, which would leak other members' DTOs in a
        # multi-app process (demo catalog+reviews+users, or co-located tests).
        self._dto_classes: list[type[BaseModel]] = list(dto_classes) if dto_classes else []
        # specs/016 γ-path: member-side DTO batch roots (by_<join_key>_in async
        # fn, join_key) keyed by public DTO name. Populated by
        # add_dto_batch_roots at handler init; served by the /nexusx/dto-batch
        # endpoint. Empty for β-only members.
        self._dto_batch_roots: dict[str, tuple[Any, str]] = {}
        # specs/016 γ-path: mounter-side DTO RemoteLoaders keyed by owner DTO +
        # field name. The owner is required because unrelated DTOs may legally
        # use the same field name for different remote services.
        self._dto_loaders: dict[tuple[type, str], type[DataLoader]] = {}
        self._mounted_services: dict[str, str] = {}
        self._pending_remote_rels: list[tuple[type, Any]] = []
        self._fed_registry: Any = None
        self._federation_transport: FederationTransport | None = None
        # Bumped whenever the entity/relationship set changes (add_virtual_entities,
        # initialize/federation). GraphQL views keyed on it to refresh lazily.
        self._version: int = 0
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
            declared_names = set(entity_rels)
            for rel in custom_rels:
                if rel.name in declared_names:
                    raise ValueError(
                        f"Custom relationship '{rel.name}' on {entity.__name__} "
                        f"conflicts with an existing relationship name"
                    )
                declared_names.add(rel.name)
                if isinstance(rel, RemoteRelationship):
                    # Federated relationship: defer wiring to federate().
                    self._pending_remote_rels.append((entity, rel))
                else:
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
            declared_names: set[str] = set()
            for rel in custom_rels:
                if rel.name in declared_names:
                    raise ValueError(
                        f"Custom relationship '{rel.name}' on "
                        f"{entity.__name__} conflicts with another "
                        f"relationship name on the same class."
                    )
                declared_names.add(rel.name)
                if isinstance(rel, RemoteRelationship):
                    self._pending_remote_rels.append((entity, rel))
                else:
                    entity_rels[rel.name] = _build_custom_relationship_info(rel)
            self._registry[entity] = entity_rels
        self._version += 1  # entity set changed; invalidate GraphQL views

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

    def get_relationships(self, entity: type[BaseModel]) -> dict[str, RelationshipInfo]:
        """Get all registered relationships for an entity.

        Accepts any registered class — SQLModel (registered via ``__init__``)
        or plain BaseModel (registered via ``add_virtual_entities()``).
        Returns ``{}`` for unknown entities.
        """
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

    def get_all_entities(self) -> list[type[BaseModel]]:
        """Get all registered entity classes (SQLModel + plain BaseModel)."""
        return list(self._registry.keys())

    def get_all_relationships(self) -> dict[type[SQLModel], dict[str, RelationshipInfo]]:
        """Get the complete relationship registry."""
        return dict(self._registry)

    def get_dto_classes(self) -> list[type[BaseModel]]:
        """All DefineSubset DTO classes this member declared (public + private)."""
        return list(self._dto_classes)

    def get_public_dtos(self) -> list[type[BaseModel]]:
        """Federation-public DTOs owned by this member (γ-path composition source).

        specs/022: auto-discovered from ``_public_dto_registry`` keyed by the
        source entity (``__subset__.kls``) — every entity this ErManager manages
        contributes its public DTOs automatically. Manually-passed
        ``dto_classes`` are merged in (backward compat / override). No need to
        pass ``dto_classes=[ReviewDTO]`` just to make a ``federation_public=True``
        DTO discoverable — the metaclass registers it on the source entity.
        """
        from nexusx.subset import _public_dto_registry

        dtos: list[type[BaseModel]] = []
        seen: set[type] = set()
        # Auto-discover: entities this ErManager manages → their public DTOs
        for entity in self._registry.keys():
            for dto in _public_dto_registry.get(entity, []):
                if dto not in seen:
                    seen.add(dto)
                    dtos.append(dto)
        # Merge manually-passed dto_classes (backward compat / override)
        for d in self._dto_classes:
            if getattr(d, "__federation_public__", False) and d not in seen:
                seen.add(d)
                dtos.append(d)
        return dtos

    def register_dto_loader(
        self,
        owner_dto: type,
        field_name: str,
        loader_cls: type[DataLoader],
    ) -> None:
        """Register a γ-path DTO RemoteLoader for one DTO field.

        Called by federate() for each member-public-DTO reference it discovers on
        the mounter's own DefineSubset DTOs. Owner-scoped keys prevent two DTOs
        with the same field name from overwriting each other's remote loader.
        """
        self._dto_loaders[(owner_dto, field_name)] = loader_cls

    def get_dto_loader(
        self,
        owner_dto: type | str,
        field_name: str | None = None,
    ) -> type[DataLoader] | None:
        """Look up a γ DTO RemoteLoader.

        The two-argument form is the precise runtime API. The one-argument
        field-name form remains for compatibility and succeeds only when the
        name is unambiguous across all owner DTOs.
        """
        if field_name is not None:
            return self._dto_loaders.get((owner_dto, field_name))
        matches = [
            loader_cls
            for (_owner, name), loader_cls in self._dto_loaders.items()
            if name == owner_dto
        ]
        if len(matches) > 1:
            raise ValueError(
                f"Ambiguous DTO loader lookup for field {owner_dto!r}; "
                f"provide the owner DTO class."
            )
        return matches[0] if matches else None

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
        force_split: bool = False,
        params_key: tuple | None = None,
    ) -> DataLoader:
        """Get or create a DataLoader instance (cached per request).

        In split mode, creates separate instances per type_key so each
        can have its own _query_meta for column pruning.

        Args:
            force_split: If True, always creates per-type_key instances
                regardless of ``_split_mode``. Used by federation RemoteLoaders
                to isolate ``_remote_selection`` per distinct selection.
            params_key: Optional hashable key for per-params split — different
                page params (limit/order/direction) MUST get separate instances
                so aiodataloader batches don't mix slice specs (one batch holds
                one set of params). When set, forces split.
        """
        use_split = (self._split_mode or force_split) and type_key is not None
        if params_key is not None:
            use_split = True

        if not use_split:
            # Default mode / no type_key / no params: shared instance per loader_cls
            if loader_cls not in self._loader_instances:
                self._loader_instances[loader_cls] = loader_cls()
            return self._loader_instances[loader_cls]

        # Split mode: per-(type_key, params_key) instances
        cache_key: tuple = (type_key, params_key)
        if loader_cls not in self._loader_instances:
            self._loader_instances[loader_cls] = {}
        inner: dict[tuple, DataLoader] = self._loader_instances[loader_cls]
        if cache_key not in inner:
            inner[cache_key] = loader_cls()
        return inner[cache_key]

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

    async def initialize(
        self,
        *,
        transport: FederationTransport | None = None,
        extra_types: dict[str, type] | None = None,
    ) -> None:
        """Bring up the ER diagram: run federation for declared remote relationships.

        The services to mount (and their endpoints) are **derived from the
        declarations** — each ``RemoteRelationship`` or DTO ``RemoteRef`` carries
        its service url via ``RemoteService(url=…)``. No ``services`` argument.
        Services without a direct URL may still be discovered transitively;
        otherwise initialization fails before serving.

        Call once at startup (app lifespan), before serving. Bumps ``_version``
        so any GraphQL view built off this ErManager (SDL / ``__schema``)
        refreshes to include the materialized remote types.

        Args:
            transport: Injectable HTTP transport (tests pass ASGITransport/fakes).
            extra_types: Extra type names to recognize when materializing remote
                scalar fields (shared enums / custom scalars). Unregistered names
                fall back to ``Any``.
        """
        # Endpoints and targets come from both β RemoteRelationships and γ DTO
        # RemoteRef fields. A DTO-only mounter must initialize federation without
        # declaring a synthetic ER relationship.
        services_map: dict[str, str] = {}
        for _src, rrel in self._pending_remote_rels:
            target_url = getattr(rrel, "target_url", None)
            if target_url:
                srv = parse_qualified_name(rrel.qualified_name)[0]
                services_map.setdefault(srv, target_url)

        from nexusx.federation.remote_ref import _remote_ref_cardinality

        dto_targets: set[str] = set()
        for dto_cls in self._dto_classes:
            refs = getattr(dto_cls, "__nexusx_remote_field_refs__", None) or {}
            for raw_annotation in refs.values():
                ref, _is_list = _remote_ref_cardinality(raw_annotation)
                if ref is None:
                    continue
                dto_targets.add(ref.qualified_name)
                if ref.url:
                    srv = parse_qualified_name(ref.qualified_name)[0]
                    services_map.setdefault(srv, ref.url)

        if self._pending_remote_rels or dto_targets:
            from nexusx.federation.manager import federate as _federate

            await _federate(
                self,
                services_map,
                transport=transport,
                extra_types=extra_types,
                dto_targets=dto_targets,
            )
        self._version += 1

    @property
    def version(self) -> int:
        """Generation counter for the entity/relationship set.

        Bumped on ``add_virtual_entities`` and ``initialize``/federation. GraphQL
        views (SDL/introspection) read this to refresh lazily; prefer it over
        touching the private ``_version`` from outside the manager.
        """
        return self._version

    async def aclose_federation(self) -> None:
        """Close the federation transport if one was created (call on shutdown).

        Idempotent: once the transport is cleared, subsequent calls are no-ops.
        """
        if self._federation_transport is not None:
            transport = self._federation_transport
            self._federation_transport = None
            await transport.close()

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


@runtime_checkable
class LoaderRegistry(Protocol):
    """``ErManager`` / ``ComposedErManager`` 共同满足的「registry 只读契约」。

    覆盖四类消费方的读取依赖面，逐条列出以便组合体实现不漏：

    - **Resolver**（auto-load）：实体/关系查询、loader 获取、生命周期、``_split_mode``
      /``_fed_registry``
    - **ER 图**（``ErDiagram.from_er_manager``）：``get_all_entities`` /
      ``get_all_relationships`` / ``_fed_registry``
    - **federation introspection**（``serialize_er_introspection`` /
      ``serialize_dto_introspection``）：``service_name`` /
      ``_expose_mounted_endpoints`` / ``get_dto_classes`` / ``get_public_dtos``
    - **GraphQLHandler 缓存**：``version``（SDL/introspection 的 cache key）

    ``ErManager`` 天然满足（其方法/属性是本 Protocol 的超集）；``ComposedErManager``
    按实体委托 + 聚合满足。本 Protocol 原为 ``= ErManager`` 的 internal 别名，此处
    升级为正式 Protocol（无 isinstance 实例化依赖，升级不 breaking）。

    注意：本 Protocol **只含只读查询面**。federation 的 mutating 管理（``federate`` /
    ``initialize`` / ``add_virtual_entities`` / ``aclose_federation`` / 写 ``service_name``）
    按 FR-013 不在组合体上实现，仍只在 ``ErManager`` 上。
    """

    # — 实体/关系查询（按 entity 路由）—
    def has_entity(self, entity: type) -> bool: ...
    def get_relationships(self, entity: type) -> dict[str, Any]: ...
    def get_relationship(self, entity: type, name: str) -> Any | None: ...
    def get_loader_for_entity(
        self, entity: type, rel_name: str, type_key: frozenset[str] | None = None
    ) -> DataLoader | None: ...

    # — 按 name / 按 class 兜底 —
    def get_loader_by_name(
        self, name: str, type_key: frozenset[str] | None = None
    ) -> DataLoader | None: ...
    def get_loader(
        self,
        loader_cls: type[DataLoader],
        *,
        type_key: frozenset[str] | None = None,
        force_split: bool = False,
        params_key: tuple | None = None,
    ) -> DataLoader: ...

    # — federation γ（DTO loader；组合体返回中性/聚合）—
    def get_dto_loader(
        self, owner_dto: Any, field_name: str | None = None
    ) -> Any | None: ...

    # — 生命周期 / 缓存 —
    def clear_cache(self) -> None: ...
    def create_resolver(self) -> type: ...

    # — Resolver / ER 图 读取的属性 —
    @property
    def _split_mode(self) -> bool: ...
    @property
    def _fed_registry(self) -> Any: ...

    # — ER 图额外用 —
    def get_all_entities(self) -> list[type]: ...
    def get_all_relationships(self) -> dict[type, dict[str, Any]]: ...

    # — federation introspection / handler 缓存 读取面（specs/019 补全）—
    @property
    def service_name(self) -> str | None: ...
    @property
    def _expose_mounted_endpoints(self) -> bool: ...
    @property
    def version(self) -> int: ...
    def get_dto_classes(self) -> list[type]: ...
    def get_public_dtos(self) -> list[type]: ...
