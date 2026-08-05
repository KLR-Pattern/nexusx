"""Resolver — model-driven traversal for Core API use case response building.

Traverses Pydantic/DefineSubset model trees, executing resolve_* methods
to load related data and post_* methods to compute derived fields.
Supports cross-layer data flow via ExposeAs, SendTo, and Collector.

A reserved ``post_default_handler(self)`` method may be defined to run
finalization logic after all ``post_*`` methods at the same node complete.
Unlike ``post_*``, it is not auto-assigned to a field — the body must set
fields manually (and may set several). It accepts the same parameter
injection as ``post_*`` (context / parent / ancestor_context / Loader /
Collector) and may be ``async``.

Uses the same ErManager as GraphQL mode for DataLoader access.
Not intended for direct construction — use ``ErManager.create_resolver()``.

Usage:
    from sqlmodel import SQLModel
    from nexusx import DefineSubset, ErManager, Loader

    class PostSummary(DefineSubset):
        __subset__ = (Post, ('id', 'title', 'author_id'))
        author: UserSummary | None = None

        def resolve_author(self, loader=Loader('author')):
            return loader.load(self.author_id)

    er = ErManager(base=SQLModel, session_factory=session_factory)
    resolver = er.create_resolver()
    result = await resolver.resolve([
        PostSummary.model_validate(p) for p in posts
    ])
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import typing
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar, get_args, get_origin

from aiodataloader import DataLoader
from pydantic import BaseModel
from pydantic.errors import PydanticUserError
from sqlmodel import SQLModel

from nexusx.context import (
    ICollector,
    scan_expose_fields,
    scan_send_to_fields,
)
from nexusx.loader.pagination import PageArgs, PageLoadCommand
from nexusx.loader.registry import RelationshipKind
from nexusx.query_parser import FieldSelection

T = TypeVar("T", bound=BaseModel | list[BaseModel] | tuple[BaseModel, ...])


# Module-level sentinel for caches that need to distinguish "not yet
# computed" from "computed to None / empty list". A regular None or [] value
# is a valid cached result; only the sentinel means "absent".
_MISSING: Any = object()

# Shared empty-dict sentinel for _LevelNode.collector_snapshot default.
# Treated as read-only — Phase B-1 replaces it with a fresh dict when a node
# actually has Collectors to merge, never mutates in place.
_EMPTY_SNAPSHOT: dict[str, ICollector] = {}


# ──────────────────────────────────────────────────────────
# BFS work item
# ──────────────────────────────────────────────────────────

class _WorkItem:
    """A node to be processed at a BFS level, with its context snapshot."""

    __slots__ = ("node", "parent", "ancestor_context", "collector_snapshot")

    def __init__(
        self,
        node: Any,
        parent: Any,
        ancestor_context: dict[str, Any],
        collector_snapshot: dict[str, ICollector],
    ) -> None:
        self.node = node
        self.parent = parent
        self.ancestor_context = ancestor_context
        self.collector_snapshot = collector_snapshot


@dataclass
class _EntityFieldJob:
    """A single entity-field's load task within one BFS level (entity-first gql).

    Relocated verbatim from ``QueryExecutor._FieldJob`` (specs/018 US3 / T016).
    Used by ``_bfs_dispatch_entity_fields`` — the entity-first gql path's
    relationship resolver now living in the Resolver.
    """

    parents: list
    parent_entity: type[SQLModel]
    rel_info: Any  # RelationshipInfo
    child_sel: FieldSelection
    original_sel: FieldSelection | None = None


# ──────────────────────────────────────────────────────────
# Loader / Depends — declares DataLoader dependency in resolve_*
# ──────────────────────────────────────────────────────────

class Depends:
    """Internal wrapper for Loader dependency declarations."""

    def __init__(self, dependency=None):
        self.dependency = dependency


def Loader(dependency=None):
    """Declare a DataLoader dependency for resolve_* method parameters.

    Args:
        dependency: One of:
            - DataLoader subclass: instantiated and cached per Resolver
            - async callable: wrapped in DataLoader(batch_load_fn=...)

    Usage::

        # By DataLoader class
        def resolve_owner(self, loader=Loader(UserLoader)):
            return loader.load(self.owner_id)

        # By async batch function
        async def load_users(keys):
            ...
        def resolve_owner(self, loader=Loader(load_users)):
            return loader.load(self.owner_id)
    """
    return Depends(dependency=dependency)


# ──────────────────────────────────────────────────────────
# Class metadata cache — avoids repeated dir()/inspect.signature()
# ──────────────────────────────────────────────────────────

@dataclass
class _MethodParamInfo:
    """Pre-computed parameter information for a resolve_* or post_* method."""
    has_context: bool = False
    has_parent: bool = False
    has_ancestor_context: bool = False
    loader_deps: list[tuple[str, Depends]] = field(default_factory=list)
    collector_deps: list[tuple[str, ICollector]] = field(default_factory=list)


@dataclass
class _ClassMeta:
    """Pre-computed metadata for a Pydantic model class.

    Populated once per class type, reused across all instances.
    """
    # (field_name, attr_name) for resolve_* methods
    resolve_methods: list[tuple[str, str]] = field(default_factory=list)
    # (field_name, attr_name) for post_* methods
    post_methods: list[tuple[str, str]] = field(default_factory=list)
    # attr_name -> pre-parsed parameter info
    resolve_params: dict[str, _MethodParamInfo] = field(default_factory=dict)
    post_params: dict[str, _MethodParamInfo] = field(default_factory=dict)
    # Special post_default_handler method, if present: (attr_name, param_info).
    # Runs after all post_* methods; return value is ignored.
    post_default_handler: tuple[str, _MethodParamInfo] | None = None
    # Collector prototypes declared via Collector(...) defaults on post_* /
    # post_default_handler params: alias -> the original default instance.
    # We deepcopy this prototype per node at Phase B-1 so any ICollector
    # implementation / Collector subclass keeps its __init__-set config
    # (key_fn, n, dict-valued aggregator, ...) instead of being silently
    # downgraded to a base Collector. (pydantic-resolve #293 equivalent.)
    collector_instances: dict[str, ICollector] = field(default_factory=dict)
    # Whether this class or any descendant needs traversal.
    # None = not yet computed; True/False = computed result.
    should_traverse: bool | None = None
    # Cached scans of ExposeAs / SendTo annotations on this class. Hoisted
    # out of the per-node hot path; lookup once per class, not per instance.
    expose_map: dict[str, str] = field(default_factory=dict)
    send_to_map: dict[str, tuple[str, ...]] = field(default_factory=dict)


# Level-node layout used across Phase A and Phase B.
# Stored as a plain tuple rather than a dataclass: at 1k+ nodes per level,
# dataclass construction is ~2.4x slower than tuple construction, which
# dominated L2 Large resolver-only timings. Named access is preserved via
# loop unpacking at consumer sites: ``for item, meta, ctx, snap in level:``.
#
# Indices:
#   0: item            — _WorkItem(node, parent, ancestor_context, collector_snapshot)
#   1: meta            — _ClassMeta for type(item.node)
#   2: new_ancestor_context — context this node's descendants will inherit
#   3: collector_snapshot   — per-node collector dict, or _EMPTY_SNAPSHOT
_LevelNode = tuple[
    _WorkItem, _ClassMeta, dict[str, Any], dict[str, ICollector],
]


def _analyze_method_params(
    method: Callable, *, include_collectors: bool = False,
) -> _MethodParamInfo:
    """Analyze a method's signature and extract parameter metadata."""
    sig = inspect.signature(method)
    info = _MethodParamInfo()

    for param_name, param in sig.parameters.items():
        if param_name == "self":
            continue
        if param_name == "context":
            info.has_context = True
            continue
        if param_name == "parent":
            info.has_parent = True
            continue
        if param_name == "ancestor_context":
            info.has_ancestor_context = True
            continue

        if param.default is not inspect.Parameter.empty:
            if isinstance(param.default, Depends):
                info.loader_deps.append((param_name, param.default))
            elif include_collectors and isinstance(param.default, ICollector):
                info.collector_deps.append((param_name, param.default))

    return info


RESOLVE_PREFIX = "resolve_"
POST_PREFIX = "post_"
# Reserved method name (not a field-bound post_*): runs after all post_*
# methods at the same node, does not auto-assign — body sets fields manually.
POST_DEFAULT_HANDLER = "post_default_handler"


