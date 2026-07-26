"""RemoteRelationship — declare a cross-service relationship.

A ``RemoteRelationship`` lives in an entity's ``__relationships__`` alongside
local ``Relationship`` entries. Its ``target`` is a ``"srv.typename"`` **marker
string**, not a Python type: the framework parses it during federation
materialization and never resolves it via Pydantic forward-refs (a dotted name
is not a valid Python identifier). The loader is not supplied inline — the
framework generates a ``RemoteLoader`` during ``federate()`` once the target
service's endpoint is known.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RemoteRelationship:
    """A cross-service relationship declared on the mounting side.

    Args:
        name: Relationship / field name on the source entity.
        target: ``"srv.typename"`` marker string (e.g. ``"reviews.Review"``).
        join_local: Field on the source entity used as the join key
            (e.g. ``Product.id``).
        join_remote: Corresponding field on the remote type; the remote service
            must expose a ``by_<join_remote>_in`` batch query root.
        is_list: True for to-many, False for to-one.
        description: Optional ER-diagram documentation.
    """

    name: str
    target: str
    join_local: str
    join_remote: str
    is_list: bool = False
    description: str | None = None


@dataclass
class RemoteEdge:
    """A cross-service edge declared on a remote (materialized) type.

    Used for remote→remote hops where the mounting service does not own the
    source class (so the edge cannot be co-located on the class body). Declared
    via ``federate(remote_edges=[...])``.

    Args:
        source: ``"srv.typename.field"`` — the source field on a remote type.
        target: ``"srv.typename"`` marker string.
        join_local: Join-key field on the source (remote) type.
        join_remote: Join-key field on the target type.
        is_list: True for to-many, False for to-one.
    """

    source: str
    target: str
    join_local: str
    join_remote: str
    is_list: bool = False


def parse_qualified_name(target: str) -> tuple[str, str]:
    """Parse a ``"srv.typename"`` marker into ``("srv", "typename")``.

    Raises:
        ValueError: if the string is not exactly two non-empty dot-separated
            parts.
    """
    if not isinstance(target, str) or target.count(".") != 1:
        msg = f"RemoteRelationship target must be 'srv.typename', got {target!r}"
        raise ValueError(msg)
    srv, typename = target.split(".")
    if not srv or not typename:
        msg = f"RemoteRelationship target parts must be non-empty: {target!r}"
        raise ValueError(msg)
    return srv, typename


def parse_edge_source(source: str) -> tuple[str, str, str]:
    """Parse a ``"srv.typename.field"`` edge source into ``(srv, typename, field)``."""
    if not isinstance(source, str) or source.count(".") != 2:
        msg = f"RemoteEdge source must be 'srv.typename.field', got {source!r}"
        raise ValueError(msg)
    srv, typename, field = source.split(".")
    if not srv or not typename or not field:
        msg = f"RemoteEdge source parts must be non-empty: {source!r}"
        raise ValueError(msg)
    return srv, typename, field
