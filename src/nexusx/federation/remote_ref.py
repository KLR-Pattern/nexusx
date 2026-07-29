"""RemoteService + RemoteRef — explicit markers for remote type references.

``RemoteService("users")`` creates a namespace-like object; ``users.User``
returns a ``RemoteRef("users.User")``. This separates service identity from
type identity and reads like importing a type from a module::

    from nexusx.federation import RemoteService

    users = RemoteService("users")
    reviews = RemoteService("reviews")

    class ReviewDTO(DefineSubset):
        __subset__ = (reviews.Review, ("title", "rating"))
        author: users.User | None = None

DefineSubset detects RemoteRef in ``__subset__`` (or annotations) and defers
processing. ``resolve_deferred_subsets`` (called during ``federate``) resolves
each RemoteRef to the materialized pydantic class and completes the DTO.
"""

from __future__ import annotations

import logging
import sys
import types
import typing
from typing import Any

logger = logging.getLogger(__name__)


class _NotResolvable(Exception):
    """Internal signal: this RemoteRef belongs to a different fed_registry
    (a service not mounted by the current federate() call). Skip silently."""


class RemoteRef:
    """A deferred reference to a remote type (``"srv.typename"``).

    Normally created via ``RemoteService("srv").TypeName`` — not called
    directly by users. DefineSubset checks ``isinstance(source, RemoteRef)``
    to decide whether to defer.

    Supports ``| None`` so it can be used directly in annotations::

        author: users.User | None = None
    """

    __slots__ = ("qualified_name", "url")

    def __init__(self, qualified_name: str, url: str | None = None) -> None:
        if not isinstance(qualified_name, str) or qualified_name.count(".") != 1:
            msg = (
                f"RemoteRef expects 'srv.typename' (exactly one dot), "
                f"got {qualified_name!r}"
            )
            raise ValueError(msg)
        self.qualified_name = qualified_name
        # Inherited from the parent RemoteService so federation can derive the
        # service endpoint from the declaration alone (no explicit services= arg).
        self.url = url

    def __repr__(self) -> str:
        return f"RemoteRef({self.qualified_name!r})"

    def __or__(self, other: Any) -> _RemoteRefOptional:
        if other is None or other is type(None):  # noqa: PLR0124
            return _RemoteRefOptional(self)
        return NotImplemented

    def __ror__(self, other: Any) -> _RemoteRefOptional:
        if other is None or other is type(None):  # noqa: PLR0124
            return _RemoteRefOptional(self)
        return NotImplemented


class _RemoteRefOptional:
    """Result of ``RemoteRef | None`` — an Optional remote reference."""

    __slots__ = ("inner",)

    def __init__(self, ref: RemoteRef) -> None:
        self.inner = ref

    def __repr__(self) -> str:
        return f"{self.inner} | None"


class RemoteService:
    """A remote nexusx service — name + url, types accessed like a namespace.

    Usage::

        reviews = RemoteService("reviews", url="http://reviews:8021")
        reviews.Review        # → RemoteRef("reviews.Review"), url carried along
        await handler.initialize()   # federation derives services from declarations

    The service (name + url) is declared **once** and reused for every type on
    that service — ``url`` is the mounter-side deployment address federation
    calls. A RemoteService used only for type references (not mounted by this
    service, e.g. reached only transitively) may omit ``url``.
    """

    __slots__ = ("_name", "_url")

    def __init__(self, name: str, url: str | None = None) -> None:
        self._name = name
        self._url = url

    @property
    def name(self) -> str:
        return self._name

    @property
    def url(self) -> str | None:
        return self._url

    def __getattr__(self, typename: str) -> RemoteRef:
        if typename.startswith("_"):
            raise AttributeError(typename)
        return RemoteRef(f"{self._name}.{typename}", url=self._url)

    def __repr__(self) -> str:
        return f"RemoteService({self._name!r}, url={self._url!r})"


# ── Helpers ─────────────────────────────────────────────────────────────


