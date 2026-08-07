"""UseCaseService base class and BusinessMeta metaclass.

Provides the foundation for defining business service classes whose
methods decorated with @query or @mutation are automatically discovered
and exposed via MCP.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, get_type_hints

from nexusx.utils.type_utils import map_annotation

USE_CASE_METHODS_ATTR = "__use_case_methods__"


def get_return_type(method: Any, *, include_extras: bool = False) -> Any:
    """Get the return type annotation of a method.

    Unwraps ``classmethod`` if needed, resolves string annotations
    via ``get_type_hints``, and falls back to ``inspect.signature``.

    Returns ``None`` if no return annotation is found.

    Federated DefineSubset: a return annotation is evaluated at ``def`` time,
    so a RemoteRef-sourced DefineSubset freezes its *placeholder* class into
    the annotation. ``federate`` later replaces the module attribute with the
    resolved class, but the frozen annotation misses it (issue #131). Re-resolve
    every class in the annotation by name against the method's module globals
    so consumers (voyager, REST router, JSONRPC) see the resolved class.
    """
    func = method.__func__ if isinstance(method, classmethod) else method
    try:
        hints = get_type_hints(func, include_extras=include_extras)
    except Exception:
        hints = {}
    return_anno = hints.get("return")
    if return_anno is None:
        try:
            sig = inspect.signature(func)
        except (ValueError, TypeError):
            return None
        if sig.return_annotation is inspect.Signature.empty:
            return None
        return_anno = sig.return_annotation
    return _refresh_class_refs(return_anno, func.__globals__)


def _refresh_class_refs(annotation: Any, module_globals: dict[str, Any]) -> Any:
    """Re-resolve classes in an annotation against module globals by name.

    Mirrors federate's ``setattr(module, name, resolved_class)`` so an
    annotation that froze a placeholder DefineSubset picks up the resolved
    class. No-op when the class was never replaced (``globals[name] is cls``).
    """
    def leaf(node: Any) -> Any:
        if isinstance(node, type):
            fresh = module_globals.get(node.__name__)
            if fresh is not None and fresh is not node:
                return fresh
        return node
    return map_annotation(annotation, leaf)


def _get_method_kind(func: Any) -> str | None:
    """Return 'query' or 'mutation' if func is marked by decorator, else None."""
    if getattr(func, "_graphql_query", False):
        return "query"
    if getattr(func, "_graphql_mutation", False):
        return "mutation"
    return None


def _get_method_description(func: Any) -> str:
    """Return the description stored by @query/@mutation decorator."""
    return (
        getattr(func, "_graphql_query_description", None)
        or getattr(func, "_graphql_mutation_description", None)
        or ""
    )


class BusinessMeta(type):
    """Metaclass that collects @query/@mutation decorated methods for introspection.

    Scans the class namespace for async classmethods marked with ``@query`` or
    ``@mutation`` decorators and stores their metadata in
    ``__use_case_methods__`` for use by ServiceIntrospector.
    """

    def __new__(mcs, name: str, bases: tuple, namespace: dict, **kwargs):
        cls = super().__new__(mcs, name, bases, namespace, **kwargs)

        # Allow UseCaseService itself to be created without __use_case_methods__
        if name == "UseCaseService" and not any(
            isinstance(b, BusinessMeta) for b in bases
        ):
            setattr(cls, USE_CASE_METHODS_ATTR, {})
            return cls

        # Collect decorated methods from this class and bases
        methods: dict[str, dict[str, Any]] = {}

        # First collect from bases
        for base in bases:
            if hasattr(base, USE_CASE_METHODS_ATTR):
                methods.update(getattr(base, USE_CASE_METHODS_ATTR))

        # Then collect from current class
        _EXCLUDED_METHODS = {"get_tag_name"}
        for attr_name, attr_value in namespace.items():
            # Skip private/protected and excluded methods
            if attr_name.startswith("_") or attr_name in _EXCLUDED_METHODS:
                continue

            func = _unwrap_classmethod(attr_value)
            if func is None:
                continue

            # Only discover methods marked with @query or @mutation
            kind = _get_method_kind(func)
            if kind is None:
                continue

            if not asyncio.iscoroutinefunction(func):
                continue

            methods[attr_name] = {
                "method": attr_value,
                "kind": kind,
                "description": _get_method_description(func),
            }

        setattr(cls, USE_CASE_METHODS_ATTR, methods)
        return cls


def _unwrap_classmethod(value: Any) -> Any | None:
    """Unwrap a classmethod to get the underlying function, if any."""
    if isinstance(value, classmethod):
        return value.__func__
    return None


class UseCaseService(metaclass=BusinessMeta):
    """Base class for business service definitions.

    Subclasses define async methods decorated with ``@query`` or ``@mutation``
    that represent use case operations. The BusinessMeta metaclass automatically
    discovers these methods and makes them available for introspection.

    Example::

        from nexusx import query, mutation

        class SprintService(UseCaseService):
            '''Sprint management service.'''

            @query
            async def list_sprints(cls) -> list[SprintSummary]:
                '''Get all sprints.'''
                ...

            @mutation
            async def create_sprint(cls, name: str) -> SprintSummary:
                '''Create a new sprint.'''
                ...
    """

    __use_case_methods__: dict[str, dict[str, Any]]

    @classmethod
    def get_tag_name(cls) -> str:
        """Return the tag name for this service.

        Returns the class name by default. Override to customize.
        """
        return cls.__name__
