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

from nexusx.federation.contract import DTOFragment, EntityFragment

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
        # Opt-in voyager cluster colors per remote service, collected from
        # RemoteService(color=...) declarations during federate().
        self._service_colors: dict[str, str] = {}

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
            # Keep the member's original annotation so SDL/introspection retain
            # its nullable/non-null contract. The default remains None because a
            # remote fetch materializes only the fields selected by the caller.
            field_defs[fd.name] = (ann, None)
        # Relationship fields: ForwardRef to target typename (resolved in pass 2).
        # These become first-class model_fields so DefineSubset, Resolver, SDL,
        # and Voyager all treat them as proper schema relationships. Respect
        # is_list: a one-to-many relationship materializes as list[Target], not
        # a scalar Target (else validating the remote's list response fails).
        for rel in frag.relationships:
            if rel.name in field_defs:
                continue
            target = rel.target_typename
            if rel.pagination:
                # The member returns {items, pagination}, not list[Target].
                # RelationshipInfo remains the schema source of truth, while
                # Any preserves the already-shaped coalesced payload.
                field_defs[rel.name] = (Any | None, None)
            else:
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

    def materialize_dtos(self, fragments: dict[str, DTOFragment]) -> None:
        """Create pydantic models from DTO fragments — γ-path composition targets.

        Symmetric to ``materialize`` but for UseCase-layer DTOs (specs/016).
        Each DTOFragment becomes a plain pydantic class the mounter uses to
        ``model_validate`` the resolved DTO trees returned by the member's batch
        root. Runs AFTER ``materialize`` so the namespace already holds every
        materialized entity a DTO's nested field (``remote_refs``) may reference;
        pass 2 then rebuilds the DTO models against the full entity+DTO namespace.

        DTOs with no remote_refs (the MVP shape — scalar subset + Resolver-computed
        fields) produce a flat model; nested-DTO out-edges render as ForwardRefs
        resolved in pass 2, exactly like entity relationships.
        """
        self._check_unique_bare_names(fragments)
        # Treat every DTO name in this response as a valid forward reference.
        # The concrete classes do not exist until pass 1 completes.
        declaration_ns = {
            **self._namespace,
            **{frag.name: Any for frag in fragments.values()},
        }

        # Pass 1: create DTO models with scalar + remote_ref fields as ForwardRef.
        for qualified, frag in fragments.items():
            if qualified in self._qualified_to_class:
                continue
            cls = self._create_dto_model(frag, declaration_ns)
            self._qualified_to_class[qualified] = cls
            self._class_to_qualified[cls] = qualified

        # Pass 2: rebuild DTO models with namespace extended by ALL materialized
        # types (entities + DTOs), so nested-DTO ForwardRefs resolve.
        extended_ns = {**self._namespace}
        for cls in self._class_to_qualified:
            extended_ns[cls.__name__] = cls
        # Fail-fast on remote_ref targets the mounter did not materialize: a DTO
        # field referencing a missing type would otherwise degrade to Any and
        # silently drop type info on every model_validate. Check the target
        # explicitly rather than relying on model_rebuild's return value — that
        # returns False for benign scalar-annotation quirks too (see the e2e
        # ReviewDTO), so it can't distinguish a genuine missing type from a
        # harmless fallback.
        known = set(extended_ns.keys())
        for frag in fragments.values():
            for rel in frag.remote_refs:
                if rel.target_typename not in known:
                    raise RuntimeError(
                        f"DTO {frag.name} remote_ref {rel.name!r} targets "
                        f"{rel.target_typename!r}, which the mounter did not "
                        f"materialize. A federation-public DTO's remote_refs "
                        f"must all resolve; check the member exposes every "
                        f"referenced type."
                    )
        for qualified, _frag in fragments.items():
            cls = self._qualified_to_class[qualified]
            ok = cls.model_rebuild(_types_namespace=extended_ns)
            if not ok:
                # Companion to the remote_ref target check above: that one catches
                # a missing target even when pydantic degrades it to Any (the
                # annotation is then not a str, so this loop wouldn't see it);
                # this one catches any ForwardRef left as a raw string annotation
                # after rebuild.
                unresolved = [
                    fname for fname, fi in cls.model_fields.items()
                    if isinstance(fi.annotation, str)
                ]
                if unresolved:
                    raise RuntimeError(
                        f"DTO materialization failed for {cls.__name__}. "
                        f"Unresolved fields: {unresolved}. Ensure every nested "
                        f"DTO type is included in DTO introspection or registered "
                        f"via federate(extra_types=...)."
                    )

    @staticmethod
    def _create_dto_model(frag: DTOFragment, namespace: dict[str, type]) -> type[BaseModel]:
        typename = frag.name
        field_defs: dict[str, Any] = {}
        for fd in frag.scalar_fields:
            ann = _safe_annotation(fd.type_name, namespace)
            field_defs[fd.name] = (ann, None)
        for rel in frag.remote_refs:
            target = rel.target_typename
            ann = f"list[{target}]" if rel.is_list else target
            field_defs[rel.name] = (f"{ann} | None", None)
        model = cast(
            "type[BaseModel]",
            create_model(typename, __config__=ConfigDict(extra="allow"), **field_defs),
        )
        model.__name__ = typename
        model.__qualname__ = typename
        return model

    def _check_unique_bare_names(
        self,
        fragments: dict[str, DTOFragment],
    ) -> None:
        """Reject DTO/entity bare-name collisions before ForwardRef rebuilding."""
        owners: dict[str, str] = {
            cls.__name__: qualified
            for cls, qualified in self._class_to_qualified.items()
        }
        for qualified, frag in fragments.items():
            previous = owners.get(frag.name)
            if previous is not None and previous != qualified:
                raise ValueError(
                    f"Federation type name {frag.name!r} is exposed by both "
                    f"{previous!r} and {qualified!r}; bare GraphQL type names "
                    f"must be unique."
                )
            owners[frag.name] = qualified

    def qualified_of(self, cls: type) -> str | None:
        return self._class_to_qualified.get(cls)

    def all_classes(self) -> list[type]:
        return list(self._class_to_qualified.keys())

    def record_service_color(self, service: str, color: str) -> None:
        """Record a service's declared cluster color (first-writer wins)."""
        self._service_colors.setdefault(service, color)

    def service_colors(self) -> dict[str, str]:
        """Snapshot of the declared ``service -> color`` map."""
        return dict(self._service_colors)
