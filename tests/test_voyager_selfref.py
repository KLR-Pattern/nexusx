"""Regression test: Voyager update_forward_refs with self-referencing DefineSubset.

Bug: `update_forward_refs` in `type_helper.py` recurses infinitely when a
DefineSubset DTO references itself (e.g. `replies: list["CommentBrief"]`).

Reproduction:
    1. Define an entity with a self-referencing FK (Comment.parent_id → Comment.id)
    2. Create a DefineSubset DTO with a self-referencing field: replies: list["DTO"]
    3. Pass the DTO as a UseCaseService return type
    4. Access Voyager endpoint → triggers update_forward_refs → RecursionError

Root cause: `update_forward_refs` had no visited-set, so self-referencing types
caused unbounded recursion through field annotations.

Fix: Added a `_visited` set parameter to track already-processed types and
skip them on re-encounter, breaking the recursion cycle.
"""
from sqlmodel import Field, SQLModel

from sqlmodel_nexus import DefineSubset, SubsetConfig
from sqlmodel_nexus.voyager.type_helper import update_forward_refs


# ── Minimal self-referencing setup ─────────────────────────────────────


class Comment(SQLModel, table=False):
    id: int | None = Field(default=None, primary_key=True)
    content: str
    parent_id: int | None = Field(default=None, foreign_key="comment.id")


class CommentDTO(DefineSubset):
    __subset__ = SubsetConfig(kls=Comment, fields=["id", "content"])
    replies: list["CommentDTO"] = []


# ── Tests ──────────────────────────────────────────────────────────────


class TestVoyagerSelfReference:
    def test_update_forward_refs_on_self_referencing_dto_completes(self):
        """update_forward_refs should handle self-referencing DTOs
        without RecursionError by using a visited-set to avoid cycles."""

        update_forward_refs(CommentDTO)  # should not raise
