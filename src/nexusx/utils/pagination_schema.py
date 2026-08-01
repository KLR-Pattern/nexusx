"""Shared federation-pagination schema helpers.

SDLGenerator and IntrospectionGenerator need identical pagination judgments
(is this relationship rendered as a pagination field? does the schema have
any ``page_by_<key>_in`` root?) and identical collection of per-key package
metadata. That logic was duplicated verbatim across the two generators; this
module is the single source. Each generator keeps its own *rendering* (SDL
string vs introspection dict) but delegates the *decisions* and the
root-package *collection* here — see D3.

specs/014 adds ``federation_order_enum_layout`` so both generators also agree
on the mounter-side ``order`` enum (values = member profile names) and the
shared ``Direction`` enum a federation-paginated relationship exposes.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from enum import Enum
from typing import Any

from nexusx.loader.registry import RelationshipKind


def is_active_paginated_relationship(rel_info: Any, enable_pagination: bool) -> bool:
    """Apply the local toggle without disabling explicit federation pagination.

    True for: REMOTE_PAGED; a REMOTE_COALESCED relationship that is paginated
    on the member side; a LOCAL relationship with a page_loader when the local
    pagination toggle is on.
    """
    return (
        rel_info is not None
        and rel_info.is_list
        and (
            rel_info.kind == RelationshipKind.REMOTE_PAGED
            or (
                rel_info.kind == RelationshipKind.REMOTE_COALESCED
                and getattr(rel_info, "pagination", False)
            )
            or (
                rel_info.kind == RelationshipKind.LOCAL
                and rel_info.page_loader is not None
                and enable_pagination
            )
        )
    )


def has_any_paginated_relationship(
    loader_registry: Any, entities: Iterable, enable_pagination: bool
) -> bool:
    """True if any registered relationship is an active paginated one."""
    if not loader_registry:
        return False
    for entity in entities:
        for rel in loader_registry.get_relationships(entity).values():
            if is_active_paginated_relationship(rel, enable_pagination):
                return True
    return False


def iter_pagination_roots(entities: Iterable) -> Iterator[tuple[Any, Any]]:
    """Yield ``(entity, PaginationRootMeta)`` for every ``page_by_<key>_in`` root.

    Dedups by ``package_name`` within the call. The entity is yielded alongside
    the meta so callers can read ``entity.__name__`` for the ``items`` type.
    """
    seen: set[str] = set()
    for entity in entities:
        for attr_name in dir(entity):
            try:
                attr = getattr(entity, attr_name)
            except Exception:
                continue
            if not callable(attr):
                continue
            func = attr.__func__ if hasattr(attr, "__func__") else attr
            pag_root = getattr(func, "_pagination_root", None)
            if not pag_root:
                continue
            if pag_root.package_name in seen:
                continue
            seen.add(pag_root.package_name)
            yield entity, pag_root


def has_any_pagination_root(entities: Iterable) -> bool:
    """True if any entity exposes a federation pagination root."""
    for _ in iter_pagination_roots(entities):
        return True
    return False


def _pascal(name: str) -> str:
    """``snake_case`` → ``PascalCase`` (for synthetic enum-name disambiguation)."""
    return "".join(p[:1].upper() + p[1:] for p in name.split("_") if p)


def federation_order_enum_layout(
    loader_registry: Any, entities: Iterable
) -> tuple[dict[str, type[Enum]], dict[tuple[str, str], str]]:
    """Single source for mounter-side federation order-enum rendering. specs/014.

    For every relationship carrying a ``page_capability`` (a federation
    REMOTE_PAGED relationship wired by ``federate()``), synthesize the
    mounter-side ``order`` enum whose values are the member's exposed profile
    names, plus the shared ``Direction`` enum. Used by BOTH sdl_generator and
    introspection so SDL and ``__schema`` expose identical ``order``/``direction``
    parameters (FR-006, contracts/order-direction.md §5).

    The mounter owns the enum *type name*; the *value set* is the member's
    ``page_capability.orders`` name set (single source of truth, D7). Two
    relationships sharing a target normally share one ``{Target}Order`` enum
    (content-deduped); the rare same-target/different-orders collision is
    disambiguated by suffixing the relationship name.

    Args:
        loader_registry: the ErManager (source of relationship metadata).
        entities: the entities being rendered.

    Returns:
        ``(enums, field_name)`` — ``enums`` maps enum type name → ``Enum`` class
        (one ``{Target}Order`` per distinct order set + ``Direction`` when any
        federation-paginated relationship exists); ``field_name`` maps
        ``(entity_name, rel_name)`` → the order enum name that relationship's
        ``order:`` argument should reference.
    """
    from nexusx.standard_queries import Direction

    enums: dict[str, type[Enum]] = {}
    name_values: dict[str, tuple[str, ...]] = {}
    field_name: dict[tuple[str, str], str] = {}
    has_fed_paged = False

    if loader_registry:
        for entity in entities:
            ent_name = entity.__name__
            for rel_name, rel_info in loader_registry.get_relationships(entity).items():
                capability = getattr(rel_info, "page_capability", None)
                if capability is None:
                    continue
                has_fed_paged = True
                values = tuple(o.name for o in capability.orders)
                target_name = rel_info.target_entity.__name__
                enum_name = f"{target_name}Order"
                existing = name_values.get(enum_name)
                if existing is None:
                    name_values[enum_name] = values
                elif existing != values:
                    # Same target, different order set (two join keys) —
                    # disambiguate so both enums render under distinct names.
                    enum_name = f"{target_name}{_pascal(rel_name)}Order"
                    name_values[enum_name] = values
                if enum_name not in enums:
                    enums[enum_name] = Enum(enum_name, {v: v for v in values})
                field_name[(ent_name, rel_name)] = enum_name

    if has_fed_paged:
        enums["Direction"] = Direction
    return enums, field_name
