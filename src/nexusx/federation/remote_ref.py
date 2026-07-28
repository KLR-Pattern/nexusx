"""RemoteRef — explicit marker for remote type references in DefineSubset.

Eliminates the ambiguity of bare strings: ``RemoteRef("reviews.Review")``
clearly signals "this is a deferred reference to a remote nexusx service's
type, resolved at federate time."

Usage::

    from nexusx.federation import RemoteRef

    class ReviewDTO(DefineSubset):
        __subset__ = (RemoteRef("reviews.Review"), ("title", "rating", "author_id"))
        author: RemoteRef("users.User") | None = None

DefineSubset detects RemoteRef and defers processing. ``resolve_deferred_subsets``
(called during federate) resolves each RemoteRef to the materialized pydantic
class and completes the DTO.
"""

from __future__ import annotations

import sys
import types
import typing
from typing import Any


class RemoteRef:
    """Marker: a deferred reference to a remote type (``"srv.typename"``).

    Wraps the qualified name string. DefineSubset checks
    ``isinstance(source, RemoteRef)`` — if True, defers; if False (a real
    class), processes immediately. This eliminates string ambiguity.

    Supports ``| None`` so it can be used directly in annotations::

        author: RemoteRef("users.User") | None = None
    """

    __slots__ = ("qualified_name",)

    def __init__(self, qualified_name: str) -> None:
        if not isinstance(qualified_name, str) or qualified_name.count(".") != 1:
            msg = (
                f"RemoteRef expects 'srv.typename' (exactly one dot), "
                f"got {qualified_name!r}"
            )
            raise ValueError(msg)
        self.qualified_name = qualified_name

    def __repr__(self) -> str:
        return f"RemoteRef({self.qualified_name!r})"

    def __or__(self, other: Any) -> _RemoteRefOptional:
        """Support ``RemoteRef("X") | None`` for Optional annotations."""
        if other is None or other is type(None):  # noqa: PLR0124
            return _RemoteRefOptional(self)
        return NotImplemented

    def __ror__(self, other: Any) -> _RemoteRefOptional:
        """Support ``None | RemoteRef("X")`` (rare, but symmetric)."""
        if other is None or other is type(None):  # noqa: PLR0124
            return _RemoteRefOptional(self)
        return NotImplemented


class _RemoteRefOptional:
    """Result of ``RemoteRef("X") | None`` — an Optional remote reference.

    Carries the inner RemoteRef. ``resolve_deferred_subsets`` detects this
    in annotations and resolves it to ``MaterializedType | None``.
    """

    __slots__ = ("inner",)

    def __init__(self, ref: RemoteRef) -> None:
        self.inner = ref

    def __repr__(self) -> str:
        return f"{self.inner} | None"


def _contains_remote_ref(annotation: Any) -> RemoteRef | None:
    """Check if an annotation contains a RemoteRef (directly or in a union).

    Returns the RemoteRef if found, None otherwise. Handles:
    - ``RemoteRef("X")`` directly
    - ``RemoteRef("X") | None`` → ``_RemoteRefOptional``
    - ``list[RemoteRef("X")]`` → GenericAlias with RemoteRef arg
    - ``None`` / plain types → no RemoteRef
    """
    if isinstance(annotation, RemoteRef):
        return annotation
    if isinstance(annotation, _RemoteRefOptional):
        return annotation.inner
    # Check generic aliases (list[RemoteRef(...)] etc.)
    import typing
    origin = typing.get_origin(annotation)
    if origin is not None:
        for arg in typing.get_args(annotation):
            ref = _contains_remote_ref(arg)
            if ref is not None:
                return ref
    return None


# ── Deferred DefineSubset registry ──────────────────────────────────────

# Classes pending resolution: {class_name: (cls, RemoteRef_source, field_names, body_namespace)}
_pending_subsets: list[tuple[str, type, RemoteRef, list[str], dict[str, Any]]] = []


def register_pending_subset(
    name: str,
    cls: type,
    source_ref: RemoteRef,
    field_names: list[str],
    namespace: dict[str, Any],
) -> None:
    """Register a deferred DefineSubset for later resolution."""
    _pending_subsets.append((name, cls, source_ref, field_names, namespace))


