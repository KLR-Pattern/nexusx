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
    DTOFragment,
    EntityFragment,
    ERIntrospectionResponse,
    FieldDescriptor,
)
from nexusx.federation.http import GraphQLTransport
from nexusx.federation.introspect import (
    _type_expr,
    fetch_dto_introspection,
    fetch_er_introspection,
    find_fragment,
)
from nexusx.federation.registry import FederatedTypeRegistry
from nexusx.federation.relationship import (
    RemoteRelationship,
    parse_qualified_name,
)
from nexusx.federation.remote_loader import (
    create_dto_remote_loader,
    create_paginated_remote_loader,
    create_remote_loader,
)
from nexusx.federation.transport import FederationTransport
from nexusx.loader.registry import RelationshipInfo, RelationshipKind

if TYPE_CHECKING:
    from nexusx.loader.registry import ErManager



class FederationError(RuntimeError):
    """Raised at federation init when a declaration is invalid (fail-fast)."""


# Decimal is deliberately excluded: member page_by buckets by the SQL column
# value, but the wire join key arrives as a JSON string, so non-string-wire
# types (Decimal) mismatch the bucket and silently resolve empty. UUID passes
# because SQLite stores UUID columns as strings too. Reject Decimal at federate()
# rather than letting it fail at query time.
_SUPPORTED_JOIN_TYPES = frozenset({"str", "int", "float", "bool", "UUID"})


