"""Nexusx-specific field utilities: FK detection, output coercion, field lookup.

Structural annotation helpers (Optional / list / Annotated / Mapped unwrapping,
``map_annotation``) live in :mod:`nexusx.annotation_utils` — the leaf module
every path shares (spec 026 R1).
"""

from __future__ import annotations

from typing import Any


def is_fk_field_info(field_info: Any) -> bool:
    """True when a field info carries a SQLModel/SQLAlchemy column FK marker.

    THE single FK detection (mindmap #15): a str ``foreign_key`` attribute, or
    a str ``foreign_key`` inside a ``metadata`` entry. The same three-line
    check used to be inlined 7 times across sdl_generator / introspection /
    er_diagram / subset (×2) / introspector — all now delegate here.
    """
    if hasattr(field_info, "foreign_key") and isinstance(
        field_info.foreign_key, str
    ):
        return True
    if hasattr(field_info, "metadata"):
        for meta in field_info.metadata:
            if hasattr(meta, "foreign_key") and isinstance(
                meta.foreign_key, str
            ):
                return True
    return False


def get_fk_fields(entity: type) -> set[str]:
    """Foreign-key field names on an entity (specs/021 P1-7).

    Shared by query_executor (output filtering), subset (FK auto-include into
    DTO subset fields) and standard_queries (PK-vs-FK filtering); built on
    the single-field detector above.
    """
    fks: set[str] = set()
    if not hasattr(entity, "model_fields"):
        return fks
    for fname, fi in entity.model_fields.items():
        if is_fk_field_info(fi):
            fks.add(fname)
    return fks


def coerce_to_dict(value: Any, mode: str | None = None) -> Any:
    """Coerce a value to a plain dict when possible (specs/021 P1-12).

    pydantic ``model_dump`` (``mode`` passed through, e.g. ``"json"``) / plain
    dict / iterable-of-pairs. Returns None for values that can't be coerced
    (None, scalars). Unifies response_builder's ``_coerce_to_dict`` and
    remote_loader's ``_to_dict``.
    """
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump() if mode is None else value.model_dump(mode=mode)
    if isinstance(value, dict):
        return value
    if hasattr(value, "__iter__"):
        try:
            return dict(value)
        except Exception:
            return None
    return None


def get_field_type(entity: type, field_name: str) -> type:
    """Get the type of a field from an entity.

    Args:
        entity: SQLModel entity class.
        field_name: Name of the field.

    Returns:
        Field type or Any if not found.
    """
    if hasattr(entity, "model_fields"):
        field_info = entity.model_fields.get(field_name)
        if field_info and field_info.annotation:
            return field_info.annotation

    # Fallback to annotations
    if hasattr(entity, "__annotations__"):
        return entity.__annotations__.get(field_name, Any)

    return Any
