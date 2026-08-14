"""ComposedErManager — same-process multi-engine composition (specs/019).

ComposedErManager is a "delegate-by-entity query proxy + cross-boundary
relationship overlay":

- Several self-contained child ErManagers (one engine each, loaders
  hard-wired to their own session) compose into a single umbrella proxy.
- Satisfies the ``LoaderRegistry`` protocol; ``create_resolver()`` produces
  a single umbrella Resolver, making cross-engine resolve transparent to
  users.
- Cross-boundary relationships are declared centrally at the composed level
  (members stay unaware of cross-boundary associations and remain pure when
  used standalone, DD-02).

Essentially "federation in the same process" — the dual of specs/012
(cross-process federation):

- 012: cross-process service composition; cross-boundary relationships go
  through a transport (HTTP).
- 019: same-process engine composition; cross-boundary relationships go
  through in-process DataLoaders (user closures).

Federation is orthogonal and stackable (FR-017): federation's mutating
operations (federate/initialize) land on ErManager; ComposedErManager only
delegates queries and aggregates ``_fed_registry``.

Immutable (FR-016): members + cross-boundary relationships are fixed once
in ``__init__``.
ErManager's management interface is intentionally NOT implemented (FR-013):
add_virtual_entities / federate / initialize etc. run on child ErManagers;
calling them on the composed manager raises an explicit error.
"""

# No ``from __future__ import annotations`` — keep method signature
# annotations (ErManager | None etc.) evaluable at runtime, consistent with
# registry.py.

from typing import Any

from aiodataloader import DataLoader

from nexusx.loader.registry import (
    ErManager,
    RelationshipInfo,
    _build_custom_relationship_info,
)
from nexusx.relationship import Relationship


class _CompositeFedRegistryView:
    """Read-only aggregation of member ``_fed_registry`` objects (federation
    stacking, US5 / FR-017).

    After each child member federates on its own, its materialized remote
    types live in its own ``_fed_registry``. This view iterates members and
    merges them so ER-diagram styling / remote-type detection stays correct.
    Without federation, member ``_fed_registry`` objects are None and this
    view's methods return empty sets / None.
    """

    def __init__(self, members: list[ErManager]):
        self._members = members

    def _frs(self):
        for m in self._members:
            fr = getattr(m, "_fed_registry", None)
            if fr is not None:
                yield fr

    def qualified_of(self, cls):
        for fr in self._frs():
            qn = fr.qualified_of(cls)
            if qn:
                return qn
        return None

    def all_classes(self):
        classes: set = set()
        for fr in self._frs():
            classes.update(fr.all_classes())
        return classes

    def service_colors(self):
        colors: dict = {}
        for fr in self._frs():
            colors.update(fr.service_colors())
        return colors

    def has(self, qn):
        return any(fr.has(qn) for fr in self._frs())

    def get(self, qn):
        for fr in self._frs():
            cls = fr.get(qn)
            if cls:
                return cls
        return None