async def federate(
    er_manager: ErManager,
    services: dict[str, str],
    *,
    transport: FederationTransport | None = None,
    service_name: str | None = None,
    extra_types: dict[str, type] | None = None,
    dto_targets: set[str] | None = None,
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
        targets.add(rrel.qualified_name)
        # Collect opt-in voyager cluster colors (RemoteService(color=...)) for
        # the target service; applied to the registry once it exists (step 3).
        target_color = getattr(rrel, "target_color", None)
        if target_color:
            declared_colors.setdefault(
                parse_qualified_name(rrel.qualified_name)[0], target_color
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

    # DTO-only references do not enter the ER traversal queue. After that
    # traversal has had a chance to discover transitive endpoints, every DTO
    # target still needs a concrete endpoint or federation cannot wire it.
    for qn in dto_targets or set():
        srv, _typename = parse_qualified_name(qn)
        if srv not in endpoints:
            raise FederationError(
                f"Service prefix {srv!r} (referenced by DTO {qn!r}) has no endpoint. "
                f"Declare RemoteService({srv!r}, url='<url>') or make the service "
                f"reachable through an endpoint-exposing federation mount."
            )

    # 3. Materialize remote types (bare __name__; qualified identity in registry).
    _check_no_cross_service_barename_dup(fragments)
    fed_registry = FederatedTypeRegistry(extra_types=extra_types)
    fed_registry.materialize(fragments)
    er_manager._fed_registry = fed_registry
    # Apply relationship-declared cluster colors (collected in step 1).
    # DefineSubset-declared colors are added by resolve_deferred_subsets below.
    fed_registry._service_colors.update(declared_colors)

    # 3a. γ-path (specs/016): fetch each mounted service's DTO introspection and
    #     materialize its federation-public DTOs. DTOs are NOT part of the ER
    #     graph, so they're fetched in their own pass over every reachable
    #     endpoint (the ER loop above only follows entity relationships). A
    #     service with no public DTOs returns an empty list — materialize_dtos
    #     is then a no-op, so β-only topologies are unaffected.
    dto_fragments: dict[str, DTOFragment] = {}
    required_dto_services = {
        parse_qualified_name(qn)[0] for qn in (dto_targets or set())
    }
    for srv, endpoint in endpoints.items():
        try:
            dto_resp = await fetch_dto_introspection(transport, endpoint)
        except Exception:  # noqa: BLE001 — member may predate the DTO endpoint; skip
            if srv in required_dto_services:
                raise
            continue
        if dto_resp.service_name != srv:
            raise FederationError(
                f"DTO service at {endpoint!r} declares name "
                f"{dto_resp.service_name!r}, expected {srv!r}"
            )
        for dto_frag in dto_resp.dtos:
            dto_fragments[f"{srv}.{dto_frag.name}"] = dto_frag
    if dto_fragments:
        fed_registry.materialize_dtos(dto_fragments)

    # 3b. Resolve deferred DefineSubset classes (those with RemoteRef sources).
    #     After materialization, the source classes exist — replace placeholders
    #     with real DefineSubset classes.
    from nexusx.federation.remote_ref import (
        replace_resolved_placeholders,
        resolve_deferred_subsets,
    )
    resolve_deferred_subsets(fed_registry)
    er_manager._dto_classes = replace_resolved_placeholders(
        er_manager._dto_classes,
    )

    # 3c. γ-path (specs/016): resolve deferred RemoteRef FIELD references on
    #     mounter DefineSubset DTOs whose source is local (e.g. ProductDTO.reviews:
    #     list[reviews.ReviewDTO]). Runs after materialize_dtos so the member DTO
    #     classes exist to swap in for the Any placeholder.
    from nexusx.federation.remote_ref import resolve_remote_field_refs
    resolve_remote_field_refs(fed_registry, er_manager.get_dto_classes())

    # 3d. γ-path (specs/016): wire a DTO RemoteLoader for each member-public-DTO
    #     reference discovered on the mounter's OWN DTOs. Discovery scans the
    #     __nexusx_remote_field_refs__ stamp (set by SubsetMeta); wiring registers
    #     under the owner DTO + field name in _dto_loaders, the namespace
    #     Resolver._get_loader checks first. This is independent from β
    #     RemoteRelationship wiring below (step 4) — the two never share a namespace.
    _wire_dto_remote_loaders(er_manager, fed_registry, dto_fragments, endpoints, transport)

    # 4. Validate + wire declared remote relationships in ONE pass (one
    #    _check_target per root per rrel — no re-validation between a validate
    #    step and a wire step). Fail-fast still holds: any invalid rrel raises
    #    before the ErManager is frozen, so partial wiring never reaches serving.
    for source_entity, rrel in er_manager._pending_remote_rels:
        _validate_and_wire_remote_relationship(
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
        # γ DTOs (specs/016) are not part of the ER graph — skip coalesced-
        # relationship registration for them (they have no EntityFragment).
        if qualified not in fragments:
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
                pagination=rel.pagination,
                kind=RelationshipKind.REMOTE_COALESCED,
            )


def _wire_dto_remote_loaders(
    er_manager: ErManager,
    fed_registry: FederatedTypeRegistry,
    dto_fragments: dict[str, DTOFragment],
    endpoints: dict[str, str],
    transport: FederationTransport,
) -> None:
    """Wire a γ DTO RemoteLoader per member-public-DTO reference on mounter DTOs.

    Scans the mounter's own DefineSubset DTOs (``er_manager.get_dto_classes()``)
    for deferred RemoteRef fields (``__nexusx_remote_field_refs__``). For each
    field referencing a member public DTO this fed_registry has mounted,
    materializes the target + creates a DTO RemoteLoader keyed by the member
    DTO's federation join_key, registered under the owner DTO + field name in
    ``_dto_loaders``. Resolver ``Loader("<field>")`` resolves there first (see
    Resolver._get_loader), so β entity relationships of the same name coexist.

    Fail-fast: a reference whose service is mounted but whose DTO was not
    introspected is a genuine config error (raised). A reference to a service
    this fed_registry did not mount is skipped (multi-app coexistence — same
    policy as resolve_deferred_subsets / resolve_remote_field_refs).
    """
    from nexusx.federation.remote_ref import _remote_ref_cardinality

    for dto_cls in er_manager.get_dto_classes():
        refs = getattr(dto_cls, "__nexusx_remote_field_refs__", None)
        if not refs:
            continue
        for field_name, raw_anno in refs.items():
            ref, is_list = _remote_ref_cardinality(raw_anno)
            if ref is None:
                continue
            qn = ref.qualified_name
            srv, typename = parse_qualified_name(qn)
            # Service not mounted by THIS fed_registry — leave for another
            # federate() (different ErManager).
            if srv not in endpoints:
                continue
            if not fed_registry.has(qn):
                raise FederationError(
                    f"{dto_cls.__name__}.{field_name} references {qn!r} but "
                    f"service {srv!r} exposes no such public DTO."
                )
            frag = dto_fragments.get(qn)
            if frag is None or not frag.join_key:
                raise FederationError(
                    f"{dto_cls.__name__}.{field_name} references {qn!r} which "
                    f"has no federation join_key; cannot wire a DTO RemoteLoader."
                )
            target_cls = fed_registry.get(qn)
            loader_cls = create_dto_remote_loader(
                typename=typename,
                join_key=frag.join_key,
                endpoint=endpoints[srv],
                target_cls=target_cls,
                transport=transport,
                is_list=is_list,
            )
            er_manager.register_dto_loader(dto_cls, field_name, loader_cls)


def _validate_and_wire_remote_relationship(
    er_manager: ErManager,
    source_entity: type,
    rrel: RemoteRelationship,
    endpoints: dict[str, str],
    fed_registry: FederatedTypeRegistry,
    fragments: dict[str, EntityFragment],
    transport: FederationTransport,
) -> None:
    """Validate a declared remote relationship, then wire it on the source
    entity — in one pass, calling ``_check_target`` once per root (page root
    and, when paginated, the full root) rather than re-validating at wire time.

    Fail-fast is preserved: any invalid rrel raises before the ErManager is
    frozen, so partial wiring never reaches query serving.
    """
    if rrel.pagination and not rrel.is_list:
        raise FederationError(
            f"RemoteRelationship {rrel.name!r} enables pagination but its "
            f"target is to-one (not list[...]); pagination only applies to "
            f"to-many relationships."
        )
    # One _check_target per root: page root (or the full root when not
    # paginated), plus the full root when paginated.
    remote_field, page_br = _check_target(
        rrel.qualified_name,
        rrel.join_remote,
        endpoints,
        fragments,
        pagination=rrel.pagination,
    )
    full_br = (
        _check_target(rrel.qualified_name, rrel.join_remote, endpoints, fragments)[1]
        if rrel.pagination
        else page_br
    )
    _check_join_contract(
        source_entity=source_entity,
        rrel=rrel,
        remote_field_type=remote_field.type_name,
        batch_arg_type=page_br.arg_type,
    )
    if rrel.pagination:
        _check_join_contract(
            source_entity=source_entity,
            rrel=rrel,
            remote_field_type=remote_field.type_name,
            batch_arg_type=full_br.arg_type,
        )

    srv, typename = parse_qualified_name(rrel.qualified_name)
    target_cls = fed_registry.get(rrel.qualified_name)
    loader_cls = create_remote_loader(
        typename=typename,
        join_remote=rrel.join_remote,
        endpoint=endpoints[srv],
        target_cls=target_cls,
        transport=transport,
        is_list=rrel.is_list,
        arg_name=full_br.arg_name,
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
        "pagination": rrel.pagination,
        "kind": (
            RelationshipKind.REMOTE_PAGED
            if rrel.pagination
            else RelationshipKind.REMOTE_PLAIN
        ),
    }
    if rrel.pagination:
        # Store the member's page capability so SDL/__schema can render the
        # `order` enum + default, and bake only the default order into the
        # loader (the chosen order/direction arrive per-query). specs/014.
        capability = _validate_page_capability(rrel.qualified_name, page_br)
        rel_info_kwargs["page_capability"] = capability
        rel_info_kwargs["page_loader"] = create_paginated_remote_loader(
            typename=typename,
            join_remote=rrel.join_remote,
            endpoint=endpoints[srv],
            target_cls=target_cls,
            transport=transport,
            arg_name=page_br.arg_name,
            default_order=capability.default_order,
        )
    rel_info = RelationshipInfo(**rel_info_kwargs)
    er_manager._registry.setdefault(source_entity, {})[rrel.name] = rel_info


def _find_batch_root(
    frag: EntityFragment,
    join_remote: str,
    *,
    pagination: bool = False,
) -> BatchRoot | None:
    """Look up the required full or paginated batch root."""
    entry = (
        f"page_by_{join_remote}_in"
        if pagination
        else f"by_{join_remote}_in"
    )
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
    pagination: bool = False,
) -> tuple[FieldDescriptor, BatchRoot]:
    """Validate a declared remote target; return its batch root for wiring.

    Checks service/type/join field, the required full or paginated root, its
    argument contract, and pagination capability when applicable. The caller
    chooses the order profile at query time, so no order is pinned here
    (specs/014); this only verifies the member advertised a non-empty,
    self-consistent capability.
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
    entry = (
        f"page_by_{join_remote}_in"
        if pagination
        else f"by_{join_remote}_in"
    )
    br = _find_batch_root(frag, join_remote, pagination=pagination)
    if br is None:
        raise FederationError(
            f"Type {target!r} does not expose batch root {entry!r}; "
            f"member must declare it on the entity via __federation_keys__ "
            f"(specs/020)."
        )
    if not br.arg_name:
        raise FederationError(
            f"Batch root {entry!r} on {target!r} has no determinable argument "
            f"name; the member must declare the join field in "
            f"__federation_keys__ (specs/020)."
        )
    if pagination:
        _validate_page_capability(target, br)
    return remote_field, br


def _validate_page_capability(
    target: str,
    batch_root: BatchRoot,
) -> Any:
    """Validate the member's page capability; return it for the mounter to store.

    The order profile is chosen by the caller at query time, so this no longer
    pins a specific order. It still fail-fast checks the capability is present,
    uses the supported protocol, and advertises a non-empty order set whose
    ``default_order`` is one of its members (the mounter needs a default to fall
    back on and an enum to render). specs/014.
    """
    capability = batch_root.page
    if capability is None:
        raise FederationError(
            f"Pagination root {batch_root.name!r} on {target!r} does not "
            "advertise a page capability."
        )
    if capability.protocol != "offset-v1":
        raise FederationError(
            f"Pagination root {batch_root.name!r} on {target!r} uses "
            f"unsupported protocol {capability.protocol!r}."
        )
    order_names = {item.name for item in capability.orders}
    if not order_names:
        raise FederationError(
            f"Pagination root {batch_root.name!r} on {target!r} exposes no "
            "order profiles."
        )
    if capability.default_order not in order_names:
        raise FederationError(
            f"Pagination root {batch_root.name!r} on {target!r} has unknown "
            f"default_order {capability.default_order!r}."
        )
    return capability


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
            f"join field {rrel.qualified_name}.{rrel.join_remote} have incompatible "
            f"types ({local_type} vs {remote_type})."
        )

    if batch_arg_type:
        batch_type = _batch_element_type(batch_arg_type)
        if batch_type != remote_type:
            raise FederationError(
                f"Batch root for {rrel.qualified_name}.{rrel.join_remote} accepts "
                f"{batch_arg_type!r}, which is incompatible with remote join "
                f"type {remote_type!r}."
            )
