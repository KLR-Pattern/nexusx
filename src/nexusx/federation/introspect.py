"""ER introspection — member-side serialization + mounter-side client.

The composition data source is ER graph info (entities + RelationshipInfo),
NOT GraphQL SDL. Same source as Voyager/executor. Member exposes it at
``GET /nexusx/er-introspection``; the mounter fetches it (transitively, via the
``target_service``/``target_endpoint`` carried on remote relationships).

Also provides ``build_federable_app(handler)`` — a FastAPI app mounting the two
routes a federable member must expose (``POST /graphql`` wrapping
``handler.execute``, ``GET /nexusx/er-introspection``). Used by members and by
tests (with httpx ASGITransport).
"""

from __future__ import annotations

import inspect
import types
import typing
import warnings
from collections.abc import Sequence
from contextlib import asynccontextmanager
from typing import Any, Union

from nexusx.federation.contract import (
    BatchRoot,
    DTOFragment,
    DTOIntrospectionResponse,
    EntityFragment,
    ERIntrospectionResponse,
    FieldDescriptor,
    RelDescriptor,
)
from nexusx.federation.transport import FederationTransport


def _type_expr(anno: Any) -> str:
    """Render a Python annotation as a LOSSLESS type-expression string.

    The mounter reconstructs the precise type from this string via
    ``create_model`` + ``model_rebuild`` against a shared type namespace, so
    ``list[str]`` / ``Optional[int]`` / ``UUID`` / enums round-trip exactly
    (instead of degrading to a bare name that loses generics). Unions render as
    ``A | B``; parameterized generics as ``list[X]`` / ``dict[K, V]``.
    """
    origin = typing.get_origin(anno)
    args = typing.get_args(anno)
    # Union / Optional (PEP 604 X | Y, incl. X | None)
    if origin in (Union, types.UnionType):
        return " | ".join(_type_expr(a) for a in args)
    # Parameterized generics: list[str], dict[K, V], set[X], tuple[...], ...
    if origin is not None:
        name = getattr(origin, "__name__", None) or str(origin)
        if args:
            return f"{name}[{', '.join(_type_expr(a) for a in args)}]"
        return name
    # NoneType
    if anno is type(None):
        return "None"
    # Bare type (int, str, UUID, enum class, custom scalar)
    if isinstance(anno, type):
        return anno.__name__
    return getattr(anno, "__name__", str(anno))


def _pk_field(entity: type) -> str | None:
    """Extract the primary key field name from a SQLModel entity."""
    from sqlalchemy import inspect as sa_inspect
    try:
        mapper = sa_inspect(entity)
        if mapper.primary_key:
            return mapper.primary_key[0].name
    except Exception:
        pass
    return None


def _batch_root_arg(method: Any) -> tuple[str, str]:
    """Extract ``(arg_name, arg_type_expr)`` from a ``by_<key>_in`` method.

    Tries the (possibly bound classmethod) attribute first, then its underlying
    ``__func__`` — the generated root sets an explicit ``__signature__`` there.
    Returns ``("", "")`` if no argument can be determined (the mounter rejects
    such roots at validation).
    """
    for target in (method, getattr(method, "__func__", None)):
        if target is None:
            continue
        try:
            sig = inspect.signature(target)
        except (TypeError, ValueError):
            continue
        for pname, param in sig.parameters.items():
            if pname in ("cls", "self"):
                continue
            ann = param.annotation
            arg_type = _type_expr(ann) if ann is not inspect.Parameter.empty else ""
            return pname, arg_type
        # Signature had only cls/self or was empty → try the next target.
    return "", ""


def _batch_roots(entity: type) -> list[BatchRoot]:
    """Generated batch roots on ``entity`` with their arg contract.

    Pagination roots carry their semantic capability in ``_pagination_root``
    metadata; full roots continue to follow ``by_<key>_in``.
    """
    roots: list[BatchRoot] = []
    for attr_name in dir(entity):
        if not (
            (attr_name.startswith("by_") and attr_name.endswith("_in"))
            or (
                attr_name.startswith("page_by_")
                and attr_name.endswith("_in")
            )
        ):
            continue
        attr = getattr(entity, attr_name, None)
        if not callable(attr):
            continue
        func = attr.__func__ if hasattr(attr, "__func__") else attr
        pagination_root = getattr(func, "_pagination_root", None)
        arg_name, arg_type = _batch_root_arg(attr)
        roots.append(
            BatchRoot(
                name=attr_name,
                arg_name=arg_name,
                arg_type=arg_type,
                page=(
                    pagination_root.page_capability
                    if pagination_root
                    else None
                ),
            )
        )
    return sorted(roots, key=lambda r: r.name)


