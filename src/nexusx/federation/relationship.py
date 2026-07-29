"""RemoteRelationship — declare a cross-service relationship.

A ``RemoteRelationship`` lives in an entity's ``__relationships__`` alongside
local ``Relationship`` entries. Its ``target`` is a :class:`RemoteRef` —
``RemoteService("srv").TypeName`` (e.g. ``reviews.Review``), the same form
``DefineSubset`` uses. The framework normalizes it to the ``"srv.typename"``
marker string during construction and parses that during federation
materialization; it never resolves the target via Pydantic forward-refs (a
dotted name is not a valid Python identifier). The loader is not supplied
inline — the framework generates a ``RemoteLoader`` during ``federate()`` once
the target service's endpoint is known.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nexusx.federation.remote_ref import RemoteRef


@dataclass
class RemoteRelationship:
    """A cross-service relationship declared on the mounting side.

    Args:
        name: Relationship / field name on the source entity.
        target: ``RemoteService("srv").TypeName`` (a :class:`RemoteRef`), e.g.
            ``reviews.Review``. The canonical way to name a remote type — the
            same form used in ``DefineSubset``. Normalized internally to the
            ``"srv.typename"`` marker string the federation pipeline parses.
        join_local: Field on the source entity used as the join key
            (e.g. ``Product.id``).
        join_remote: Corresponding field on the remote type; the remote service
            must expose a ``by_<join_remote>_in`` batch query root.
        is_list: True for to-many, False for to-one.
        description: Optional ER-diagram documentation.
    """

    name: str
    target: RemoteRef
    join_local: str
    join_remote: str
    is_list: bool = False
    description: str | None = None

    def __post_init__(self) -> None:
        # Capture the service url from the RemoteRef (so federation can derive
        # the endpoint from the declaration alone), then normalize target to the
        # "srv.typename" marker string downstream code parses. Not a declared
        # field (derived, not passed by callers).
        self.target_url = getattr(self.target, "url", None)
        self.target = self.target.qualified_name


@dataclass
class RemoteEdge:
    """A cross-service edge declared on a remote (materialized) type.

    Used for remote→remote hops where the mounting service does not own the
    source class (so the edge cannot be co-located on the class body). Declared
    via ``federate(remote_edges=[...])``.

    Args:
        source: ``"srv.typename.field"`` — the source field on a remote type
            (kept as a string: it carries a field name, not just a type).
        target: ``RemoteService("srv").TypeName`` (a :class:`RemoteRef`), e.g.
            ``reviews.Review``. Normalized internally to ``"srv.typename"``.
        join_local: Join-key field on the source (remote) type.
        join_remote: Join-key field on the target type.
        is_list: True for to-many, False for to-one.
    """

    source: str
    target: RemoteRef
    join_local: str
    join_remote: str
    is_list: bool = False

    def __post_init__(self) -> None:
        self.target_url = getattr(self.target, "url", None)
        self.target = self.target.qualified_name


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
