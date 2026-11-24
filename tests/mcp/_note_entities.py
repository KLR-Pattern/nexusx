"""Entities with an ordered list relationship — pagination-note fixtures.

Deliberately WITHOUT ``from __future__ import annotations``: SQLModel/SQLAlchemy
must evaluate the relationship annotations at class creation (same pattern as
tests/test_local_pagination_order.py). Importing these into a PEP-563 module
is fine — only this file's own annotations need to stay evaluable.
"""

from typing import Optional

from sqlmodel import Field, Relationship, SQLModel

from nexusx import query


class NoteBase(SQLModel):
    """Non-table base (Application(base=…) scans subclasses)."""


class NoteChild(NoteBase, table=True):
    __tablename__ = "note_child"
    __test__ = False

    id: int | None = Field(default=None, primary_key=True)
    parent_id: int = Field(foreign_key="note_parent.id")
    parent: Optional["NoteParent"] = Relationship(back_populates="children")


class NoteParent(NoteBase, table=True):
    __tablename__ = "note_parent"
    __test__ = False

    id: int | None = Field(default=None, primary_key=True)
    # order_by declared → this list relationship renders as a Result-wrapped
    # paginated field (the thing PAGINATION_CONTRACT_NOTE is keyed on)
    children: list[NoteChild] = Relationship(
        back_populates="parent",
        sa_relationship_kwargs={"order_by": "NoteChild.id"},
    )

    @query
    async def get_all(cls) -> list["NoteParent"]:
        return []
