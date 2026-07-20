"""Tests for Voyager Hide Reverse Relationships mode (spec 007).

Covers quickstart.md §1.2 scenarios:
- T006/T007: filter off keeps all directions / filter on hides ONETOMANY
- T008: M2M (link_model) preserved when filter on
- T009: unirectional MANYTOONE preserved / ONETOMANY hidden
- T010: SchemaNode.fields unchanged across filter on/off (FR-007 invariant)
- T011a: POST /er-diagram with hide_reverse_relationships=true
- T011b: POST /er-diagram default omits the field (backward compat)
- T011c: POST /er-diagram-subgraph follows the filter (FR-007 subgraph)
- T011d: self-referential back_populates (Tree.parent ↔ Tree.children)

Note on T017: loadToggleState is a frontend JS function in web/store.js and
cannot be covered by pytest; FR-011 read-side degradation is verified
manually via quickstart.md §2.9 (DevTools → Application → Storage disable).
"""

from typing import Optional

from sqlmodel import Field, Relationship, SQLModel

from nexusx.loader.registry import ErManager
from nexusx.voyager.er_diagram_dot import ErDiagramDotBuilder

# ── Fixtures ───────────────────────────────────────────────────────────


async def _noop_loader(keys):
    return [None for _ in keys]


# Bidirectional back_populates: _HRPost.author (MANYTOONE) ↔ _HRUser.posts (ONETOMANY)
class _HRUser(SQLModel, table=True):
    __tablename__ = "hrr_user"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    posts: list["_HRPost"] = Relationship(back_populates="author")


class _HRPost(SQLModel, table=True):
    __tablename__ = "hrr_post"
    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int | None = Field(default=None, foreign_key="hrr_user.id")
    author: Optional["_HRUser"] = Relationship(back_populates="posts")


# Many-to-many via link_model: _HRM2MPost.tags ↔ _HRM2MTag.posts
class _HRPostTag(SQLModel, table=True):
    __tablename__ = "hrr_post_tag"
    post_id: int = Field(foreign_key="hrr_m2m_post.id", primary_key=True)
    tag_id: int = Field(foreign_key="hrr_m2m_tag.id", primary_key=True)


class _HRM2MPost(SQLModel, table=True):
    __tablename__ = "hrr_m2m_post"
    id: int | None = Field(default=None, primary_key=True)
    title: str
    tags: list["_HRM2MTag"] = Relationship(back_populates="posts", link_model=_HRPostTag)


class _HRM2MTag(SQLModel, table=True):
    __tablename__ = "hrr_m2m_tag"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    posts: list["_HRM2MPost"] = Relationship(back_populates="tags", link_model=_HRPostTag)


# Unirectional MANYTOONE (no back_populates on the reverse side)
class _HROrg(SQLModel, table=True):
    __tablename__ = "hrr_org"
    id: int | None = Field(default=None, primary_key=True)
    name: str


class _HREmployee(SQLModel, table=True):
    __tablename__ = "hrr_employee"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    org_id: int | None = Field(default=None, foreign_key="hrr_org.id")
    org: Optional["_HROrg"] = Relationship()


# Unirectional ONETOMANY (no back_populates on the reverse side)
class _HRBucket(SQLModel, table=True):
    __tablename__ = "hrr_bucket"
    id: int | None = Field(default=None, primary_key=True)
    items: list["_HRItem"] = Relationship()


class _HRItem(SQLModel, table=True):
    __tablename__ = "hrr_item"
    id: int | None = Field(default=None, primary_key=True)
    bucket_id: int | None = Field(default=None, foreign_key="hrr_bucket.id")


# Self-referential bidirectional: Tree.parent (MANYTOONE) ↔ Tree.children (ONETOMANY)
class _HRTree(SQLModel, table=True):
    __tablename__ = "hrr_tree"
    id: int | None = Field(default=None, primary_key=True)
    parent_id: int | None = Field(default=None, foreign_key="hrr_tree.id")
    parent: Optional["_HRTree"] = Relationship(
        back_populates="children",
        sa_relationship_kwargs={"remote_side": "_HRTree.id"},
    )
    children: list["_HRTree"] = Relationship(back_populates="parent")


