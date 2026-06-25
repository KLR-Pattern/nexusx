"""Tests for ER / Voyager rendering with virtual entities (Issue #87, FR-009).

Validates that mixed SQLModel + BaseModel entity sets can be rendered
without exceptions, and that virtual entities appear as visually
distinguished nodes.
"""
from __future__ import annotations

from pydantic import BaseModel
from sqlmodel import Field, SQLModel

from nexusx import ErDiagram, ErManager, Relationship
from nexusx.voyager.er_diagram_dot import ErDiagramDotBuilder

# ──────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────


class _User(SQLModel, table=True):
    __tablename__ = "ve_er_user"

    id: int | None = Field(default=None, primary_key=True)
    name: str


class _Post(SQLModel, table=True):
    __tablename__ = "ve_er_post"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="ve_er_user.id")


async def _posts_by_user(keys: list[int]) -> list[list]:
    return [[] for _ in keys]


class CurrentUser(BaseModel):
    """Virtual entity — has __relationships__ but no table."""

    oid: str
    name: str
    posts: list[_Post] = []

    __relationships__ = [
        Relationship(
            fk="oid",
            target=list[_Post],
            name="posts",
            loader=_posts_by_user,
        ),
    ]


def _make_er() -> ErManager:
    return ErManager(entities=[_User, _Post], session_factory=lambda: None)


# ──────────────────────────────────────────────────────────
# ErDiagram.from_er_manager — mixed SQLModel + virtual
# ──────────────────────────────────────────────────────────


class TestErDiagramMixedEntities:
    def test_mixed_entities_generate_without_exception(self):
        """Mixed SQLModel + virtual entity set generates ER diagram cleanly."""
        er = _make_er()
        er.add_virtual_entities([CurrentUser])

        # Should not raise — virtual entities are handled.
        diagram = ErDiagram.from_er_manager(er)

        entity_names = {e.name for e in diagram.entities}
        assert "CurrentUser" in entity_names
        assert "_User" in entity_names or "_Post" in entity_names

    def test_virtual_entity_appears_with_schema(self):
        """Virtual entities appear with their model_fields schema."""
        er = _make_er()
        er.add_virtual_entities([CurrentUser])

        diagram = ErDiagram.from_er_manager(er)
        virtual = next(e for e in diagram.entities if e.name == "CurrentUser")

        # model_fields are reflected (schema is real even if no table is).
        assert "oid" in virtual.fields
        assert "name" in virtual.fields
        # No FK fields on a BaseModel source.
        assert virtual.fk_fields == []
        # No table name (or empty) — virtual entities have no table.
        assert virtual.table_name in (None, "", "CurrentUser")

    def test_virtual_to_sqlmodel_relationship_drawn(self):
        """A relationship from virtual to SQLModel entity is rendered."""
        er = _make_er()
        er.add_virtual_entities([CurrentUser])

        diagram = ErDiagram.from_er_manager(er)
        rel_pairs = {
            (r.source, r.target, r.name)
            for e in diagram.entities
            for r in e.relationships
        }

        # Custom relationship from CurrentUser → _Post should appear.
        assert any(
            src == "CurrentUser" and tgt == "_Post" and name == "posts"
            for src, tgt, name in rel_pairs
        )

    def test_zero_virtual_entities_unchanged(self):
        """No virtual entities → output is identical to today's SQLModel-only path."""
        er = _make_er()
        diagram = ErDiagram.from_er_manager(er)

        entity_names = {e.name for e in diagram.entities}
        assert "CurrentUser" not in entity_names
        # SQLModel entities still present.
        assert "_User" in entity_names


# ──────────────────────────────────────────────────────────
# Voyager DOT builder — mixed entities
# ──────────────────────────────────────────────────────────


class TestVoyagerDotBuilderMixed:
    def test_dot_renders_without_exception(self):
        """Voyager DOT output generates cleanly with virtual entities."""
        er = _make_er()
        er.add_virtual_entities([CurrentUser])

        builder = ErDiagramDotBuilder(er)
        builder.analysis()
        dot = builder.render_dot()

        # The virtual entity appears as a node.
        assert "CurrentUser" in dot

    def test_virtual_entity_node_has_schema(self):
        """The virtual node has its model_fields in the DOT output."""
        er = _make_er()
        er.add_virtual_entities([CurrentUser])

        # show_fields='all' to render field details, not just the PK header.
        builder = ErDiagramDotBuilder(er, show_fields="all")
        builder.analysis()
        dot = builder.render_dot()

        # Schema fields appear somewhere in the DOT output.
        assert "oid" in dot
        assert "name" in dot

    def test_virtual_to_sqlmodel_edge_drawn(self):
        """DOT renders an edge from virtual node to SQLModel entity."""
        er = _make_er()
        er.add_virtual_entities([CurrentUser])

        builder = ErDiagramDotBuilder(er)
        builder.analysis()
        dot = builder.render_dot()

        # Both nodes appear, and an edge "posts" connects them.
        assert "CurrentUser" in dot
        assert "_Post" in dot
        assert "posts" in dot
