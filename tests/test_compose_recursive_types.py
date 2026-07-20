"""Regression tests for recursive DTO types in ``build_compose_schema``.

A Pydantic DTO that references itself — directly (``parent: Self | None``) or
via a container (``children: list[Self]``) — must build without hitting the
Python recursion limit. The same applies to mutual recursion across two
DTOs (``A.b: B``, ``B.a: A``) and to self-referential INPUT_OBJECTs on the
argument side (e.g. a tree-filter input).

This is the same shape as note-tool's ``TagTreeItem`` (children: list[TagTreeItem])
which crashed at app startup. See ``compose_type_mapper.ComposeTypeMapper._register_object``.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from nexusx.decorator import query
from nexusx.use_case.business import UseCaseService
from nexusx.use_case.compose_schema import build_compose_schema
from nexusx.use_case.types import UseCaseAppConfig

# ──────────────────────────────────────────────────────────────────────
# Self-referential DTO (return side → OBJECT)
# ──────────────────────────────────────────────────────────────────────


class TreeNode(BaseModel):
    """A tree node — references itself via list-of-self AND optional self."""

    id: int
    name: str
    children: list[TreeNode] = []
    parent: TreeNode | None = None


class TreeService(UseCaseService):
    @query
    async def get_tree(cls, root_id: int) -> TreeNode | None:
        """Return a tree node with nested children."""
        ...


@pytest.fixture
def tree_app() -> UseCaseAppConfig:
    return UseCaseAppConfig(name="tree", services=[TreeService])


# ──────────────────────────────────────────────────────────────────────
# Mutually-recursive DTOs (A.b → B, B.a → A)
# ──────────────────────────────────────────────────────────────────────


class NodeA(BaseModel):
    id: int
    b: NodeB | None = None


class NodeB(BaseModel):
    id: int
    a: NodeA | None = None


# Forward refs span two class bodies — rebuild after both are defined so
# Pydantic resolves the cross-references rather than leaving them deferred.
NodeA.model_rebuild()
NodeB.model_rebuild()


class MutualService(UseCaseService):
    @query
    async def get_a(cls, aid: int) -> NodeA | None:
        """Return an A with a nested B."""
        ...


@pytest.fixture
def mutual_app() -> UseCaseAppConfig:
    return UseCaseAppConfig(name="mutual", services=[MutualService])


# ──────────────────────────────────────────────────────────────────────
# Self-referential INPUT_OBJECT (argument side → INPUT_OBJECT)
# ──────────────────────────────────────────────────────────────────────


class TreeFilter(BaseModel):
    """A tree-shaped filter used as a method argument (INPUT_OBJECT)."""

    label: str
    children: list[TreeFilter] = []


class TreeFilterService(UseCaseService):
    @query
    async def search(cls, filter: TreeFilter) -> bool:
        """Search nodes matching the filter tree."""
        ...


@pytest.fixture
def input_app() -> UseCaseAppConfig:
    return UseCaseAppConfig(name="input-rec", services=[TreeFilterService])


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


class TestRecursiveDto:
    def test_self_reference_builds_without_recursion_error(self, tree_app) -> None:
        """Building a schema for a self-referential DTO must terminate and
        register the OBJECT once."""
        schema = build_compose_schema(tree_app)
        assert "TreeNode" in schema.registry

    def test_self_reference_field_round_trips(self, tree_app) -> None:
        """``children: list[TreeNode]`` and ``parent: TreeNode | None`` resolve
        to type refs pointing back at the same registered OBJECT, not new types."""
        schema = build_compose_schema(tree_app)
        node_info = schema.registry["TreeNode"]
        field_by_name = {f.name: f for f in node_info.fields}

        children_field = field_by_name["children"]
        # list[TreeNode] → NON_NULL LIST of NON_NULL OBJECT named "TreeNode"
        assert children_field.type_ref.kind == "NON_NULL"
        list_type = children_field.type_ref.of_type
        assert list_type.kind == "LIST"
        inner = list_type.of_type
        assert inner.kind == "NON_NULL"
        assert inner.of_type.kind == "OBJECT"
        assert inner.of_type.name == "TreeNode"

        parent_field = field_by_name["parent"]
        # TreeNode | None → nullable OBJECT pointing at "TreeNode"
        # (nullable = bare OBJECT without NON_NULL wrapper, per mapper convention)
        assert parent_field.type_ref.kind == "OBJECT"
        assert parent_field.type_ref.name == "TreeNode"


class TestMutuallyRecursiveDto:
    def test_mutual_recursion_builds_and_resolves_cross_refs(self, mutual_app) -> None:
        """Mutually-recursive DTOs (A → B → A) must build without recursion,
        and cross-references must resolve back to the registered peer OBJECT."""
        schema = build_compose_schema(mutual_app)
        assert "NodeA" in schema.registry
        assert "NodeB" in schema.registry

        a_b_field = next(f for f in schema.registry["NodeA"].fields if f.name == "b")
        # NodeB | None → nullable OBJECT named "NodeB"
        assert a_b_field.type_ref.kind == "OBJECT"
        assert a_b_field.type_ref.name == "NodeB"

        b_a_field = next(f for f in schema.registry["NodeB"].fields if f.name == "a")
        assert b_a_field.type_ref.kind == "OBJECT"
        assert b_a_field.type_ref.name == "NodeA"


class TestRecursiveInputDto:
    def test_input_self_reference_builds_without_recursion_error(self, input_app) -> None:
        """A self-referential INPUT_OBJECT (e.g. tree-filter input) must build
        without recursion, and the self-reference must resolve back to the
        same INPUT_OBJECT — exercising the symmetric fix in
        ``_register_input_object``, not just ``_register_object``."""
        schema = build_compose_schema(input_app)
        filter_info = schema.registry["TreeFilter"]
        assert filter_info.kind == "INPUT_OBJECT"

        field_by_name = {f.name: f for f in filter_info.input_fields}
        children_field = field_by_name["children"]
        # list[TreeFilter] → NON_NULL LIST of NON_NULL INPUT_OBJECT named "TreeFilter"
        assert children_field.type_ref.kind == "NON_NULL"
        list_type = children_field.type_ref.of_type
        assert list_type.kind == "LIST"
        inner = list_type.of_type
        assert inner.kind == "NON_NULL"
        assert inner.of_type.kind == "INPUT_OBJECT"
        assert inner.of_type.name == "TreeFilter"