def get_pending_subsets() -> list[tuple[str, type, RemoteRef, list[str], dict[str, Any]]]:
    """Return all pending subsets (for resolve_deferred_subsets)."""
    return list(_pending_subsets)


def clear_pending_subsets() -> None:
    """Clear the registry (after resolution)."""
    _pending_subsets.clear()


def resolve_deferred_subsets(fed_registry: Any) -> list[type]:
    """Resolve all pending DefineSubset classes with materialized types.

    Called during ``federate()`` after materialization. For each pending class:
    1. Resolve RemoteRef → materialized class from FederatedTypeRegistry.
    2. Create a new DefineSubset with the resolved source.
    3. Replace the deferred class in its module namespace.

    Returns the list of resolved classes.
    """

    from nexusx.subset import DefineSubset

    resolved: list[type] = []
    replacements: dict[type, type] = {}

    for name, deferred_cls, source_ref, field_names, namespace in get_pending_subsets():
        materialized = fed_registry.get(source_ref.qualified_name)

        # Capture the placeholder BEFORE replacing it.
        module_name = namespace.get("__module__", "__main__")
        module = sys.modules.get(module_name)
        old_cls = getattr(module, name, None) if module else None

        # Build resolved annotations: replace RemoteRef/_RemoteRefOptional with real types.
        resolved_annotations = {}
        for fname, anno in namespace.get("__annotations__", {}).items():
            ref = _contains_remote_ref(anno)
            if ref is not None:
                target = fed_registry.get(ref.qualified_name)
                if isinstance(anno, _RemoteRefOptional):
                    resolved_annotations[fname] = target | None
                elif isinstance(anno, RemoteRef):
                    resolved_annotations[fname] = target
                else:
                    resolved_annotations[fname] = _replace_remote_ref(anno, fed_registry)
            else:
                resolved_annotations[fname] = anno

        # Build the new class via DefineSubset's metaclass.
        new_namespace = {
            "__subset__": (materialized, tuple(field_names)),
            "__annotations__": resolved_annotations,
            "__module__": module_name,
        }
        for fname, anno in resolved_annotations.items():
            if fname not in field_names:
                new_namespace[fname] = namespace.get(fname, None)

        new_cls = type(name, (DefineSubset,), new_namespace)

        # Replace in module namespace + track for updating referencing classes.
        if module is not None:
            setattr(module, name, new_cls)
        if old_cls is not None and old_cls is not new_cls:
            replacements[old_cls] = new_cls

        resolved.append(new_cls)

    clear_pending_subsets()

    # Update existing DefineSubset classes: directly replace placeholder refs
    # in BOTH __annotations__ AND model_fields[].annotation (pydantic v2's
    # model_rebuild does NOT re-read __annotations__ to update FieldInfo.annotation,
    # so we must mutate it directly).
    from nexusx.subset import _subset_registry
    for dto_cls in list(_subset_registry.keys()):
        changed = False
        # Update __annotations__.
        new_annotations = {}
        for fname, anno in dto_cls.__annotations__.items():
            replaced = _replace_classes_in_annotation(anno, replacements)
            new_annotations[fname] = replaced
            if replaced is not anno:
                changed = True
        # Update model_fields[].annotation directly.
        for fname, field_info in dto_cls.model_fields.items():
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
    # Direct match.
    if isinstance(annotation, type) and annotation in replacements:
        return replacements[annotation]

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is None or not args:
        return annotation

    new_args = tuple(_replace_classes_in_annotation(a, replacements) for a in args)
    if new_args == args:
        return annotation  # no change

    # Reconstruct: list[X], X | None, etc.
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
    import typing


    ref = _contains_remote_ref(annotation)
    if ref is not None and not isinstance(annotation, (RemoteRef, _RemoteRefOptional)):
        # Generic alias containing RemoteRef (e.g. list[RemoteRef("X")]).
        origin = typing.get_origin(annotation)
        args = typing.get_args(annotation)
        new_args = tuple(
            fed_registry.get(r.qualified_name) if isinstance(a, (RemoteRef, _RemoteRefOptional))
            else _replace_remote_ref(a, fed_registry)
            for a in args
        )
        if origin is list and len(new_args) == 1:
            return list[new_args[0]]
        return annotation  # fallback: leave as-is
    return annotation
