"""FederatedTypeRegistry — qualified-name ↔ materialized class.

Materializes remote types from ER fragments via ``pydantic.create_model`` at
init time. Materialized classes keep a **bare** ``__name__`` (no service
prefix, no camelCase mangling); the qualified identity ``"srv.typename"`` lives
only here, used for internal addressing. Internal lookups key on the qualified
name (or the class object), never on ``__name__`` — so two services' ``Review``
never collide internally.
"""

from __future__ import annotations

import datetime as _dt
import decimal
import logging
import re
import uuid
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, create_model

from nexusx.federation.contract import EntityFragment

logger = logging.getLogger(__name__)

# Shared type namespace for materializing remote types from their type-expression
# strings (see introspect._type_expr). Builtins + nexusx's common scalars; user
# types/enums are added via FederatedTypeRegistry(extra_types=...).
_BASE_NAMESPACE: dict[str, type] = {
    "Any": Any,
    "int": int, "str": str, "float": float, "bool": bool, "bytes": bytes,
    "list": list, "dict": dict, "tuple": tuple, "set": set, "frozenset": frozenset,
    "None": type(None),
    "UUID": uuid.UUID,
    "datetime": _dt.datetime, "date": _dt.date, "time": _dt.time,
    "Decimal": decimal.Decimal,
}

_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
# Identifiers in a type expression that are structural (containers/operators),
# not type names to look up in the namespace.
_KEYWORDS = {"None", "list", "dict", "tuple", "set", "frozenset"}


def _safe_annotation(expr: str, namespace: dict[str, type]) -> str:
    """Return ``expr`` if every referenced type resolves in ``namespace``.

    Falls back to ``Any`` (with a warning) for unknown names — e.g. a remote
    enum or project custom scalar the mounter hasn't registered. Register such
    types via ``federate(extra_types={...})`` for precise materialization.
    """
    unknown = {
        n for n in _IDENT_RE.findall(expr) if n not in _KEYWORDS and n not in namespace
    }
    if unknown:
        logger.warning(
            "Federation materialization: type expression %r references unknown "
            "name(s) %s; falling back to Any. Register them via "
            "federate(extra_types=...).",
            expr, sorted(unknown),
        )
        return "Any"
    return expr


class FederatedTypeRegistry:
    """Holds materialized remote types keyed by qualified name.

    Remote scalar types are carried as lossless type-expression strings
    (introspect._type_expr) and reconstructed exactly here via ``create_model``
    + ``model_rebuild`` against the type namespace — so ``list[str]`` / Optional
    / UUID / enums round-trip instead of degrading to ``Any``.
    """

    def __init__(self, extra_types: dict[str, type] | None = None) -> None:
        self._qualified_to_class: dict[str, type] = {}
        self._class_to_qualified: dict[type, str] = {}
        self._namespace: dict[str, type] = {**_BASE_NAMESPACE, **(extra_types or {})}

    def materialize(self, fragments: dict[str, EntityFragment]) -> None:
        """Create pydantic models from ER fragments — first-class schema types.

        Two passes: (1) create all models with scalar + relationship fields as
        ForwardRef string annotations; (2) model_rebuild each with an extended
        namespace that resolves all cross-type references. After rebuild, every
        relationship field is a REAL type (not a string) — so DefineSubset,
        Resolver, get_type_hints, and model_dump all work naturally.
        """
        # Pass 1: create all models (scalar + relationship fields as ForwardRef).
        for qualified, frag in fragments.items():
            if qualified in self._qualified_to_class:
                continue
            cls = self._create_model(frag, self._namespace)
            self._qualified_to_class[qualified] = cls
            self._class_to_qualified[cls] = qualified

        # Pass 2: rebuild with namespace extended by all materialized types.
        extended_ns = {**self._namespace}
        for cls in self._class_to_qualified:
            extended_ns[cls.__name__] = cls
        for cls in self._class_to_qualified:
            ok = cls.model_rebuild(_types_namespace=extended_ns)
            if not ok:
                unresolved = [
                    fname for fname, fi in cls.model_fields.items()
                    if isinstance(fi.annotation, str)
                ]
                if unresolved:
                    msg = (
                        f"model_rebuild failed for {cls.__name__}. "
                        f"Unresolved fields: {unresolved}. "
                        f"Register the types via federate(extra_types=...) "
                        f"or check that all referenced types were introspected."
                    )
                    raise RuntimeError(msg)
                # Fallback (Any types): rebuild technically failed but all
                # fields are resolved (just to Any). Keep the model as-is.
                logger.warning(
                    "model_rebuild returned False for %s but all fields "
                    "resolved (likely Any fallback); continuing.",
                    cls.__name__,
                )

    @staticmethod
    def _create_model(frag: EntityFragment, namespace: dict[str, type]) -> type[BaseModel]:
        typename = frag.typename
        field_defs: dict[str, Any] = {}
        # Scalar fields: type-expression string (resolved by model_rebuild).
        for fd in frag.scalar_fields:
            ann = _safe_annotation(fd.type_name, namespace)
            field_defs[fd.name] = (f"({ann}) | None", None)
        # Relationship fields: ForwardRef to target typename (resolved in pass 2).
        # These become first-class model_fields so DefineSubset, Resolver, SDL,
        # and Voyager all treat them as proper schema relationships. Respect
        # is_list: a one-to-many relationship materializes as list[Target], not
        # a scalar Target (else validating the remote's list response fails).
        for rel in frag.relationships:
            if rel.name in field_defs:
                continue
            target = rel.target_typename
            ann = f"list[{target}]" if rel.is_list else target
            field_defs[rel.name] = (f"{ann} | None", None)
        # keys (e.g. `author`) stay on the instance for the serializer.
        model = cast(
            "type[BaseModel]",
            create_model(typename, __config__=ConfigDict(extra="allow"), **field_defs),
        )
        # NOTE: no model_rebuild here — pass 2 (materialize) rebuilds ALL models
        # after all siblings exist, so cross-type ForwardRefs resolve.
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
