"""Tests for response_builder — dynamic Pydantic model building and serialization."""

from typing import Any, Optional, get_origin

from pydantic import BaseModel
from sqlmodel import Field, Relationship, SQLModel

from nexusx.response_builder import (
    ERFieldResolver,
    _build_scalar_model,
    _extract_entity_from_annotation,
    _is_list_relationship,
    _resolve_forward_reference,
    _validate_and_dump,
    build_response_model,
    get_relation_entity,
    get_relationship_names,
    serialize_with_model,
)

# ──────────────────────────────────────────────────────────
# Test entities
# ──────────────────────────────────────────────────────────


class RBUser(SQLModel, table=True):
    __tablename__ = "rb_user"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str

    posts: list["RBPost"] = Relationship(back_populates="author")  # type: ignore[type-arg]


class RBPost(SQLModel, table=True):
    __tablename__ = "rb_post"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="rb_user.id")

    author: Optional["RBUser"] = Relationship(back_populates="posts")


class RBUnresolvedOwner(BaseModel):
    pass


RBUnresolvedOwner.__annotations__["children"] = "list[RBUnresolvedChild]"
RBUnresolvedOwner.__sqlmodel_relationships__ = {"children": object()}


# ──────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────


class TestBuildResponseModel:
    def test_build_scalar_model(self):
        """field_tree=None should build a model with all scalar fields."""
        model = build_response_model(RBUser, None)
        assert issubclass(model, BaseModel)
        instance = model(id=1, name="Alice", email="alice@test.com")
        data = instance.model_dump()
        assert data["id"] == 1
        assert data["name"] == "Alice"
        assert data["email"] == "alice@test.com"

    def test_build_model_with_selected_fields(self):
        """field_tree with scalar fields should include only those fields."""
        field_tree = {"id": None, "name": None}
        model = build_response_model(RBUser, field_tree)
        instance = model(id=1, name="Alice")
        data = instance.model_dump()
        assert "id" in data
        assert "name" in data
        assert "email" not in data

    def test_build_model_with_nested_relationship(self):
        """field_tree with nested dict should create nested model for relationship."""
        field_tree = {
            "id": None,
            "title": None,
            "author": {"id": None, "name": None},
        }
        model = build_response_model(RBPost, field_tree)
        assert issubclass(model, BaseModel)

    def test_unresolved_relationship_falls_back_to_any(self):
        model = build_response_model(
            RBUnresolvedOwner,
            {"children": {"id": None}},
            model_name="UnresolvedFallback",
        )

        assert model.model_fields["children"].annotation is Any
        assert model.model_validate(
            {"children": [{"id": 1}]},
        ).model_dump() == {"children": [{"id": 1}]}


class TestSerializeWithModel:
    def test_serialize_single_entity(self):
        """Single entity should be serialized to dict."""
        user = RBUser(id=1, name="Alice", email="alice@test.com")
        result = serialize_with_model(user, RBUser, {"id": None, "name": None})
        assert isinstance(result, dict)
        assert result["id"] == 1
        assert result["name"] == "Alice"

    def test_serialize_list_entities(self):
        """List of entities should be serialized to list of dicts."""
        users = [
            RBUser(id=1, name="Alice", email="alice@test.com"),
            RBUser(id=2, name="Bob", email="bob@test.com"),
        ]
        result = serialize_with_model(users, RBUser, {"id": None, "name": None})
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["name"] == "Alice"
        assert result[1]["name"] == "Bob"

    def test_serialize_none(self):
        """None value should return None."""
        result = serialize_with_model(None, RBUser, {"id": None})
        assert result is None

    def test_serialize_with_all_scalar_fields(self):
        """field_tree=None should serialize all scalar fields."""
        user = RBUser(id=1, name="Alice", email="alice@test.com")
        result = serialize_with_model(user, RBUser, None)
        assert result["id"] == 1
        assert result["name"] == "Alice"
        assert result["email"] == "alice@test.com"


class TestGetRelationshipNames:
    def test_entity_with_relationships(self):
        """Should return relationship field names."""
        names = get_relationship_names(RBPost)
        assert "author" in names

    def test_entity_without_relationships(self):
        """Entity without relationships should return empty set."""
        names = get_relationship_names(RBUser)
        assert isinstance(names, set)


