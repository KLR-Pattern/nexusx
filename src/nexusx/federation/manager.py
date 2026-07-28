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

from nexusx.federation.contract import EntityFragment, ERIntrospectionResponse
from nexusx.federation.http import GraphQLTransport
from nexusx.federation.introspect import fetch_er_introspection, find_fragment
from nexusx.federation.registry import FederatedTypeRegistry
from nexusx.federation.relationship import (
    RemoteEdge,
    RemoteRelationship,
    parse_edge_source,
    parse_qualified_name,
)
from nexusx.federation.remote_loader import create_remote_loader
from nexusx.loader.registry import RelationshipInfo

if TYPE_CHECKING:
    from nexusx.loader.registry import ErManager


class FederationError(RuntimeError):
    """Raised at federation init when a declaration is invalid (fail-fast)."""


async def federate(
    er_manager: ErManager,
    services: dict[str, str],
    *,
    remote_edges: list[RemoteEdge] | None = None,
    transport: GraphQLTransport | None = None,
    service_name: str | None = None,
    extra_types: dict[str, type] | None = None,
) -> None:
    """Mount ``services`` (name → endpoint) into ``er_manager``.

    Args:
        services: Mapping of mounted service name (prefix) → base URL.
        remote_edges: Cross-service edges on remote (materialized) types.
        transport: Injectable HTTP transport (tests pass ASGITransport client).
        service_name: This service's own name (prefix); set on the ErManager so
            its own ER introspection exposes it.
    """
    if service_name is not None:
        er_manager.service_name = service_name
    er_manager._mounted_services.update(services)
    transport = transport or GraphQLTransport()
    remote_edges = remote_edges or []

    # 1. Seed the fetch queue from declared remote relationships + edges.
    targets: set[str] = set()
    for _src, rrel in er_manager._pending_remote_rels:
        targets.add(rrel.target)
    for edge in remote_edges:
        ssrv, stname, _ = parse_edge_source(edge.source)
        targets.add(f"{ssrv}.{stname}")
        targets.add(edge.target)

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
                f"Unknown service prefix {srv!r} (referenced by {qn!r}); no endpoint "
                f"declared and none discovered transitively. Known: {sorted(endpoints)}"
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

    # 3b. Resolve deferred DefineSubset classes (those with RemoteRef sources).
    #     After materialization, the source classes exist — replace placeholders
    #     with real DefineSubset classes.
    from nexusx.federation.remote_ref import resolve_deferred_subsets
    resolve_deferred_subsets(fed_registry)

    # 4. Validate declared remote relationships (correctness subset; full
    #    7-check suite incl. prefix/bare-name/cycle in US3).
    _validate_declarations(er_manager, services, fragments)

    # 5. Wire declared remote relationships (on local source entities).
    for source_entity, rrel in er_manager._pending_remote_rels:
        _wire_remote_relationship(
            er_manager, source_entity, rrel, services, fed_registry, transport
        )

    # 6. Wire remote edges (on materialized source types).
    for edge in remote_edges:
        _wire_remote_edge(er_manager, edge, services, fed_registry, transport)

    # 7. Register every materialized type + its (coalesced) relationships. Each
    #    relationship on a remote type is resolved by the owning service within
    #    the parent fetch (β coalescing): the executor skips these (coalesced
    #    flag) and uses the nested-forwarded data. But the Resolver path DOES
    #    call the loader (it doesn't check coalesced) — so attach a REAL
    #    RemoteLoader, not a placeholder.
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
            target_frag = fragments.get(target_qn)
            target_pk = (target_frag.pk_field if target_frag and target_frag.pk_field else "id")
            loader_cls = create_remote_loader(
                typename=rel.target_typename,
                join_remote=target_pk,
                endpoint=endpoints[owner],
                target_cls=target_cls,
                transport=transport,
                is_list=rel.is_list,
            )
            rels_map[rel.name] = RelationshipInfo(
                name=rel.name,
                direction=rel.direction,
                fk_field=rel.fk_field,
                target_entity=target_cls,
                is_list=rel.is_list,
                loader=loader_cls,
                target_service=owner,
                coalesced=True,
            )


def _validate_declarations(
    er_manager: ErManager,
    services: dict[str, str],
    fragments: dict[str, EntityFragment],
) -> None:
    for _src, rrel in er_manager._pending_remote_rels:
        _check_target(rrel.target, rrel.join_remote, services, fragments)


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
) -> None:
    srv, _typename = parse_qualified_name(target)
    if srv not in services:
        raise FederationError(f"Unknown service prefix {srv!r} in target {target!r}")
    frag = fragments.get(target)
    if frag is None:
        raise FederationError(f"Service {srv!r} has no type for {target!r}")
    scalar_names = {f.name for f in frag.scalar_fields}
    if join_remote not in scalar_names:
        raise FederationError(
            f"Type {target!r} has no scalar field {join_remote!r} "
            f"(needed as join key). Fields: {sorted(scalar_names)}"
        )
    entry = f"by_{join_remote}_in"
    if entry not in frag.batch_roots:
        raise FederationError(
            f"Type {target!r} does not expose batch root {entry!r}; "
            f"member must generate it (AutoQueryConfig.batch_keys)."
        )


def _wire_remote_relationship(
    er_manager: ErManager,
    source_entity: type,
    rrel: RemoteRelationship,
    services: dict[str, str],
    fed_registry: FederatedTypeRegistry,
    transport: Any,
) -> None:
    srv, typename = parse_qualified_name(rrel.target)
    target_cls = fed_registry.get(rrel.target)
    loader_cls = create_remote_loader(
        typename=typename,
        join_remote=rrel.join_remote,
        endpoint=services[srv],
        target_cls=target_cls,
        transport=transport,
        is_list=rrel.is_list,
    )
    rel_info = RelationshipInfo(
        name=rrel.name,
        direction="ONETOMANY" if rrel.is_list else "MANYTOONE",
        fk_field=rrel.join_local,
        target_entity=target_cls,
        is_list=rrel.is_list,
        loader=loader_cls,
        target_service=srv,
        description=rrel.description,
    )
    er_manager._registry.setdefault(source_entity, {})[rrel.name] = rel_info


def _wire_remote_edge(
    er_manager: ErManager,
    edge: RemoteEdge,
    services: dict[str, str],
    fed_registry: FederatedTypeRegistry,
    transport: Any,
) -> None:
    ssrv, stname, field = parse_edge_source(edge.source)
    source_cls = fed_registry.get(f"{ssrv}.{stname}")
    target_cls = fed_registry.get(edge.target)
    tsrv, ttypename = parse_qualified_name(edge.target)
    loader_cls = create_remote_loader(
        typename=ttypename,
        join_remote=edge.join_remote,
        endpoint=services[tsrv],
        target_cls=target_cls,
        transport=transport,
        is_list=edge.is_list,
    )
    rel_info = RelationshipInfo(
        name=field,
        direction="ONETOMANY" if edge.is_list else "MANYTOONE",
        fk_field=edge.join_local,
        target_entity=target_cls,
        is_list=edge.is_list,
        loader=loader_cls,
        target_service=tsrv,
    )
    er_manager._registry.setdefault(source_cls, {})[field] = rel_info
