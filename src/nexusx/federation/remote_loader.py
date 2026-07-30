"""RemoteLoader — fetch multi-level nested data from a mounted nexusx service.

A DataLoader whose ``batch_load_fn`` issues ONE GraphQL query per mounted
service per traversal, requesting the multi-level nested subtree. The mounted
service resolves its own composed subgraph with its own executor and returns
shaped data; the mounter only stitches at service boundaries (no per-level
flat fetching → no network-level N+1).

The FieldSelection for the relationship is injected onto the loader instance
by the executor (``set_remote_selection``) before ``load_many`` — same
side-channel pattern as ``loader._query_meta``.
"""

from __future__ import annotations

import decimal
import json
import uuid
from typing import Any

from aiodataloader import DataLoader
from pydantic import BaseModel

from nexusx.federation.transport import FederationTransport


class RemoteQueryError(RuntimeError):
    """A remote gql query returned errors or an unexpected response shape.

    Attributes:
        typename: The remote type that was queried.
        gql_errors: The raw errors list from the remote response.
    """

    def __init__(self, typename: str, gql_errors: Any) -> None:
        self.typename = typename
        self.gql_errors = gql_errors
        super().__init__(
            f"Remote {typename} query failed: {gql_errors}"
        )


def set_remote_selection(loader: Any, selection: Any) -> None:
    """Stash the current FieldSelection onto a loader (side-channel)."""
    loader._remote_selection = selection


async def fetch_remote_subtree(
    *,
    registry: Any,
    rel_info: Any,
    parents: list[Any],
    selection: Any,
) -> list[Any]:
    """Fetch a federated sub-tree: ONE nested gql to ``rel_info``'s owning
    service, returning target instances — with the whole sub-tree populated by
    the member — aligned to ``parents``.

    This is the shared "fetch a federated sub-tree" primitive, consumed by BOTH
    the gql executor (β path, selection from the parsed query) and the Resolver
    (γ path, selection built from the DTO/materialized graph). One mechanism
    instead of two.

    Args:
        registry: the ErManager (provides ``get_loader`` + ``get_relationships``).
        rel_info: the RelationshipInfo for the (non-coalesced) service-boundary
            relationship. Its ``loader``/``fk_field``/``target_entity`` drive the fetch.
        parents: the source instances whose ``fk_field`` values key the fetch.
        selection: a FieldSelection over ``rel_info.target_entity`` describing the
            nested sub-tree to request. The member resolves everything under it
            (local edges + further cross-service hops).
    """
    from nexusx.loader.query_meta import generate_type_key_from_selection

    # type_key from the selection so distinct selections get distinct loader
    # instances; force_split isolates _remote_selection per selection (prevents
    # races when two concurrent groups query the same remote rel differently).
    target_rels = registry.get_relationships(rel_info.target_entity)
    fk_lookup = {name: info.fk_field for name, info in target_rels.items()}
    type_key = generate_type_key_from_selection(
        selection, rel_info.target_entity, fk_lookup=fk_lookup,
    )
    loader = registry.get_loader(
        rel_info.loader, type_key=type_key, force_split=True,
    )
    set_remote_selection(loader, selection)
    fk_values = [getattr(p, rel_info.fk_field) for p in parents]
    return await loader.load_many(fk_values)


def _render_value(v: Any) -> str:
    """Render a Python value as a GraphQL literal."""
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_render_value(x) for x in v) + "]"
    if isinstance(v, (uuid.UUID, decimal.Decimal)):
        return json.dumps(str(v))
    return str(v)


def _normalize_join_key(v: Any) -> Any:
    """Coerce a LOCAL join key into the wire form the remote echoes back.

    Symmetric with outbound ``_render_value``: UUID/Decimal travel as strings
    over JSON, so the member's response carries the join key as a plain string.
    Without this, a local ``UUID`` key would miss a string-keyed bucket
    (``UUID("x") != "x"``) and silently resolve to ``None``/``[]``. int/str/bool
    already match their JSON form and pass through unchanged.
    """
    if isinstance(v, (uuid.UUID, decimal.Decimal)):
        return str(v)
    return v


def _render_keys(keys: list[Any]) -> str:
    return "[" + ", ".join(_render_value(k) for k in keys) + "]"


def _render_selection(sel: Any, indent: int = 6) -> str:
    """Render a FieldSelection subtree as a GraphQL selection set.

    Recurses into nested selections so the mounted service resolves its own
    subgraph (multi-hop). Dotted-name targets are never used here — only bare
    field names appear, matching the mounted service's (un-prefixed) schema.
    """
    pad = " " * indent
    lines: list[str] = []
    sub_fields = getattr(sel, "sub_fields", None) or {}
    for fname, child in sub_fields.items():
        child_sub = getattr(child, "sub_fields", None) or {}
        if child_sub:
            lines.append(f"{pad}{fname} {{")
            lines.append(_render_selection(child, indent + 2))
            lines.append(f"{pad}}}")
        else:
            args = getattr(child, "arguments", None) or {}
            arg_str = (
                "(" + ", ".join(f"{k}: {_render_value(v)}" for k, v in args.items()) + ")"
                if args
                else ""
            )
            lines.append(f"{pad}{fname}{arg_str}")
    return "\n".join(lines)


