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

    __slots__ = ("qualified_name", "url", "color")

    def __init__(
        self, qualified_name: str, url: str | None = None, color: str | None = None
    ) -> None:
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
        # Optional cluster color for voyager (opt-in, declared on RemoteService).
        # None ⇒ the remote service renders with no special color (still dashed).
        self.color = color

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

    __slots__ = ("_name", "_url", "_color")

    def __init__(
        self, name: str, url: str | None = None, color: str | None = None
    ) -> None:
        self._name = name
        self._url = url
        self._color = color

    @property
    def name(self) -> str:
        return self._name

    @property
    def url(self) -> str | None:
        return self._url

    @property
    def color(self) -> str | None:
        return self._color

    def __getattr__(self, typename: str) -> RemoteRef:
        if typename.startswith("_"):
            raise AttributeError(typename)
        return RemoteRef(
            f"{self._name}.{typename}", url=self._url, color=self._color
        )

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


def _remote_ref_cardinality(annotation: Any) -> tuple[RemoteRef | None, bool]:
    """Return ``(RemoteRef, is_list)`` for an annotation referencing a remote DTO.

    ``list[reviews.ReviewDTO]`` → to-many (``is_list=True``);
    ``reviews.ReviewDTO`` / ``reviews.ReviewDTO | None`` → to-one. Used by
    federate() to wire the γ DTO RemoteLoader with the right cardinality.
    """
    ref = _contains_remote_ref(annotation)
    if ref is None:
        return None, False
    # Peel Annotated (Annotated[list[Ref], Paged(...)] → list[Ref]) so the
    # list/union inspection sees the real container, not the Annotated generic.
    # specs/016: Paged marker on a remote-DTO field.
    inner = annotation
    if hasattr(inner, "__metadata__"):
        args = typing.get_args(inner)
        if args:
            inner = args[0]
    # Peel Optional (X | None) to inspect the inner container.
    origin = typing.get_origin(inner)
    if origin in (typing.Union, types.UnionType):
        non_none = [a for a in typing.get_args(inner) if a is not type(None)]
        if len(non_none) == 1:
            inner = non_none[0]
    is_list = typing.get_origin(inner) is list
    return ref, is_list


def _record_service_color(fed_registry: Any, ref: RemoteRef) -> None:
    """Record a RemoteRef's declared cluster color onto the registry.

    The color is opt-in (set on ``RemoteService(color=...)`` and carried on the
    ref). Only services this registry actually mounts get colored — call this
    after a successful ``_resolve_ref`` so unresolvable refs (belonging to a
    different ErManager) contribute nothing.
    """
    color = getattr(ref, "color", None)
    if color:
        srv = ref.qualified_name.split(".", 1)[0]
        fed_registry.record_service_color(srv, color)


# ── Deferred DefineSubset registry ──────────────────────────────────────

_pending_subsets: list[tuple[str, type, RemoteRef, list[str], dict[str, Any]]] = []

# Accumulates placeholder-class → resolved-class across ALL resolve_deferred_subsets
# calls. A subset referenced by another DTO may resolve in an earlier federate()
# call (different ErManager) than the DTO that references it; this map lets a
# later call's replacement pass still swap the stale placeholder ref.
_resolved_placeholders: dict[type, type] = {}


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