class ComposedErManager:
    """Umbrella proxy composing several self-contained ErManagers + the
    cross-boundary relationship overlay.

    Satisfies the :class:`LoaderRegistry` protocol. ``create_resolver()``
    produces a single umbrella Resolver; cross-engine resolve is transparent
    to users.

    Args:
        members: Self-contained child ErManagers (one engine each, loaders
            hard-wired to their own session). Non-empty and immutable after
            construction (FR-016). Member entity sets must be mutually
            exclusive (duplicates raise).
        cross_relationships: Cross-engine boundary relationships, shaped like
            ``[(source_entity, Relationship), ...]``. Declared centrally at
            the composed level (DD-02/FR-008); members stay unaware of
            cross-boundary associations. Relationship.loader is a user
            closure that picks the target engine's session internally.
        service_name: Unified service name for the composed manager when it
            is itself consumed as a federation member (optional; not needed
            for standalone use).

    ErManager's management interface is intentionally NOT implemented
    (FR-013): ``add_virtual_entities`` / ``federate`` / ``initialize`` etc.
    run on child ErManagers; calling them on the composed manager raises
    ``AttributeError``.
    """

    def __init__(
        self,
        members: list[ErManager],
        *,
        cross_relationships: list[tuple[type, Relationship]] | None = None,
        service_name: str | None = None,
    ):
        if not members:
            raise ValueError(
                "ComposedErManager requires at least one member ErManager"
            )

        self._members: list[ErManager] = list(members)
        self._service_name: str | None = service_name

        # entity → owning member (delegation route table)
        self._route: dict[type, ErManager] = {}
        # loader_cls → member (reverse route; avoids get_loader cache pollution)
        self._loader_owner: dict[type, ErManager] = {}
        # Cross-boundary relationship overlay: source entity → {rel_name: RelationshipInfo}
        self._cross_rels: dict[type, dict[str, RelationshipInfo]] = {}
        # Cross-boundary loader instance cache (composed-owned, cleared by clear_cache)
        self._cross_loader_cache: dict[type, DataLoader] = {}
        # _fed_registry aggregate view (created lazily)
        self._fed_registry_view: _CompositeFedRegistryView | None = None
        # Member grouping map (specs/022, created lazily): cls → (service_name, color)
        self._member_styling_cache: dict[type, tuple[str, str | None]] | None = None

        # Build the route table + loader reverse map + entity exclusivity check
        for m in self._members:
            for cls in m.get_all_entities():
                if cls in self._route:
                    raise ValueError(
                        f"Entity {cls!r} is registered by multiple members "
                        f"({self._route[cls]!r} and {m!r}); "
                        f"ComposedErManager requires mutually exclusive entity sets"
                    )
                self._route[cls] = m
            for _entity, rels in m.get_all_relationships().items():
                for rel_info in rels.values():
                    # Register BOTH loader and page_loader: the pagination
                    # path fetches instances via page_loader (a separate
                    # class — registering only loader would KeyError on
                    # paged queries).
                    for _lk in (rel_info.loader, rel_info.page_loader):
                        if _lk is not None:
                            self._loader_owner[_lk] = m

        # Duplicate member service_name check (specs/022 FR-009): a
        # duplicated grouping key would merge two members' entities into one
        # voyager cluster, let their colors overwrite each other
        # first-come-first-served, and crash on the duplicate DOT cluster id
        # — fail fast at construction, alongside the entity exclusivity
        # check.
        named_members: dict[str, ErManager] = {}
        for m in self._members:
            m_name = getattr(m, "service_name", None)
            if m_name is None:
                continue
            if m_name in named_members:
                raise ValueError(
                    f"Member service_name '{m_name}' is used by multiple members; "
                    f"service_name must be unique within a ComposedErManager "
                    f"(it is the voyager cluster key)"
                )
            named_members[m_name] = m

        # Cross-boundary relationships → RelationshipInfo
        # (reuses _build_custom_relationship_info)
        for source_entity, rel in cross_relationships or []:
            if source_entity not in self._route:
                raise ValueError(
                    f"Cross-boundary relationship source {source_entity!r} "
                    f"is not registered in any member"
                )
            if rel.target_entity not in self._route:
                raise ValueError(
                    f"Cross-boundary relationship {source_entity.__name__}.{rel.name} "
                    f"target {rel.target_entity!r} is not registered in any member"
                )
            rel_info = _build_custom_relationship_info(rel)
            bucket = self._cross_rels.setdefault(source_entity, {})
            if rel.name in bucket:
                raise ValueError(
                    f"Cross-boundary relationship {source_entity.__name__}.{rel.name} "
                    f"is declared more than once"
                )
            # A cross relationship shadowing a member-local one raises
            # (fail fast at construction; otherwise get_relationships would
            # silently replace the local ORM relationship with the cross one)
            local_owner = self._route[source_entity]
            if rel.name in local_owner.get_relationships(source_entity):
                raise ValueError(
                    f"Cross-boundary relationship {source_entity.__name__}.{rel.name} "
                    f"shadows a member-local relationship of the same name; "
                    f"use a different name"
                )
            bucket[rel.name] = rel_info

    # ── Internal helpers ───────────────────────────────────────

    def _member_for(self, entity: type) -> ErManager | None:
        return self._route.get(entity)

    def _get_cross_loader(self, loader_cls: type[DataLoader]) -> DataLoader:
        """Cross-boundary loader instances are cached by the composed manager
        (not via member.get_loader)."""
        if loader_cls not in self._cross_loader_cache:
            self._cross_loader_cache[loader_cls] = loader_cls()
        return self._cross_loader_cache[loader_cls]

    def _cross_loader_classes(self) -> set[type]:
        cls_set: set[type] = set()
        for rels in self._cross_rels.values():
            for rel_info in rels.values():
                if rel_info.loader is not None:
                    cls_set.add(rel_info.loader)
        return cls_set

    # ── Query interface consumed by the Resolver (route by entity + cross-boundary overlay) ──

    def has_entity(self, entity: type) -> bool:
        return entity in self._route

    def get_relationships(self, entity: type) -> dict[str, RelationshipInfo]:
        """Delegate to the member's local relationships + overlay the
        cross-boundary ones."""
        member = self._member_for(entity)
        local = dict(member.get_relationships(entity)) if member else {}
        cross = self._cross_rels.get(entity, {})
        if cross:
            # Merge cross-boundary rels (construction guarantees no clash
            # with local names).
            local.update(cross)
        return local

    def get_relationship(
        self, entity: type, name: str
    ) -> RelationshipInfo | None:
        return self.get_relationships(entity).get(name)

    def get_loader_for_entity(
        self,
        entity: type,
        rel_name: str,
        type_key: frozenset[str] | None = None,
    ) -> DataLoader | None:
        """Cross-boundary relationships → composed-owned loader; local →
        delegate to the member."""
        cross = self._cross_rels.get(entity, {}).get(rel_name)
        if cross is not None and cross.loader is not None:
            return self._get_cross_loader(cross.loader)
        member = self._member_for(entity)
        if member is None:
            return None
        return member.get_loader_for_entity(entity, rel_name, type_key)

    def get_loader_by_name(
        self, name: str, type_key: frozenset[str] | None = None
    ) -> DataLoader | None:
        """Look up a loader by relationship name.

        Same-name relationships across members raise on ambiguity — aligned
        with ``ErManager.get_loader_by_name``, which raises ``ValueError``
        on same-name collisions within a single manager. With a silent
        "first wins", a same-name cross-engine relationship (e.g.
        owner/tags) would fetch data through engine A's session for a
        relationship that belongs to engine B — results that look right but
        are wrong. Cross-boundary overlay names participate in the
        ambiguity check too.
        """
        member_hits: list[ErManager] = []
        for m in self._members:
            if any(name in rels for rels in m.get_all_relationships().values()):
                member_hits.append(m)
        cross_hit = any(name in rels for rels in self._cross_rels.values())

        total = len(member_hits) + (1 if cross_hit else 0)
        if total == 0:
            return None
        if total > 1:
            raise ValueError(
                f"Ambiguous loader lookup: relationship '{name}' resolved to "
                f"{len(member_hits)} member(s)"
                f"{' plus the cross-boundary layer' if cross_hit else ''} in "
                f"ComposedErManager. Use get_loader_for_entity() for precision."
            )

        if member_hits:
            # Exactly one member hit: delegate (if several entities inside
            # the member share the name, its own error still fires)
            return member_hits[0].get_loader_by_name(name, type_key)
        # Only the cross-boundary layer hit: take its loader class; the
        # composed manager owns the instance
        for rels in self._cross_rels.values():
            rel_info = rels.get(name)
            if rel_info is not None and rel_info.loader is not None:
                return self._get_cross_loader(rel_info.loader)
        return None

    def get_loader(
        self,
        loader_cls: type[DataLoader],
        *,
        type_key: frozenset[str] | None = None,
        force_split: bool = False,
        params_key: tuple | None = None,
    ) -> DataLoader:
        """Reverse-route member loaders; cross-boundary loaders are
        composed-owned.

        Local loaders go through ``_loader_owner`` (collected at
        construction); **loaders a member adds AFTER federate (e.g.
        RemoteLoader) fall back to dynamic lookup** — they do not exist yet
        when the composed manager is constructed (federation materializes
        after the child member's ``initialize()``), so construction-time
        collection cannot see them. Dynamic lookup walks
        ``member.get_all_relationships()`` (which includes materialized
        relationships) to locate the owner. Cross-boundary loaders are
        composed-owned.
        """
        owner = self._loader_owner.get(loader_cls)
        if owner is None:
            # Loader added by a member after federate — dynamically find
            # the member that owns it
            for m in self._members:
                for _entity, rels in m.get_all_relationships().items():
                    for rel_info in rels.values():
                        if loader_cls in (rel_info.loader, rel_info.page_loader):
                            owner = m
                            break
                    if owner is not None:
                        break
                if owner is not None:
                    break
        if owner is not None:
            return owner.get_loader(
                loader_cls,
                type_key=type_key,
                force_split=force_split,
                params_key=params_key,
            )
        if loader_cls in self._cross_loader_classes():
            return self._get_cross_loader(loader_cls)
        raise KeyError(
            f"loader_cls {loader_cls!r} belongs to no member ErManager "
            f"or cross-boundary relationship"
        )

    def get_dto_loader(
        self, owner_dto: Any, field_name: str | None = None
    ) -> Any | None:
        """Aggregate γ DTO loaders: search across members."""
        for m in self._members:
            loader = m.get_dto_loader(owner_dto, field_name)
            if loader is not None:
                return loader
        return None

    # ── Lifecycle / cache ──────────────────────────────────────

    def clear_cache(self) -> None:
        """Aggregate all members' clear_cache + clear the cross-boundary
        loader cache."""
        for m in self._members:
            m.clear_cache()
        self._cross_loader_cache.clear()

    def create_resolver(self) -> type:
        """Produce the umbrella Resolver (mirrors ErManager.create_resolver,
        injecting the composed manager itself).

        The Resolver itself is unchanged — its ``__init__`` already takes
        ``loader_registry: Any``, so injecting the composed manager as the
        loader_registry makes cross-engine resolve transparent.
        """
        from nexusx.resolver import Resolver as _Resolver

        composed = self

        class BoundResolver(_Resolver):
            def __init__(
                self,
                context: dict[str, Any] | None = None,
                loader_instances: dict[type, DataLoader] | None = None,
            ):
                super().__init__(
                    loader_registry=composed,
                    context=context,
                    loader_instances=loader_instances,
                )

        BoundResolver.__name__ = "Resolver"
        BoundResolver.__qualname__ = "Resolver"
        return BoundResolver

    # ── Attributes read by the Resolver / ER diagram ───────────

    @property
    def _split_mode(self) -> bool:
        # The composed manager does not support split mode (each member
        # decides on its own; the composed level reports False uniformly).
        # Existing split_mode uses (query_meta column pruning) apply inside
        # each member.
        return False

    @property
    def _fed_registry(self) -> Any:
        """Read-only aggregate view of members' _fed_registry (federation
        stacking, US5)."""
        if self._fed_registry_view is None:
            self._fed_registry_view = _CompositeFedRegistryView(self._members)
        return self._fed_registry_view

    @property
    def _member_styling(self) -> dict[type, tuple[str, str | None]]:
        """Member grouping map (specs/022) — probed by the voyager consumers.

        Keys are member entity classes or DTO classes from ``dto_classes``;
        values are the owning member's ``(service_name, color)``. Contains
        ONLY members that declared a ``service_name``: an unnamed member's
        entities fall back to Python ``__module__`` grouping (the
        pre-existing behavior), and its color (if any) is silently ignored
        — color takes effect only through service_name.

        Consumer convention (duck-typed probe in the same style as
        ``_fed_registry``)::

            styling = getattr(er_manager, "_member_styling", None)

        A standalone ErManager has no such attribute → None → consumers
        fall back to the status quo (single-manager output stays
        byte-identical). Immutable (same discipline as FR-016): members are
        fixed after construction; the map is built lazily and cached once.
        """
        if self._member_styling_cache is None:
            cache: dict[type, tuple[str, str | None]] = {}
            for m in self._members:
                m_name = getattr(m, "service_name", None)
                if m_name is None:
                    continue
                m_color = getattr(m, "_voyager_color", None)
                for cls in m.get_all_entities():
                    cache[cls] = (m_name, m_color)
                for dto in getattr(m, "_dto_classes", []):
                    cache[dto] = (m_name, m_color)
            self._member_styling_cache = cache
        return self._member_styling_cache

    # ── Extra surface for the ER diagram ───────────────────────

    def get_all_entities(self) -> list[type]:
        return list(self._route.keys())

    def get_all_relationships(self) -> dict[type, dict[str, RelationshipInfo]]:
        merged: dict[type, dict[str, RelationshipInfo]] = {}
        for m in self._members:
            for entity, rels in m.get_all_relationships().items():
                merged.setdefault(entity, {}).update(rels)
        # Overlay cross-boundary relationships
        for entity, rels in self._cross_rels.items():
            merged.setdefault(entity, {}).update(rels)
        return merged

    # ── Federation-member exposure aggregates (when consumed AS a member, US5-A2) ──

    @property
    def service_name(self) -> str | None:
        return self._service_name

    def get_dto_classes(self) -> list[type]:
        """Aggregate all members' DTO classes (for federation member
        introspection)."""
        classes: list[type] = []
        for m in self._members:
            classes.extend(m.get_dto_classes())
        return classes

    def get_public_dtos(self) -> list[type]:
        """Aggregate all members' federation-public DTOs (γ-path
        composition source)."""
        dtos: list[type] = []
        for m in self._members:
            dtos.extend(m.get_public_dtos())
        return dtos

    @property
    def _expose_mounted_endpoints(self) -> bool:
        """Members' expose policy (expose if ANY member is True, enabling
        transitive discovery)."""
        return any(
            getattr(m, "_expose_mounted_endpoints", False) for m in self._members
        )

    # ── Version (ER diagram / SDL cache key; aggregates member versions) ──

    @property
    def version(self) -> int:
        # Member versions grow monotonically (initialize /
        # add_virtual_entities each +1). max() would NOT do: when one member
        # already dominates with a high version, a lower-versioned member
        # federating (version+1) does not change the max, so
        # GraphQLHandler's SDL / introspection cache (keyed by version)
        # would not refresh and the schema would miss newly materialized
        # remote types (review #4). sum() is strictly monotonic under the
        # "only grows" discipline — any member entering a new generation
        # changes the aggregate — and stays an int, preserving consumers
        # that use version as a cache key / counter.
        return sum(getattr(m, "version", 0) for m in self._members)