def build_gql_query(
    *,
    typename: str,
    entry: str,
    arg_name: str,
    keys: list[Any],
    selection: Any,
    target_cls: type,
    join_remote: str,
) -> str:
    """Construct the nested GraphQL query document."""
    # Field set: client selection (if any) plus the join key (needed for align).
    wanted: list[str] = []
    sub_fields = getattr(selection, "sub_fields", None) or {}
    for fname in sub_fields:
        wanted.append(fname)
    if join_remote not in wanted:
        wanted.append(join_remote)

    pad = "  "
    body_lines: list[str] = []
    for fname in wanted:
        child = sub_fields.get(fname)
        child_sub = getattr(child, "sub_fields", None) if child else None
        if child_sub:
            body_lines.append(f"{pad*2}{fname} {{")
            body_lines.append(_render_selection(child, 6))
            body_lines.append(f"{pad*2}}}")
        else:
            body_lines.append(f"{pad*2}{fname}")

    keys_lit = _render_keys(keys)
    return (
        f"query {{\n"
        f"{pad}{typename} {{\n"
        f"{pad*2}{entry}({arg_name}: {keys_lit}) {{\n"
        + "\n".join(body_lines)
        + f"\n{pad*2}}}\n"
        f"{pad}}}\n"
        f"}}"
    )


def _to_dict(obj: Any) -> Any:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return obj


def create_remote_loader(
    *,
    typename: str,
    join_remote: str,
    endpoint: str,
    target_cls: type[BaseModel],
    transport: FederationTransport,
    is_list: bool,
    arg_name: str | None = None,
) -> type[DataLoader]:  # type: ignore[type-arg]
    """Build a DataLoader subclass that fetches from a mounted service.

    Config (typename / join key / endpoint / target class / transport) is baked
    into the class — same pattern as ErManager's ``_CustomLoader``.

    Args:
        arg_name: The GraphQL argument name the member's ``by_<join_remote>_in``
            root expects, taken from the introspection contract (BatchRoot).
            Defaults to the ``<join_remote>_list`` convention when unknown —
            callers should pass the contract's value so a member that renamed
            the argument is caught at ``federate()``, not at query time.
    """
    entry = f"by_{join_remote}_in"
    if not arg_name:
        arg_name = f"{join_remote}_list"
    gql_url = endpoint.rstrip("/") + "/graphql"

    class _RemoteLoader(DataLoader):  # type: ignore[type-arg]
        async def batch_load_fn(self, keys: list[Any]) -> list[Any]:
            selection = getattr(self, "_remote_selection", None)
            if selection is None:
                # Default selection: all SCALAR fields (exclude relationship
                # fields which are BaseModel-typed and need sub-selections).
                from pydantic import BaseModel as _BM

                from nexusx.query_parser import FieldSelection
                sub = {
                    fname: FieldSelection(name=fname)
                    for fname, fi in target_cls.model_fields.items()
                    if not (isinstance(fi.annotation, type) and issubclass(fi.annotation, _BM))
                }
                selection = FieldSelection(name=typename, sub_fields=sub)
            query = build_gql_query(
                typename=typename,
                entry=entry,
                arg_name=arg_name,
                keys=list(keys),
                selection=selection,
                target_cls=target_cls,
                join_remote=join_remote,
            )
            resp = await transport.post_json(gql_url, {"query": query})
            if resp.get("errors"):
                raise RemoteQueryError(typename, resp["errors"])
            data = resp.get("data") or {}
            group = (data.get(typename) or {}).get(entry) or []
            rows = [_to_dict(r) for r in group]

            # Group rows by join key, align to input order.
            buckets: dict[Any, list[Any]] = {}
            for row in rows:
                k = row.get(join_remote)
                buckets.setdefault(k, []).append(row)

            aligned: list[Any] = []
            for key in keys:
                matches = buckets.get(_normalize_join_key(key), [])
                if is_list:
                    aligned.append([target_cls.model_validate(r) for r in matches])
                else:
                    aligned.append(target_cls.model_validate(matches[0]) if matches else None)
            return aligned

    _RemoteLoader.__name__ = f"RemoteLoader_{typename}_{join_remote}"
    _RemoteLoader.__qualname__ = _RemoteLoader.__name__
    return _RemoteLoader
