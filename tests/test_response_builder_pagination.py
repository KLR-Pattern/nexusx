"""specs/018 T009 / 020 — build_response_model paged package shape 单测。

020 后 model 是纯形状容器:paged 字段(paginated-package field_tree)→ plain
``result_type``({items, pagination} shape),**无 Paged marker**。paged 检测在
dispatch 用 ``rel_info.page_loader``,值经 ``paged_provider`` 注入(见
``test_paged_provider.py``)。本文件只验证 shape;marker / pagination_metadata
注入相关的旧断言已随 020 删除(model 不再携带 paged 信息)。
"""

from typing import Optional

from sqlmodel import Field, Relationship, SQLModel

from nexusx.response_builder import build_response_model


class RB2User(SQLModel, table=True):
    __tablename__ = "rb2_user"

    id: int | None = Field(default=None, primary_key=True)
    name: str

    posts: list["RB2Post"] = Relationship(  # type: ignore[type-arg]
        back_populates="author",
        sa_relationship_kwargs={"order_by": "RB2Post.id"},
    )


class RB2Post(SQLModel, table=True):
    __tablename__ = "rb2_post"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="rb2_user.id")

    author: Optional["RB2User"] = Relationship(back_populates="posts")


def test_paginated_package_field_renders_result_type_shape():
    """paginated-package field_tree → plain ``result_type`` ({items, pagination}).

    specs/020: paged fields are plain result_type (no Annotated marker). Paged
    detection at dispatch uses rel_info.page_loader; paged values come from
    paged_provider. The model only carries the {items, pagination} shape.
    """
    field_tree = {
        "posts": {"items": {"title": None}, "pagination": {"has_more": None}},
    }
    model = build_response_model(RB2User, field_tree)
    field = model.model_fields["posts"]
    inner = field.annotation
    assert hasattr(inner, "model_fields"), f"expected Result pydantic model, got {inner!r}"
    assert "items" in inner.model_fields
    assert "pagination" in inner.model_fields
