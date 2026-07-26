"""FederatedTypeRegistry — qualified-name ↔ materialized class.

Materializes remote types from ER fragments via ``pydantic.create_model`` at
init time. Materialized classes keep a **bare** ``__name__`` (no service
prefix, no camelCase mangling); the qualified identity ``"srv.typename"`` lives
only here, used for internal addressing. Internal lookups key on the qualified
name (or the class object), never on ``__name__`` — so two services' ``Review``
never collide internally.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from typing import Any, cast

from pydantic import BaseModel, create_model

from nexusx.federation.contract import EntityFragment

# Map wire type-name → Python type for materialized model fields.
_TYPE_MAP: dict[str, type] = {
    "int": int,
    "str": str,
    "float": float,
    "bool": bool,
    "bytes": bytes,
    "UUID": uuid.UUID,
    "datetime": datetime.datetime,
    "date": datetime.date,
    "time": datetime.time,
    "Decimal": decimal.Decimal,
}


def _resolve_type(type_name: str) -> type:
    """Resolve a wire type-name to a Python type (falls back to ``Any``)."""
    return _TYPE_MAP.get(type_name, Any)


class FederatedTypeRegistry:
    """Holds materialized remote types keyed by qualified name.

    Relationships are NOT pydantic fields on the materialized classes (they are
    registered as ``RelationshipInfo`` on the ErManager separately), so there
    are no cross-type forward references to resolve — materialization is a
    single pass over fragments.
    """

    def __init__(self) -> None:
        self._qualified_to_class: dict[str, type] = {}
        self._class_to_qualified: dict[type, str] = {}

    def materialize(self, fragments: dict[str, EntityFragment]) -> None:
        """Create a pydantic model per fragment and register it."""
        for qualified, frag in fragments.items():
            if qualified in self._qualified_to_class:
                continue
            cls = self._create_model(frag)
            self._qualified_to_class[qualified] = cls
            self._class_to_qualified[cls] = qualified

    @staticmethod
    def _create_model(frag: EntityFragment) -> type[BaseModel]:
        typename = frag.typename
        # Loose typing on field_defs: pydantic.create_model accepts per-field
        # (type, default) tuples via **field_definitions.
        field_defs: dict[str, Any] = {}
        for fd in frag.scalar_fields:
            py_type = _resolve_type(fd.type_name)
            # Optional[Any] default so construction from partial JSON is robust.
            field_defs[fd.name] = (py_type | None, None)
        model = cast("type[BaseModel]", create_model(typename, **field_defs))
        model.__name__ = typename  # bare name, no prefix
        model.__qualname__ = typename
        return model

    def get(self, qualified: str) -> type:
        return self._qualified_to_class[qualified]

    def has(self, qualified: str) -> bool:
        return qualified in self._qualified_to_class

    def qualified_of(self, cls: type) -> str | None:
        return self._class_to_qualified.get(cls)

    def all_classes(self) -> list[type]:
        return list(self._class_to_qualified.keys())