def _build_class_meta(kls: type) -> _ClassMeta:
    """Build metadata for a class by scanning its methods once."""
    meta = _ClassMeta()

    for attr_name in dir(kls):
        # Reserved name — must be checked BEFORE the post_* prefix branch,
        # otherwise it would be treated as `post_default_handler` → field
        # `default_handler` and auto-assigned.
        if attr_name == POST_DEFAULT_HANDLER:
            attr = getattr(kls, attr_name, None)
            if attr is not None and callable(attr):
                # Detect semantic trap: when the user also declares a field
                # named ``default_handler``, the ``post_<field>`` naming
                # convention implies this method should populate that field.
                # But ``post_default_handler`` is reserved as a finalizer
                # (no auto-binding). Rather than silently discard the return
                # value while the field sits at its default, fail loud so
                # the user picks a clear path:
                #   - rename the method (e.g. ``post_finalize``) and call it
                #     from the field it should populate, OR
                #   - drop the field if it was only meant to receive the
                #     method's return value.
                model_fields = getattr(kls, "model_fields", None)
                if isinstance(model_fields, dict) and "default_handler" in model_fields:
                    raise ValueError(
                        f"Conflict on {kls.__name__}: method "
                        f"`post_default_handler` is a reserved finalizer "
                        f"(runs after all post_*, no field auto-binding), "
                        f"but the class also declares a field "
                        f"`default_handler`. The `post_<field>` naming "
                        f"convention suggests the method should populate "
                        f"the field, which it does not. Either rename the "
                        f"method (e.g. `post_finalize`) and assign the "
                        f"field manually in the body, or remove the "
                        f"`default_handler` field."
                    )
                param_info = _analyze_method_params(attr, include_collectors=True)
                meta.post_default_handler = (attr_name, param_info)
                for _pname, collector in param_info.collector_deps:
                    if collector.alias not in meta.collector_instances:
                        meta.collector_instances[collector.alias] = collector
            continue

        if attr_name.startswith(RESOLVE_PREFIX):
            field_name = attr_name[len(RESOLVE_PREFIX):]
            # Verify it's actually callable (not just an attribute)
            attr = getattr(kls, attr_name, None)
            if attr is not None and callable(attr):
                meta.resolve_methods.append((field_name, attr_name))
                meta.resolve_params[attr_name] = _analyze_method_params(attr)

        elif attr_name.startswith(POST_PREFIX):
            field_name = attr_name[len(POST_PREFIX):]
            attr = getattr(kls, attr_name, None)
            if attr is not None and callable(attr):
                meta.post_methods.append((field_name, attr_name))
                param_info = _analyze_method_params(attr, include_collectors=True)
                meta.post_params[attr_name] = param_info
                # Record collector aliases for _prepare_collectors
                for _pname, collector in param_info.collector_deps:
                    if collector.alias not in meta.collector_instances:
                        meta.collector_instances[collector.alias] = collector

    return meta


# Module-level class metadata cache. Uses WeakKeyDictionary so entries are
# released when the class itself is garbage-collected (e.g. dynamically
# created DefineSubset classes in tests).
_class_meta_cache: weakref.WeakKeyDictionary[type, _ClassMeta] = weakref.WeakKeyDictionary()


def _clear_resolver_caches() -> None:
    """Clear all resolver-level caches. For testing only."""
    _class_meta_cache.clear()


def _get_class_meta(kls: type) -> _ClassMeta:
    """Get or compute class metadata (cached globally)."""
    cached = _class_meta_cache.get(kls)
    if cached is not None:
        return cached
    meta = _build_class_meta(kls)
    # Hoist per-class annotation scans onto meta so the per-node hot path
    # in _init_level_nodes / _collect_send_to_for_node doesn't re-walk
    # model_fields for every instance.
    meta.expose_map = scan_expose_fields(kls)
    meta.send_to_map = scan_send_to_fields(kls)
    _class_meta_cache[kls] = meta
    return meta


def _compute_should_traverse(kls: type, registry: Any = None) -> bool:
    """Determine if a class or any of its BaseModel descendants needs traversal.

    A class needs traversal if it has resolve/post methods, ExposeAs/SendTo
    annotations, Collector parameters, or any descendant that does.
    Handles self-referencing types by using a sentinel value.
    Result is cached in ``_ClassMeta.should_traverse``.

    When ``registry`` (an ErManager) is provided, ALSO checks ErManager-
    registered relationships — so materialized remote types (which have rels
    in the ErManager but not as model_fields) are recognized as traversable.
    """
    meta = _get_class_meta(kls)

    if meta.should_traverse is not None:
        return meta.should_traverse

    # Sentinel: mark as True to handle cycles (self-referencing types).
    meta.should_traverse = True

    # Check own configuration
    if (meta.resolve_methods or meta.post_methods or meta.collector_instances
            or meta.post_default_handler is not None
            or scan_expose_fields(kls) or scan_send_to_fields(kls)):
        return True

    # Check descendants
    for field_info in kls.model_fields.values():
        child_cls = Resolver._do_extract_dto_cls(field_info.annotation)
        if child_cls is not None and _compute_should_traverse(child_cls, registry):
            return True

    # Check ErManager-registered relationships (materialized remote types).
    if registry is not None and hasattr(registry, 'has_entity') and registry.has_entity(kls):
        if hasattr(registry, 'get_relationships') and registry.get_relationships(kls):
            return True

    meta.should_traverse = False
    return False


# ──────────────────────────────────────────────────────────
# Resolver implementation
# ──────────────────────────────────────────────────────────

