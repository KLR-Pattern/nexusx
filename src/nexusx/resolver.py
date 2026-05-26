"""Resolver — model-driven traversal for Core API use case response building.

Traverses Pydantic/DefineSubset model trees, executing resolve_* methods
to load related data and post_* methods to compute derived fields.
Supports cross-layer data flow via ExposeAs, SendTo, and Collector.

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
import contextvars
import inspect
import typing
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar, get_args, get_origin

from aiodataloader import DataLoader
from pydantic import BaseModel

from nexusx.context import (
    Collector,
    ICollector,
    scan_expose_fields,
    scan_send_to_fields,
)

T = TypeVar("T")

_MISSING = object()


# ──────────────────────────────────────────────────────────
# BFS work item
# ──────────────────────────────────────────────────────────

@dataclass
class _WorkItem:
    """A node to be processed at a BFS level, with its context snapshot."""

    node: Any  # BaseModel instance
    parent: Any  # Parent BaseModel instance or None
    ancestor_context: dict[str, Any]  # Snapshot of ExposeAs values from ancestors
    collector_snapshot: dict[str, ICollector]  # Active ancestor Collector references


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
    # Collector aliases found in post_* methods: alias -> flat
    collector_aliases: dict[str, bool] = field(default_factory=dict)


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


def _build_class_meta(kls: type) -> _ClassMeta:
    """Build metadata for a class by scanning its methods once."""
    meta = _ClassMeta()

    for attr_name in dir(kls):
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


# Module-level class metadata cache. Safe because class structure doesn't
# change at runtime. Shared across all Resolver instances.
_class_meta_cache: dict[type, _ClassMeta] = {}

# Auto-load plan cache: (DTO class, registry id) → auto-load specs
_auto_load_cache: dict[tuple[type, int], list] = {}

# Type extraction cache: annotation → DTO class or None
_dto_cls_cache: dict[Any, type[BaseModel] | None] = {}


def _clear_resolver_caches() -> None:
    """Clear all resolver-level caches. For testing only."""
    _auto_load_cache.clear()
    _dto_cls_cache.clear()


def _get_class_meta(kls: type) -> _ClassMeta:
    """Get or compute class metadata (cached globally)."""
    cached = _class_meta_cache.get(kls)
    if cached is not None:
        return cached
    meta = _build_class_meta(kls)
    _class_meta_cache[kls] = meta
    return meta


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
        self._parent_var: contextvars.ContextVar[Any] = contextvars.ContextVar(
            "parent", default=None
        )
        # Ancestor context: dict of {alias: value} from ExposeAs fields
        self._ancestor_var: contextvars.ContextVar[dict[str, Any]] = (
            contextvars.ContextVar("ancestors", default=None)
        )
        # Collectors: dict of {alias: Collector} active in current scope
        self._collector_var: contextvars.ContextVar[dict[str, ICollector]] = (
            contextvars.ContextVar("collectors", default=None)
        )
        # Per-node collector instances (for Collector parameter injection)
        self._node_collectors: dict[int, dict[str, ICollector]] = {}
        # Loader instance cache for Depends-based loaders
        self._loader_cache: dict[Any, DataLoader] = {}

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

    def _get_object_fields(self, node: Any) -> list[tuple[str, Any]]:
        """Get non-None fields that are BaseModel instances (for recursive traversal)."""
        results = []
        if not isinstance(node, BaseModel):
            return results
        for field_name in type(node).model_fields:
            value = getattr(node, field_name, None)
            if value is None:
                continue
            if isinstance(value, BaseModel):
                results.append((field_name, value))
            elif isinstance(value, list):
                if value and isinstance(value[0], BaseModel):
                    results.append((field_name, value))
        return results

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

        cache_key = (type(node), id(self._registry))
        cached = _auto_load_cache.get(cache_key)
        if cached is not None:
            return cached

        from nexusx.subset import get_subset_source
        from nexusx.utils.type_compat import is_compatible_type

        source_entity = get_subset_source(type(node))
        if source_entity is None:
            _auto_load_cache[cache_key] = []
            return []
            return []

        # Get relationship names from source entity
        entity_rels = self._registry.get_relationships(source_entity)

        # Get subset field names so we can skip them (only extra fields are candidates)
        subset_field_names = set(getattr(type(node), "__subset_fields__", []))

        # Build set of resolve method field names from cached meta
        resolve_field_names = {fname for fname, _ in meta.resolve_methods}

        results = []
        for field_name, field_info in type(node).model_fields.items():
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

        _auto_load_cache[cache_key] = results
        return results

    def _extract_dto_cls(self, field_info: Any) -> type[BaseModel] | None:
        """Extract the DTO class from a field annotation.

        Handles Optional, list, Annotated wrappers.
        Results are cached by annotation object for repeated lookups.
        """
        anno = field_info.annotation
        cached = _dto_cls_cache.get(anno)
        if cached is not None:
            return cached
        if anno in _dto_cls_cache:
            return None

        result = self._do_extract_dto_cls(anno)
        _dto_cls_cache[anno] = result
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

    @staticmethod
    def _orm_to_dto(orm_instance: Any, dto_cls: type[BaseModel]) -> BaseModel:
        """Convert a SQLModel ORM instance to a DefineSubset DTO."""
        subset_fields = getattr(dto_cls, "__subset_fields__", None)
        if subset_fields is None:
            return dto_cls.model_validate(orm_instance)
        kwargs = {}
        for fname in subset_fields:
            val = getattr(orm_instance, fname, None)
            if val is not None:
                kwargs[fname] = val
        try:
            return dto_cls(**kwargs)
        except Exception:
            # Handle forward references from __future__ import annotations.
            # Build a namespace with all known DefineSubset DTOs so
            # model_rebuild can resolve type names like 'UserDTO'.
            import sys

            from nexusx.subset import _subset_registry

            module = sys.modules.get(dto_cls.__module__, None)
            ns = dict(vars(module)) if module else {}
            # Add all known DefineSubset DTOs to the namespace
            for dto_class in _subset_registry:
                ns[dto_class.__name__] = dto_class
            dto_cls.model_rebuild(_types_namespace=ns)
            return dto_cls(**kwargs)

    async def _auto_resolve_and_set(
        self,
        node: Any,
        field_name: str,
        rel_name: str,
        rel_info: Any,
        field_info: Any,
    ) -> None:
        """Execute auto-resolve for an implicit auto-load field and set on node."""
        from nexusx.loader.query_meta import (
            generate_query_meta_from_dto,
            generate_type_key_from_dto,
            set_query_meta,
        )

        dto_cls = self._extract_dto_cls(field_info)

        # Generate type_key for split mode and inject _query_meta.
        # Safe for implicit auto-load because _orm_to_dto only accesses
        # __subset_fields__ fields, which are covered by _query_meta.
        type_key = generate_type_key_from_dto(dto_cls) if dto_cls else None
        loader = self._get_loader(node, rel_name, type_key=type_key)
        if loader is None:
            return

        if dto_cls is not None and type_key is not None:
            set_query_meta(loader, generate_query_meta_from_dto(dto_cls))

        is_custom = getattr(rel_info, "direction", "") == "CUSTOM"

        if rel_info.is_list:
            # One-to-many / many-to-many: load by source key
            pk_value = getattr(node, rel_info.fk_field, None)
            if pk_value is None:
                return
            results = await loader.load(pk_value)
            if dto_cls and results:
                results = [
                    r if (is_custom and isinstance(r, BaseModel))
                    else self._orm_to_dto(r, dto_cls)
                    for r in results
                ]
            results = await self._traverse(results, node)
            setattr(node, field_name, results)
        else:
            # Many-to-one: load by FK
            fk_value = getattr(node, rel_info.fk_field, None)
            if fk_value is None:
                return
            result = await loader.load(fk_value)
            if result is None:
                return
            if dto_cls:
                if not (is_custom and isinstance(result, BaseModel)):
                    result = self._orm_to_dto(result, dto_cls)
            result = await self._traverse(result, node)
            setattr(node, field_name, result)

    # ──────────────────────────────────────────────────────
    # ExposeAs / Collector preparation
    # ──────────────────────────────────────────────────────

    def _prepare_expose_fields(self, node: Any) -> Callable[[], None]:
        """Push ExposeAs field values into ancestor context.

        Returns a cleanup function that restores the previous context.
        """
        if not isinstance(node, BaseModel):
            return lambda: None

        expose_map = scan_expose_fields(type(node))
        if not expose_map:
            return lambda: None

        current = self._ancestor_var.get()
        new_context = dict(current or {})
        for field_name, alias in expose_map.items():
            new_context[alias] = getattr(node, field_name, None)

        token = self._ancestor_var.set(new_context)
        return lambda: self._safe_reset(self._ancestor_var, token)

    def _prepare_collectors(self, node: Any, meta: _ClassMeta) -> Callable[[], None]:
        """Create Collector instances for this node's post_* methods.

        Uses pre-computed collector_aliases from _ClassMeta to avoid
        repeated method scanning and signature inspection.

        Returns a cleanup function.
        """
        if not isinstance(node, BaseModel):
            return lambda: None

        if not meta.collector_aliases:
            return lambda: None

        # Create fresh Collector instances from cached alias info
        new_collectors: dict[str, ICollector] = {}
        for alias, flat in meta.collector_aliases.items():
            new_collectors[alias] = Collector(alias=alias, flat=flat)

        # Store per-node collectors for parameter injection
        self._node_collectors[id(node)] = new_collectors

        # Merge with existing ancestor collectors (propagate downward)
        current = self._collector_var.get()
        merged = dict(current or {})
        merged.update(new_collectors)

        token = self._collector_var.set(merged)
        return lambda: self._safe_reset(self._collector_var, token)

    def _add_values_into_collectors(self, node: Any) -> None:
        """Send SendTo-annotated field values to active collectors."""
        if not isinstance(node, BaseModel):
            return

        send_to_map = scan_send_to_fields(type(node))
        if not send_to_map:
            return

        collectors = self._collector_var.get() or {}
        for field_name, collector_names in send_to_map.items():
            value = getattr(node, field_name, None)
            if value is None:
                continue

            # Normalize to tuple
            if isinstance(collector_names, str):
                collector_names = (collector_names,)

            for name in collector_names:
                collector = collectors.get(name)
                if collector is not None:
                    collector.add(value)

    @staticmethod
    def _safe_reset(var: contextvars.ContextVar, token: Any) -> None:
        """Safely reset a contextvar, ignoring errors."""
        try:
            var.reset(token)
        except (ValueError, LookupError):
            pass

    # ──────────────────────────────────────────────────────
    # Method execution with cached parameter info
    # ──────────────────────────────────────────────────────

    async def _execute_resolve_method(
        self,
        node: Any,
        method: Callable,
        param_info: _MethodParamInfo,
        *,
        parent: Any = _MISSING,
        ancestor_context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a resolve_* method with parameter injection using cached info."""
        params = {}

        if param_info.has_context:
            params["context"] = self._context
        if param_info.has_parent:
            params["parent"] = parent if parent is not _MISSING else self._parent_var.get()
        if param_info.has_ancestor_context:
            params["ancestor_context"] = (
                ancestor_context if ancestor_context is not None
                else (self._ancestor_var.get() or {})
            )

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
        parent: Any = _MISSING,
        ancestor_context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a post_* method with parameter injection using cached info."""
        params = {}

        if param_info.has_context:
            params["context"] = self._context
        if param_info.has_parent:
            params["parent"] = parent if parent is not _MISSING else self._parent_var.get()
        if param_info.has_ancestor_context:
            params["ancestor_context"] = (
                ancestor_context if ancestor_context is not None
                else (self._ancestor_var.get() or {})
            )

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
    # DFS traversal (kept for fallback)
    # ──────────────────────────────────────────────────────

    async def _traverse(self, node: T, parent: Any) -> T:
        """DFS traversal: prepare -> resolve -> traverse children -> post -> collect -> cleanup."""
        if isinstance(node, (list, tuple)):
            await asyncio.gather(*[self._traverse(t, parent) for t in node])
            return node

        if not isinstance(node, BaseModel):
            return node

        meta = _get_class_meta(type(node))

        parent_token = self._parent_var.set(parent)
        expose_reset = self._prepare_expose_fields(node)
        collector_reset = self._prepare_collectors(node, meta)

        try:
            auto_load_entries = self._scan_auto_load_fields(node, meta)

            resolve_tasks = []
            for field_name, attr_name in meta.resolve_methods:
                method = getattr(node, attr_name)
                param_info = meta.resolve_params[attr_name]
                resolve_tasks.append(
                    self._resolve_and_set(node, field_name, method, param_info)
                )

            for field_name, rel_name, rel_info, field_info in auto_load_entries:
                resolve_tasks.append(
                    self._auto_resolve_and_set(
                        node, field_name, rel_name, rel_info, field_info
                    )
                )

            object_fields = self._get_object_fields(node)
            for _field_name, child in object_fields:
                resolve_tasks.append(self._traverse(child, node))

            await asyncio.gather(*resolve_tasks)

            post_tasks = []
            for field_name, attr_name in meta.post_methods:
                method = getattr(node, attr_name)
                param_info = meta.post_params[attr_name]
                post_tasks.append(
                    self._post_and_set(node, field_name, method, param_info)
                )
            await asyncio.gather(*post_tasks)

            self._add_values_into_collectors(node)

        finally:
            self._node_collectors.pop(id(node), None)
            collector_reset()
            expose_reset()
            self._parent_var.reset(parent_token)

        return node

    async def _resolve_and_set(
        self, node: Any, trim_field: str, method: Callable, param_info: _MethodParamInfo,
    ) -> None:
        """Execute resolve method, traverse result, and set on node."""
        result = await self._execute_resolve_method(node, method, param_info)
        result = await self._traverse(result, node)
        setattr(node, trim_field, result)

    async def _post_and_set(
        self, node: Any, trim_field: str, method: Callable, param_info: _MethodParamInfo,
    ) -> None:
        """Execute post method and set result on node."""
        result = await self._execute_post_method(node, method, param_info)
        setattr(node, trim_field, result)

    # ──────────────────────────────────────────────────────
    # BFS traversal
    # ──────────────────────────────────────────────────────

    _EMPTY_DICT: dict[str, Any] = {}  # Shared empty dict for _WorkItem

    async def _bfs_resolve(self, node: T) -> T:
        """BFS resolve: level-by-level traversal with batched DataLoader calls."""
        if isinstance(node, (list, tuple)):
            items = [
                _WorkItem(n, parent=None, ancestor_context=self._EMPTY_DICT,
                          collector_snapshot=self._EMPTY_DICT)
                for n in node
                if isinstance(n, BaseModel)
            ]
        elif isinstance(node, BaseModel):
            items = [_WorkItem(node, parent=None, ancestor_context=self._EMPTY_DICT,
                               collector_snapshot=self._EMPTY_DICT)]
        else:
            return node
        await self._process_level(items)
        return node

    async def _process_level(self, items: list[_WorkItem]) -> None:
        """Process all nodes at one BFS level."""
        if not items:
            return

        # ── Phase 0: Prepare — group by type for shared metadata ──
        # Pre-compute: expose_map, collector_aliases, resolve_methods, post_methods, send_to_map
        # are all per-type (same for all instances of the same class).
        type_meta: dict[
            type, tuple[_ClassMeta, dict[str, str], dict[str, str | tuple[str, ...]]]
        ] = {}

        # Per-node state: (item, meta, new_ancestor_ctx, merged_collectors)
        level_state: list[tuple[_WorkItem, _ClassMeta, dict[str, Any], dict[str, ICollector]]] = []

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

            # Extend ancestor context with this node's ExposeAs fields
            if expose_map:
                new_ancestor_ctx = dict(item.ancestor_context)
                for field_name, alias in expose_map.items():
                    new_ancestor_ctx[alias] = getattr(node, field_name, None)
            else:
                new_ancestor_ctx = item.ancestor_context

            # Create per-node collectors and merge with ancestor collectors
            if meta.collector_aliases:
                node_collectors: dict[str, ICollector] = {
                    alias: Collector(alias=alias, flat=flat)
                    for alias, flat in meta.collector_aliases.items()
                }
                self._node_collectors[id(node)] = node_collectors
                merged_collectors = dict(item.collector_snapshot)
                merged_collectors.update(node_collectors)
            else:
                node_collectors = {}
                merged_collectors = item.collector_snapshot

            level_state.append((item, meta, new_ancestor_ctx, merged_collectors))

        # ── Phase 1: Resolve + Auto-load (batched) ──
        resolve_tasks: list[Any] = []

        for item, meta, new_ancestor_ctx, merged_collectors in level_state:
            node = item.node
            for field_name, attr_name in meta.resolve_methods:
                method = getattr(node, attr_name)
                param_info = meta.resolve_params[attr_name]
                resolve_tasks.append(
                    self._bfs_resolve_and_set(
                        node, field_name, method, param_info,
                        parent=item.parent, ancestor_context=item.ancestor_context,
                        child_ancestor_ctx=new_ancestor_ctx,
                        child_collectors=merged_collectors,
                    )
                )

        # Batch auto-load: group by relationship, collect FK values, load_many
        auto_load_children = await self._batch_auto_load(level_state)

        # Collect existing object-field children — only for types that have extra fields
        existing_children: list[_WorkItem] = []
        for item, _meta, new_ancestor_ctx, merged_collectors in level_state:
            node = item.node
            for field_name in type(node).model_fields:
                val = getattr(node, field_name, None)
                if val is None:
                    continue
                if isinstance(val, BaseModel):
                    existing_children.append(_WorkItem(
                        node=val, parent=node,
                        ancestor_context=new_ancestor_ctx,
                        collector_snapshot=merged_collectors,
                    ))
                elif isinstance(val, list) and val and isinstance(val[0], BaseModel):
                    for c in val:
                        existing_children.append(_WorkItem(
                            node=c, parent=node,
                            ancestor_context=new_ancestor_ctx,
                            collector_snapshot=merged_collectors,
                        ))

        # Await all resolve_* tasks
        if resolve_tasks:
            await asyncio.gather(*resolve_tasks)

        # ── Phase 2: Process next level ──
        next_level = auto_load_children + existing_children
        if next_level:
            await self._process_level(next_level)

        # ── Phase 3: Post_* methods ──
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

        # ── Phase 4: SendTo collection ──
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

        # ── Phase 5: Cleanup ──
        for item, meta, _new_ancestor_ctx, _merged_collectors in level_state:
            if meta.collector_aliases:
                self._node_collectors.pop(id(item.node), None)

    async def _bfs_resolve_and_set(
        self,
        node: Any,
        trim_field: str,
        method: Callable,
        param_info: _MethodParamInfo,
        *,
        parent: Any,
        ancestor_context: dict[str, Any],
        child_ancestor_ctx: dict[str, Any],
        child_collectors: dict[str, ICollector],
    ) -> None:
        """Execute resolve method for BFS mode, traverse result via BFS."""
        result = await self._execute_resolve_method(
            node, method, param_info,
            parent=parent, ancestor_context=ancestor_context,
        )
        # Traverse result as a new sub-tree via BFS
        if isinstance(result, (list, tuple)):
            children = [
                _WorkItem(r, parent=node, ancestor_context=child_ancestor_ctx,
                          collector_snapshot=child_collectors)
                for r in result if isinstance(r, BaseModel)
            ]
            if children:
                await self._process_level(children)
        elif isinstance(result, BaseModel):
            await self._process_level([_WorkItem(
                result, parent=node, ancestor_context=child_ancestor_ctx,
                collector_snapshot=child_collectors,
            )])
        setattr(node, trim_field, result)

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
    ) -> list[_WorkItem]:
        """Batch auto-load relationships for all nodes at a level.

        Groups nodes by relationship, collects all FK values, uses load_many
        for batched loading, then ORM→DTO conversion.
        """
        if self._registry is None:
            return []

        from nexusx.loader.query_meta import (
            generate_query_meta_from_dto,
            generate_type_key_from_dto,
            set_query_meta,
        )

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
            return []

        next_items: list[_WorkItem] = []

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
                    for child in items_list:
                        if isinstance(child, BaseModel):
                            next_items.append(_WorkItem(
                                node=child, parent=node,
                                ancestor_context=new_ancestor_ctx,
                                collector_snapshot=merged_collectors,
                            ))
                else:
                    if result is None:
                        continue
                    if dto_cls:
                        if not (is_custom and isinstance(result, BaseModel)):
                            result = self._orm_to_dto(result, dto_cls)
                    setattr(node, field_name, result)
                    if isinstance(result, BaseModel):
                        next_items.append(_WorkItem(
                            node=result, parent=node,
                            ancestor_context=new_ancestor_ctx,
                            collector_snapshot=merged_collectors,
                        ))

        return next_items

    async def resolve(self, node: T, *, mode: str = "bfs") -> T:
        """Resolve a model tree: execute resolve_* and post_* methods.

        Args:
            node: A BaseModel instance, or list of BaseModel instances.
            mode: Traversal strategy — ``"bfs"`` (default) or ``"dfs"``.

                - ``"bfs"`` — breadth-first: processes all nodes at one level
                  before moving to the next. Relationships are batched via
                  ``DataLoader.load_many``, minimizing SQL round-trips. Best
                  for wide trees with auto-loaded relationships, especially
                  when database latency is non-trivial.
                - ``"dfs"`` — depth-first: processes each node recursively.
                  Simpler overhead per node. Best for narrow/deep trees or
                  when resolve_* methods return varied sub-trees.

        Returns:
            The same node with all resolve_* and post_* fields populated.
        """
        if self._registry is not None and hasattr(self._registry, "clear_cache"):
            self._registry.clear_cache()
        self._node_collectors.clear()
        self._loader_cache.clear()
        if mode == "dfs":
            await self._traverse(node, None)
        else:
            await self._bfs_resolve(node)
        return node
