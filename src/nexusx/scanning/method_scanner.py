"""Method scanning for GraphQL decorators.

Produces a *grouped* view of ``@query`` / ``@mutation`` methods keyed by entity
class name, mirroring how the compose (UseCaseService) path groups methods by
service. The resulting shape is::

    {entity_name: {method_name: (entity, method)}}

consumed unchanged by the SDL generator, the introspection generator, and the
executor. Method names are used verbatim (no camelCase / entity-prefix), so the
field on the ``{Entity}Query`` group type is the original Python name.

Entities without any ``@query`` / ``@mutation`` method produce no group and are
invisible. Name collisions are rejected eagerly at scan time (see
:mod:`nexusx.scanning.errors`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nexusx.annotation_utils import unwrap_func
from nexusx.scanning.errors import (
    DuplicateEntityError,
    DuplicateMethodError,
    ReservedEntityError,
    ReservedMethodFieldError,
)

# GraphQL root operation type names — an entity class named one of these would
# collide with the synthesized root types.
_RESERVED_ROOT_NAMES = frozenset({"Query", "Mutation", "Subscription"})

# Shape of a grouped method map: entity_name -> method_name -> (entity, method).
GroupedMethods = dict[str, dict[str, tuple[type, Callable[..., Any]]]]

QUERY_MARKER = "_graphql_query"
MUTATION_MARKER = "_graphql_mutation"


@dataclass(frozen=True, slots=True)
class EntityCallable:
    """One callable attribute of an entity class, as found by ``dir()``.

    ``attr`` is the attribute as retrieved (a bound classmethod or plain
    function — what executors call); ``func`` is the same thing unwrapped to
    the underlying function (what introspection / signature reads use).
    """

    name: str
    attr: Callable[..., Any]
    func: Callable[..., Any]

    @property
    def kind(self) -> str | None:
        """``"query"`` / ``"mutation"`` when marked by ``@query`` / ``@mutation``,
        else ``None``."""
        if hasattr(self.attr, QUERY_MARKER):
            return "query"
        if hasattr(self.attr, MUTATION_MARKER):
            return "mutation"
        return None


def iter_entity_callables(entity: type) -> list[EntityCallable]:
    """The **one** ``dir(entity)`` scan every consumer shares (spec 026 R3).

    Returns every callable attribute in ``dir()`` order with its underlying
    function unwrapped, so callers filter by function-attribute markers
    (``_graphql_query`` / ``_graphql_mutation`` / ``_pagination_root`` /
    ``_filter_input_type`` / ``_nexusx_federation_batch_root``) instead of
    re-walking the class. Attributes that raise on ``getattr`` are skipped —
    the most lenient of the behaviours the nine former call sites had.
    """
    found: list[EntityCallable] = []
    for attr_name in dir(entity):
        try:
            attr = getattr(entity, attr_name)
        except Exception:
            continue
        if not callable(attr):
            continue
        found.append(EntityCallable(attr_name, attr, unwrap_func(attr)))
    return found


def iter_operations(entity: type) -> list[tuple[EntityCallable, str]]:
    """``[(callable, kind)]`` for the entity's ``@query`` / ``@mutation`` methods."""
    return [(ec, kind) for ec in iter_entity_callables(entity) if (kind := ec.kind) is not None]


class MethodScanner:
    """Scans entities for @query and @mutation methods."""

    def scan(self, entities: list[type]) -> tuple[GroupedMethods, GroupedMethods]:
        """Scan all entities for @query and @mutation methods.

        Args:
            entities: List of entity classes to scan.

        Returns:
            Tuple of ``(query_groups, mutation_groups)`` where each is a nested
            mapping ``{entity_name: {method_name: (entity, method)}}``. Method
            names are the original Python names (verbatim).

        Raises:
            ReservedEntityError: An entity contributing methods is named
                ``Query`` / ``Mutation`` / ``Subscription``.
            DuplicateEntityError: Two distinct entity classes sharing a name
                both contribute methods.
            ReservedMethodFieldError: A method name starts with ``__``.
            DuplicateMethodError: Two methods on one entity share a name.
        """
        query_groups: GroupedMethods = {}
        mutation_groups: GroupedMethods = {}
        entity_by_name: dict[str, type] = {}

        for entity in entities:
            query_methods: list[tuple[Callable[..., Any], str]] = []
            mutation_methods: list[tuple[Callable[..., Any], str]] = []

            for ec, kind in iter_operations(entity):
                if kind == "query":
                    query_methods.append((ec.attr, ec.func.__name__))
                else:
                    mutation_methods.append((ec.attr, ec.func.__name__))

            # Entities without any GraphQL method produce no group — skip them
            # entirely (no group type, no root mount, no name validation).
            if not query_methods and not mutation_methods:
                continue

            self._validate_entity(entity, entity_by_name)

            for attr, method_name in query_methods:
                self._register_method(query_groups, entity, attr, method_name)
            for attr, method_name in mutation_methods:
                self._register_method(mutation_groups, entity, attr, method_name)

        return query_groups, mutation_groups

    @staticmethod
    def _validate_entity(entity: type, entity_by_name: dict[str, type]) -> None:
        """Reject reserved root-type names and distinct same-named entities."""
        name = entity.__name__

        if name in _RESERVED_ROOT_NAMES:
            msg = (
                f"Entity class '{name}' clashes with a GraphQL root operation "
                f"type name; rename the class (defined in {entity.__module__})."
            )
            raise ReservedEntityError(msg)

        prior = entity_by_name.get(name)
        if prior is not None and prior is not entity:
            msg = (
                f"Entity name '{name}' is declared by two distinct classes: "
                f"{prior.__module__}.{name} and {entity.__module__}.{name}. "
                f"Rename one of them."
            )
            raise DuplicateEntityError(msg)
        if prior is None:
            entity_by_name[name] = entity

    @staticmethod
    def _register_method(
        groups: GroupedMethods,
        entity: type,
        attr: Callable[..., Any],
        method_name: str,
    ) -> None:
        """Insert one method into its entity's group, rejecting collisions."""
        if method_name.startswith("__"):
            msg = (
                f"Method '{method_name}' on entity '{entity.__name__}' "
                f"({entity.__module__}.{entity.__name__}) starts with '__', "
                f"which is reserved by GraphQL introspection; rename the method."
            )
            raise ReservedMethodFieldError(msg)

        entity_name = entity.__name__
        inner = groups.setdefault(entity_name, {})
        if method_name in inner:
            msg = (
                f"Method '{method_name}' appears more than once on entity "
                f"'{entity_name}' ({entity.__module__}.{entity_name})."
            )
            raise DuplicateMethodError(msg)
        inner[method_name] = (entity, attr)
