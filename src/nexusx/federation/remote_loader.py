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


def set_remote_selection(loader: Any, selection: Any) -> None:
    """Stash the current FieldSelection onto a loader (side-channel)."""
    loader._remote_selection = selection


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


def _scalar_field_names(target_cls: type) -> list[str]:
    return list(getattr(target_cls, "model_fields", {}).keys())


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
    transport: Any,
    is_list: bool,
) -> type[DataLoader]:  # type: ignore[type-arg]
    """Build a DataLoader subclass that fetches from a mounted service.

    Config (typename / join key / endpoint / target class / transport) is baked
    into the class — same pattern as ErManager's ``_CustomLoader``.
    """
    entry = f"by_{join_remote}_in"
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
                msg = f"Remote {typename} query failed: {resp['errors']}"
                raise RuntimeError(msg)
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
                matches = buckets.get(key, [])
                if is_list:
                    aligned.append([target_cls.model_validate(r) for r in matches])
                else:
                    aligned.append(target_cls.model_validate(matches[0]) if matches else None)
            return aligned

    _RemoteLoader.__name__ = f"RemoteLoader_{typename}_{join_remote}"
    _RemoteLoader.__qualname__ = _RemoteLoader.__name__
    return _RemoteLoader
