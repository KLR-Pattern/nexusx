"""specs/018 T009 — US2 pagination 进 DTO field metadata 单测。

验证 build_response_model 在 paginated package + pagination_metadata 输入时，
把字段类型从 ``{items, pagination}`` shape 升级为
``Annotated[{items, pagination} shape, Paged(...)]``。

跟 γ 路径的 ``Annotated[list[X], Paged(...)]`` 形态对称 —— 区别只在 inner
type（γ 是 ``list[Target]``；entity-first dynamic model 是 ``{items, pagination}``
shape，因为 gql selection 已经把 shape bake 进 result_type）。

覆盖 spec US2 acceptance scenarios 1 + 3（scenario 2 跨 US2+US3 边界，
T013 完成后才能在 Resolver e2e 验证）：
  (a) reviews(limit: 5) + pagination_metadata → Annotated + Paged(limit=5)
  (b) 无 args reviews（无 metadata）→ 裸 result_type（向后兼容）
  (c) reviews(limit: 5, order: HIGHEST_RATING) → metadata 含 order
"""

from typing import Annotated, Optional, get_args, get_origin

import pytest
from pydantic import BaseModel
from sqlmodel import Field, Relationship, SQLModel

from nexusx.loader.pagination import Paged, create_result_type
from nexusx.response_builder import build_response_model


# ──────────────────────────────────────────────────────────
# Test entities
# ──────────────────────────────────────────────────────────


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


# ──────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────


def _paged_metadata_in(field_info: object) -> Paged | None:
    """Return the ``Paged`` marker carried on a pydantic FieldInfo.

    Pydantic v2 ``create_model`` unwraps ``Annotated[X, Paged(...)]``: the
    ``Paged`` marker lands in ``FieldInfo.metadata`` (a list), and
    ``FieldInfo.annotation`` holds only ``X``. The marker survives — the
    in-memory build_response_model consumer (Resolver._extract_paged_metadata
    in T012) reads the same ``FieldInfo.metadata`` list, not the annotation.
    """
    metadata = getattr(field_info, "metadata", None) or []
    for meta in metadata:
        if isinstance(meta, Paged):
            return meta
    # Fallback: some pydantic versions carry it on the annotation directly.
    annotation = getattr(field_info, "annotation", None)
    if annotation is not None and get_origin(annotation) is Annotated:
        for meta in annotation.__metadata__:
            if isinstance(meta, Paged):
                return meta
    return None


# ──────────────────────────────────────────────────────────
# (a) reviews(limit: 5) + pagination_metadata → Annotated + Paged(limit=5)
# ──────────────────────────────────────────────────────────


def test_paginated_field_with_limit_metadata_wraps_in_annotated():
    """(a) gql ``reviews(limit: 5)`` triggers ``Annotated[..., Paged(limit=5)]``."""
    field_tree = {
        "posts": {"items": {"title": None}, "pagination": {"has_more": None}},
    }
    metadata = {"posts": Paged(limit=5)}
    model = build_response_model(
        RB2User, field_tree, pagination_metadata=metadata
    )
    field = model.model_fields["posts"]
    paged = _paged_metadata_in(field)
    assert paged is not None, f"expected Paged metadata on FieldInfo, got metadata={field.metadata!r}"
    assert paged.limit == 5


# ──────────────────────────────────────────────────────────
# (b) 无 args reviews（无 metadata）→ 裸 result_type（向后兼容）
# ──────────────────────────────────────────────────────────


def test_paginated_field_without_metadata_keeps_plain_result_type():
    """(b) paginated package but no ``pagination_metadata`` → no Annotated wrap.

    Backward compatibility with US1: build_response_model callers that don't
    pass ``pagination_metadata`` (e.g. all current callers pre-US2) keep getting
    a plain ``{items, pagination}`` shape, no Annotated metadata wrapping.
    """
    field_tree = {
        "posts": {"items": {"title": None}, "pagination": {"has_more": None}},
    }
    model = build_response_model(RB2User, field_tree)  # no pagination_metadata
    field = model.model_fields["posts"]
    paged = _paged_metadata_in(field)
    assert paged is None, f"expected no Paged metadata, got {paged!r}"
    # Inner shape still {items, pagination}; verify by name match.
    inner = field.annotation
    if get_origin(inner) is Annotated:
        inner = get_args(inner)[0]
    assert hasattr(inner, "model_fields"), f"expected Result pydantic model, got {inner!r}"
    assert "items" in inner.model_fields
    assert "pagination" in inner.model_fields


