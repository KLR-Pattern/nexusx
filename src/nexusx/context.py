"""Cross-layer data flow: ExposeAs, SendTo, Collector.

Enables parent nodes to pass context down to descendants (ExposeAs)
and descendants to aggregate values up to ancestors (SendTo + Collector).

Usage:
    from typing import Annotated
    from nexusx import ExposeAs, SendTo, Collector

    class SprintDTO(DefineSubset):
        __subset__ = (Sprint, ('id', 'name'))
        name: Annotated[str, ExposeAs('sprint_name')]
        tasks: list[TaskDTO] = []
        contributors: list[UserDTO] = []

        def post_contributors(self, collector=Collector('contributors')):
            return collector.values()

    class TaskDTO(DefineSubset):
        __subset__ = (Task, ('id', 'title'))
        full_title: str = ""
        owner: Annotated[UserDTO | None, SendTo('contributors')] = None

        def post_full_title(self, ancestor_context):
            return f"{ancestor_context['sprint_name']} / {self.title}"
"""

from __future__ import annotations

import abc
import weakref
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

# ──────────────────────────────────────────────────────────
# ExposeAs — expose field value to descendant nodes
# ──────────────────────────────────────────────────────────

@dataclass
class ExposeInfo:
    """Metadata for ExposeAs annotation."""
    alias: str


def ExposeAs(alias: str) -> ExposeInfo:
    """Mark a field to be exposed to descendant nodes via ancestor_context.

    Args:
        alias: The key name under which the value appears in ancestor_context.

    Example:
        name: Annotated[str, ExposeAs('sprint_name')]

        # In descendant:
        def post_full_title(self, ancestor_context):
            return ancestor_context['sprint_name']
    """
    return ExposeInfo(alias=alias)


# ──────────────────────────────────────────────────────────
# SendTo — send field value to ancestor's Collector
# ──────────────────────────────────────────────────────────

@dataclass
class SendToInfo:
    """Metadata for SendTo annotation."""
    collector_name: str | tuple[str, ...]


def SendTo(name: str | tuple[str, ...]) -> SendToInfo:
    """Mark a field to be collected by an ancestor's Collector.

    Args:
        name: Collector alias name (or tuple of names for multi-collector).

    Example:
        owner: Annotated[UserDTO | None, SendTo('contributors')]
    """
    return SendToInfo(collector_name=name)


# ──────────────────────────────────────────────────────────
# Collector — aggregate values from descendants
# ──────────────────────────────────────────────────────────

class ICollector(metaclass=abc.ABCMeta):
    """Abstract base class for collectors."""

    @abc.abstractmethod
    def __init__(self, alias: str):
        self.alias = alias

    @abc.abstractmethod
    def add(self, val: Any) -> None:
        """Add a value to the collection."""

    @abc.abstractmethod
    def values(self) -> Any:
        """Get collected values."""


class Collector(ICollector):
    """Collect values from descendant nodes marked with SendTo.

    Used as a parameter in post_* methods:

        def post_contributors(self, collector=Collector('contributors')):
            return collector.values()

    Args:
        alias: The collector name, matching SendTo's target.
        flat: If True, flatten list values (for list fields with SendTo).
    """

    def __init__(self, alias: str, flat: bool = False):
        super().__init__(alias)
        self.flat = flat
        self.val: list[Any] = []

    def add(self, val: Any | list[Any]) -> None:
        if self.flat:
            if isinstance(val, list):
                self.val.extend(val)
            else:
                raise TypeError("flat mode requires list values")
        else:
            self.val.append(val)

    def values(self) -> list[Any]:
        return self.val


# ──────────────────────────────────────────────────────────
# Metadata scanning helpers (cached per class)
# ──────────────────────────────────────────────────────────

# Keyed weakly so dynamically created DTO classes (tests, federation
# materialization) can be collected instead of leaking (issue #160 DESIGN_6).
_expose_cache: weakref.WeakKeyDictionary[type, dict[str, str]] = (
    weakref.WeakKeyDictionary()
)
_send_to_cache: weakref.WeakKeyDictionary[type, dict[str, tuple[str, ...]]] = (
    weakref.WeakKeyDictionary()
)


def scan_expose_fields(kls: type[BaseModel]) -> dict[str, str]:
    """Scan a class for fields with ExposeAs annotation.

    Results are cached per class since field metadata doesn't change.

    Returns:
        Dict mapping field_name -> alias for all ExposeAs-annotated fields.
    """
    cached = _expose_cache.get(kls)
    if cached is not None:
        return cached
    result: dict[str, str] = {}
    for field_name, field_info in kls.model_fields.items():
        for meta in field_info.metadata:
            if isinstance(meta, ExposeInfo):
                result[field_name] = meta.alias
                break
    _expose_cache[kls] = result
    return result


def scan_send_to_fields(kls: type[BaseModel]) -> dict[str, tuple[str, ...]]:
    """Scan a class for fields with SendTo annotation.

    Results are cached per class since field metadata doesn't change.

    Returns:
        Dict mapping field_name -> tuple of collector names. Single-name
        SendTo is normalized to a 1-tuple so callers iterate without an
        isinstance check per field.
    """
    cached = _send_to_cache.get(kls)
    if cached is not None:
        return cached
    result: dict[str, tuple[str, ...]] = {}
    for field_name, field_info in kls.model_fields.items():
        for meta in field_info.metadata:
            if isinstance(meta, SendToInfo):
                name = meta.collector_name
                result[field_name] = (name,) if isinstance(name, str) else tuple(name)
                break
    _send_to_cache[kls] = result
    return result


# ──────────────────────────────────────────────────────────
# AutoLoad — automatic relationship loading
# ──────────────────────────────────────────────────────────

@dataclass
class AutoLoadInfo:
    """Metadata for AutoLoad annotation."""
    origin: str | None = None  # Override relationship name, defaults to field name


def AutoLoad(origin: str | None = None) -> AutoLoadInfo:
    """Mark a field for automatic relationship loading via LoaderRegistry.

    When used in a DefineSubset DTO, the Resolver will automatically:
    1. Look up the relationship in the LoaderRegistry
    2. Load the data via DataLoader
    3. Convert ORM results to the annotated DTO type

    Args:
        origin: Override relationship name. Defaults to the field name.

    Example::

        class TaskSummary(DefineSubset):
            __subset__ = (Task, ('id', 'title', 'owner_id'))
            owner: Annotated[UserSummary | None, AutoLoad()] = None
    """
    return AutoLoadInfo(origin=origin)
