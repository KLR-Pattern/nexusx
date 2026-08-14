"""Shared member-styling helpers for the ER and UseCase voyager builders.

``ComposedErManager._member_styling`` (specs/022) maps each member entity/DTO
class to ``(service_name, color)``. Both builders consume it the same way —
cluster-key resolution and color extraction live here so the two pages cannot
drift apart.
"""
from nexusx.federation.relationship import parse_qualified_name

# cls → (service_name, color); color is None when the member declared none.
MemberStyling = dict[type, tuple[str, str | None]]


def probe_member_styling(er_manager) -> MemberStyling | None:
    """Duck-typed probe for ``ComposedErManager._member_styling``.

    Returns None for a standalone ErManager (no such attribute) or when no
    er_manager is wired at all — callers then fall back to pre-022 behavior.
    """
    if er_manager is None:
        return None
    return getattr(er_manager, "_member_styling", None)


def resolve_cluster_key(
    cls: type,
    fed_qn: str | None,
    member_styling: MemberStyling | None,
) -> str:
    """Resolve the cluster key for a class.

    Priority (specs/022 FR-003):
      1. federation qualified name → owning remote service (FR-016)
      2. ComposedErManager member grouping → service_name (FR-002)
      3. Python ``__module__`` (pre-022 default)
    """
    if fed_qn:
        return parse_qualified_name(fed_qn)[0]
    if member_styling and cls in member_styling:
        return member_styling[cls][0]
    return cls.__module__


def member_service_colors(member_styling: MemberStyling | None) -> dict[str, str]:
    """``{service_name: color}`` from member styling, skipping colorless members."""
    if not member_styling:
        return {}
    return {name: color for name, color in member_styling.values() if color}