def serialize_er_introspection(er_manager: Any) -> ERIntrospectionResponse:
    """Serialize an ErManager's full ER graph into the federation wire payload.

    loader callables are NOT serialized (code, not data). Remote relationships
    carry ``target_service`` so the mounter knows a type lives on another
    service. They carry ``target_endpoint`` (the URL) ONLY when the member has
    ``expose_mounted_endpoints=True`` — otherwise the URL is suppressed (it
    leaks internal topology) and the mounter must resolve the service from its
    own ``services=`` map.
    """
    service_name = getattr(er_manager, "service_name", None)
    if not service_name:
        msg = (
            "ErManager.service_name is not set; a federable member must declare "
            "its service name (prefix). Pass service_name= to GraphQLHandler/"
            "ErManager."
        )
        raise ValueError(msg)
    mounted: dict[str, str] = getattr(er_manager, "_mounted_services", {}) or {}
    # When False (default), the member does NOT advertise the endpoints of
    # services it itself has mounted — only their names. Internal URLs are
    # strictly more sensitive than type names (they reveal network topology
    # usable for lateral movement), so they are suppressed unless the operator
    # opts in. The mounter then resolves such services from its own `services=`
    # map, or fails fast with an actionable error.
    expose = getattr(er_manager, "_expose_mounted_endpoints", False)

    entities: list[EntityFragment] = []
    for entity in er_manager.get_all_entities():
        rels: list[RelDescriptor] = []
        rel_map = er_manager.get_relationships(entity)
        # Relationship field names to exclude from scalar_fields.
        rel_names = set(rel_map.keys())
        for r_info in rel_map.values():
            target_service = getattr(r_info, "target_service", None)
            rels.append(
                RelDescriptor(
                    name=r_info.name,
                    direction=r_info.direction,
                    fk_field=r_info.fk_field,
                    target_typename=r_info.target_entity.__name__,
                    is_list=r_info.is_list,
                    pagination=r_info.is_list
                    and (
                        # federation 远程分页(RemoteRelationship pagination=True)
                        getattr(r_info, "pagination", False)
                        and target_service is not None
                    )
                    # member 本地分页(enable_pagination: 本地关系, page_loader set;
                    # 它的 RelationshipInfo.pagination=False 且 target_service=None,
                    # 不透传则 catalog 物化层看不到这是个分页关系 → 物化成扁平 list)
                    or (
                        r_info.is_list
                        and target_service is None
                        and getattr(r_info, "page_loader", None) is not None
                    ),
                    target_service=target_service,
                    target_endpoint=(
                        mounted.get(target_service) if (target_service and expose) else None
                    ),
                )
            )

        scalar_fields: list[FieldDescriptor] = []
        model_fields = getattr(entity, "model_fields", {})
        for fname, finfo in model_fields.items():
            if fname in rel_names:
                continue
            scalar_fields.append(
                FieldDescriptor(name=fname, type_name=_type_expr(finfo.annotation))
            )

        entities.append(
            EntityFragment(
                typename=entity.__name__,
                pk_field=_pk_field(entity),
                scalar_fields=scalar_fields,
                relationships=rels,
                batch_roots=_batch_roots(entity),
            )
        )

    return ERIntrospectionResponse(service_name=service_name, entities=entities)


def find_fragment(resp: ERIntrospectionResponse, typename: str) -> EntityFragment:
    """Look up a single entity fragment by bare typename."""
    for frag in resp.entities:
        if frag.typename == typename:
            return frag
    msg = f"Service {resp.service_name!r} has no type {typename!r}"
    raise KeyError(msg)


async def fetch_er_introspection(
    transport: FederationTransport, base_url: str
) -> ERIntrospectionResponse:
    """Mounter-side: GET ``<base_url>/nexusx/er-introspection`` and parse."""
    url = base_url.rstrip("/") + "/nexusx/er-introspection"
    raw = await transport.get_json(url)
    return ERIntrospectionResponse.model_validate(raw)


# ──────────────────────────────────────────────────────────────────────
# specs/016 — DTO introspection (γ-path, independent from β ER introspection)
# ──────────────────────────────────────────────────────────────────────


