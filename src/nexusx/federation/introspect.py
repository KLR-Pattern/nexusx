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
from collections.abc import Sequence
from typing import Any, Union

from nexusx.federation.contract import (
    BatchRoot,
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
    """Generated ``by_<key>_in`` batch roots on ``entity`` with their arg contract."""
    roots: list[BatchRoot] = []
    for attr_name in dir(entity):
        if not (attr_name.startswith("by_") and attr_name.endswith("_in")):
            continue
        attr = getattr(entity, attr_name, None)
        if not callable(attr):
            continue
        arg_name, arg_type = _batch_root_arg(attr)
        roots.append(BatchRoot(name=attr_name, arg_name=arg_name, arg_type=arg_type))
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
                    sort_field=getattr(r_info, "sort_field", None),
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


def build_federable_app(
    handler: Any,
    *,
    dependencies: Sequence[Any] | None = None,
) -> Any:
    """Build a FastAPI app exposing the two routes a federable member needs.

    Routes:
      - ``POST /graphql`` → ``{data, errors}`` (wraps ``handler.execute``)
      - ``GET  /nexusx/er-introspection`` → ER introspection payload

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
    from fastapi import FastAPI

    from nexusx.federation.introspect import serialize_er_introspection

    app = FastAPI()

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

    return app
