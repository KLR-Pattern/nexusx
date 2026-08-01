"""Shared federation-pagination schema helpers.

SDLGenerator and IntrospectionGenerator need identical pagination judgments
(is this relationship rendered as a pagination field? does the schema have
any ``page_by_<key>_in`` root?) and identical collection of per-key package
metadata. That logic was duplicated verbatim across the two generators; this
module is the single source. Each generator keeps its own *rendering* (SDL
string vs introspection dict) but delegates the *decisions* and the
root-package *collection* here — see D3.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
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