class Resolver:
    """Model-driven resolver for building use case responses.

    Traverses a tree of Pydantic models (typically DefineSubset DTOs),
    executing resolve_* methods to load related data via DataLoaders
    and post_* methods to compute derived fields.

    Supports cross-layer data flow:
    - ExposeAs: parent fields exposed to descendants via ancestor_context
    - SendTo + Collector: descendant fields aggregated to ancestors
    - Implicit auto-loading: fields matching ORM relationships are loaded automatically

    Args:
        loader_registry: ErManager providing DataLoader instances.
            If None, resolve_* methods must use their own loaders.
        context: Optional context dict accessible via `context` parameter.
        loader_instances: Optional dict of pre-created DataLoader instances,
            keyed by class. When a ``resolve_*`` method declares
            ``loader=Loader(Cls)`` and ``Cls`` is a key in this dict, the
            supplied instance is used instead of a Resolver-created fresh
            instance. Supplied instances are stored by reference and are NOT
            cleared between ``resolve()`` calls — the caller owns the
            lifecycle (per-request isolation requires fresh instances per
            request). Does not affect auto-loaded relationship fields: the
            auto-load path uses ErManager exclusively and never consults
            this dict.
    """

    # Class-level caches shared across Resolver instances. Both depend only
    # on type identity (annotation objects / model classes), not on the
    # per-instance registry or context, so sharing is safe and avoids
    # re-computing on every Resolver() construction.
    #
    # Sentinel ``_MISSING`` distinguishes "not yet computed" from cached
    # None / empty-list results (issue #77 B4).
    _dto_cls_cache: dict[Any, Any] = {}
    _traversable_fields_cache: dict[type, Any] = {}

    def __init__(
        self,
        loader_registry: Any = None,
        context: dict[str, Any] | None = None,
        loader_instances: dict[type[DataLoader], DataLoader] | None = None,
    ):
        self._registry = loader_registry
        # Validate context up-front so misuse fails at construction, not as a
        # confusing AttributeError / KeyError later. None and a non-empty dict
        # are the only valid shapes — empty dict is almost always a bug
        # (pydantic-resolve #291 equivalent).
        if context is not None:
            if not isinstance(context, dict):
                raise TypeError(
                    f'context must be a dict, got {type(context).__name__}.'
                )
            if not context:
                raise ValueError(
                    'context must be a non-empty dict, or None/omitted if no '
                    'context is needed.'
                )
        self._context = context or {}
        # Per-node collector instances keyed by id(node). Safe because every
        # node is held alive by its _LevelNode entry across the levels list
        # for the whole traversal, and Phase B-2 pops entries level-by-level
        # before any node can be GC'd. Do NOT use this map outside the
        # Phase A → Phase B window.
        self._node_collectors: dict[int, dict[str, ICollector]] = {}
        # Loader instance cache for Depends-based loaders (Resolver-created).
        self._loader_cache: dict[Any, DataLoader] = {}
        # Caller-supplied loader instances (from ``loader_instances``). Stored
        # by reference, validated at construction, NOT cleared between
        # ``resolve()`` calls — caller owns the lifecycle. Consulted by
        # ``_get_or_create_loader`` before the Resolver-created cache.
        if loader_instances:
            self._validate_loader_instances(loader_instances)
            self._loader_instances: dict[type[DataLoader], DataLoader] = loader_instances
        else:
            self._loader_instances = {}
        # Auto-load plan cache: DTO class → auto-load specs (per Resolver,
        # avoids id(registry) reuse issues across ErManager lifetimes)
        self._auto_load_cache: dict[type, list] = {}
        # Reentrancy / concurrent-call guard. Per-call mutable state lives on
        # self (_node_collectors, _loader_cache, levels list), so two overlapping
        # resolve() calls on the same instance would clobber each other and
        # surface as a cryptic KeyError. Detect and raise clearly instead.
        self._in_resolve: bool = False

    @staticmethod
    def _validate_loader_instances(loader_instances: dict[Any, Any]) -> None:
        """Validate every (key, value) pair in ``loader_instances``.

        Each key MUST be a ``DataLoader`` subclass; each value MUST be an
        instance of its key class. Raises ``TypeError`` so misuse fails fast
        at construction — never reaches the traversal loop.
        """
        for cls, instance in loader_instances.items():
            if not isinstance(cls, type) or not issubclass(cls, DataLoader):
                raise TypeError(
                    f"loader_instances key {cls!r} must be a subclass of "
                    f"aiodataloader.DataLoader"
                )
            if not isinstance(instance, cls):
                raise TypeError(
                    f"loader_instances[{cls.__name__}] must be an instance of "
                    f"{cls.__name__}, got {type(instance).__name__}"
                )

    def _resolve_source(self, node_type: type) -> Any:
        """FR-017 unified source-resolution.

        Find the source class for a ``node_type``, then let the caller look
        up its relationships / loaders. Source type (SQLModel vs BaseModel)
        is irrelevant to that goal. Two strategies:

        1. DefineSubset DTO → ``get_subset_source`` returns its source.
        2. Plain BaseModel root registered via ``add_virtual_entities`` →
           fallback: the ``node_type`` itself is in ``_registry`` as its
           own source.

        Returns ``None`` when neither strategy matches AND ``node_type``
        declares no ``__relationships__`` (no auto-load expected, no error).
        Raises ``RuntimeError`` when ``node_type`` declares
        ``__relationships__`` but is not registered in any ErManager —
        spec Edge Case B requires a clear error pointing at the
        registration API rather than silent skip.
        """
        from nexusx.relationship import get_custom_relationships
        from nexusx.subset import get_subset_source

        source = get_subset_source(node_type)
        if source is None and self._registry is not None:
            if self._registry.has_entity(node_type):
                source = node_type
            elif get_custom_relationships(node_type):
                raise RuntimeError(
                    f"{node_type.__name__} declares __relationships__ but is "
                    f"not registered with ErManager. Call "
                    f"er.add_virtual_entities([{node_type.__name__}]) before "
                    f"er.create_resolver()."
                )
        return source

    def _get_loader(
        self,
        node: Any,
        loader_name: str,
        type_key: frozenset[str] | None = None,
    ) -> DataLoader | None:
        """Get a DataLoader by name from the registry.

        DefineSubset DTOs resolve loaders within their source entity first,
        avoiding collisions when multiple entities share the same relationship
        name.
        """
        if self._registry is None:
            return None

        # specs/016 γ-path: a DTO field referencing a member public DTO is wired
        # under its owner DTO + field name in _dto_loaders. Check it FIRST so
        # that, when a β entity relationship of the same name exists (e.g.
        # Product.reviews), a γ DTO field wins for γ resolution. β entity loading
        # does not go through _get_loader, so this never diverts a β load.
        if isinstance(node, BaseModel):
            dto_loader_cls = self._registry.get_dto_loader(type(node), loader_name)
            if dto_loader_cls is not None:
                # γ remote: Paged default (field) + caller context override →
                # merged → per-params split + side-channel into POST body.
                paged_default = getattr(type(node), "__paged_fields__", {}).get(loader_name)
                paged_caller = self._extract_page_params(loader_name)
                merged = self._merge_paged(paged_default, paged_caller)
                # γ DTO fetch primitive (specs/018 US4 / T023): consolidate the
                # per-params loader + page-params side-channel into one place so
                # ``set_dto_page_params`` has a single caller (fetch_dto_subtree).
                from nexusx.federation.remote_loader import fetch_dto_subtree

                return fetch_dto_subtree(
                    registry=self._registry,
                    dto_loader_cls=dto_loader_cls,
                    params_key=merged.params_key() if merged else None,
                    page_params=merged,
                )

        source_entity = None
        if isinstance(node, BaseModel):
            source_entity = self._resolve_source(type(node))
        if source_entity is not None:
            loader = self._registry.get_loader_for_entity(
                source_entity, loader_name, type_key=type_key,
            )
            if loader is not None:
                return loader
        return self._registry.get_loader_by_name(loader_name, type_key=type_key)

    def _resolve_dep(self, node: Any, dep: Depends) -> DataLoader | None:
        """Resolve a Depends wrapper to a DataLoader instance."""
        dep_val = dep.dependency
        if dep_val is None:
            return None
        if isinstance(dep_val, type) and issubclass(dep_val, DataLoader):
            return self._get_or_create_loader(dep_val)
        if callable(dep_val):
            return self._get_or_create_fn_loader(dep_val)
        if isinstance(dep_val, str):
            # Name-based ``Loader("rel_name")``: resolve through the registry's
            # named lookup. ``_get_loader`` checks γ DTO loaders (specs/016)
            # first, then the source entity's relationships, then the global
            # name index — so a γ DTO field and a β entity relationship of the
            # same name both resolve correctly from a ``Loader("<name>")``.
            return self._get_loader(node, dep_val)
        return None

    def _get_or_create_loader(
        self, loader_cls: type[DataLoader], params_key: tuple | None = None,
    ) -> DataLoader:
        """Get or create a DataLoader instance by class.

        Caller-supplied instances (from ``loader_instances``) win over
        Resolver-created cached instances.

        ``params_key`` opts into per-params split (different page params →
        different instance → different batch), mirroring registry.get_loader.
        """
        if loader_cls in self._loader_instances:
            return self._loader_instances[loader_cls]
        cache_key: tuple = (loader_cls, params_key)
        if cache_key not in self._loader_cache:
            self._loader_cache[cache_key] = loader_cls()
        return self._loader_cache[cache_key]

    def _get_or_create_fn_loader(self, fn: Callable) -> DataLoader:
        """Get or create a cached DataLoader wrapping an async batch function."""
        if fn not in self._loader_cache:
            self._loader_cache[fn] = DataLoader(batch_load_fn=fn)
        return self._loader_cache[fn]

    def _extract_page_params(self, field_name: str) -> Any:
        """Read caller page params from Resolver ``context`` (set by the use
        case method入口 from query args). Per-field dict first
        (``context[field]``), then global (``context``). Returns a Paged
        carrying the caller's override values, else None (→ no override).
        """
        from nexusx.loader.pagination import Paged

        if not self._context:
            return None
        raw = self._context.get(field_name)
        if not isinstance(raw, dict):
            raw = self._context
        limit = raw.get("limit")
        order = raw.get("order")
        direction = raw.get("direction")
        offset = raw.get("offset", 0)
        if limit is None and order is None and direction is None and not offset:
            return None
        return Paged(
            limit=limit, offset=offset, order=order, direction=direction,
        )

    @staticmethod
    def _merge_paged(default: Any, caller: Any) -> Any:
        """Merge a field's Paged default with caller-context override.

        Caller field non-None wins; else the default's value. Both None → None
        (→ full fetch, back-compat). offset 0 is falsy: caller offset=0 falls
        back to the default (first page is the common case).
        """
        from nexusx.loader.pagination import Paged

        if default is None and caller is None:
            return None
        d = default or Paged()
        c = caller or Paged()
        return Paged(
            limit=c.limit if c.limit is not None else d.limit,
            offset=c.offset if c.offset else d.offset,
            order=c.order if c.order is not None else d.order,
            direction=c.direction if c.direction is not None else d.direction,
        )

    @staticmethod
    def _extract_paged_metadata(field_info_or_hint: Any) -> Any:
        """Return the ``Paged`` marker carried on a field, or None.

        Reads two carry-mechanisms (specs/018 US2 / T012):
          1. ``pydantic.FieldInfo.metadata`` — when ``build_response_model`` /
             ``create_model`` consumes ``Annotated[X, Paged(...)]``, pydantic v2
             stashes the metadata in ``FieldInfo.metadata`` (a list).
          2. Raw ``typing.Annotated[X, Paged(...)]`` alias — when the caller
             passes the annotation itself (no FieldInfo wrapper); reads
             ``__metadata__`` via ``get_args``.

        Used by entity-first dynamic model dispatch (US3 will plug it into the
        Resolver's BFS-relocated entity branch): if a field carries ``Paged``
        metadata, dispatch routes through ``page_loader`` (vs. plain loader for
        non-paginated fields).
        """
        from nexusx.loader.pagination import Paged

        metadata = getattr(field_info_or_hint, "metadata", None) or []
        for meta in metadata:
            if isinstance(meta, Paged):
                return meta

        annotation = getattr(field_info_or_hint, "annotation", field_info_or_hint)
        if annotation is not None and get_origin(annotation) is typing.Annotated:
            for meta in get_args(annotation)[1:]:
                if isinstance(meta, Paged):
                    return meta
        return None

    def _resolve_paged_for_dynamic_field(
        self,
        field_info: Any,
        field_name: str,
    ) -> Any:
        """Compute the effective ``Paged`` for a dynamic-model field.

        Combines the field's metadata ``Paged`` (set by ``build_response_model``
        from gql args — specs/018 US2 / T010-T011) with the caller-context
        override (gql-level per-field page params coming through the use case
        method context). Field metadata wins per-attribute when set; caller
        context fills the rest. Both None → None (no pagination; the field is
        a plain ``{items, pagination}`` shape served by ``_serialize``'s
        back-compat path, no ``page_loader`` dispatch).

        Plug point for US3 BFS-relocation: the entity-field dispatch branch in
        ``Resolver._bfs_dispatch_entity_fields`` (T016) will call this to decide
        between ``page_loader`` and plain ``loader`` for a dynamic-model field.
        Until US3 lands, exercised by unit tests only.
        """
        paged_default = self._extract_paged_metadata(field_info)
        paged_caller = self._extract_page_params(field_name)
        return self._merge_paged(paged_default, paged_caller)

    # ──────────────────────────────────────────────────────
    # Implicit auto-loading — automatic relationship loading
    # ──────────────────────────────────────────────────────

    def _scan_auto_load_fields(
        self, node: Any, meta: _ClassMeta,
    ) -> list[tuple[str, str, Any, Any]]:
        """Scan fields that should be auto-loaded from relationships.

        A field is auto-loaded when ALL of these conditions are met:
        1. No manual resolve_* method exists for the field
        2. The field is not part of the __subset__ definition (it's an extra field)
        3. The field name matches a registered relationship on the source entity
        4. Either:
           a. The field type is a BaseModel DTO compatible with the relationship's
              target entity, OR
           b. The field type is a scalar (list[int], str, ...) matching a CUSTOM
              Relationship whose raw target is the same primitive type.

        Returns list of (field_name, rel_name, rel_info, field_info).
        """
        if not isinstance(node, BaseModel) or self._registry is None:
            return []

        node_type = type(node)
        cached = self._auto_load_cache.get(node_type)
        if cached is not None:
            return cached

        from nexusx.utils.type_compat import is_compatible_type

        # Unified source resolution (FR-017) — single helper used by both
        # _get_loader and _scan_auto_load_fields. See _resolve_source.
        source_entity = self._resolve_source(node_type)
        if source_entity is None:
            self._auto_load_cache[node_type] = []
            return []

        # Get relationship names from source entity
        entity_rels = self._registry.get_relationships(source_entity)

        # Get subset field names so we can skip them (only extra fields are candidates)
        subset_field_names = set(getattr(node_type, "__subset_fields__", []))

        # Build set of resolve method field names from cached meta
        resolve_field_names = {fname for fname, _ in meta.resolve_methods}

        results = []
        for field_name, field_info in node_type.model_fields.items():
            if field_name in resolve_field_names:
                continue
            if field_name in subset_field_names:
                continue

            # Field name must match a registered relationship
            if field_name not in entity_rels:
                continue

            # Field type must be a BaseModel DTO, or a scalar matching a
            # CUSTOM relationship whose raw target is the same primitive type
            # (e.g. field=list[int] vs Relationship(target=list[int])).
            dto_cls = self._extract_dto_cls(field_info)
            rel_info = entity_rels[field_name]
            # Coalesced rels are resolved within the owning service's nested
            # fetch (β) — they arrive populated on the instance, not loaded
            # per-edge here (see fetch_remote_subtree). Mirrors the executor.
            if rel_info.kind == RelationshipKind.REMOTE_COALESCED:
                continue
            if dto_cls is None:
                if self._is_scalar_rel_field(field_info, rel_info):
                    results.append((field_name, field_name, rel_info, field_info))
                continue

            # DTO must be compatible with the relationship's target entity
            if is_compatible_type(dto_cls, rel_info.target_entity):
                results.append((field_name, field_name, rel_info, field_info))

        # Also auto-load ErManager rels NOT in model_fields — but ONLY when
        # the node IS the source entity (materialized types, not DefineSubset
        # DTOs whose source is a different entity). For materialized types the
        # class has no model_field for its rels (they're in the ErManager only),
        # so the Resolver must discover them here.
        if source_entity is node_type:
            for rel_name, rel_info in entity_rels.items():
                if rel_info.kind == RelationshipKind.REMOTE_COALESCED:
                    continue  # populated by the parent fetch's nested selection
                if rel_name in node_type.model_fields:
                    continue  # already handled above
                if rel_name in resolve_field_names or rel_name in subset_field_names:
                    continue
                # field_info=None signals: construct target_entity instances directly.
                results.append((rel_name, rel_name, rel_info, None))

        self._auto_load_cache[node_type] = results
        return results

    def _extract_dto_cls(self, field_info: Any) -> type[BaseModel] | None:
        """Extract the DTO class from a field annotation.

        Handles Optional, list, Annotated wrappers.
        Results are cached by annotation object on the class — sentinel
        ``_MISSING`` distinguishes "not computed" from "computed to None".
        """
        anno = field_info.annotation
        cached = self._dto_cls_cache.get(anno, _MISSING)
        if cached is not _MISSING:
            return cached

        result = self._do_extract_dto_cls(anno)
        self._dto_cls_cache[anno] = result
        return result

    @staticmethod
    def _do_extract_dto_cls(anno: Any) -> type[BaseModel] | None:
        """Actual type extraction logic (uncached).

        Returns None for string annotations (from ``__future__ import
        annotations`` or unresolved forward refs) — callers must invoke
        ``model_rebuild()`` before traversal if such fields need to be
        followed. Returning None here is a silent degradation path, not
        a crash, so users who forget to rebuild simply see missing
        descendants rather than a confusing error.
        """
        extracted = Resolver._extract_dto_cls_and_cardinality(anno)
        return extracted[0] if extracted is not None else None

    @staticmethod
    def _extract_dto_cls_and_cardinality(
        anno: Any,
    ) -> tuple[type[BaseModel], bool] | None:
        """Extract ``(dto_cls, is_list)`` from an annotation.

        Handles ``Annotated[X, ...]``, ``Optional[X]`` / ``X | None``
        (PEP 604 unions), and ``list[X]`` wrappers. ``is_list`` is True
        only when the unwrapped annotation was syntactically a list
        (``list[X]``, ``list[X] | None``); single-model fields always
        return ``False``.

        Returns ``None`` when the annotation does not refer to a single
        BaseModel subclass (e.g. scalars, bare ``None``, unions of two
        non-None types).
        """
        if isinstance(anno, str):
            return None

        # Unwrap Annotated[X, ...] → X
        origin = get_origin(anno)
        if origin is typing.Annotated:
            anno = get_args(anno)[0]
            origin = get_origin(anno)

        # Unwrap Optional / Union[X, None] → X when exactly one non-None arm.
        # ``origin is not list`` guards against misinterpreting ``list[X]``'s
        # own __args__ as a union.
        args = get_args(anno)
        if args and origin is not list:
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1 and len(args) > 1:
                anno = non_none[0]
                origin = get_origin(anno)

        # Unwrap list[X] → X, remember cardinality
        is_list = False
        if origin is list:
            is_list = True
            args = get_args(anno)
            if args:
                anno = args[0]

        if isinstance(anno, type) and issubclass(anno, BaseModel):
            return anno, is_list
        return None

    @staticmethod
    def _is_scalar_rel_field(field_info: Any, rel_info: Any) -> bool:
        """True if a non-DTO scalar field still matches a custom relationship.

        Used when the field type is a primitive (e.g. ``list[int]``, ``str``)
        rather than a BaseModel DTO, but the relationship is a CUSTOM
        ``Relationship`` whose raw ``target`` equals that primitive type.
        """
        from nexusx.utils.type_compat import is_compatible_type

        if getattr(rel_info, "direction", "") != "CUSTOM":
            return False
        raw_target = (
            list[rel_info.target_entity] if rel_info.is_list else rel_info.target_entity
        )
        return is_compatible_type(field_info.annotation, raw_target)

    # Cache: dto_cls -> pre-built subset_fields tuple (or None for model_validate path)
    _dto_fields_cache: dict[type, tuple[str, ...] | None] = {}

    @classmethod
    def _orm_to_dto(cls, orm_instance: Any, dto_cls: type[BaseModel]) -> BaseModel:
        """Project an arbitrary instance onto a DefineSubset DTO.

        Called from ``_batch_auto_load`` when a relationship loader returns
        something that is NOT already an instance of the field's declared
        DTO type — typically a SQLModel row, but the function is type-
        agnostic (``getattr`` over ``__subset_fields__``) and handles any
        source whose attributes line up with the DTO's subset fields. When
        the loader already returns ``dto_cls`` instances, the caller skips
        this function via the ``isinstance(r, dto_cls)`` short-circuit in
        ``_batch_auto_load``.

        The historical ``_orm_to_dto`` name comes from the SQLModel-row use
        case; a rename to ``_source_to_dto`` is tracked as optional polish
        in research.md R8 and is intentionally NOT done here.
        """
        subset_fields = cls._dto_fields_cache.get(dto_cls)
        if subset_fields is None and dto_cls not in cls._dto_fields_cache:
            subset_fields = getattr(dto_cls, "__subset_fields__", None)
            cls._dto_fields_cache[dto_cls] = subset_fields

        if subset_fields is None:
            return dto_cls.model_validate(orm_instance)

        # Pass values through as-is — including None. Filtering None here
        # would silently replace DB NULLs with the DTO field's declared
        # default (Field(default=...) on the source entity), making
        # "row has NULL" indistinguishable from "row has explicit default"
        # in API responses. If the DTO field type doesn't allow None,
        # Pydantic validation will raise — which is the correct signal
        # that the schema needs Optional[...].
        kwargs = {f: getattr(orm_instance, f, None) for f in subset_fields}
        # Pass through nested relationship fields declared on the DTO but not in
        # __subset_fields__ (e.g. ``comments: list[CommentDTO]`` on a ReviewDTO
        # whose __subset__ is Review's scalars). Only for materialized (β-fetch)
        # sources — those carry the nested data already. For SQLModel sources the
        # Resolver loads each relationship via its own loader, so touching a
        # nested attr here would trigger a detached lazy-load.
        from sqlmodel import SQLModel

        if not isinstance(orm_instance, SQLModel):
            for fname, fi in dto_cls.model_fields.items():
                if fname in subset_fields or fname in kwargs:
                    continue
                extracted = cls._extract_dto_cls_and_cardinality(fi.annotation)
                if extracted is None:
                    continue
                nested_dto, nested_is_list = extracted
                raw = getattr(orm_instance, fname, None)
                if raw is None:
                    kwargs[fname] = [] if nested_is_list else None
                elif nested_is_list:
                    kwargs[fname] = [cls._orm_to_dto(item, nested_dto) for item in raw]
                else:
                    kwargs[fname] = cls._orm_to_dto(raw, nested_dto)
        # Pydantic can leave DTO classes with unresolved forward refs when
        # a DTO references another DTO that wasn't yet defined at class
        # creation time (e.g. cross-module cycles, lazy imports). The first
        # instantiation attempt raises PydanticUserError / NameError; we
        # rebuild with a namespace containing every registered DTO and
        # retry once. If the rebuild also fails the exception propagates —
        # genuine schema bugs (typos, missing imports) are NOT masked.
        try:
            return dto_cls(**kwargs)
        except (PydanticUserError, NameError):
            import sys

            from nexusx.subset import _subset_registry

            module = sys.modules.get(dto_cls.__module__, None)
            ns = dict(vars(module)) if module else {}
            for dto_class in _subset_registry:
                ns[dto_class.__name__] = dto_class
            dto_cls.model_rebuild(_types_namespace=ns)
            return dto_cls(**kwargs)

    # ──────────────────────────────────────────────────────
    # Method execution with cached parameter info
    # ──────────────────────────────────────────────────────

    def _build_injected_params(
        self,
        node: Any,
        param_info: _MethodParamInfo,
        *,
        parent: Any = None,
        ancestor_context: dict[str, Any] | None = None,
        inject_collectors: bool = False,
    ) -> dict[str, Any]:
        """Build the kwargs dict for a resolve_* / post_* / post_default_handler
        method, given its pre-parsed parameter info.

        ``inject_collectors`` enables Collector parameter injection (only
        post_* / post_default_handler declare Collector defaults; resolve_*
        never does).

        Hoisted out of ``_execute_resolve_method`` and ``_execute_post_method``
        to consolidate the ~12 duplicated lines of context / parent /
        ancestor_context / loader injection (issue #77 B1).
        """
        params: dict[str, Any] = {}

        if param_info.has_context:
            params["context"] = self._context
        if param_info.has_parent:
            params["parent"] = parent
        if param_info.has_ancestor_context:
            params["ancestor_context"] = ancestor_context if ancestor_context is not None else {}

        if inject_collectors:
            for param_name, collector_default in param_info.collector_deps:
                node_cols = self._node_collectors.get(id(node), {})
                collector = node_cols.get(collector_default.alias)
                if collector is not None:
                    params[param_name] = collector

        for param_name, dep in param_info.loader_deps:
            loader = self._resolve_dep(node, dep)
            if loader is not None:
                params[param_name] = loader

        return params

    async def _execute_resolve_method(
        self,
        node: Any,
        method: Callable,
        param_info: _MethodParamInfo,
        *,
        parent: Any = None,
        ancestor_context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a resolve_* method with parameter injection using cached info."""
        params = self._build_injected_params(
            node, param_info, parent=parent, ancestor_context=ancestor_context,
        )
        result = method(**params)
        # Single await is enough: resolve_* methods are either sync or
        # `async def` returning the value directly. The historical `while`
        # loop was a defensive no-op for the (unsupported) case of methods
        # returning a coroutine that itself returns a coroutine.
        if inspect.isawaitable(result):
            result = await result
        return result

    async def _execute_post_method(
        self,
        node: Any,
        method: Callable,
        param_info: _MethodParamInfo,
        *,
        parent: Any = None,
        ancestor_context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a post_* method with parameter injection using cached info."""
        params = self._build_injected_params(
            node, param_info,
            parent=parent, ancestor_context=ancestor_context,
            inject_collectors=True,
        )
        result = method(**params)
        if inspect.isawaitable(result):
            result = await result
        return result

    # ──────────────────────────────────────────────────────
    # BFS traversal
    # ──────────────────────────────────────────────────────

    async def _traverse(self, root: T) -> T:
        """Two-phase iterative traversal.

        Phase A (top-down): run resolve_* + auto-load level-by-level, setattr
        immediately, collect children for the next level. No recursion — uses
        an explicit ``levels`` list, so tree depth is bounded by heap, not by
        ``sys.getrecursionlimit()``.

        Phase B-1 (top-down): instantiate per-node Collectors and propagate
        the collector snapshot to descendants.

        Phase B-2 (bottom-up): run all post_* at a level concurrently via
        ``asyncio.gather``, then post_default_handler serially per node, then
        collect SendTo values into ancestor Collectors, then cleanup.

        Replaces the recursive ``_process_level``. The split separates
        resolve-time concerns (top-down data loading) from post-time concerns
        (bottom-up aggregation) and lets Phase B-2 maximize post_* concurrency.
        """
        if isinstance(root, (list, tuple)):
            items = [
                _WorkItem(n, parent=None, ancestor_context={}, collector_snapshot={})
                for n in root
                if isinstance(n, BaseModel)
            ]
        elif isinstance(root, BaseModel):
            items = [_WorkItem(root, parent=None, ancestor_context={}, collector_snapshot={})]
        else:
            return root

        if not items:
            return root

        # Build level 0 inline (rather than via _init_level_nodes) to avoid
        # 1k+ function calls on large root lists. Tuple layout matches _LevelNode.
        level_0: list[_LevelNode] = []
        for item in items:
            meta = _get_class_meta(type(item.node))
            if meta.expose_map:
                new_ctx = dict(item.ancestor_context)
                for field_name, alias in meta.expose_map.items():
                    new_ctx[alias] = getattr(item.node, field_name, None)
            else:
                new_ctx = item.ancestor_context
            level_0.append((item, meta, new_ctx, _EMPTY_SNAPSHOT))

        levels: list[list[_LevelNode]] = [level_0]
        node_id_to_ln: dict[int, _LevelNode] = {
            id(ln[0].node): ln for ln in level_0
        }

        await self._phase_a_resolve(levels, node_id_to_ln)
        self._phase_b_prepare_collectors(levels, node_id_to_ln)
        await self._phase_b_execute_posts(levels)

        return root

    def _init_level_nodes(self, items: list[_WorkItem]) -> list[_LevelNode]:
        """Build _LevelNode wrappers for a level's work items.

        Computes the new_ancestor_context (this node's ExposeAs values merged
        into the inherited context). Collector snapshots stay empty here —
        Phase B-1 fills them in before any post_*/SendTo needs them.
        """
        level: list[_LevelNode] = []
        for item in items:
            meta = _get_class_meta(type(item.node))

            if meta.expose_map:
                new_ctx = dict(item.ancestor_context)
                for field_name, alias in meta.expose_map.items():
                    new_ctx[alias] = getattr(item.node, field_name, None)
            else:
                new_ctx = item.ancestor_context

            level.append((item, meta, new_ctx, _EMPTY_SNAPSHOT))
        return level

    async def _phase_a_resolve(
        self,
        levels: list[list[_LevelNode]],
        node_id_to_ln: dict[int, _LevelNode],
    ) -> None:
        """Phase A: top-down iterative resolve + auto-load.

        Per level:
          1. Collect resolve_* jobs across all nodes (gather for concurrency).
          2. ``asyncio.gather`` all resolve_* coros; each does immediate
             ``object.__setattr__`` so descendants see the new value.
          3. Batch auto-load relationships (DataLoader.load_many per rel).
          4. Build next level: children from resolve results, auto-load results,
             AND pre-existing object fields — skipping any field already loaded
             by steps 2/3 via ``loaded_field_keys`` (explicit dedup, replaces
             the old "field still None" implicit dedup).
        """
        while True:
            current = levels[-1]

            # 1. Collect resolve jobs
            resolve_jobs: list[tuple[_LevelNode, str, str]] = []
            for ln in current:
                _item, meta, _ctx, _snap = ln
                for field_name, attr_name in meta.resolve_methods:
                    resolve_jobs.append((ln, field_name, attr_name))

            # 2. Execute resolves concurrently + immediate setattr
            if resolve_jobs:
                resolve_outputs = await asyncio.gather(
                    *(
                        self._do_resolve(ln, field_name, attr_name)
                        for ln, field_name, attr_name in resolve_jobs
                    )
                )
            else:
                resolve_outputs = []

            # Track resolve_*-loaded fields for dedup in existing-fields scan
            loaded_field_keys: set[tuple[int, str]] = set()
            for ln, field_name, _ in resolve_jobs:
                loaded_field_keys.add((id(ln[0].node), field_name))

            # 3. Batch auto-load (immediate setattr, returns children + keys)
            auto_children: list[_WorkItem] = []
            auto_keys = await self._batch_auto_load(current, auto_children)
            loaded_field_keys.update(auto_keys)

            # 4. Build next level
            next_items: list[_WorkItem] = []

            # 4a. Children from resolve_* results
            for (ln, _field_name, _attr_name), result in zip(
                resolve_jobs, resolve_outputs, strict=True,
            ):
                _item, _meta, new_ctx, _snap = ln
                parent_node = ln[0].node
                if isinstance(result, (list, tuple)):
                    for r in result:
                        if isinstance(r, BaseModel):
                            next_items.append(_WorkItem(
                                r, parent_node, new_ctx, {},
                            ))
                elif isinstance(result, BaseModel):
                    next_items.append(_WorkItem(
                        result, parent_node, new_ctx, {},
                    ))

            # 4b. Children from auto-load
            next_items.extend(auto_children)

            # 4c. Children from pre-existing object fields (skip loaded)
            for ln in current:
                item, _meta, new_ctx, _snap = ln
                node = item.node
                node_id = id(node)
                for field_name, is_list in self._get_traversable_fields(type(node)):
                    if (node_id, field_name) in loaded_field_keys:
                        continue
                    val = getattr(node, field_name, None)
                    if val is None:
                        continue
                    if is_list:
                        for c in val:
                            next_items.append(_WorkItem(
                                c, node, new_ctx, {},
                            ))
                    else:
                        next_items.append(_WorkItem(
                            val, node, new_ctx, {},
                        ))

            if not next_items:
                break

            next_level = self._init_level_nodes(next_items)
            for ln in next_level:
                node_id_to_ln[id(ln[0].node)] = ln
            levels.append(next_level)

    async def _do_resolve(
        self,
        ln: _LevelNode,
        field_name: str,
        attr_name: str,
    ) -> Any:
        """Execute one resolve_* method and immediately write the result.

        Immediate setattr (vs the old deferred setattr that waited until after
        the recursion returned) lets Phase A discard the ``resolve_results``
        list and avoids the "field still None" implicit dedup. The cost is that
        the existing-fields scan in ``_phase_a_resolve`` must explicitly skip
        resolve_*-loaded fields via ``loaded_field_keys``.

        ``object.__setattr__`` bypasses Pydantic's validation overhead — the
        value type was already chosen by the user writing the resolve_* method.
        """
        item, meta, _ctx, _snap = ln
        node = item.node
        method = getattr(node, attr_name)
        param_info = meta.resolve_params[attr_name]
        result = await self._execute_resolve_method(
            node, method, param_info,
            parent=item.parent, ancestor_context=item.ancestor_context,
        )
        object.__setattr__(node, field_name, result)
        return result

    def _get_traversable_fields(
        self, node_type: type,
    ) -> list[tuple[str, bool]]:
        """Cache per-type: which fields can yield traversable children.

        Returns list of (field_name, is_list). Empty list means the type was
        already scanned and has no traversable fields — caller iterates
        harmlessly. Sentinel ``_MISSING`` (issue #77 B4) distinguishes
        "not computed" from "computed to empty".

        Shares the typing-unwrap logic with auto-load (``_extract_dto_cls``)
        so ``Optional[X]``, ``X | None``, ``list[X] | None``, and
        ``Annotated[X, ...]`` all traverse consistently. Issue #77 review
        flagged the prior inline check that only recognized bare ``list[X]``
        and bare ``X``.
        """
        cached = self._traversable_fields_cache.get(node_type, _MISSING)
        if cached is not _MISSING:
            return cached

        result: list[tuple[str, bool]] = []
        for field_name, field_info in node_type.model_fields.items():
            extracted = Resolver._extract_dto_cls_and_cardinality(
                field_info.annotation,
            )
            if extracted is None:
                continue
            dto_cls, is_list = extracted
            if _compute_should_traverse(dto_cls, self._registry):
                result.append((field_name, is_list))

        # Also include ErManager-registered relationships that are NOT
        # model_fields — but ONLY for materialized types (source == node_type),
        # not DefineSubset DTOs whose source is a different entity.
        if self._registry is not None:
            source = self._resolve_source(node_type)
            if source is not None and source is node_type:
                for rel_name, rel_info in self._registry.get_relationships(source).items():
                    if rel_name not in node_type.model_fields:
                        result.append((rel_name, rel_info.is_list))

        self._traversable_fields_cache[node_type] = result
        return result

    def _build_nested_selection(
        self,
        target_cls: type[BaseModel],
        dto_cls: type[BaseModel] | None = None,
        visited: set[type] | None = None,
    ) -> Any:
        """Build a nested ``FieldSelection`` for a federated sub-tree rooted at
        ``target_cls`` — the shape ``fetch_remote_subtree`` sends to the owning
        service so the member resolves the whole sub-tree (its local edges +
        further cross-service hops) in one nested gql.

        ``dto_cls`` (when the field is DTO-typed) drives the projection — only
        its declared fields are requested; otherwise the materialized
        ``target_cls``'s full reachable graph is used. ``visited`` guards cycles
        (re-entry → scalar-only leaf, preserving the field name without looping).
        """
        from nexusx.query_parser import FieldSelection

        if visited is None:
            visited = set()
        shape_cls = dto_cls if dto_cls is not None else target_cls
        sub_fields: dict[str, Any] = {}

        # Look up relationships on target_cls (this Resolver's registered type,
        # i.e. rel_info.target_entity) — NOT the DTO's subset source. When
        # multiple services federate in one process, a DTO resolved at an earlier
        # federate references that federate's materialized copy; the Resolver
        # must use its OWN registry's type so relationship lookups succeed.
        entity_rels = (
            self._registry.get_relationships(target_cls) if self._registry else {}
        )

        recurse = shape_cls not in visited
        if recurse:
            visited.add(shape_cls)

        for fname, fi in shape_cls.model_fields.items():
            rel_info = entity_rels.get(fname)
            if rel_info is None or not recurse:
                # Scalar leaf (or cycle stop — keep the name, don't descend).
                sub_fields[fname] = FieldSelection(name=fname)
                continue
            sub_fields[fname] = self._build_nested_selection(
                rel_info.target_entity,
                dto_cls=self._extract_dto_cls(fi),
                visited=visited,
            )

        # Materialized type with no DTO: also include ErManager rels not present
        # as model_fields, so the member resolves those edges too.
        if recurse and dto_cls is None:
            for rname, rinfo in entity_rels.items():
                if rname in shape_cls.model_fields:
                    continue
                sub_fields[rname] = self._build_nested_selection(
                    rinfo.target_entity, dto_cls=None, visited=visited,
                )

        return FieldSelection(name=target_cls.__name__, sub_fields=sub_fields)

    def _phase_b_prepare_collectors(
        self,
        levels: list[list[_LevelNode]],
        node_id_to_ln: dict[int, _LevelNode],
    ) -> None:
        """Phase B-1: top-down collector instantiation + snapshot propagation.

        For each node, in BFS order (root → leaves):
          1. Look up the parent's already-built collector_snapshot.
          2. Instantiate this node's own Collectors (declared via Collector(...)
             defaults on post_* / post_default_handler params).
          3. Register own Collectors in ``_node_collectors`` for injection.
          4. Build new level tuple with the merged snapshot so children
             inherit the right Collector instances by reference.

        Must run AFTER Phase A (so the tree is fully populated) and BEFORE
        Phase B-2 (so post_default_handler / SendTo can find Collectors).

        Tuples are immutable, so any snapshot change rebuilds the level entry.
        For trees where no class declares Collectors (the common L1/L2 case)
        every snapshot stays as ``_EMPTY_SNAPSHOT``, the fast path skips the
        rebuild, and the entire phase is essentially free.
        """
        for depth in range(len(levels)):
            old_level = levels[depth]
            new_level: list[_LevelNode] | None = None  # lazily built on first change

            for idx, ln in enumerate(old_level):
                item, meta, ctx, old_snap = ln

                if not meta.collector_instances:
                    # No own collectors — inherit parent snapshot by reference.
                    parent_ln = (
                        node_id_to_ln.get(id(item.parent))
                        if item.parent is not None else None
                    )
                    new_snap = parent_ln[3] if parent_ln is not None else _EMPTY_SNAPSHOT
                else:
                    parent_ln = (
                        node_id_to_ln.get(id(item.parent))
                        if item.parent is not None else None
                    )
                    parent_snap = parent_ln[3] if parent_ln is not None else _EMPTY_SNAPSHOT

                    # Deepcopy the user-declared Collector prototype so any
                    # ICollector implementation (or Collector subclass with
                    # extra __init__ config) survives per-node instantiation.
                    # Hard-coding Collector(alias=..., flat=...) here would
                    # silently downgrade subclasses — pydantic-resolve #293.
                    own: dict[str, ICollector] = {
                        alias: copy.deepcopy(prototype)
                        for alias, prototype in meta.collector_instances.items()
                    }
                    self._node_collectors[id(item.node)] = own
                    if parent_snap:
                        new_snap = dict(parent_snap)
                        new_snap.update(own)
                    else:
                        new_snap = own

                if new_snap is old_snap:
                    # No change for this node — but if a previous node in this
                    # level already triggered a rebuild, copy ln forward into
                    # new_level so positions stay aligned.
                    if new_level is not None:
                        new_level.append(ln)
                    continue

                # First change in this level → lazily copy everything seen so far.
                if new_level is None:
                    new_level = list(old_level[:idx])
                new_ln = (item, meta, ctx, new_snap)
                new_level.append(new_ln)
                node_id_to_ln[id(item.node)] = new_ln

            if new_level is not None:
                levels[depth] = new_level

    async def _phase_b_execute_posts(self, levels: list[list[_LevelNode]]) -> None:
        """Phase B-2: bottom-up post execution + SendTo + cleanup.

        For each level from leaves to root:
          1. Collect all post_* coros across ALL nodes at this level into one
             gather — same-level posts run concurrently (issue #77 A1).
          2. setattr each post_* result.
          3. Run post_default_handler serially per node (must read post_* fields).
          4. Collect SendTo values from this level's nodes into ancestor
             Collectors (bottom-up so descendant values reach ancestors).
          5. Cleanup per-node Collectors (free ``_node_collectors`` entries).

        Concurrent execution is safe because users do not rely on inter-post_*
        ordering: ``meta.post_methods`` comes from ``dir()`` (alphabetical),
        which was never a contract.
        """
        for depth in range(len(levels) - 1, -1, -1):
            level = levels[depth]

            # 1. Collect all post_* coros at this level (across all nodes).
            # Single-pass also tracks whether any node declares SendTo or
            # Collectors — lets steps 4/5 skip the per-node loop entirely on
            # plain-data levels (the common L1/L2 case). At 1k+ nodes the
            # saved function calls dominate the resolver-only timings.
            post_jobs: list[tuple[_LevelNode, str]] = []
            post_coros: list[Any] = []
            has_async_post = False
            level_has_send_to = False
            level_has_collectors = False
            level_has_default_handler = False
            for ln in level:
                item, meta, _ctx, _snap = ln
                if meta.post_methods:
                    node = item.node
                    for field_name, attr_name in meta.post_methods:
                        method = getattr(node, attr_name)
                        if inspect.iscoroutinefunction(method):
                            has_async_post = True
                        param_info = meta.post_params[attr_name]
                        post_coros.append(
                            self._execute_post_method(
                                node, method, param_info,
                                parent=item.parent,
                                ancestor_context=item.ancestor_context,
                            )
                        )
                        post_jobs.append((ln, field_name))
                if meta.send_to_map:
                    level_has_send_to = True
                if meta.collector_instances:
                    level_has_collectors = True
                if meta.post_default_handler is not None:
                    level_has_default_handler = True

            # 2. Run + setattr results
            #
            # Fast path: when every post_* at this level is sync, awaiting the
            # coros serially is much cheaper than asyncio.gather — gather pays
            # ~30-50μs per Task creation/scheduling, which dominates when the
            # post bodies themselves are O(1) (e.g. ``return self.a + self.b``).
            #
            # Slow path: if ANY post_* is async, gather so the awaits overlap
            # (issue #77 A1).
            if post_coros:
                if has_async_post:
                    post_results = await asyncio.gather(*post_coros)
                else:
                    post_results = [await coro for coro in post_coros]
                for (post_ln, field_name), result in zip(
                    post_jobs, post_results, strict=True,
                ):
                    object.__setattr__(post_ln[0].node, field_name, result)

            # 3. post_default_handler per node, serially
            if level_has_default_handler:
                for ln in level:
                    item, meta, _ctx, _snap = ln
                    if meta.post_default_handler is None:
                        continue
                    attr_name, param_info = meta.post_default_handler
                    node = item.node
                    method = getattr(node, attr_name)
                    # Return value intentionally ignored — handler sets fields itself.
                    await self._execute_post_method(
                        node, method, param_info,
                        parent=item.parent,
                        ancestor_context=item.ancestor_context,
                    )

            # 4. SendTo → ancestor Collectors (skip per-node loop when no class
            # at this level declares any SendTo).
            if level_has_send_to:
                for ln in level:
                    item, meta, _ctx, snap = ln
                    if not meta.send_to_map:
                        continue
                    node = item.node
                    for field_name, collector_names in meta.send_to_map.items():
                        value = getattr(node, field_name, None)
                        if value is None:
                            continue
                        for name in collector_names:
                            collector = snap.get(name)
                            if collector is not None:
                                collector.add(value)

            # 5. Cleanup per-node Collectors (skip when no class declares any).
            if level_has_collectors:
                for ln in level:
                    item, meta, _ctx, _snap = ln
                    if meta.collector_instances:
                        self._node_collectors.pop(id(item.node), None)

    async def _batch_auto_load(
        self,
        level: list[_LevelNode],
        auto_children: list[_WorkItem],
    ) -> set[tuple[int, str]]:
        """Batch auto-load relationships for all nodes at a level.

        Groups nodes by relationship, collects all FK values, uses load_many
        for batched loading, then ORM→DTO conversion. Appends child WorkItems
        into *auto_children* (caller merges them into next_items).

        Returns set of (id(node), field_name) pairs that were auto-loaded,
        so ``_phase_a_resolve`` can skip them in the existing-fields scan
        via ``loaded_field_keys``.
        """
        if self._registry is None:
            return set()

        from nexusx.loader.query_meta import (
            generate_query_meta_from_dto,
            generate_type_key_from_dto,
            set_query_meta,
        )

        auto_loaded: set[tuple[int, str]] = set()

        # Collect auto-load specs per node, group by (node_type, rel_name)
        groups: dict[
            tuple[type, str], list[tuple[int, Any, str, Any, Any, type[BaseModel] | None]]
        ] = {}

        for idx, ln in enumerate(level):
            item, meta, _new_ctx, _snap = ln
            node = item.node
            auto_load_entries = self._scan_auto_load_fields(node, meta)
            if not auto_load_entries:
                continue

            for field_name, rel_name, rel_info, field_info in auto_load_entries:
                dto_cls = self._extract_dto_cls(field_info) if field_info is not None else None
                groups.setdefault((type(node), rel_name), []).append(
                    (idx, node, field_name, rel_info, field_info, dto_cls)
                )

        if not groups:
            return auto_loaded

        # Process each relationship group
        for (_node_type, rel_name), entries in groups.items():
            first_node = entries[0][1]
            first_dto = entries[0][5]
            first_rel = entries[0][3]

            is_custom = getattr(first_rel, "direction", "") == "CUSTOM"
            is_list = first_rel.is_list
            fk_field = first_rel.fk_field
            # A non-coalesced service-boundary rel: fetch the whole sub-tree via
            # the shared β primitive (one nested gql to the owning service; the
            # member resolves its local edges + further cross-service hops).
            is_remote_entry = first_rel.kind in (
                RelationshipKind.REMOTE_PAGED, RelationshipKind.REMOTE_PLAIN
            )

            # Collect FK/PK values + valid entries (shared by both paths).
            keys: list[Any] = []
            valid_entries: list[tuple[int, Any, str, type[BaseModel] | None]] = []
            for idx, node, field_name, _rel_info, _field_info, dto_cls in entries:
                key = getattr(node, fk_field, None)
                if key is not None:
                    keys.append(key)
                    valid_entries.append((idx, node, field_name, dto_cls))

            if not valid_entries:
                continue

            if is_remote_entry:
                from nexusx.federation.remote_loader import fetch_remote_subtree

                selection = self._build_nested_selection(
                    target_cls=first_rel.target_entity, dto_cls=first_dto,
                )
                results = await fetch_remote_subtree(
                    registry=self._registry,
                    rel_info=first_rel,
                    parents=[ve[1] for ve in valid_entries],
                    selection=selection,
                )
            else:
                type_key = generate_type_key_from_dto(first_dto) if first_dto else None
                # Caller page params (from Resolver context): if present and a
                # page_loader exists, slice per-parent via PageLoadCommand.
                # per-params split (params_key) keeps different params in
                # different batches (aiodataloader: one instance = one batch).
                # Paged default (field Annotated metadata) + caller override.
                paged_default = getattr(type(first_node), "__paged_fields__", {}).get(rel_name)
                paged_caller = self._extract_page_params(rel_name)
                merged = self._merge_paged(paged_default, paged_caller)
                use_page_loader = (
                    merged is not None
                    and first_rel.page_loader is not None
                )
                if use_page_loader:
                    loader = self._registry.get_loader(
                        first_rel.page_loader, type_key=type_key,
                        params_key=merged.params_key(),
                    )
                else:
                    loader = self._get_loader(first_node, rel_name, type_key=type_key)
                if loader is None:
                    continue
                if first_dto is not None and type_key is not None:
                    set_query_meta(loader, generate_query_meta_from_dto(first_dto))
                if use_page_loader:
                    from nexusx.loader.pagination import PageArgs, PageLoadCommand

                    page_args = PageArgs(
                        limit=merged.limit,
                        offset=merged.offset,
                        default_page_size=first_rel.default_page_size,
                        max_page_size=first_rel.max_page_size,
                    )
                    commands = [
                        PageLoadCommand(
                            fk_value=k,
                            page_args=page_args,
                            order=merged.order,
                            direction=merged.direction,
                        )
                        for k in keys
                    ]
                    results = await loader.load_many(commands)
                else:
                    results = await loader.load_many(keys)

            # Map results back to nodes
            for j, (idx, node, field_name, dto_cls) in enumerate(valid_entries):
                result = results[j]
                ln = level[idx]
                _item, _meta, new_ctx, _snap = ln

                if is_list:
                    items_list = result if result is not None else []
                    if isinstance(result, dict):
                        # page_loader returns {items, pagination}; take items.
                        items_list = result.get("items") or []
                    if dto_cls and items_list:
                        if is_custom:
                            # CUSTOM rels may already yield the right DTO
                            # type — trust the loader only when it actually
                            # returned ``dto_cls`` instances (or subclasses).
                            # The looser ``isinstance(r, BaseModel)`` check
                            # we used before treated SQLModel source rows as
                            # "already converted" (SQLModel IS a BaseModel),
                            # silently skipping projection. See
                            # tests/test_definesubset_basemodel.py::
                            #   TestCustomRelationshipAutoConversion.
                            items_list = [
                                r if isinstance(r, dto_cls)
                                else self._orm_to_dto(r, dto_cls)
                                for r in items_list
                            ]
                        else:
                            items_list = [
                                self._orm_to_dto(r, dto_cls)
                                for r in items_list
                            ]
                    object.__setattr__(node, field_name, items_list)
                    auto_loaded.add((id(node), field_name))
                    for child in items_list:
                        if isinstance(child, BaseModel):
                            auto_children.append(_WorkItem(
                                child, node, new_ctx, {},
                            ))
                else:
                    if result is None:
                        continue
                    if dto_cls and not (is_custom and isinstance(result, dto_cls)):
                        result = self._orm_to_dto(result, dto_cls)
                    object.__setattr__(node, field_name, result)
                    auto_loaded.add((id(node), field_name))
                    if isinstance(result, BaseModel):
                        auto_children.append(_WorkItem(
                            result, node, new_ctx, {},
                        ))

        return auto_loaded

    # ──────────────────────────────────────────────────────────
    # Entity-first gql dispatch (specs/018 US3)
    #
    # BFS relationship resolution relocated verbatim from
    # ``QueryExecutor._bfs_resolve`` (zero behavior change). The
    # entity-first gql path used to BFS-resolve inside the executor and
    # call ``fetch_remote_subtree`` (β) directly; US3 collapses both into
    # the Resolver so β federation dispatch lives alongside the γ DTO
    # dispatch above. ``QueryExecutor._resolve_result`` is now a thin
    # delegate (see T017); the executor's own BFS methods are deleted.
    # ──────────────────────────────────────────────────────────

    async def _bfs_dispatch_entity_fields(
        self,
        parents: list,
        parent_entity: type[SQLModel],
        field_sel: FieldSelection,
        response_model: type[BaseModel] | None,
        *,
        store: Callable[[Any, str, Any], None],
        enable_pagination: bool = False,
    ) -> None:
        """Level-by-level BFS relationship resolution using DataLoaders.

        At each level, all relationship fields are loaded concurrently via
        ``asyncio.gather``. The loaded children become the parents for the
        next level. Relocated from ``QueryExecutor._bfs_resolve`` (specs/018
        US3 / T016) — zero behavior change.

        ``store`` is the executor's ``_results`` write callback
        (``store(entity, field_name, value)``); resolved relationship values
        are written there and read back by ``QueryExecutor._serialize``. The
        Resolver owns no entity-result cache — it is a pure dispatcher here.

        ``response_model`` is the dynamic DTO built by ``build_response_model``
        (US2 stamps ``Annotated[..., Paged(...)]`` on paginated fields). It is
        accepted for contract parity and as the future hook for
        metadata-driven dispatch; this relocation still drives pagination off
        ``enable_pagination`` + gql field args (verbatim from the executor) to
        guarantee zero regression. Metadata-driven routing is a follow-up.

        ``enable_pagination`` mirrors ``QueryExecutor._enable_pagination``.
        """
        queue: list[_EntityFieldJob] = self._build_entity_field_jobs(
            parents, parent_entity, field_sel, enable_pagination,
        )

        while queue:
            # Concurrent load all fields in this level
            load_results = await asyncio.gather(
                *(
                    self._load_entity_field(job, store, enable_pagination)
                    for job in queue
                )
            )

            # Build next level's jobs from loaded children
            next_jobs: list[_EntityFieldJob] = []
            for job, children in zip(queue, load_results, strict=True):
                next_jobs.extend(
                    self._build_entity_field_jobs(
                        children,
                        job.rel_info.target_entity,
                        job.child_sel,
                        enable_pagination,
                    )
                )
            queue = next_jobs

    def _build_entity_field_jobs(
        self,
        parents: list,
        parent_entity: type[SQLModel],
        field_sel: FieldSelection,
        enable_pagination: bool,
    ) -> list[_EntityFieldJob]:
        """Extract relationship fields that need loading and build jobs."""
        if not parents or not field_sel.sub_fields:
            return []

        jobs: list[_EntityFieldJob] = []
        for field_name, child_sel in field_sel.sub_fields.items():
            rel_info = self._registry.get_relationship(parent_entity, field_name)
            if rel_info is None:
                continue

            # Coalesced (β): data already resolved by the owning service within
            # the parent fetch and preserved on the instance — no BFS job.
            if rel_info.kind == RelationshipKind.REMOTE_COALESCED:
                continue

            if not child_sel.sub_fields:
                continue

            # Paginated: use items sub-selection for deeper resolution
            effective_sel = child_sel
            if (
                enable_pagination
                and rel_info.is_list
                and rel_info.page_loader is not None
            ):
                items_sel = (
                    child_sel.sub_fields.get("items")
                    if child_sel.sub_fields
                    else None
                )
                if items_sel and items_sel.sub_fields:
                    effective_sel = items_sel

            if not effective_sel.sub_fields:
                continue

            # Collect valid FK values
            fk_values = [getattr(p, rel_info.fk_field, None) for p in parents]
            valid_indices = [i for i, fk in enumerate(fk_values) if fk is not None]
            if not valid_indices:
                continue

            valid_parents = [parents[i] for i in valid_indices]
            jobs.append(
                _EntityFieldJob(
                    parents=valid_parents,
                    parent_entity=parent_entity,
                    rel_info=rel_info,
                    child_sel=effective_sel,
                    original_sel=child_sel if effective_sel is not child_sel else None,
                )
            )
        return jobs

    async def _load_entity_field(
        self,
        job: _EntityFieldJob,
        store: Callable[[Any, str, Any], None],
        enable_pagination: bool,
    ) -> list:
        """Load a single field's relationship data and store results.

        Returns a flat list of all loaded child entities for the next BFS level.
        """
        if (
            enable_pagination
            and job.rel_info.is_list
            and job.rel_info.page_loader is not None
        ):
            return await self._load_entity_field_paginated(job, store)
        return await self._load_entity_field_batch(job, store)

    async def _load_entity_field_batch(
        self,
        job: _EntityFieldJob,
        store: Callable[[Any, str, Any], None],
    ) -> list:
        """Batch load a non-paginated relationship field."""
        from nexusx.loader.query_meta import (
            generate_query_meta_from_selection,
            generate_type_key_from_selection,
            merge_query_meta,
            set_query_meta,
        )

        rel_info = job.rel_info
        child_sel = job.child_sel

        is_remote = rel_info.kind in (
            RelationshipKind.REMOTE_PAGED, RelationshipKind.REMOTE_PLAIN
        )
        is_paged_remote = rel_info.kind == RelationshipKind.REMOTE_PAGED
        if is_paged_remote:
            # β paginated path: route to the member's page_by_<key>_in root.
            # {items, pagination} per parent.
            from nexusx.federation.remote_loader import fetch_remote_subtree

            results = await fetch_remote_subtree(
                registry=self._registry,
                rel_info=rel_info,
                parents=job.parents,
                selection=child_sel,
                paged=True,
            )
        elif is_remote:
            # β path: fetch the whole nested sub-tree via the shared primitive
            # (one gql to the owning service; the member resolves everything
            # under it). Same mechanism the Resolver uses — fetch_remote_subtree.
            from nexusx.federation.remote_loader import fetch_remote_subtree

            results = await fetch_remote_subtree(
                registry=self._registry,
                rel_info=rel_info,
                parents=job.parents,
                selection=child_sel,
            )
        else:
            # Build FK lookup from target entity's registered relationships
            target_rels = self._registry.get_relationships(rel_info.target_entity)
            fk_lookup = {name: info.fk_field for name, info in target_rels.items()}

            # Generate type_key for split mode (None in default mode)
            type_key = generate_type_key_from_selection(
                child_sel, rel_info.target_entity, fk_lookup=fk_lookup,
            )
            loader = self._registry.get_loader(rel_info.loader, type_key=type_key)

            # Inject _query_meta for SQL column pruning
            meta = generate_query_meta_from_selection(
                child_sel, rel_info.target_entity, fk_lookup=fk_lookup,
            )
            if type_key is not None and self._registry._split_mode:
                set_query_meta(loader, meta)
            else:
                merge_query_meta(loader, meta)

            fk_values = [getattr(p, rel_info.fk_field) for p in job.parents]
            results = await loader.load_many(fk_values)

        all_children: list = []
        for parent, result in zip(job.parents, results, strict=True):
            if isinstance(result, dict) and "items" in result and "pagination" in result:
                # Paginated result: {items, pagination} — store whole, items to BFS.
                items = result.get("items") or []
                store(parent, rel_info.name, result)
                all_children.extend(items)
            elif rel_info.is_list:
                items = result or []
                store(parent, rel_info.name, items)
                all_children.extend(items)
            else:
                store(parent, rel_info.name, result)
                if result is not None:
                    all_children.append(result)
        return all_children

    async def _load_entity_field_paginated(
        self,
        job: _EntityFieldJob,
        store: Callable[[Any, str, Any], None],
    ) -> list:
        """Load a paginated relationship field."""
        from nexusx.loader.query_meta import (
            generate_query_meta_from_selection,
            generate_type_key_from_selection,
            merge_query_meta,
            set_query_meta,
        )

        rel_info = job.rel_info
        child_sel = job.child_sel

        # Extract page args from original field selection (before items adjustment).
        # job.original_sel holds the original child_sel when it was replaced by
        # items_sel; otherwise fall back to child_sel (no pagination adjustment).
        page_args = self._extract_entity_page_args(
            job.original_sel if job.original_sel is not None else child_sel,
            rel_info,
        )

        target_rels = self._registry.get_relationships(rel_info.target_entity)
        fk_lookup = {name: info.fk_field for name, info in target_rels.items()}

        type_key = generate_type_key_from_selection(
            child_sel, rel_info.target_entity, fk_lookup=fk_lookup,
        )
        loader = self._registry.get_loader(rel_info.page_loader, type_key=type_key)

        meta = generate_query_meta_from_selection(
            child_sel, rel_info.target_entity, fk_lookup=fk_lookup,
        )
        if type_key is not None and self._registry._split_mode:
            set_query_meta(loader, meta)
        else:
            merge_query_meta(loader, meta)

        order, direction = self._extract_entity_order_direction(
            job.original_sel if job.original_sel is not None else child_sel,
            rel_info,
        )
        fk_values = [getattr(p, rel_info.fk_field) for p in job.parents]
        commands = [
            PageLoadCommand(
                fk_value=fk, page_args=page_args, order=order, direction=direction
            )
            for fk in fk_values
        ]
        results = await loader.load_many(commands)

        all_children: list = []
        for parent, page_result in zip(job.parents, results, strict=True):
            store(parent, rel_info.name, page_result)
            if page_result and page_result.get("items"):
                all_children.extend(page_result["items"])
        return all_children

    def _extract_entity_page_args(
        self, field_sel: FieldSelection, rel_info: Any
    ) -> PageArgs:
        """Extract PageArgs from GraphQL field arguments."""
        args = field_sel.arguments or {}
        return PageArgs(
            limit=args.get("limit"),
            offset=args.get("offset", 0),
            default_page_size=rel_info.default_page_size,
            max_page_size=rel_info.max_page_size,
        )

    def _extract_entity_order_direction(
        self, field_sel: FieldSelection, rel_info: Any
    ) -> tuple[str | None, Any]:
        """Extract order/direction for a local paginated relationship that
        carries a ``page_capability`` (specs/015). Returns (None, None) when the
        relationship has no profile — the page_loader then falls back to its
        fixed ``sort_field`` (backward compat)."""
        if rel_info.page_capability is None:
            return None, None
        args = field_sel.arguments or {}
        order = args.get("order")
        direction = args.get("direction")
        order_name = order.value if hasattr(order, "value") else order
        dir_value = direction.value if hasattr(direction, "value") else direction
        return order_name, dir_value

    async def resolve(self, node: T) -> T:
        """Resolve a model tree: execute resolve_* and post_* methods.

        Args:
            node: A BaseModel instance, or list of BaseModel instances.

        Returns:
            The same node with all resolve_* and post_* fields populated.
        """
        # Resolver is NOT reentrant: per-call state (_node_collectors,
        # _loader_cache, the levels list inside _traverse) lives on self.
        # Two overlapping resolve() calls on the same instance would clobber
        # each other and surface as a cryptic KeyError. Detect and raise.
        if self._in_resolve:
            raise RuntimeError(
                'Resolver.resolve() is already running on this instance. '
                'A Resolver cannot be shared across concurrent resolve() '
                'calls — create a fresh Resolver per call.'
            )
        self._in_resolve = True
        try:
            # Resolver is request-scoped by convention: each resolve() starts a
            # fresh traversal with empty caches. Reusing a Resolver instance
            # across requests is supported but pays the cache-clear cost on every
            # call; long-lived resolvers that want cross-request caching should
            # bypass this method and call _traverse directly. (issue #77 review)
            if self._registry is not None and hasattr(self._registry, "clear_cache"):
                self._registry.clear_cache()
            self._node_collectors.clear()
            self._loader_cache.clear()
            await self._traverse(node)
            return node
        finally:
            self._in_resolve = False