def _contains_remote_ref(annotation: Any) -> RemoteRef | None:
    """Check if an annotation contains a RemoteRef (directly, in a union, or
    in a generic alias). Returns the RemoteRef if found, None otherwise."""
    if isinstance(annotation, RemoteRef):
        return annotation
    if isinstance(annotation, _RemoteRefOptional):
        return annotation.inner
    origin = typing.get_origin(annotation)
    if origin is not None:
        for arg in typing.get_args(annotation):
            ref = _contains_remote_ref(arg)
            if ref is not None:
                return ref
    return None


# ── Deferred DefineSubset registry ──────────────────────────────────────

_pending_subsets: list[tuple[str, type, RemoteRef, list[str], dict[str, Any]]] = []


def register_pending_subset(
    name: str,
    cls: type,
    source_ref: RemoteRef,
    field_names: list[str],
    namespace: dict[str, Any],
) -> None:
    _pending_subsets.append((name, cls, source_ref, field_names, namespace))


def get_pending_subsets() -> list[tuple[str, type, RemoteRef, list[str], dict[str, Any]]]:
    return list(_pending_subsets)


def clear_pending_subsets() -> None:
    _pending_subsets.clear()


def resolve_deferred_subsets(fed_registry: Any) -> list[type]:
    """Resolve pending DefineSubset classes whose RemoteRef targets types in
    THIS fed_registry.

    Called during ``federate()`` after materialization. Only resolves subsets
    whose source RemoteRef points to a type this fed_registry actually has;
    unresolvable subsets stay pending for a subsequent ``federate()`` call
    (supports multiple ErManagers in one process each mounting different
    services). Raises on RemoteRef whose service IS mounted but whose type
    name doesn't match (clear configuration error).
    """
    from nexusx.subset import DefineSubset

    resolved: list[type] = []
    replacements: dict[type, type] = {}

    all_pending = get_pending_subsets()
    available = sorted(
        getattr(fed_registry, "_qualified_to_class", {}).keys()
    )

    def _resolve_ref(ref: RemoteRef, context: str) -> type:
        """Resolve a RemoteRef to a materialized class with a clear error."""
        qn = ref.qualified_name
        if not fed_registry.has(qn):
            srv = qn.split(".")[0]
            # Is the service mounted but the type name wrong?
            has_any_from_srv = any(k.startswith(f"{srv}.") for k in available)
            if has_any_from_srv:
                # Service is mounted — type name is a genuine typo.
                from_this = [k for k in available if k.startswith(f"{srv}.")]
                msg = (
                    f"{context}: remote type {qn!r} does not match any type "
                    f"from service {srv!r}. Available from {srv!r}: {from_this}"
                )
                raise ValueError(msg)
            else:
                # Service not mounted by THIS fed_registry — skip (maybe
                # belongs to a different ErManager's federate() call).
                raise _NotResolvable(srv)

    resolvable: list[tuple] = []
    still_pending: list[tuple] = []

    for entry in all_pending:
        name, _cls, source_ref, _fields, _ns = entry
        srv = source_ref.qualified_name.split(".")[0]
        # Quick filter: does this fed_registry have ANY type from this service?
        if any(k.startswith(f"{srv}.") for k in available):
            resolvable.append(entry)
        else:
            still_pending.append(entry)

    for name, deferred_cls, source_ref, field_names, namespace in resolvable:
        try:
            materialized = _resolve_ref(source_ref, f"{name}.__subset__")
        except _NotResolvable:
            # Source service not in this fed_registry — defer to next federate().
            still_pending.append(
                (name, deferred_cls, source_ref, field_names, namespace)
            )
            continue

        module_name = namespace.get("__module__", "__main__")
        module = sys.modules.get(module_name)
        old_cls = getattr(module, name, None) if module else None

        # Build resolved annotations.
        resolved_annotations: dict[str, Any] = {}
        try:
            for fname, anno in namespace.get("__annotations__", {}).items():
                ref = _contains_remote_ref(anno)
                if ref is not None:
                    target = _resolve_ref(ref, f"{name}.{fname}")
                    if isinstance(anno, _RemoteRefOptional):
                        resolved_annotations[fname] = target | None
                    elif isinstance(anno, RemoteRef):
                        resolved_annotations[fname] = target
                    else:
                        resolved_annotations[fname] = _replace_remote_ref(anno, fed_registry)
                else:
                    resolved_annotations[fname] = anno
        except _NotResolvable:
            # An annotation references a service not in this fed_registry.
            still_pending.append(
                (name, deferred_cls, source_ref, field_names, namespace)
            )
            continue

        new_namespace: dict[str, Any] = {
            "__subset__": (materialized, tuple(field_names)),
            "__annotations__": resolved_annotations,
            "__module__": module_name,
        }
        for fname, _anno in resolved_annotations.items():
            if fname not in field_names:
                new_namespace[fname] = namespace.get(fname, None)

        new_cls = type(name, (DefineSubset,), new_namespace)

        if module is not None:
            setattr(module, name, new_cls)
        if old_cls is not None and old_cls is not new_cls:
            replacements[old_cls] = new_cls

        resolved.append(new_cls)

    # Only remove resolved subsets; keep unresolvable ones for a subsequent
    # federate() call (supports multiple ErManagers in one process).
    _pending_subsets[:] = still_pending

    # Update existing DefineSubset classes: replace placeholder refs in BOTH
    # __annotations__ AND model_fields[].annotation (pydantic v2 model_rebuild
    # does NOT re-read __annotations__ to update FieldInfo.annotation).
    from nexusx.subset import _subset_registry
    for dto_cls in list(_subset_registry.keys()):
        changed = False
        new_annotations: dict[str, Any] = {}
        for fname, anno in dto_cls.__annotations__.items():
            replaced = _replace_classes_in_annotation(anno, replacements)
            new_annotations[fname] = replaced
            if replaced is not anno:
                changed = True
        for _fname, field_info in dto_cls.model_fields.items():
            replaced = _replace_classes_in_annotation(field_info.annotation, replacements)
            if replaced is not field_info.annotation:
                field_info.annotation = replaced
                changed = True
        if changed:
            dto_cls.__annotations__ = new_annotations
            try:
                dto_cls.model_rebuild(force=True)
            except Exception:
                pass

    return resolved


