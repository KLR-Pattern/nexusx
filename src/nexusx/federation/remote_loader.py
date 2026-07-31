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
from typing import Any, cast

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
    return cast("list[Any]", await loader.load_many(fk_values))


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


def _render_arguments(selection: Any) -> str:
    args = getattr(selection, "arguments", None) or {}
    if not args:
        return ""
    rendered = ", ".join(f"{key}: {_render_value(value)}" for key, value in args.items())
    return f"({rendered})"


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
        arg_str = _render_arguments(child)
        if child_sub:
            lines.append(f"{pad}{fname}{arg_str} {{")
            lines.append(_render_selection(child, indent + 2))
            lines.append(f"{pad}}}")
        else:
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
        arg_str = _render_arguments(child) if child is not None else ""
        if child_sub:
            body_lines.append(f"{pad*2}{fname}{arg_str} {{")
            body_lines.append(_render_selection(child, 6))
            body_lines.append(f"{pad*2}}}")
        else:
            body_lines.append(f"{pad*2}{fname}{arg_str}")

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
    resolved_arg_name = arg_name or f"{join_remote}_list"
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
                arg_name=resolved_arg_name,
                keys=list(keys),
                selection=selection,
                target_cls=target_cls,
                join_remote=join_remote,
            )
            resp = await transport.post_json(gql_url, {"query": query})
            if not isinstance(resp, dict):
                raise RemoteQueryError(
                    typename,
                    [{"message": f"Expected object response, got {type(resp).__name__}"}],
                )
            if resp.get("errors"):
                raise RemoteQueryError(typename, resp["errors"])
            data = resp.get("data")
            if not isinstance(data, dict):
                raise RemoteQueryError(
                    typename,
                    [{"message": "Response is missing an object-valued 'data' field"}],
                )
            type_group = data.get(typename)
            if not isinstance(type_group, dict):
                raise RemoteQueryError(
                    typename,
                    [{"message": f"Response is missing data.{typename}"}],
                )
            if entry not in type_group:
                raise RemoteQueryError(
                    typename,
                    [{"message": f"Response is missing data.{typename}.{entry}"}],
                )
            group = type_group[entry]
            if not isinstance(group, list):
                raise RemoteQueryError(
                    typename,
                    [{
                        "message": (
                            f"Expected data.{typename}.{entry} to be a list, "
                            f"got {type(group).__name__}"
                        )
                    }],
                )
            rows = [_to_dict(r) for r in group]

            # Group rows by join key, align to input order.
            buckets: dict[Any, list[Any]] = {}
            for row in rows:
                if not isinstance(row, dict):
                    raise RemoteQueryError(
                        typename,
                        [{
                            "message": (
                                f"Expected rows in data.{typename}.{entry} to be "
                                f"objects, got {type(row).__name__}"
                            )
                        }],
                    )
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


def build_paginated_gql_query(
    *,
    typename: str,
    entry: str,
    arg_name: str,
    join_remote: str,
    keys: list[Any],
    items_sel: Any,
    sort_field: str,
    sort_direction: str = "asc",
    limit: int | None = None,
    offset: int = 0,
    want_total_count: bool = True,
) -> str:
    """Construct the paginated GraphQL query document (``by_<key>_in_page``)."""
    keys_lit = _render_keys(keys)
    args = [f"{arg_name}: {keys_lit}"]
    if limit is not None:
        args.append(f"limit: {_render_value(limit)}")
    args.append(f"offset: {_render_value(offset)}")
    args.append(f"sort_field: {_render_value(sort_field)}")
    args.append(f"sort_direction: {_render_value(sort_direction)}")
    items_body = _render_selection(items_sel, indent=6)
    pag_lines = ["      has_more"]
    if want_total_count:
        pag_lines.append("      total_count")
    pagination_body = "\n".join(pag_lines)
    return (
        f"query {{\n"
        f"  {typename} {{\n"
        f"    {entry}({', '.join(args)}) {{\n"
        f"      {join_remote}\n"
        f"      items {{\n{items_body}\n      }}\n"
        f"      pagination {{\n{pagination_body}\n      }}\n"
        f"    }}\n"
        f"  }}\n"
        f"}}"
    )


