"""Loader module - DataLoader factories and entity-relationship management."""

from nexusx.loader.pagination import (
    PageArgs,
    PageLoadCommand,
    Pagination,
    create_result_type,
)
from nexusx.loader.composed import ComposedErManager
from nexusx.loader.registry import ErManager, LoaderRegistry, RelationshipInfo

__all__ = [
    "ErManager",
    "LoaderRegistry",
    "ComposedErManager",
    "RelationshipInfo",
    "PageArgs",
    "PageLoadCommand",
    "Pagination",
    "create_result_type",
]
