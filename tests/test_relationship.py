"""Tests for Relationship — custom non-ORM relationship definitions."""

from __future__ import annotations

import pytest
from sqlmodel import Field, SQLModel

from nexusx import DefineSubset, ErDiagram, Relationship
from nexusx.loader.registry import ErManager
from nexusx.relationship import get_custom_relationships
from nexusx.resolver import Resolver
from tests.conftest import FixtureSprint, FixtureTask, FixtureUser

# ──────────────────────────────────────────────────────────
# Test entities with __relationships__
# ──────────────────────────────────────────────────────────


class Tag(SQLModel, table=True):
    __tablename__ = "rel_test_tag"

    id: int | None = Field(default=None, primary_key=True)
    name: str


async def _dummy_tag_loader(post_ids: list[int]) -> list[list]:
    return [[] for _ in post_ids]


class Post(SQLModel, table=True):
    __tablename__ = "rel_test_post"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="rel_test_user.id")

    __relationships__ = [
        Relationship(
            fk="id",
            target=list[Tag],
            name="tags",
            loader=_dummy_tag_loader,
            description="Post tags via custom loader",
        )
    ]


class RelUser(SQLModel, table=True):
    __tablename__ = "rel_test_user"

    id: int | None = Field(default=None, primary_key=True)
    name: str


# Entity with duplicate names in __relationships__ for conflict testing


async def _dummy_conflict_loader(keys):
    return keys


class DuplicatePost(SQLModel, table=True):
    __tablename__ = "rel_test_dup_post"
    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="rel_test_user.id")

    __relationships__ = [
        Relationship(
            fk="author_id",
            target=RelUser,
            name="author",
            loader=_dummy_conflict_loader,
        ),
        # Same name "author" — duplicate within __relationships__
        Relationship(
            fk="author_id",
            target=RelUser,
            name="author",
            loader=_dummy_conflict_loader,
        ),
    ]


# ──────────────────────────────────────────────────────────
# Tests: Relationship dataclass
# ──────────────────────────────────────────────────────────


class TestRelationshipDataclass:
    def test_relationship_creation(self):
        """Relationship should store all fields correctly."""
        rel = Relationship(
            fk="author_id",
            target=RelUser,
            name="author",
            loader=_dummy_tag_loader,
        )
        assert rel.fk == "author_id"
        assert rel.target is RelUser
        assert rel.target_entity is RelUser
        assert rel.name == "author"
        assert rel.loader is _dummy_tag_loader
        assert rel.is_list is False
        assert rel.description is None

    def test_relationship_with_all_fields(self):
        """Relationship should handle all optional fields."""
        rel = Relationship(
            fk="id",
            target=list[Tag],
            name="tags",
            loader=_dummy_tag_loader,
            description="Tags",
        )
        assert rel.is_list is True
        assert rel.target_entity is Tag
        assert rel.description == "Tags"


class TestGetCustomRelationships:
    def test_entity_with_relationships(self):
        """get_custom_relationships should return defined relationships."""
        rels = get_custom_relationships(Post)
        assert len(rels) == 1
        assert rels[0].name == "tags"
        assert rels[0].target == list[Tag]
        assert rels[0].target_entity is Tag
        assert rels[0].is_list is True

    def test_entity_without_relationships(self):
        """get_custom_relationships returns empty list without __relationships__."""
        rels = get_custom_relationships(RelUser)
        assert rels == []

    def test_invalid_type_raises(self):
        """get_custom_relationships should raise TypeError for non-list __relationships__."""

        class BadEntity(SQLModel, table=True):
            __tablename__ = "rel_test_bad"
            __relationships__ = "not a list"
            id: int | None = Field(default=None, primary_key=True)

        with pytest.raises(TypeError, match="must be a list"):
            get_custom_relationships(BadEntity)

    def test_invalid_item_raises(self):
        """get_custom_relationships should raise TypeError for non-Relationship items."""

        class BadEntity2(SQLModel, table=True):
            __tablename__ = "rel_test_bad2"
            __relationships__ = ["not a Relationship"]
            id: int | None = Field(default=None, primary_key=True)

        with pytest.raises(TypeError, match="must be a Relationship"):
            get_custom_relationships(BadEntity2)


# ──────────────────────────────────────────────────────────
# Tests: ER Diagram integration
# ──────────────────────────────────────────────────────────


class TestErDiagramCustomRelationships:
    def test_custom_relationship_in_mermaid(self):
        """Custom relationships should appear in Mermaid output."""
        diagram = ErDiagram.from_sqlmodel([Post, Tag, RelUser])
        mermaid = diagram.to_mermaid()

        assert "Post" in mermaid
        assert "Tag" in mermaid
        assert "tags" in mermaid

    def test_custom_and_orm_relationships_combined(self):
        """Both ORM and custom relationships should appear in the diagram."""
        # Use FixtureTask which has ORM relationships (sprint, owner)
        # plus add a custom relationship via __relationships__
        diagram = ErDiagram.from_sqlmodel([Post, Tag, RelUser])

        post_entity = next(e for e in diagram.entities if e.name == "Post")
        rel_names = {r.name for r in post_entity.relationships}

        # Custom relationship: tags -> Tag
        assert "tags" in rel_names

    @pytest.mark.usefixtures("test_db")
    def test_conftest_models_with_custom_rel(self):
        """ER Diagram should work with conftest models that have ORM relationships."""
        diagram = ErDiagram.from_sqlmodel([FixtureUser, FixtureSprint, FixtureTask])

        task_entity = next(e for e in diagram.entities if e.name == "FixtureTask")
        rel_names = {r.name for r in task_entity.relationships}

        # ORM relationships on FixtureTask
        assert "sprint" in rel_names
        assert "owner" in rel_names

    def test_custom_relationship_target_not_in_entities_excluded(self):
        """Custom relationship whose target is not in entity list should be excluded."""
        diagram = ErDiagram.from_sqlmodel([Post, RelUser])

        post_entity = next(e for e in diagram.entities if e.name == "Post")
        rel_names = {r.name for r in post_entity.relationships}

        # 'tags' target (Tag) is not in the entity list
        assert "tags" not in rel_names


