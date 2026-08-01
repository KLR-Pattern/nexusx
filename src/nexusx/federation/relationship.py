"""RemoteRelationship — declare a cross-service relationship.

A ``RemoteRelationship`` lives in an entity's ``__relationships__`` alongside
local ``Relationship`` entries. Its shape mirrors :class:`nexusx.Relationship`:
``fk`` is the source-side join key, ``target`` names the remote type (wrap in
``list[...]`` for to-many, exactly like ``Relationship``), and the single
structural difference is the load slot — a local ``Relationship`` takes an
inline ``loader`` callable, while a ``RemoteRelationship`` takes a
``join_remote`` field name and lets the framework synthesize the loader against
the member's ``by_<join_remote>_in`` batch root during ``federate()``.

The ``target`` is a :class:`RemoteRef` — ``RemoteService("srv").TypeName`` (e.g.
``reviews.Review``), the same form ``DefineSubset`` uses. It is normalized to the
``"srv.typename"`` marker string during construction and parsed during
federation materialization; it never resolves via Pydantic forward-refs (a
dotted name is not a valid Python identifier).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import get_args, get_origin

from nexusx.federation.remote_ref import RemoteRef


def _unwrap_target(target: object, owner: str) -> tuple[RemoteRef, bool]:
    """Return ``(remote_ref, is_list)`` for a ``target`` declaration.

    ``list[RemoteRef]`` means to-many (mirrors ``Relationship.target``); a bare
    ``RemoteRef`` means to-one. Anything else is a declaration error.
    """
    if get_origin(target) is list:
        args = get_args(target)
        if not args or not isinstance(args[0], RemoteRef):
            msg = (
                f"{owner} target=list[...] must wrap a RemoteRef, got {target!r}"
            )
            raise TypeError(msg)
        return args[0], True
    if not isinstance(target, RemoteRef):
        msg = (
            f"{owner} target must be a RemoteRef (or list[RemoteRef] for "
            f"to-many), got {target!r}"
        )
        raise TypeError(msg)
    return target, False


@dataclass
class RemoteRelationship:
    """A cross-service relationship declared on the mounting side.

    Shape mirrors :class:`nexusx.Relationship` — same ``fk``/``target``/``name``
    vocabulary and the same ``list[...]`` convention for to-many — differing
    only in the load slot: ``join_remote`` (a field name) instead of ``loader``
    (a callable), because the loader is generated during ``federate()``.

    Args:
        fk: Field on the source entity used as the join key (e.g. ``Product.id``
            for one-to-many, ``author_id`` for many-to-one). Same concept as
            ``Relationship.fk``.
        target: ``RemoteService("srv").TypeName`` (a :class:`RemoteRef`), e.g.
            ``reviews.Review``. Wrap in ``list[...]`` for to-many
            (``list[reviews.Review]``) — the same convention ``Relationship``
            uses. Normalized internally to the ``"srv.typename"`` marker string.
        name: Relationship / field name on the source entity.
        join_remote: Corresponding field on the remote type; the remote service
            must expose a ``by_<join_remote>_in`` batch query root.
        description: Optional ER-diagram documentation.
        pagination: Whether this to-many relationship uses member-side offset
            pagination. The order profile is chosen by the caller at query time
            (``reviews(order: ..., direction: ...)``) — it is NOT pinned here.
    """

    fk: str
    target: RemoteRef | list[RemoteRef]
    name: str
    join_remote: str
    description: str | None = None
    pagination: bool = False
    # Derived from `target` (list[...] => True); not passed by callers.
    is_list: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        # `target_url`/`target_color` are derived from the RemoteRef (so
        # federation can derive the endpoint from the declaration alone);
        # `qualified_name` exposes the "srv.typename" marker downstream parses.
        # `target` itself stays the caller-supplied RemoteRef/list[RemoteRef] —
        # input type and stored address are no longer smeared across one field.
        ref, is_list = _unwrap_target(self.target, "RemoteRelationship")
        self.is_list = is_list
        self.target_url = getattr(ref, "url", None)
        # Optional voyager cluster color, carried the same way as target_url.
        self.target_color = getattr(ref, "color", None)
        self._qualified_name = ref.qualified_name

    @property
    def qualified_name(self) -> str:
        """The ``"srv.typename"`` marker parsed from ``target``.

        Consumers address remote types by this qualified name. ``target`` itself
        stays the caller-supplied RemoteRef (typed precisely), so the input type
        and the stored address are no longer smeared across one field.
        """
        return self._qualified_name


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