def _dto_remote_refs(dto: type) -> list[RelDescriptor]:
    """Cross-service out-edges declared on a public DTO (``__relationships__``).

    The member Resolver fully resolves these before the DTO tree leaves the
    service, so the mounter never fetches them itself — they're informational
    (SDL/Voyager/contract completeness), not a load instruction. Empty for DTOs
    whose cross-service data is baked into scalar ``resolve_*`` fields.
    """
    from nexusx.federation.relationship import RemoteRelationship
    from nexusx.relationship import get_custom_relationships

    refs: list[RelDescriptor] = []
    for rel in get_custom_relationships(dto):
        if isinstance(rel, RemoteRelationship):
            refs.append(
                RelDescriptor(
                    name=rel.name,
                    direction="ONETOMANY" if rel.is_list else "MANYTOONE",
                    fk_field=rel.fk,
                    target_typename=rel.qualified_name.split(".", 1)[1],
                    is_list=rel.is_list,
                    target_service=rel.qualified_name.split(".", 1)[0],
                )
            )
    return refs


def serialize_dto_introspection(er_manager: Any) -> DTOIntrospectionResponse:
    """Serialize a member's federation-public DTOs into the γ-path wire payload.

    Symmetric to ``serialize_er_introspection`` but for UseCase-layer DTOs. Each
    ``get_public_dtos()`` entry becomes a ``DTOFragment``: every ``model_fields``
    entry (subset skeleton + PK + Resolver-computed) is a scalar from the
    federation standpoint, the join_key drives the member batch root, and
    ``batch_root`` carries its (diagnostic) name + arg contract. The mounter
    materializes these into local DTO classes (``materialize_dtos``) and fetches
    resolved DTO trees through ``/nexusx/dto-batch``.

    β ER introspection is untouched — DTOs never appear in ``/nexusx/er-introspection``.
    """
    from nexusx.subset import get_subset_source

    service_name = getattr(er_manager, "service_name", None)
    if not service_name:
        msg = (
            "ErManager.service_name is not set; a federable member must declare "
            "its service name (prefix). Pass service_name= to GraphQLHandler/"
            "ErManager."
        )
        raise ValueError(msg)

    dtos: list[DTOFragment] = []
    for dto in er_manager.get_public_dtos():
        join_key = getattr(dto, "__federation_join_key__", None) or ""
        source = get_subset_source(dto)
        base_entity = source.__name__ if source is not None else ""
        scalar_fields = [
            FieldDescriptor(name=fname, type_name=_type_expr(fi.annotation))
            for fname, fi in dto.model_fields.items()
        ]
        batch_root = BatchRoot(
            name=f"by_{join_key}_in",
            arg_name=f"{join_key}_list",
            arg_type="",
        )
        # γ remote top-N (specs/020): the order profile is the source entity's
        # single __pagination_orders__ — the DTO inherits the entity's own sort.
        # Validated against the base entity's physical columns via
        # _resolve_page_orders, so an order field that isn't a column fails fast.
        cfg = getattr(source, "__pagination_orders__", None) if source is not None else None
        if cfg is not None:
            from nexusx.federation.contract import (
                BatchPageCapability,
                PageOrderDescriptor,
            )
            from nexusx.standard_queries import _resolve_page_orders

            resolved = _resolve_page_orders(source, cfg)
            batch_root = BatchRoot(
                name=f"by_{join_key}_in",
                arg_name=f"{join_key}_list",
                arg_type="",
                page=BatchPageCapability(
                    default_order=cfg.default_order,
                    orders=[
                        PageOrderDescriptor(name=n, description=o.description)
                        for n, o in resolved.items()
                    ],
                ),
            )
        dtos.append(
            DTOFragment(
                name=dto.__name__,
                base_entity=base_entity,
                scalar_fields=scalar_fields,
                join_key=join_key,
                batch_root=batch_root,
                remote_refs=_dto_remote_refs(dto),
            )
        )

    return DTOIntrospectionResponse(service_name=service_name, dtos=dtos)


async def fetch_dto_introspection(
    transport: FederationTransport, base_url: str
) -> DTOIntrospectionResponse:
    """Mounter-side: GET ``<base_url>/nexusx/dto-introspection`` and parse."""
    url = base_url.rstrip("/") + "/nexusx/dto-introspection"
    raw = await transport.get_json(url)
    return DTOIntrospectionResponse.model_validate(raw)