def replace_resolved_placeholders(classes: list[type]) -> list[type]:
    """Replace deferred DTO placeholders with their latest resolved classes."""
    replaced: list[type] = []
    for cls in classes:
        while cls in _resolved_placeholders:
            cls = _resolved_placeholders[cls]
        replaced.append(cls)
    return replaced


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
        return fed_registry.get(qn)

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

        # Record the source service's declared cluster color (opt-in) now that
        # the ref resolved against this registry.
        _record_service_color(fed_registry, source_ref)

        module_name = namespace.get("__module__", "__main__")
        module = sys.modules.get(module_name)
        old_cls = getattr(module, name, None) if module else None

        # Build resolved annotations.
        resolved_annotations: dict[str, Any] = {}
        remote_field_refs: dict[str, Any] = {}
        try:
            for fname, anno in namespace.get("__annotations__", {}).items():
                raw_anno = anno
                if isinstance(raw_anno, str):
                    try:
                        raw_anno = eval(  # noqa: S307
                            raw_anno,
                            vars(module) if module is not None else {},
                            namespace,
                        )
                    except (NameError, TypeError):
                        pass
                ref = _contains_remote_ref(raw_anno)
                if ref is not None:
                    target = _resolve_ref(ref, f"{name}.{fname}")
                    _record_service_color(fed_registry, ref)
                    remote_field_refs[fname] = raw_anno
                    if isinstance(raw_anno, _RemoteRefOptional):
                        resolved_annotations[fname] = target | None
                    elif isinstance(raw_anno, RemoteRef):
                        resolved_annotations[fname] = target
                    else:
                        resolved_annotations[fname] = _replace_remote_ref(
                            raw_anno, fed_registry,
                        )
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

        # Preserve user-defined members from the original class body. The
        # rebuild above carries only __subset__/annotations/field-defaults; any
        # other methods, properties, or descriptors (post_*, resolve_*,
        # @property, @computed_field, …) would otherwise be stripped and never
        # execute on remote-sourced DTO nodes. Skip dunder names (__subset__,
        # __annotations__, __module__, …) already set explicitly above, and
        # field names already carried via __annotations__.
        for key, value in namespace.items():
            if key.startswith("__") and key.endswith("__"):
                continue
            if isinstance(value, (staticmethod, classmethod, property)) or callable(value):
                new_namespace[key] = value

        new_cls = type(name, (DefineSubset,), new_namespace)
        if remote_field_refs:
            new_cls.__nexusx_remote_field_refs__ = remote_field_refs

        if module is not None:
            setattr(module, name, new_cls)
        if old_cls is not None and old_cls is not new_cls:
            replacements[old_cls] = new_cls
            # Record globally so a later federate() call (different ErManager)
            # can still swap this placeholder in DTOs that reference it.
            _resolved_placeholders[old_cls] = new_cls

        resolved.append(new_cls)

    # Only remove resolved subsets; keep unresolvable ones for a subsequent
    # federate() call (supports multiple ErManagers in one process).
    _pending_subsets[:] = still_pending

    # Update existing DefineSubset classes: replace placeholder refs in BOTH
    # __annotations__ AND model_fields[].annotation (pydantic v2 model_rebuild
    # does NOT re-read __annotations__ to update FieldInfo.annotation). Iterate
    # the resolved classes too — a deferred DTO that references another deferred
    # DTO (e.g. ReviewDTO.comments: list[CommentDTO]) keeps the placeholder ref
    # in its annotation until this pass swaps it for the resolved class.
    from nexusx.subset import _subset_registry
    # Use the global placeholder→resolved map (superset of this call's
    # replacements) so refs to subsets resolved in earlier federate() calls
    # are still swapped.
    all_replacements = {**replacements, **_resolved_placeholders}
    _all_dto_classes = set(_subset_registry.keys()) | set(resolved)
    for dto_cls in _all_dto_classes:
        changed = False
        new_annotations: dict[str, Any] = {}
        for fname, anno in dto_cls.__annotations__.items():
            replaced = _replace_classes_in_annotation(anno, all_replacements)
            new_annotations[fname] = replaced
            if replaced is not anno:
                changed = True
        for _fname, field_info in dto_cls.model_fields.items():
            replaced = _replace_classes_in_annotation(field_info.annotation, all_replacements)
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


def resolve_remote_field_refs(
    fed_registry: Any,
    dto_classes: list[type] | None = None,
) -> list[type]:
    """Resolve deferred extra-field RemoteRefs on DefineSubset classes (specs/016).

    Companion to ``SubsetMeta._collect_remote_field_refs``: a mounter DTO whose
    source is local but which declares an extra field referencing a member public
    DTO (e.g. ``ProductDTO.reviews: list[reviews.ReviewDTO]``) carries the raw
    RemoteRef annotation on ``__nexusx_remote_field_refs__``. After federate has
    materialized the member DTOs, this swaps each placeholder ``Any`` field for
    the materialized DTO class and rebuilds the model.

    Only refs whose service this ``fed_registry`` actually mounts are resolved;
    others stay deferred for a subsequent federate() call (multi-app coexistence,
    same pattern as ``resolve_deferred_subsets``). Idempotent — once a field holds
    a real class, re-resolution yields the same type.
    """
    resolved: list[type] = []
    if dto_classes is None:
        from nexusx.subset import _subset_registry

        dto_classes = list(_subset_registry.keys())
    for dto_cls in dto_classes:
        refs = getattr(dto_cls, "__nexusx_remote_field_refs__", None)
        if not refs:
            continue

        changed = False
        for fname, raw_anno in refs.items():
            ref = _contains_remote_ref(raw_anno)
            if ref is None:
                continue
            if not fed_registry.has(ref.qualified_name):
                # Target service not mounted by THIS fed_registry — defer to a
                # subsequent federate() (different ErManager).
                continue
            _record_service_color(fed_registry, ref)
            new_anno = _replace_remote_ref(raw_anno, fed_registry)
            field_info = dto_cls.model_fields.get(fname)
            if field_info is not None:
                field_info.annotation = new_anno
            dto_cls.__annotations__[fname] = new_anno
            changed = True

        if changed:
            try:
                dto_cls.model_rebuild(force=True)
            except Exception:  # noqa: BLE001 — rebuild best-effort, mirrors resolve_deferred_subsets
                pass
            resolved.append(dto_cls)

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
    if isinstance(annotation, RemoteRef):
        return fed_registry.get(annotation.qualified_name)
    if isinstance(annotation, _RemoteRefOptional):
        return fed_registry.get(annotation.inner.qualified_name) | None

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is None or not args:
        return annotation

    new_args = tuple(_replace_remote_ref(arg, fed_registry) for arg in args)
    if new_args == args:
        return annotation

    if origin is list and len(new_args) == 1:
        return list[new_args[0]]
    if origin is types.UnionType:
        result = new_args[0]
        for arg in new_args[1:]:
            result = result | arg
        return result
    try:
        return origin[new_args] if len(new_args) > 1 else origin[new_args[0]]
    except Exception:
        return annotation