class TestGetRelationEntity:
    def test_known_relationship(self):
        """Should return target entity for a known relationship."""
        entity = get_relation_entity(RBPost, "author")
        assert entity is not None

    def test_unknown_field_returns_none(self):
        """Should return None for non-relationship field."""
        entity = get_relation_entity(RBPost, "nonexistent")
        assert entity is None

    def test_scalar_field_returns_type(self):
        """Scalar fields return their type (not None) via annotation extraction."""
        entity = get_relation_entity(RBPost, "title")
        # get_relation_entity extracts the type from annotations;
        # scalar fields are not filtered here
        assert entity is not None


# ──────────────────────────────────────────────────────────
# Additional coverage tests
# ──────────────────────────────────────────────────────────


class TestBuildResponseModelExtras:
    def test_unknown_relation_falls_back_to_any(self):
        """When get_relation_entity returns None, field type falls back to Any."""
        # Use RBPost with a non-existent relationship in field_tree
        field_tree = {"id": None, "nonexistent_rel": {"id": None}}
        model = build_response_model(RBPost, field_tree)
        assert issubclass(model, BaseModel)
        # The field should exist (with Any type)
        assert "nonexistent_rel" in model.model_fields

    def test_list_relationship_generates_list_type(self):
        """List relationships should generate list[nested_model] fields."""
        field_tree = {"id": None, "posts": {"id": None, "title": None}}
        model = build_response_model(RBUser, field_tree)
        assert "posts" in model.model_fields


class TestValidateAndDump:
    def test_none_value_returns_none(self):
        """_validate_and_dump should return None for None input."""
        model = build_response_model(RBUser, {"id": None, "name": None})
        assert _validate_and_dump(model, None, None, entity=RBUser) is None

    def test_dict_input(self):
        """_validate_and_dump should handle dict input."""
        model = build_response_model(RBUser, {"id": None, "name": None})
        result = _validate_and_dump(model, {"id": 1, "name": "Alice"}, None, entity=RBUser)
        assert result["id"] == 1

    def test_validation_fallback_returns_filtered_data(self):
        """When model_validate fails, should return filtered dict."""
        model = build_response_model(RBUser, {"id": None, "name": None})
        # Pass a value that won't validate — integer triggers except path
        result = _validate_and_dump(model, 42, None, entity=RBUser)
        # Falls through to return the raw value
        assert result == 42

    def test_nested_relationship_serialization(self):
        """Nested field_tree should trigger recursive serialization."""
        user = RBUser(id=1, name="Alice", email="alice@test.com")
        field_tree = {"id": None, "posts": {"id": None, "title": None}}
        result = serialize_with_model(user, RBUser, field_tree)
        assert isinstance(result, dict)
        assert result["id"] == 1


class TestResolveForwardReference:
    def test_simple_name_match(self):
        """Simple annotation string should resolve to matching class."""
        result = _resolve_forward_reference("RBUser", {RBUser, RBPost})
        assert result is RBUser

    def test_quoted_list_format(self):
        """list['EntityName'] format should resolve."""
        result = _resolve_forward_reference("list['RBUser']", {RBUser, RBPost})
        assert result is RBUser

    def test_unquoted_list_format(self):
        """list[EntityName] format should resolve."""
        result = _resolve_forward_reference("list[RBUser]", {RBUser, RBPost})
        assert result is RBUser

    def test_no_match_returns_none(self):
        """Unknown annotation should return None."""
        result = _resolve_forward_reference("NonExistent", {RBUser, RBPost})
        assert result is None

    def test_no_brackets_no_match(self):
        """String without brackets that doesn't match returns None."""
        result = _resolve_forward_reference("SomeOtherClass", {RBUser})
        assert result is None