def _replace_classes_in_annotation(annotation: Any, replacements: dict[type, type]) -> Any:
    """Recursively replace placeholder classes in a type annotation."""
    if isinstance(annotation, type) and annotation in replacements:
        return replacements[annotation]

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is None or not args:
        return annotation

    new_args = tuple(_replace_classes_in_annotation(a, replacements) for a in args)
    if new_args == args:
        return annotation

    if origin is list and len(new_args) == 1:
        return list[new_args[0]]
    if origin is types.UnionType:
        result = new_args[0]
        for a in new_args[1:]:
            result = result | a
        return result
    try:
        return origin[new_args] if len(new_args) > 1 else origin[new_args[0]]
    except Exception:
        return annotation


def _replace_remote_ref(annotation: Any, fed_registry: Any) -> Any:
    """Recursively replace RemoteRef in a generic annotation with real types."""
    ref = _contains_remote_ref(annotation)
    if ref is not None and not isinstance(annotation, (RemoteRef, _RemoteRefOptional)):
        origin = typing.get_origin(annotation)
        args = typing.get_args(annotation)
        new_args = tuple(
            fed_registry.get(_contains_remote_ref(a).qualified_name)
            if _contains_remote_ref(a) is not None
            else _replace_remote_ref(a, fed_registry)
            for a in args
        )
        if origin is list and len(new_args) == 1:
            return list[new_args[0]]
        try:
            return origin[new_args] if len(new_args) > 1 else origin[new_args[0]]
        except Exception:
            return annotation
    return annotation
