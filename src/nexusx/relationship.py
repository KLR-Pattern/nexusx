"""Custom relationship definitions for SQLModel entities.

Define non-ORM relationships with manually provided async batch loaders.
Used alongside ORM relationships discovered by SQLAlchemy inspection.

Usage:
    from nexusx import Relationship

    async def tags_by_post_id_loader(post_ids: list[int]) -> list[list[Tag]]:
        ...

    class Post(SQLModel, table=True):
        __tablename__ = "post"
        __relationships__ = [
            Relationship(
                fk='id',
                target=list[Tag],
                name='tags',
                loader=tags_by_post_id_loader,
            )
        ]
        id: int | None = Field(default=None, primary_key=True)
        title: str
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, get_args, get_origin

from pydantic import BaseModel
from sqlmodel import SQLModel

RELATIONSHIPS_ATTR = "__relationships__"


def is_virtual_entity(cls: Any) -> bool:
    """True if ``cls`` is a plain ``pydantic.BaseModel`` subclass that is NOT
    a SQLModel.

    Used by ER diagram builders and the DOT renderer to decide which nodes
    receive the Contract 3 visual-distinction treatment (yellow fill,
    ``«virtual»`` stereotype, ``cluster_virtual`` grouping). A single
    canonical definition here avoids drift between ``er_diagram.py`` and
    ``voyager/er_diagram_dot.py``.
    """
    return isinstance(cls, type) and issubclass(cls, BaseModel) and not issubclass(cls, SQLModel)


@dataclass
class Relationship:
    """Defines a custom (non-ORM) relationship for a SQLModel entity.

    Args:
        fk: Field name on the source entity whose value is passed to the
            loader as the batch key. For many-to-one this is typically the
            FK column (e.g. ``'owner_id'``); for one-to-many it is the
            source entity's PK (e.g. ``'id'``).
        target: Target entity type. Use a plain class for scalar (many-to-one)
            relationships, or ``list[Entity]`` for collection (one-to-many)
            relationships. Examples: ``target=User`` or ``target=list[Tag]``.
        name: Unique relationship name within this entity. Becomes the lookup
            key in ErManager and auto-loading.
        loader: Async batch loader function. Signature varies by target:
            - scalar target: ``async def fn(keys: list[K]) -> list[V | None]``
            - list target:   ``async def fn(keys: list[K]) -> list[list[V]]``
        description: Optional description for ER diagram documentation.
    """

    fk: str
    target: Any
    name: str
    loader: Callable
    description: str | None = None

    @property
    def is_list(self) -> bool:
        """True if target is ``list[Entity]`` (one-to-many relationship)."""
        return get_origin(self.target) is list

    @property
    def target_entity(self) -> type:
        """Extract the bare entity class, stripping ``list[...]`` wrapper."""
        if self.is_list:
            args = get_args(self.target)
            if args:
                return args[0]
        return self.target


def get_custom_relationships(entity: type) -> list[Relationship]:
    """Read __relationships__ from an entity class.

    Accepts any class — SQLModel entities today, plain BaseModel classes
    registered via ``ErManager.add_virtual_entities()`` tomorrow. The
    function body is shape-agnostic: it just reads the ``__relationships__``
    attribute and validates each entry is a Relationship instance.

    Returns an empty list if __relationships__ is not defined.
    """
    raw = getattr(entity, RELATIONSHIPS_ATTR, None)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise TypeError(
            f"{entity.__name__}.__relationships__ must be a list of Relationship, "
            f"got {type(raw).__name__}"
        )
    for i, item in enumerate(raw):
        if not isinstance(item, Relationship):
            raise TypeError(
                f"{entity.__name__}.__relationships__[{i}] must be a Relationship, "
                f"got {type(item).__name__}"
            )
    return list(raw)
