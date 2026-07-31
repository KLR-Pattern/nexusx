"""federate() — mount other nexusx services into this ErManager.

Async (HTTP) — must run during application startup (e.g. FastAPI lifespan),
before the ErManager serves queries. Pulls ER fragments transitively from each
mounted service, materializes remote types, validates declarations, and wires a
``RemoteLoader`` per cross-service relationship.

Topology is relative composition: any nexusx service can mount others; no
privileged router. The orchestrator of a query is the service it enters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexusx.federation.contract import (
    BatchRoot,
    EntityFragment,
    ERIntrospectionResponse,
    FieldDescriptor,
)
from nexusx.federation.http import GraphQLTransport
from nexusx.federation.introspect import _type_expr, fetch_er_introspection, find_fragment
from nexusx.federation.registry import FederatedTypeRegistry
from nexusx.federation.relationship import (
    RemoteRelationship,
    parse_qualified_name,
)
from nexusx.federation.remote_loader import create_paginated_remote_loader, create_remote_loader
from nexusx.federation.transport import FederationTransport
from nexusx.loader.registry import RelationshipInfo

if TYPE_CHECKING:
    from nexusx.loader.registry import ErManager



class FederationError(RuntimeError):
    """Raised at federation init when a declaration is invalid (fail-fast)."""


_SUPPORTED_JOIN_TYPES = frozenset({"str", "int", "float", "bool", "UUID", "Decimal"})


async def federate(
    er_manager: ErManager,
    services: dict[str, str],
    *,
    transport: FederationTransport | None = None,
    service_name: str | None = None,
    extra_types: dict[str, type] | None = None,
) -> None:
    """Mount ``services`` (name → endpoint) into ``er_manager``.

    Internal orchestrator. The public entry is ``ErManager.initialize()``, which
    derives this mapping from the declared ``RemoteRelationship``s (each carries
    its service url via ``RemoteService``). Tests may call this directly with a
    hand-built map + fake transport.
    """
    if service_name is not None:
        er_manager.service_name = service_name
    er_manager._mounted_services.update(services)
    if transport is None:
        transport = getattr(er_manager, "_federation_transport", None)
    if transport is None:
        transport = GraphQLTransport()
    er_manager._federation_transport = transport

    # 1. Seed the fetch queue from declared remote relationships.
    targets: set[str] = set()
    declared_colors: dict[str, str] = {}
    for _src, rrel in er_manager._pending_remote_rels:
        targets.add(rrel.target)
        # Collect opt-in voyager cluster colors (RemoteService(color=...)) for
        # the target service; applied to the registry once it exists (step 3).
        target_color = getattr(rrel, "target_color", None)
        if target_color:
            declared_colors.setdefault(
                parse_qualified_name(rrel.target)[0], target_color
            )

    # 2. Transitive fetch (visited-set prevents cycles/non-termination).
    #    `endpoints` is self-extending: it starts with the user-declared mounts
    #    and grows as remote relationships reveal their target_endpoint — so
    #    mounting one service transitively reaches everything it mounted
    #    (FR-005), without the caller having to mount each transitively-reachable
    #    service explicitly.
    endpoints: dict[str, str] = dict(services)
    fragments: dict[str, EntityFragment] = {}
    service_responses: dict[str, ERIntrospectionResponse] = {}
    visited: set[str] = set()
    queue: list[str] = list(targets)
    while queue:
        qn = queue.pop()
        if qn in visited:
            continue
        visited.add(qn)
        srv, typename = parse_qualified_name(qn)
        if srv not in endpoints:
            raise FederationError(
                f"Service prefix {srv!r} (referenced by {qn!r}) has no endpoint. "
                f"Either pass it explicitly in services={{'{srv}': '<url>'}}, or enable "
                f"expose_mounted_endpoints=True on the member that advertises it so its "
                f"endpoint is discovered transitively. Known: {sorted(endpoints)}"
            )
        if srv not in service_responses:
            resp = await fetch_er_introspection(transport, endpoints[srv])
            if resp.service_name != srv:
                raise FederationError(
                    f"Service at {endpoints[srv]!r} declares name "
                    f"{resp.service_name!r}, expected {srv!r}"
                )
            service_responses[srv] = resp
        resp = service_responses[srv]
        try:
            frag = find_fragment(resp, typename)
        except KeyError as e:
            raise FederationError(str(e)) from e
        fragments[qn] = frag
        # Follow every relationship (local-to-member or remote-to-member): from
        # the mounter's view each leads to a type it must materialize. The
        # target's owning service is target_service if set, else this service.
        for rel in frag.relationships:
            owner = rel.target_service or srv
            # Transitive discovery: learn the owner's endpoint from the fragment.
            if rel.target_service and rel.target_endpoint and owner not in endpoints:
                endpoints[owner] = rel.target_endpoint
            child_qn = f"{owner}.{rel.target_typename}"
            if child_qn not in visited:
                queue.append(child_qn)

    # 3. Materialize remote types (bare __name__; qualified identity in registry).
    _check_no_cross_service_barename_dup(fragments)
    fed_registry = FederatedTypeRegistry(extra_types=extra_types)
    fed_registry.materialize(fragments)
    er_manager._fed_registry = fed_registry
    # Apply relationship-declared cluster colors (collected in step 1).
    # DefineSubset-declared colors are added by resolve_deferred_subsets below.
    fed_registry._service_colors.update(declared_colors)

    # 3b. Resolve deferred DefineSubset classes (those with RemoteRef sources).
    #     After materialization, the source classes exist — replace placeholders
    #     with real DefineSubset classes.
    from nexusx.federation.remote_ref import resolve_deferred_subsets
    resolve_deferred_subsets(fed_registry)

    # 4. Validate declared remote relationships (correctness subset; full
    #    7-check suite incl. prefix/bare-name/cycle in US3).
    _validate_declarations(er_manager, endpoints, fragments)

    # 5. Wire declared remote relationships (on local source entities).
    for source_entity, rrel in er_manager._pending_remote_rels:
        _wire_remote_relationship(
            er_manager, source_entity, rrel, endpoints, fed_registry, fragments, transport
        )
    er_manager._pending_remote_rels.clear()  # M7: prevent double-wiring on re-federate

    # 6. Register every materialized type + its (coalesced) relationships.
    #    Relationships on a remote type are resolved within the owning service's
    #    nested fetch (β) — both the executor and the Resolver skip loading them
    #    and read the result off the instance (the nested fetch via
    #    fetch_remote_subtree populates them). So register them with loader=None
    #    (no per-edge loader / no batch root required); the relationship is still
    #    registered so SDL / Voyager / traversal discovery see it.
    for cls in fed_registry.all_classes():
        qualified = fed_registry.qualified_of(cls)
        if qualified is None:
            continue
        srv, _tname = parse_qualified_name(qualified)
        frag = fragments[qualified]
        rels_map = er_manager._registry.setdefault(cls, {})
        for rel in frag.relationships:
            if rel.name in rels_map:
                continue
            owner = rel.target_service or srv
            target_qn = f"{owner}.{rel.target_typename}"
            if not fed_registry.has(target_qn):
                continue
            target_cls = fed_registry.get(target_qn)
            rels_map[rel.name] = RelationshipInfo(
                name=rel.name,
                direction=rel.direction,
                fk_field=rel.fk_field,
                target_entity=target_cls,
                is_list=rel.is_list,
                loader=None,
                target_service=owner,
                coalesced=True,
            )


def _validate_declarations(
    er_manager: ErManager,
    endpoints: dict[str, str],
    fragments: dict[str, EntityFragment],
) -> None:
    # Validate pending RemoteRelationship declarations.
    for source_entity, rrel in er_manager._pending_remote_rels:
        if rrel.sort_field and not rrel.is_list:
            raise FederationError(
                f"RemoteRelationship {rrel.name!r} declares sort_field but its "
                f"target is to-one (not list[...]); pagination only applies to "
                f"to-many relationships."
            )
        remote_field, batch_root = _check_target(
            rrel.target,
            rrel.join_remote,
            endpoints,
            fragments,
            sort_field=rrel.sort_field,
        )
        _check_join_contract(
            source_entity=source_entity,
            rrel=rrel,
            remote_field_type=remote_field.type_name,
            batch_arg_type=batch_root.arg_type,
        )


def _find_batch_root(frag: EntityFragment, join_remote: str) -> BatchRoot | None:
    """Look up the ``by_<join_remote>_in`` batch root on a fragment, if exposed."""
    entry = f"by_{join_remote}_in"
    for br in frag.batch_roots:
        if br.name == entry:
            return br
    return None


def _check_no_cross_service_barename_dup(fragments: dict[str, EntityFragment]) -> None:
    """FR-013f: two different services must not expose the same bare typename."""
    owner_of: dict[str, str] = {}
    for qn, frag in fragments.items():
        srv = parse_qualified_name(qn)[0]
        prev = owner_of.get(frag.typename)
        if prev is not None and prev != srv:
            raise FederationError(
                f"Cross-service bare-name duplicate: type {frag.typename!r} exposed "
                f"by both service {prev!r} and service {srv!r}. GraphQL forbids two "
                f"types with the same name in one schema."
            )
        owner_of.setdefault(frag.typename, srv)


def _check_target(
    target: str,
    join_remote: str,
    services: dict[str, str],
    fragments: dict[str, EntityFragment],
    sort_field: str | None = None,
) -> tuple[FieldDescriptor, BatchRoot]:
    """Validate a declared remote target; return its batch root for wiring.

    Checks (fail-fast at ``federate()``): service known, type exists, join field
    is a scalar, the ``by_<join_remote>_in`` batch root is exposed, AND its
    argument name is introspectable — so the mounter sends the argument name the
    member actually declared instead of guessing the ``<key>_list`` convention.
    """
    srv, _typename = parse_qualified_name(target)
    if srv not in services:
        raise FederationError(f"Unknown service prefix {srv!r} in target {target!r}")
    frag = fragments.get(target)
    if frag is None:
        raise FederationError(f"Service {srv!r} has no type for {target!r}")
    scalar_fields = {f.name: f for f in frag.scalar_fields}
    remote_field = scalar_fields.get(join_remote)
    if remote_field is None:
        raise FederationError(
            f"Type {target!r} has no scalar field {join_remote!r} "
            f"(needed as join key). Fields: {sorted(scalar_fields)}"
        )
    if sort_field and sort_field not in scalar_fields:
        raise FederationError(
            f"Type {target!r} has no scalar field {sort_field!r} "
            f"(needed as pagination sort_field). Fields: {sorted(scalar_fields)}"
        )
    entry = f"by_{join_remote}_in"
    br = _find_batch_root(frag, join_remote)
    if br is None:
        raise FederationError(
            f"Type {target!r} does not expose batch root {entry!r}; "
            f"member must generate it (AutoQueryConfig.batch_keys)."
        )
    if not br.arg_name:
        raise FederationError(
            f"Batch root {entry!r} on {target!r} has no determinable argument "
            f"name; the member must generate it via AutoQueryConfig.batch_keys."
        )
    return remote_field, br


def _normalize_join_type(type_expr: str) -> str | None:
    """Return the non-null scalar name from a federation type expression."""
    parts = {
        part.strip().strip("()")
        for part in type_expr.split("|")
        if part.strip().strip("()") != "None"
    }
    if len(parts) != 1:
        return None
    scalar = next(iter(parts))
    if any(token in scalar for token in "[] ,"):
        return None
    return scalar


def _batch_element_type(type_expr: str) -> str | None:
    compact = type_expr.replace(" ", "")
    if not (compact.startswith("list[") and compact.endswith("]")):
        return None
    return _normalize_join_type(compact[5:-1])


def _check_join_contract(
    *,
    source_entity: type,
    rrel: RemoteRelationship,
    remote_field_type: str,
    batch_arg_type: str,
) -> None:
    local_field = getattr(source_entity, "model_fields", {}).get(rrel.fk)
    if local_field is None:
        raise FederationError(
            f"RemoteRelationship {source_entity.__name__}.{rrel.name} uses "
            f"{rrel.fk!r} as a local join field, but that field does not exist."
        )

    local_type = _normalize_join_type(_type_expr(local_field.annotation))
    remote_type = _normalize_join_type(remote_field_type)
    for side, type_name in (("local", local_type), ("remote", remote_type)):
        if type_name not in _SUPPORTED_JOIN_TYPES:
            supported = ", ".join(sorted(_SUPPORTED_JOIN_TYPES))
            raise FederationError(
                f"Unsupported {side} federation join-key type {type_name!r} on "
                f"{source_entity.__name__}.{rrel.name}; supported types: {supported}."
            )

    if local_type != remote_type:
        raise FederationError(
            f"Local join field {source_entity.__name__}.{rrel.fk} and remote "
            f"join field {rrel.target}.{rrel.join_remote} have incompatible "
            f"types ({local_type} vs {remote_type})."
        )

    if batch_arg_type:
        batch_type = _batch_element_type(batch_arg_type)
        if batch_type != remote_type:
            raise FederationError(
                f"Batch root for {rrel.target}.{rrel.join_remote} accepts "
                f"{batch_arg_type!r}, which is incompatible with remote join "
                f"type {remote_type!r}."
            )


def _wire_remote_relationship(
    er_manager: ErManager,
    source_entity: type,
    rrel: RemoteRelationship,
    endpoints: dict[str, str],
    fed_registry: FederatedTypeRegistry,
    fragments: dict[str, EntityFragment],
    transport: FederationTransport,
) -> None:
    srv, typename = parse_qualified_name(rrel.target)
    target_cls = fed_registry.get(rrel.target)
    _remote_field, br = _check_target(
        rrel.target,
        rrel.join_remote,
        endpoints,
        fragments,
    )
    loader_cls = create_remote_loader(
        typename=typename,
        join_remote=rrel.join_remote,
        endpoint=endpoints[srv],
        target_cls=target_cls,
        transport=transport,
        is_list=rrel.is_list,
        arg_name=br.arg_name,
    )
    rel_info_kwargs: dict[str, Any] = {
        "name": rrel.name,
        "direction": "ONETOMANY" if rrel.is_list else "MANYTOONE",
        "fk_field": rrel.fk,
        "target_entity": target_cls,
        "is_list": rrel.is_list,
        "loader": loader_cls,
        "target_service": srv,
        "description": rrel.description,
    }
    # Pagination: RemoteRelationship.sort_field's presence IS the switch (mirrors
    # local Relationship.order_by). Wire a paginated RemoteLoader to page_loader
    # and carry sort_field, so the mounter executor routes to it and the loader
    # knows how to ORDER BY on the member side.
    if rrel.sort_field:
        rel_info_kwargs["page_loader"] = create_paginated_remote_loader(
            typename=typename,
            join_remote=rrel.join_remote,
            endpoint=endpoints[srv],
            target_cls=target_cls,
            transport=transport,
            arg_name=br.arg_name,
            sort_field=rrel.sort_field,
            sort_direction=rrel.sort_direction,
        )
        rel_info_kwargs["sort_field"] = rrel.sort_field
    rel_info = RelationshipInfo(**rel_info_kwargs)
    er_manager._registry.setdefault(source_entity, {})[rrel.name] = rel_info