def build_federable_app(
    handler: Any,
    *,
    dependencies: Sequence[Any] | None = None,
) -> Any:
    """Build a FastAPI app exposing the routes a federable member needs.

    Routes:
      - ``POST /graphql`` → ``{data, errors}`` (wraps ``handler.execute``)
      - ``GET  /nexusx/er-introspection`` → ER introspection payload
      - ``GET  /nexusx/dto-introspection`` → public DTO introspection payload
      - ``POST /nexusx/dto-batch`` → resolved DTO rows

    Args:
        dependencies: Optional FastAPI dependencies (e.g.
            ``[Depends(verify_token)]``) applied to BOTH routes. The
            introspection endpoint exposes the full ER topology (and, when
            ``expose_mounted_endpoints=True``, internal service URLs), so
            production deployments MUST protect it — pass an auth dependency
            here, or wire the routes into your own app with your own guards.
            Members may instead wire these routes into their own app; this
            helper is the canonical minimal surface (and what tests use with
            ASGITransport).
    """
    if dependencies is None:
        warnings.warn(
            "build_federable_app() exposes /nexusx/er-introspection with no auth "
            "dependency. That endpoint publishes the full ER topology (and, when "
            "expose_mounted_endpoints=True, internal service URLs). Pass "
            "dependencies=[Depends(...)] in production.",
            stacklevel=2,
        )
    from fastapi import FastAPI

    from nexusx.federation.introspect import serialize_er_introspection

    @asynccontextmanager
    async def lifespan(_app: Any):
        try:
            yield
        finally:
            close = getattr(handler, "aclose", None)
            if close is not None:
                await close()

    app = FastAPI(lifespan=lifespan)

    @app.post("/graphql", dependencies=dependencies)
    async def graphql_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        query = payload.get("query", "")
        variables = payload.get("variables")
        operation_name = payload.get("operationName")
        result = await handler.execute(query, variables, operation_name)
        return result if isinstance(result, dict) else {"data": None}

    @app.get("/nexusx/er-introspection", dependencies=dependencies)
    async def er_introspection_endpoint() -> dict[str, Any]:
        return serialize_er_introspection(handler._er_manager).model_dump()

    @app.get("/nexusx/dto-introspection", dependencies=dependencies)
    async def dto_introspection_endpoint() -> dict[str, Any]:
        # γ-path (specs/016): serializes the member's federation-public DTOs.
        # Independent from the β ER endpoint above — DTOs never appear in
        # er-introspection. Same auth guard expectations apply (topology leak).
        return serialize_dto_introspection(handler._er_manager).model_dump()

    @app.post("/nexusx/dto-batch", dependencies=dependencies)
    async def dto_batch_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        # γ-path (specs/016): mounter DTO RemoteLoader posts {dto, join_key,
        # keys}; this dispatches to the member's pre-registered batch root
        # (add_dto_batch_roots), which runs the member Resolver and returns an
        # already-resolved DTO tree. Independent from /graphql (β) — the β
        # surface is untouched.
        dto_name = payload.get("dto")
        roots = getattr(handler._er_manager, "_dto_batch_roots", {}) or {}
        entry = roots.get(dto_name)
        if entry is None:
            return {
                "errors": [{
                    "message": (
                        f"Member has no federation-public DTO {dto_name!r}; "
                        f"known: {sorted(roots)}"
                    )
                }]
            }
        batch_fn, registered_join_key = entry
        requested_join_key = payload.get("join_key")
        if requested_join_key != registered_join_key:
            return {
                "errors": [{
                    "message": (
                        f"DTO {dto_name!r} uses join_key "
                        f"{registered_join_key!r}, got {requested_join_key!r}"
                    )
                }]
            }
        keys = payload.get("keys") or []
        # specs/016 Phase 2: order/direction/limit drive per-parent top-N in
        # the member batch root (ROW_NUMBER). Omitted (None) ⇒ full fetch
        # (back-compat for un-paged DTOs).
        order = payload.get("order")
        direction = payload.get("direction")
        limit = payload.get("limit")
        offset = payload.get("offset", 0)
        try:
            rows = await batch_fn(
                keys, order=order, direction=direction, limit=limit, offset=offset,
            )
        except Exception as exc:  # noqa: BLE001 — member Resolver failure surfaces
            # spec Edge Case: member Resolver/computation failing during the
            # batch root must NOT crash this endpoint with a 500 — return an
            # errors envelope so the mounter DTO RemoteLoader wraps it into a
            # RemoteQueryError (same {data, errors} convention as /graphql).
            return {
                "errors": [{
                    "message": (
                        f"Member DTO batch root for {dto_name!r} failed: "
                        f"{type(exc).__name__}: {exc}"
                    )
                }]
            }
        return {"data": rows}

    return app