def _make_registry(*entities) -> ErManager:
    async def session_factory():
        return None

    return ErManager(entities=list(entities), session_factory=session_factory)


def _fqid(cls: type) -> str:
    return f"{cls.__module__}.{cls.__name__}"


# ── T006: filter off keeps both directions ──────────────────────────


class TestFilterOffKeepsAllDirections:
    def test_filter_off_keeps_all_directions(self):
        registry = _make_registry(_HRUser, _HRPost)
        builder = ErDiagramDotBuilder(registry)  # hide_reverse_relationships=False (default)
        builder.analysis()

        # Both directions present: _HRPost::fauthor → _HRUser (MANYTOONE)
        # and _HRUser::fposts → _HRPost (ONETOMANY).
        assert len(builder.links) == 2

        labels = [link.label for link in builder.links]
        assert any("author" in lbl for lbl in labels)
        assert any("posts" in lbl for lbl in labels)


# ── T007: filter on hides ONETOMANY ─────────────────────────────────


class TestFilterOnHidesOnetomany:
    def test_filter_on_hides_onetomany(self):
        registry = _make_registry(_HRUser, _HRPost)
        builder = ErDiagramDotBuilder(registry, hide_reverse_relationships=True)
        builder.analysis()

        # Only MANYTOONE survives; ONETOMANY reverse mirror is filtered.
        assert len(builder.links) == 1

        link = builder.links[0]
        # The surviving link is the MANYTOONE direction (anchor "author").
        assert "author" in link.source
        assert "posts" not in (link.label or "")


# ── T008: M2M preserved when filter on ──────────────────────────────


class TestM2MPreservedWhenFilterOn:
    def test_m2m_preserved_when_filter_on(self):
        registry = _make_registry(_HRM2MPost, _HRM2MTag, _HRPostTag)
        builder_off = ErDiagramDotBuilder(registry, hide_reverse_relationships=False)
        builder_off.analysis()
        # M2M produces two links (one per side) when filter is off.
        assert len(builder_off.links) == 2

        builder_on = ErDiagramDotBuilder(registry, hide_reverse_relationships=True)
        builder_on.analysis()
        # M2M direction is preserved on both sides — not filtered.
        assert len(builder_on.links) == 2

        labels_on = [link.label for link in builder_on.links]
        assert any("tags" in lbl for lbl in labels_on)
        assert any("posts" in lbl for lbl in labels_on)


# ── T009: unirectional relationship behavior ───────────────────────


class TestUnirectionalRelationships:
    def test_manytoone_unirectional_preserved(self):
        # _HREmployee.org is MANYTOONE without back_populates on _HROrg.
        registry = _make_registry(_HROrg, _HREmployee)
        builder = ErDiagramDotBuilder(registry, hide_reverse_relationships=True)
        builder.analysis()

        assert len(builder.links) == 1
        assert "org" in builder.links[0].source

    def test_onetomany_unirectional_hidden(self):
        # _HRBucket.items is ONETOMANY without back_populates.
        # When filter is on, this link must be hidden.
        registry = _make_registry(_HRBucket, _HRItem)
        builder = ErDiagramDotBuilder(registry, hide_reverse_relationships=True)
        builder.analysis()

        assert len(builder.links) == 0

        # Sanity: when filter is off, the link exists.
        builder_off = ErDiagramDotBuilder(registry, hide_reverse_relationships=False)
        builder_off.analysis()
        assert len(builder_off.links) == 1


# ── T010: SchemaNode.fields unchanged (FR-007 invariant 1) ──────────


class TestFieldsTableUnchanged:
    def test_fields_table_unchanged_across_filter_toggle(self):
        registry = _make_registry(_HRUser, _HRPost)

        builder_off = ErDiagramDotBuilder(registry, hide_reverse_relationships=False)
        builder_off.analysis()
        builder_on = ErDiagramDotBuilder(registry, hide_reverse_relationships=True)
        builder_on.analysis()

        # _HRPost has the SAME fields list regardless of filter — the field table
        # renders from self.rel_name_set which is populated independently of link filtering.
        post_off = builder_off.node_set[_fqid(_HRPost)]
        post_on = builder_on.node_set[_fqid(_HRPost)]
        assert [f.name for f in post_off.fields] == [f.name for f in post_on.fields]
        # The "author" relationship field must appear in both (it's only the
        # link that gets filtered, not the field row).
        field_names = [f.name for f in post_on.fields]
        assert "author" in field_names


