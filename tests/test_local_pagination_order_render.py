"""US2 (specs/015 T008): 本地分页关系配 ``__pagination_orders__`` 后, SDL +
``__schema`` 渲染 order enum + direction。

渲染层(``_paginated_field_args`` / ``federation_order_enum_layout``)基于
``RelationshipInfo.page_capability`` 不限 kind——本地分页(LOCAL)配 profile 时
``page_capability`` 非 None, 复用 federation(REMOTE_PAGED)的同一套渲染。
未配 profile 的本地分页关系维持 ``limit/offset``(向后兼容, 已由
test_pagination_mixed 覆盖)。
"""
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel

from nexusx import BatchPageConfig, OrderTerm, PageOrder
from nexusx.loader.registry import ErManager
from nexusx.sdl_generator import SDLGenerator
from tests.conftest import get_test_session_factory


class LPOBase(SQLModel):
    pass


class LPOComment(LPOBase, table=True):
    __tablename__ = "lpo_comment"
    __pagination_orders__ = BatchPageConfig(
        default_order="NEWEST",
        orders={
            "NEWEST": PageOrder([OrderTerm("created_at", "desc")]),
            "MOST_LIKED": PageOrder([OrderTerm("likes", "desc", nulls="last")]),
        },
    )
    id: int | None = Field(default=None, primary_key=True)
    text: str
    likes: int = 0
    created_at: int = 0
    review_id: int = Field(foreign_key="lpo_review.id")
    review: Optional["LPOReview"] = Relationship(back_populates="comments")


class LPOReview(LPOBase, table=True):
    __tablename__ = "lpo_review"
    id: int | None = Field(default=None, primary_key=True)
    title: str
    comments: list["LPOComment"] = Relationship(
        back_populates="review",
        sa_relationship_kwargs={"order_by": "LPOComment.id"},
    )
    # specs/020: comments order profile lives on LPOComment (the sorted object).


LPO_ENTITIES = [LPOReview, LPOComment]


def _make_registry() -> ErManager:
    return ErManager(
        entities=LPO_ENTITIES,
        session_factory=get_test_session_factory(),
        enable_pagination=True,
    )


def test_sdl_renders_order_enum_and_direction():
    """配 __pagination_orders__ 的本地分页关系 → SDL 含 order enum + direction。"""
    registry = _make_registry()
    sdl = SDLGenerator(LPO_ENTITIES).generate(
        enable_pagination=True, loader_registry=registry
    )
    review_block = sdl.split("type LPOReview {", 1)[1].split("}", 1)[0]
    # 字段签名: order enum(默认=default_order) + direction
    assert "order: LPOCommentOrder = NEWEST" in review_block
    assert "direction: Direction" in review_block
    # order enum 类型定义 + 含两个 profile 名
    assert "enum LPOCommentOrder" in sdl
    enum_block = sdl.split("enum LPOCommentOrder {", 1)[1].split("}", 1)[0]
    assert "NEWEST" in enum_block and "MOST_LIKED" in enum_block
    # 共享 Direction enum
    assert "enum Direction" in sdl


def test_order_enum_layout_covers_local():
    """federation_order_enum_layout(SDL 与 __schema 内省共用同一 layout, 不限 kind)
    覆盖本地分页配 profile 的关系 → SC-003 两条渲染路径同源。
    """
    from nexusx.utils.pagination_schema import federation_order_enum_layout

    registry = _make_registry()
    enums, field_name = federation_order_enum_layout(registry, LPO_ENTITIES)
    # 本地分页(LOCAL)配 profile 的关系也被 layout 收录
    assert ("LPOReview", "comments") in field_name
    assert field_name[("LPOReview", "comments")] == "LPOCommentOrder"
    assert "LPOCommentOrder" in enums
    assert "NEWEST" in [v for v in enums["LPOCommentOrder"].__members__]
