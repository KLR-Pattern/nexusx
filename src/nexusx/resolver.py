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
import inspect
import typing
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar, get_args, get_origin

from aiodataloader import DataLoader
from pydantic import BaseModel
from pydantic.errors import PydanticUserError

from nexusx.context import (
    Collector,
    ICollector,
    scan_expose_fields,
    scan_send_to_fields,
)

T = TypeVar("T")


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
    collector_deps: list[tuple[str, Collector]] = field(default_factory=list)


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
    # Collector aliases found in post_* / post_default_handler: alias -> flat
    collector_aliases: dict[str, bool] = field(default_factory=dict)
    # Whether this class or any descendant needs traversal.
    # None = not yet computed; True/False = computed result.
    should_traverse: bool | None = None


# Type aliases for level processing
_LevelMeta = tuple[_ClassMeta, dict[str, str], dict[str, str | tuple[str, ...]]]
_LevelState = list[tuple[_WorkItem, _ClassMeta, dict[str, Any], dict[str, ICollector]]]


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
            elif include_collectors and isinstance(param.default, Collector):
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
                param_info = _analyze_method_params(attr, include_collectors=True)
                meta.post_default_handler = (attr_name, param_info)
                for _pname, collector in param_info.collector_deps:
                    if collector.alias not in meta.collector_aliases:
                        meta.collector_aliases[collector.alias] = collector.flat
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
                    if collector.alias not in meta.collector_aliases:
                        meta.collector_aliases[collector.alias] = collector.flat

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
    _class_meta_cache[kls] = meta
    return meta