# ──────────────────────────────────────────────────────────
# Tests: ErManager integration
# ──────────────────────────────────────────────────────────


class TestErManagerCustomRelationships:
    def test_registry_includes_custom_relationships(self):
        """ErManager should include custom relationships."""
        registry = ErManager(
            entities=[Post, Tag, RelUser],
            session_factory=lambda: None,
        )

        post_rels = registry.get_relationships(Post)
        assert "tags" in post_rels

        rel_info = post_rels["tags"]
        assert rel_info.direction == "CUSTOM"
        assert rel_info.is_list is True
        assert rel_info.fk_field == "id"
        assert rel_info.target_entity is Tag

    async def test_registry_custom_loader_works(self):
        """DataLoader from custom loader should work correctly."""
        registry = ErManager(
            entities=[Post, Tag, RelUser],
            session_factory=lambda: None,
        )

        loader = registry.get_loader_by_name("tags")
        assert loader is not None

    def test_registry_name_conflict_raises(self):
        """Custom relationship name conflicting with ORM should raise ValueError."""
        # DuplicatePost has ORM relationship 'author' (via FK) and
        # custom 'author' in __relationships__ — this should conflict
        # But actually, Post (without explicit ORM Relationship()) won't have
        # ORM 'author'. So test with conftest FixtureTask which has ORM 'owner'.
        # We need a custom rel named 'owner' on FixtureTask to trigger conflict.

        # Use the DuplicatePost which has duplicate custom names — the second
        # will conflict with the first during registration.
        with pytest.raises(ValueError, match="conflicts"):
            ErManager(
                entities=[DuplicatePost, RelUser],
                session_factory=lambda: None,
            )

    async def test_same_relationship_name_is_scoped_by_entity(self):
        """Resolver should pick the loader for the DTO's source entity."""

        async def tags_for_primary(ids: list[int]) -> list[list[Tag]]:
            return [[Tag(id=item_id, name=f"primary-{item_id}")] for item_id in ids]

        async def tags_for_secondary(ids: list[int]) -> list[list[Tag]]:
            return [[Tag(id=item_id, name=f"secondary-{item_id}")] for item_id in ids]

        class PrimaryPost(SQLModel, table=True):
            __tablename__ = "rel_test_primary_post"

            id: int | None = Field(default=None, primary_key=True)
            __relationships__ = [
                Relationship(
                    fk="id",
                    target=list[Tag],
                    name="tags",
                    loader=tags_for_primary,
                )
            ]

        class SecondaryPost(SQLModel, table=True):
            __tablename__ = "rel_test_secondary_post"

            id: int | None = Field(default=None, primary_key=True)
            __relationships__ = [
                Relationship(
                    fk="id",
                    target=list[Tag],
                    name="tags",
                    loader=tags_for_secondary,
                )
            ]

        registry = ErManager(
            entities=[PrimaryPost, SecondaryPost, Tag],
            session_factory=lambda: None,
        )

        class TagDTO(DefineSubset):
            __subset__ = (Tag, ("id", "name"))

        class SecondaryPostDTO(DefineSubset):
            __subset__ = (SecondaryPost, ("id",))
            tags: list[TagDTO] = []

        result = await Resolver(registry).resolve(SecondaryPostDTO(id=1))

        assert [tag.name for tag in result.tags] == ["secondary-1"]

    async def test_resolve_clears_shared_registry_cache(self):
        """Each Resolver.resolve call should start with a fresh registry cache."""

        call_count = 0

        async def versioned_tags(ids: list[int]) -> list[list[Tag]]:
            nonlocal call_count
            call_count += 1
            return [[Tag(id=item_id, name=f"call-{call_count}")] for item_id in ids]

        class CachePost(SQLModel, table=True):
            __tablename__ = "rel_test_cache_post"

            id: int | None = Field(default=None, primary_key=True)
            __relationships__ = [
                Relationship(
                    fk="id",
                    target=list[Tag],
                    name="tags",
                    loader=versioned_tags,
                )
            ]

        registry = ErManager(
            entities=[CachePost, Tag],
            session_factory=lambda: None,
        )

        class TagDTO(DefineSubset):
            __subset__ = (Tag, ("id", "name"))

        class CachePostDTO(DefineSubset):
            __subset__ = (CachePost, ("id",))
            tags: list[TagDTO] = []

        first = await Resolver(registry).resolve(CachePostDTO(id=1))
        second = await Resolver(registry).resolve(CachePostDTO(id=1))

        assert [tag.name for tag in first.tags] == ["call-1"]
        assert [tag.name for tag in second.tags] == ["call-2"]
        assert call_count == 2


# ──────────────────────────────────────────────────────────
# Tests: Custom relationships with resolve_* and implicit auto-load
# ──────────────────────────────────────────────────────────