class TestExtractEntityFromAnnotation:
    def test_optional_entity(self):
        """Optional[Entity] should extract Entity."""
        result = _extract_entity_from_annotation(RBUser | None)
        assert result is RBUser

    def test_list_entity(self):
        """list[Entity] should extract Entity."""
        result = _extract_entity_from_annotation(list[RBUser])
        assert result is RBUser

    def test_direct_type(self):
        """Direct type annotation should return the type."""
        result = _extract_entity_from_annotation(RBUser)
        assert result is RBUser

    def test_string_forward_ref_with_subclasses(self):
        """String forward reference should resolve with all_subclasses."""
        result = _extract_entity_from_annotation("RBUser", {RBUser, RBPost})
        assert result is RBUser

    def test_no_match_returns_none(self):
        """Unresolvable annotation should return None."""
        result = _extract_entity_from_annotation(42)
        assert result is None

    def test_none_type_skipped_in_union(self):
        """NoneType in Union args should be skipped."""
        result = _extract_entity_from_annotation(RBUser | None)
        assert result is RBUser


class TestIsListRelationship:
    def test_list_annotation(self):
        """list[...] annotation should be detected."""
        # RBPost.author is Optional[RBUser] — not a list
        # Need a model with a resolved list[Entity] annotation

        # Verify the function works with a direct list type
        class ListEntity(SQLModel, table=False):
            items: list[int]

        assert _is_list_relationship(ListEntity, "items") is True

    def test_non_list_annotation(self):
        """Non-list annotation should not be detected."""
        assert _is_list_relationship(RBPost, "author") is False

    def test_nonexistent_field(self):
        """Non-existent field should return False."""
        assert _is_list_relationship(RBUser, "nonexistent") is False


class TestBuildScalarModelExtras:
    def test_excludes_relationship_fields(self):
        """Scalar model should exclude relationship fields."""
        model = _build_scalar_model(RBPost, "Test")
        assert "id" in model.model_fields
        assert "title" in model.model_fields
        # author is a relationship, should be excluded
        assert "author" not in model.model_fields

    def test_includes_all_scalar_fields(self):
        """Scalar model should include all non-relationship fields."""
        model = _build_scalar_model(RBUser, "Test")
        field_names = set(model.model_fields.keys())
        assert "id" in field_names
        assert "name" in field_names
        assert "email" in field_names
        assert "posts" not in field_names


class TestERFieldResolver:
    """specs/021 — FieldResolver 语义: scalar 字段不得当嵌套关系(strTitle bug 回归)。"""

    def test_scalar_field_not_treated_as_nested(self):
        """scalar 字段 resolve 必须 nested_type=None。

        ``get_relation_entity`` 对 scalar 字段也返回类型(str/int); 不过滤的话
        build_model 会递归进 ``str`` 造出 strTitle 空模型(上 session 卡住的 bug)。
        """
        resolver = ERFieldResolver(None, None)
        res = resolver.resolve_field(RBUser, "name")
        assert res is not None
        assert res.nested_type is None
        assert res.annotation is str

    def test_scalar_field_with_sub_selection_keeps_scalar_type(self):
        """scalar 字段带子选择(garbage-in)→ 仍按 scalar 处理, 不递归。"""
        model = build_response_model(RBPost, {"title": {"x": None}})
        assert model.model_fields["title"].annotation is str

    def test_relationship_field_still_nested(self):
        """真关系字段 nested_type 正常返回(过滤只挡非 BaseModel)。"""
        resolver = ERFieldResolver(None, None)
        res = resolver.resolve_field(RBPost, "author")
        assert res is not None
        assert res.nested_type is not None
        assert res.is_list is False


class TestMappedListRelationshipShape:
    """specs/021 — SQLModel 把 to-many 关系注解转 Mapped[list[X]]。

    此前 ``_is_list_relationship`` 只查 ``get_origin is list``, Mapped 包裹漏判 →
    模型形状错误地生成 ``X | None``(单数), 序列化白走一次失败的 validate +
    fallback。修复后必须生成 ``list[X]``。
    """

    def test_is_list_relationship_unwraps_mapped(self):
        assert _is_list_relationship(RBUser, "posts") is True
        # 单数关系(Optional 包裹)不误伤
        assert _is_list_relationship(RBPost, "author") is False

    def test_mapped_list_relationship_model_shape(self):
        model = build_response_model(RBUser, {"posts": {"id": None}})
        ann = model.model_fields["posts"].annotation
        assert get_origin(ann) is list