def create_paginated_remote_loader(
    *,
    typename: str,
    join_remote: str,
    endpoint: str,
    target_cls: type[BaseModel],
    transport: FederationTransport,
    arg_name: str,
    sort_field: str,
    sort_direction: str = "asc",
) -> type[DataLoader]:  # type: ignore[type-arg]
    """Build a DataLoader that fetches a paginated sub-tree from a mounted service.

    Emits one ``by_<join_remote>_in_page`` gql carrying batch-level
    ``limit``/``offset``/``sort_field``/``sort_direction`` (read from the injected
    FieldSelection arguments), then aligns the per-key packages into
    ``{items, pagination}`` per parent by join key. ``sort_field``/``sort_direction``
    are baked in from the ``RemoteRelationship`` declaration; ``limit``/``offset``
    come from the client query args (selection.arguments).
    """

    entry = f"by_{join_remote}_in_page"
    gql_url = endpoint.rstrip("/") + "/graphql"

    class _PaginatedRemoteLoader(DataLoader):  # type: ignore[type-arg]
        async def batch_load_fn(self, keys: list[Any]) -> list[Any]:
            selection = getattr(self, "_remote_selection", None)
            items_sel = None
            want_tc = True
            sel_args: dict[str, Any] = {}
            if selection is not None:
                sub = getattr(selection, "sub_fields", None) or {}
                items_sel = sub.get("items")
                pag_field = sub.get("pagination")
                pag_sub = (
                    getattr(pag_field, "sub_fields", None) or {}
                    if pag_field else {}
                )
                want_tc = "total_count" in pag_sub
                sel_args = getattr(selection, "arguments", None) or {}
            if items_sel is None:
                from pydantic import BaseModel as _BM

                from nexusx.query_parser import FieldSelection

                items_sel = FieldSelection(
                    name=typename,
                    sub_fields={
                        fname: FieldSelection(name=fname)
                        for fname, fi in target_cls.model_fields.items()
                        if not (
                            isinstance(fi.annotation, type)
                            and issubclass(fi.annotation, _BM)
                        )
                    },
                )
            limit = sel_args.get("limit")
            offset = sel_args.get("offset", 0)
            query = build_paginated_gql_query(
                typename=typename, entry=entry, arg_name=arg_name,
                join_remote=join_remote, keys=list(keys), items_sel=items_sel,
                sort_field=sort_field, sort_direction=sort_direction,
                limit=limit, offset=offset, want_total_count=want_tc,
            )
            resp = await transport.post_json(gql_url, {"query": query})
            if resp.get("errors"):
                raise RemoteQueryError(typename, resp["errors"])
            data = resp.get("data") or {}
            packages = (data.get(typename) or {}).get(entry) or []
            buckets: dict[Any, Any] = {}
            for pkg in packages:
                pkg_d = _to_dict(pkg)
                fk = pkg_d.get(join_remote)
                buckets[_normalize_join_key(fk)] = pkg_d
            aligned: list[Any] = []
            for key in keys:
                pkg_d = buckets.get(_normalize_join_key(key))
                if pkg_d is None:
                    aligned.append({
                        "items": [],
                        "pagination": {"has_more": False, "total_count": 0},
                    })
                else:
                    items = [
                        target_cls.model_validate(_to_dict(r))
                        for r in (pkg_d.get("items") or [])
                    ]
                    aligned.append({
                        "items": items,
                        "pagination": pkg_d.get("pagination") or {},
                    })
            return aligned

    _PaginatedRemoteLoader.__name__ = f"PaginatedRemoteLoader_{typename}_{join_remote}"
    _PaginatedRemoteLoader.__qualname__ = _PaginatedRemoteLoader.__name__
    return _PaginatedRemoteLoader


async def fetch_remote_subtree_paged(
    *,
    registry: Any,
    rel_info: Any,
    parents: list[Any],
    selection: Any,
) -> list[Any]:
    """Fetch a paginated federated sub-tree via ``rel_info.page_loader``.

    Like :func:`fetch_remote_subtree` but uses the paginated RemoteLoader
    (``rel_info.page_loader``), which emits ``by_<key>_in_page`` and aligns
    per-key packages into ``{items, pagination}``. The client ``limit``/``offset``
    live in ``selection.arguments``; ``sort_field``/``sort_direction`` are baked
    into the loader class (from the ``RemoteRelationship`` declaration).
    """
    from nexusx.loader.query_meta import generate_type_key_from_selection

    target_rels = registry.get_relationships(rel_info.target_entity)
    fk_lookup = {name: info.fk_field for name, info in target_rels.items()}
    type_key = generate_type_key_from_selection(
        selection, rel_info.target_entity, fk_lookup=fk_lookup,
    )
    loader = registry.get_loader(
        rel_info.page_loader, type_key=type_key, force_split=True,
    )
    set_remote_selection(loader, selection)
    fk_values = [getattr(p, rel_info.fk_field) for p in parents]
    return await loader.load_many(fk_values)