# ──────────────────────────────────────────────────────────
# (c) reviews(limit: 5, order: HIGHEST_RATING) → metadata 含 order
# ──────────────────────────────────────────────────────────


def test_paginated_field_with_order_metadata_carries_order():
    """(c) gql ``reviews(limit: 5, order: HIGHEST_RATING)`` carries order in metadata."""
    field_tree = {
        "posts": {"items": {"title": None}, "pagination": {"has_more": None}},
    }
    metadata = {"posts": Paged(limit=5, order="HIGHEST_RATING")}
    model = build_response_model(
        RB2User, field_tree, pagination_metadata=metadata
    )
    field = model.model_fields["posts"]
    paged = _paged_metadata_in(field)
    assert paged is not None
    assert paged.limit == 5
    assert paged.order == "HIGHEST_RATING"


# ──────────────────────────────────────────────────────────
# (d) 边界：未在 metadata 里登记的 paginated 字段 → 不包装（向前兼容）
# ──────────────────────────────────────────────────────────


def test_paginated_field_metadata_missing_for_this_field_keeps_plain():
    """pagination_metadata given but key missing → that field stays plain.

    Defensive: caller passes ``pagination_metadata={"other": ...}`` for an
    unrelated field; this field should not silently get an empty Paged wrap.
    """
    field_tree = {
        "posts": {"items": {"title": None}, "pagination": {"has_more": None}},
    }
    metadata = {"unrelated": Paged(limit=10)}
    model = build_response_model(
        RB2User, field_tree, pagination_metadata=metadata
    )
    field = model.model_fields["posts"]
    paged = _paged_metadata_in(field)
    assert paged is None


# ──────────────────────────────────────────────────────────
# (e) T014: _field_sel_to_pagination_metadata — gql args → Paged
# ──────────────────────────────────────────────────────────


def test_field_sel_to_pagination_metadata_derives_paged_from_args():
    """gql ``reviews(limit: 5)`` → ``{"reviews": Paged(limit=5)}`` via FieldSelection.arguments."""
    from nexusx.execution.query_executor import _field_sel_to_pagination_metadata
    from nexusx.query_parser import FieldSelection

    inner = FieldSelection()
    inner.sub_fields = {
        "title": FieldSelection(name="title"),
    }
    pag_sub = FieldSelection()
    pag_sub.sub_fields = {
        "has_more": FieldSelection(name="has_more"),
    }
    posts_sel = FieldSelection(name="posts")
    posts_sel.arguments = {"limit": 5}
    posts_sel.sub_fields = {
        "items": inner,
        "pagination": pag_sub,
    }

    root = FieldSelection()
    root.sub_fields = {"posts": posts_sel}

    metadata = _field_sel_to_pagination_metadata(root)
    assert metadata is not None
    assert "posts" in metadata
    assert metadata["posts"].limit == 5


def test_field_sel_to_pagination_metadata_returns_none_for_no_args():
    """No ``arguments`` on any field → None (US1 backward-compat: caller skips
    pagination_metadata path entirely)."""
    from nexusx.execution.query_executor import _field_sel_to_pagination_metadata
    from nexusx.query_parser import FieldSelection

    posts_sel = FieldSelection(name="posts")
    posts_sel.sub_fields = {
        "items": FieldSelection(),
        "pagination": FieldSelection(),
    }
    root = FieldSelection()
    root.sub_fields = {"posts": posts_sel}

    assert _field_sel_to_pagination_metadata(root) is None


def test_field_sel_to_pagination_metadata_carries_order_and_direction():
    """gql ``reviews(limit: 5, order: HIGHEST_RATING, direction: ASC)`` → all
    four attrs land in the Paged."""
    from nexusx.execution.query_executor import _field_sel_to_pagination_metadata
    from nexusx.query_parser import FieldSelection

    posts_sel = FieldSelection(name="posts")
    posts_sel.arguments = {
        "limit": 5, "order": "HIGHEST_RATING", "direction": "ASC", "offset": 10,
    }
    posts_sel.sub_fields = {"items": FieldSelection(), "pagination": FieldSelection()}
    root = FieldSelection()
    root.sub_fields = {"posts": posts_sel}

    metadata = _field_sel_to_pagination_metadata(root)
    assert metadata is not None
    paged = metadata["posts"]
    assert paged.limit == 5
    assert paged.order == "HIGHEST_RATING"
    assert paged.direction == "ASC"
    assert paged.offset == 10