def _compute_should_traverse(kls: type) -> bool:
    """Determine if a class or any of its BaseModel descendants needs traversal.

    A class needs traversal if it has resolve/post methods, ExposeAs/SendTo
    annotations, Collector parameters, or any descendant that does.
    Handles self-referencing types by using a sentinel value.
    Result is cached in ``_ClassMeta.should_traverse``.
    """
    meta = _get_class_meta(kls)

    if meta.should_traverse is not None:
        return meta.should_traverse

    # Sentinel: mark as True to handle cycles (self-referencing types).
    meta.should_traverse = True

    # Check own configuration
    if (meta.resolve_methods or meta.post_methods or meta.collector_aliases
            or meta.post_default_handler is not None
            or scan_expose_fields(kls) or scan_send_to_fields(kls)):
        return True

    # Check descendants
    for field_info in kls.model_fields.values():
        child_cls = Resolver._do_extract_dto_cls(field_info.annotation)
        if child_cls is not None and _compute_should_traverse(child_cls):
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
    """

    def __init__(
        self,
        loader_registry: Any = None,
        context: dict[str, Any] | None = None,
    ):
        self._registry = loader_registry
        self._context = context or {}
        # Per-node collector instances (for Collector parameter injection)
        self._node_collectors: dict[int, dict[str, ICollector]] = {}
        # Loader instance cache for Depends-based loaders
        self._loader_cache: dict[Any, DataLoader] = {}
        # Auto-load plan cache: DTO class → auto-load specs (per Resolver,
        # avoids id(registry) reuse issues across ErManager lifetimes)
        self._auto_load_cache: dict[type, list] = {}
        # Type extraction cache: annotation → DTO class or None
        self._dto_cls_cache: dict[Any, type[BaseModel] | None] = {}
        # Per-type cache: model type → list of (field_name, is_list) for traversable fields
        self._traversable_fields_cache: dict[type, list[tuple[str, bool]] | None] = {}

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

        from nexusx.subset import get_subset_source

        source_entity = None
        if isinstance(node, BaseModel):
            source_entity = get_subset_source(type(node))
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
        return None

    def _get_or_create_loader(self, loader_cls: type[DataLoader]) -> DataLoader:
        """Get or create a cached DataLoader instance by class."""
        if loader_cls not in self._loader_cache:
            self._loader_cache[loader_cls] = loader_cls()
        return self._loader_cache[loader_cls]

    def _get_or_create_fn_loader(self, fn: Callable) -> DataLoader:
        """Get or create a cached DataLoader wrapping an async batch function."""
        if fn not in self._loader_cache:
            self._loader_cache[fn] = DataLoader(batch_load_fn=fn)
        return self._loader_cache[fn]

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
        4. The field type is a BaseModel subclass (DTO)
        5. The DTO type is compatible with the relationship's target entity

        Returns list of (field_name, rel_name, rel_info, field_info).
        """
        if not isinstance(node, BaseModel) or self._registry is None:
            return []

        node_type = type(node)
        cached = self._auto_load_cache.get(node_type)
        if cached is not None:
            return cached

        from nexusx.subset import get_subset_source
        from nexusx.utils.type_compat import is_compatible_type

        source_entity = get_subset_source(node_type)
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

            # Field type must be a BaseModel DTO
            dto_cls = self._extract_dto_cls(field_info)
            if dto_cls is None:
                continue

            # DTO must be compatible with the relationship's target entity
            rel_info = entity_rels[field_name]
            if is_compatible_type(dto_cls, rel_info.target_entity):
                results.append((field_name, field_name, rel_info, field_info))

        self._auto_load_cache[node_type] = results
        return results

    def _extract_dto_cls(self, field_info: Any) -> type[BaseModel] | None:
        """Extract the DTO class from a field annotation.

        Handles Optional, list, Annotated wrappers.
        Results are cached by annotation object for repeated lookups.
        """
        anno = field_info.annotation
        cached = self._dto_cls_cache.get(anno)
        if cached is not None:
            return cached
        if anno in self._dto_cls_cache:
            return None

        result = self._do_extract_dto_cls(anno)
        self._dto_cls_cache[anno] = result
        return result

    @staticmethod
    def _do_extract_dto_cls(anno: Any) -> type[BaseModel] | None:
        """Actual type extraction logic (uncached)."""
        # Resolve string annotations from __future__ import annotations
        if isinstance(anno, str):
            return None

        # Unwrap Annotated
        origin = get_origin(anno)
        if origin is typing.Annotated:
            anno = get_args(anno)[0]
            origin = get_origin(anno)

        # Unwrap Optional (Union[X, None])
        if origin is type(None):
            return None
        args = get_args(anno)
        if args:
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1 and len(args) > 1:
                anno = non_none[0]
                origin = get_origin(anno)

        # Unwrap list
        if origin is list:
            args = get_args(anno)
            if args:
                anno = args[0]

        # Check if it's a BaseModel subclass
        if isinstance(anno, type) and issubclass(anno, BaseModel):
            return anno
        return None

    # Cache: dto_cls -> pre-built subset_fields tuple (or None for model_validate path)
    _dto_fields_cache: dict[type, tuple[str, ...] | None] = {}

    @classmethod
    def _orm_to_dto(cls, orm_instance: Any, dto_cls: type[BaseModel]) -> BaseModel:
        """Convert a SQLModel ORM instance to a DefineSubset DTO."""
        subset_fields = cls._dto_fields_cache.get(dto_cls)
        if subset_fields is None and dto_cls not in cls._dto_fields_cache:
            subset_fields = getattr(dto_cls, "__subset_fields__", None)
            cls._dto_fields_cache[dto_cls] = subset_fields

        if subset_fields is None:
            return dto_cls.model_validate(orm_instance)

        kwargs = {f: v for f in subset_fields if (v := getattr(orm_instance, f, None)) is not None}
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
        params = {}

        if param_info.has_context:
            params["context"] = self._context
        if param_info.has_parent:
            params["parent"] = parent
        if param_info.has_ancestor_context:
            params["ancestor_context"] = ancestor_context if ancestor_context is not None else {}

        for param_name, dep in param_info.loader_deps:
            loader = self._resolve_dep(node, dep)
            if loader is not None:
                params[param_name] = loader

        result = method(**params)
        while inspect.isawaitable(result):
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
        params = {}

        if param_info.has_context:
            params["context"] = self._context
        if param_info.has_parent:
            params["parent"] = parent
        if param_info.has_ancestor_context:
            params["ancestor_context"] = ancestor_context if ancestor_context is not None else {}

        for param_name, collector_default in param_info.collector_deps:
            node_cols = self._node_collectors.get(id(node), {})
            collector = node_cols.get(collector_default.alias)
            if collector is not None:
                params[param_name] = collector

        for param_name, dep in param_info.loader_deps:
            loader = self._resolve_dep(node, dep)
            if loader is not None:
                params[param_name] = loader

        result = method(**params)
        while inspect.isawaitable(result):
            result = await result
        return result

    # ──────────────────────────────────────────────────────
    # BFS traversal
    # ──────────────────────────────────────────────────────

    async def _bfs_resolve(self, node: T) -> T:
        """BFS resolve: level-by-level traversal with batched DataLoader calls."""
        if isinstance(node, (list, tuple)):
            items = [
                _WorkItem(n, parent=None, ancestor_context={},
                          collector_snapshot={})
                for n in node
                if isinstance(n, BaseModel)
            ]
        elif isinstance(node, BaseModel):
            items = [_WorkItem(node, parent=None, ancestor_context={},
                               collector_snapshot={})]
        else:
            return node
        await self._process_level(items)
        return node

    async def _process_level(self, items: list[_WorkItem]) -> None:
        """Process all nodes at one BFS level."""
        if not items:
            return

        type_meta, level_state = self._prepare_level(items)
        resolve_results, next_level = await self._execute_resolves(level_state)
        auto_loaded_fields = await self._batch_auto_load(level_state, next_level)
        self._collect_existing_children(level_state, auto_loaded_fields, next_level)

        if next_level:
            await self._process_level(next_level)

        for node, field_name, result in resolve_results:
            setattr(node, field_name, result)

        await self._execute_posts(level_state)
        self._collect_send_to(level_state, type_meta)
        self._cleanup_collectors(level_state)

    def _prepare_level(
        self, items: list[_WorkItem]
    ) -> tuple[dict[type, _LevelMeta], _LevelState]:
        """Phase 0: group by type, build ancestor context and collector snapshots."""
        type_meta: dict[type, _LevelMeta] = {}
        level_state: _LevelState = []

        for item in items:
            node = item.node
            node_type = type(node)

            if node_type not in type_meta:
                meta = _get_class_meta(node_type)
                expose_map = scan_expose_fields(node_type)
                send_to_map = scan_send_to_fields(node_type)
                type_meta[node_type] = (meta, expose_map, send_to_map)
            else:
                meta, expose_map, send_to_map = type_meta[node_type]

            if expose_map:
                new_ancestor_ctx = dict(item.ancestor_context)
                for field_name, alias in expose_map.items():
                    new_ancestor_ctx[alias] = getattr(node, field_name, None)
            else:
                new_ancestor_ctx = item.ancestor_context

            if meta.collector_aliases:
                node_collectors: dict[str, ICollector] = {
                    alias: Collector(alias=alias, flat=flat)
                    for alias, flat in meta.collector_aliases.items()
                }
                self._node_collectors[id(node)] = node_collectors
                merged_collectors = dict(item.collector_snapshot)
                merged_collectors.update(node_collectors)
            else:
                merged_collectors = item.collector_snapshot

            level_state.append((item, meta, new_ancestor_ctx, merged_collectors))

        return type_meta, level_state

    async def _execute_resolves(
        self, level_state: _LevelState
    ) -> tuple[list[tuple[Any, str, Any]], list[_WorkItem]]:
        """Phase 1: run all resolve_* methods concurrently and collect children."""
        resolve_jobs: list[tuple[Any, str, dict[str, Any], dict[str, ICollector]]] = []
        resolve_coros: list[Any] = []

        for item, meta, new_ancestor_ctx, merged_collectors in level_state:
            node = item.node
            for field_name, attr_name in meta.resolve_methods:
                method = getattr(node, attr_name)
                param_info = meta.resolve_params[attr_name]
                resolve_coros.append(
                    self._execute_resolve_method(
                        node, method, param_info,
                        parent=item.parent, ancestor_context=item.ancestor_context,
                    )
                )
                resolve_jobs.append((node, field_name, new_ancestor_ctx, merged_collectors))

        resolve_outputs = await asyncio.gather(*resolve_coros) if resolve_coros else []

        resolve_results: list[tuple[Any, str, Any]] = []
        next_level: list[_WorkItem] = []

        for (node, field_name, new_ancestor_ctx, merged_collectors), result in zip(
            resolve_jobs, resolve_outputs, strict=True,
        ):
            resolve_results.append((node, field_name, result))

            if isinstance(result, (list, tuple)):
                for r in result:
                    if isinstance(r, BaseModel):
                        next_level.append(_WorkItem(
                            r, node, new_ancestor_ctx, merged_collectors,
                        ))
            elif isinstance(result, BaseModel):
                next_level.append(_WorkItem(
                    result, node, new_ancestor_ctx, merged_collectors,
                ))

        return resolve_results, next_level

    def _get_traversable_fields(
        self, node_type: type,
    ) -> list[tuple[str, bool]] | None:
        """Cache per-type: which fields can yield traversable children.

        Returns list of (field_name, is_list) or None if no traversable fields.
        """
        cached = self._traversable_fields_cache.get(node_type)
        if cached is not None:
            return cached if cached else None

        result: list[tuple[str, bool]] = []
        for field_name, field_info in node_type.model_fields.items():
            anno = field_info.annotation
            if anno is None:
                continue
            origin = getattr(anno, "__origin__", None)
            args = getattr(anno, "__args__", ())

            if origin is list and args:
                child_cls = args[0]
                if isinstance(child_cls, type) and issubclass(child_cls, BaseModel):
                    if _compute_should_traverse(child_cls):
                        result.append((field_name, True))
            elif isinstance(anno, type) and issubclass(anno, BaseModel):
                if _compute_should_traverse(anno):
                    result.append((field_name, False))

        self._traversable_fields_cache[node_type] = result
        return result if result else None

    def _collect_existing_children(
        self,
        level_state: _LevelState,
        auto_loaded_fields: set[tuple[int, str]],
        next_level: list[_WorkItem],
    ) -> None:
        """Collect existing object-field children (skip auto-loaded and non-traversable)."""
        for item, _meta, new_ancestor_ctx, merged_collectors in level_state:
            node = item.node
            node_id = id(node)
            traversable = self._get_traversable_fields(type(node))
            if traversable is None:
                continue
            for field_name, is_list in traversable:
                if (node_id, field_name) in auto_loaded_fields:
                    continue
                val = getattr(node, field_name, None)
                if val is None:
                    continue
                if is_list:
                    for c in val:
                        next_level.append(_WorkItem(
                            c, node, new_ancestor_ctx, merged_collectors,
                        ))
                else:
                    next_level.append(_WorkItem(
                        val, node, new_ancestor_ctx, merged_collectors,
                    ))

    async def _execute_posts(self, level_state: _LevelState) -> None:
        """Phase 3: run all post_* methods, then post_default_handler if present.

        post_default_handler runs after every post_* method at this level has
        finished (so it can read fields populated by them) and is not
        auto-assigned — its body sets fields manually. It shares the same
        parameter injection as post_* (context / parent / ancestor_context /
        Loader / Collector); by this point descendant SendTo values have
        already populated ancestor Collectors (recursion precedes this phase).
        """
        for item, meta, _new_ancestor_ctx, _merged_collectors in level_state:
            if not meta.post_methods:
                continue
            node = item.node
            for field_name, attr_name in meta.post_methods:
                method = getattr(node, attr_name)
                param_info = meta.post_params[attr_name]
                await self._bfs_post_and_set(
                    node, field_name, method, param_info,
                    parent=item.parent, ancestor_context=item.ancestor_context,
                )

        for item, meta, _new_ancestor_ctx, _merged_collectors in level_state:
            if meta.post_default_handler is None:
                continue
            attr_name, param_info = meta.post_default_handler
            node = item.node
            method = getattr(node, attr_name)
            # Return value intentionally ignored — the handler sets fields itself.
            await self._execute_post_method(
                node, method, param_info,
                parent=item.parent, ancestor_context=item.ancestor_context,
            )

    def _collect_send_to(
        self, level_state: _LevelState, type_meta: dict[type, _LevelMeta]
    ) -> None:
        """Phase 4: collect SendTo values into ancestor collectors."""
        for item, _meta, _new_ancestor_ctx, merged_collectors in level_state:
            node_type = type(item.node)
            _, _, send_to_map = type_meta[node_type]
            if not send_to_map:
                continue
            node = item.node
            for field_name, collector_names in send_to_map.items():
                value = getattr(node, field_name, None)
                if value is None:
                    continue
                if isinstance(collector_names, str):
                    collector_names = (collector_names,)
                for name in collector_names:
                    collector = merged_collectors.get(name)
                    if collector is not None:
                        collector.add(value)

    def _cleanup_collectors(self, level_state: _LevelState) -> None:
        """Phase 5: remove per-node collector references."""
        for item, meta, _new_ancestor_ctx, _merged_collectors in level_state:
            if meta.collector_aliases:
                self._node_collectors.pop(id(item.node), None)

    async def _bfs_post_and_set(
        self,
        node: Any,
        trim_field: str,
        method: Callable,
        param_info: _MethodParamInfo,
        *,
        parent: Any,
        ancestor_context: dict[str, Any],
    ) -> None:
        """Execute post method and set result on node (BFS mode)."""
        result = await self._execute_post_method(
            node, method, param_info,
            parent=parent, ancestor_context=ancestor_context,
        )
        setattr(node, trim_field, result)

    async def _batch_auto_load(
        self,
        level_state: list[tuple[_WorkItem, _ClassMeta, dict[str, Any], dict[str, ICollector]]],
        next_level: list[_WorkItem],
    ) -> set[tuple[int, str]]:
        """Batch auto-load relationships for all nodes at a level.

        Groups nodes by relationship, collects all FK values, uses load_many
        for batched loading, then ORM→DTO conversion.  Appends child WorkItems
        directly into *next_level*.

        Returns set of (id(node), field_name) pairs that were auto-loaded,
        so the caller can skip them in the existing-fields scan.
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

        for idx, (item, meta, _new_ancestor_ctx, _merged_collectors) in enumerate(level_state):
            node = item.node
            auto_load_entries = self._scan_auto_load_fields(node, meta)
            if not auto_load_entries:
                continue

            for field_name, rel_name, rel_info, field_info in auto_load_entries:
                dto_cls = self._extract_dto_cls(field_info)
                groups.setdefault((type(node), rel_name), []).append(
                    (idx, node, field_name, rel_info, field_info, dto_cls)
                )

        if not groups:
            return auto_loaded

        # Process each relationship group
        for (_node_type, rel_name), entries in groups.items():
            # Get loader from first entry's node
            first_node = entries[0][1]
            first_dto = entries[0][5]
            first_rel = entries[0][3]

            type_key = generate_type_key_from_dto(first_dto) if first_dto else None
            loader = self._get_loader(first_node, rel_name, type_key=type_key)
            if loader is None:
                continue

            if first_dto is not None and type_key is not None:
                set_query_meta(loader, generate_query_meta_from_dto(first_dto))

            is_custom = getattr(first_rel, "direction", "") == "CUSTOM"
            is_list = first_rel.is_list
            fk_field = first_rel.fk_field

            # Collect all FK/PK values and dispatch batch load
            keys: list[Any] = []
            valid_entries: list[tuple[int, Any, str, type[BaseModel] | None]] = []
            for idx, node, field_name, _rel_info, _field_info, dto_cls in entries:
                key = getattr(node, fk_field, None)
                if key is not None:
                    keys.append(key)
                    valid_entries.append((idx, node, field_name, dto_cls))

            if not keys:
                continue

            results = await loader.load_many(keys)

            # Map results back to nodes
            for j, (idx, node, field_name, dto_cls) in enumerate(valid_entries):
                result = results[j]
                item, meta, new_ancestor_ctx, merged_collectors = level_state[idx]

                if is_list:
                    items_list = result if result is not None else []
                    if dto_cls and items_list:
                        items_list = [
                            r if (is_custom and isinstance(r, BaseModel))
                            else self._orm_to_dto(r, dto_cls)
                            for r in items_list
                        ]
                    setattr(node, field_name, items_list)
                    auto_loaded.add((id(node), field_name))
                    for child in items_list:
                        if isinstance(child, BaseModel):
                            next_level.append(_WorkItem(
                                child, node, new_ancestor_ctx, merged_collectors,
                            ))
                else:
                    if result is None:
                        continue
                    if dto_cls:
                        if not (is_custom and isinstance(result, BaseModel)):
                            result = self._orm_to_dto(result, dto_cls)
                    setattr(node, field_name, result)
                    auto_loaded.add((id(node), field_name))
                    if isinstance(result, BaseModel):
                        next_level.append(_WorkItem(
                            result, node, new_ancestor_ctx, merged_collectors,
                        ))

        return auto_loaded

    async def resolve(self, node: T) -> T:
        """Resolve a model tree: execute resolve_* and post_* methods.

        Args:
            node: A BaseModel instance, or list of BaseModel instances.

        Returns:
            The same node with all resolve_* and post_* fields populated.
        """
        if self._registry is not None and hasattr(self._registry, "clear_cache"):
            self._registry.clear_cache()
        self._node_collectors.clear()
        self._loader_cache.clear()
        await self._bfs_resolve(node)
        return node