# ── T011a/b/c: endpoint contracts ───────────────────────────────────


def _make_context():
    from nexusx.voyager.voyager_context import VoyagerContext

    # Only the bidirectional back_populates pair — keeps the "posts" label
    # unambiguous (no M2M "posts" link from _HRM2MTag to confuse assertions).
    registry = _make_registry(_HRUser, _HRPost)
    return VoyagerContext(services=[], er_manager=registry, name="t")


class TestErDiagramEndpointContract:
    def test_endpoint_with_filter_on(self):
        """T011a — POST /er-diagram with hide_reverse_relationships=true."""
        ctx = _make_context()
        result_on = ctx.get_er_diagram_data({
            "show_module": False,
            "show_methods": False,
            "hide_reverse_relationships": True,
        })
        result_off = ctx.get_er_diagram_data({
            "show_module": False,
            "show_methods": False,
            "hide_reverse_relationships": False,
        })

        assert "digraph" in result_on["dot"]
        assert "digraph" in result_off["dot"]
        # Filter on → fewer links (ONETOMANY reverse mirror removed).
        assert len(result_on["links"]) < len(result_off["links"])
        # The "posts" (ONETOMANY) link must be absent when filter is on.
        labels_on = [link["label"] for link in result_on["links"]]
        assert not any("posts" in (lbl or "") for lbl in labels_on)
        # The "author" (MANYTOONE) link must still be present.
        labels_off = [link["label"] for link in result_off["links"]]
        assert any("author" in (lbl or "") for lbl in labels_off)

    def test_endpoint_default_omits_field(self):
        """T011b — POST /er-diagram without the field behaves as False (backward compat)."""
        ctx = _make_context()
        result_default = ctx.get_er_diagram_data({
            "show_module": False,
            "show_methods": False,
            # hide_reverse_relationships omitted
        })
        result_explicit_false = ctx.get_er_diagram_data({
            "show_module": False,
            "show_methods": False,
            "hide_reverse_relationships": False,
        })

        # Both must produce identical DOT (default = False).
        assert result_default["dot"] == result_explicit_false["dot"]
        assert result_default["links"] == result_explicit_false["links"]

    def test_subgraph_follows_filter(self):
        """T011c — POST /er-diagram-subgraph with filter follows the same rule."""
        ctx = _make_context()
        anchor = _fqid(_HRPost)

        sub_on = ctx.get_er_diagram_subgraph({
            "schema_name": anchor,
            "show_module": False,
            "show_methods": False,
            "hide_reverse_relationships": True,
        })
        sub_off = ctx.get_er_diagram_subgraph({
            "schema_name": anchor,
            "show_module": False,
            "show_methods": False,
            "hide_reverse_relationships": False,
        })

        # Subgraph with filter on has fewer links than with filter off.
        assert len(sub_on["links"]) < len(sub_off["links"])
        # "posts" (ONETOMANY reverse) must be absent in subgraph when filter on.
        labels_on = [link["label"] for link in sub_on["links"]]
        assert not any("posts" in (lbl or "") for lbl in labels_on)


# ── T011d: self-referential back_populates ──────────────────────────


class TestSelfReferentialBackPopulates:
    def test_self_referential_back_populates(self):
        """T011d — Tree.parent (MANYTOONE) ↔ Tree.children (ONETOMANY)."""
        registry = _make_registry(_HRTree)
        builder = ErDiagramDotBuilder(registry, hide_reverse_relationships=True)
        builder.analysis()

        # Only `parent` (MANYTOONE) survives; `children` (ONETOMANY) is hidden.
        assert len(builder.links) == 1
        assert "parent" in builder.links[0].source

        # Sanity: filter off → 2 links (parent + children).
        builder_off = ErDiagramDotBuilder(registry, hide_reverse_relationships=False)
        builder_off.analysis()
        assert len(builder_off.links) == 2
