"""Federation order/direction (specs/014) — member-side unit tests.

Covers ``_apply_direction`` (direction flip + nulls follow) and the
single-column ``PageOrder`` constraint. Mounter end-to-end (透传 + member 排序)
and schema-discovery tests are added alongside in later tasks (T013/T014/T015).
"""

import pytest
from sqlmodel import Field, SQLModel

from nexusx.standard_queries import (
    BatchPageConfig,
    Direction,
    OrderTerm,
    PageOrder,
    _apply_direction,
    _resolve_page_orders,
    _ResolvedOrderTerm,
)


# ── _apply_direction: direction flip + nulls follow ──────────────────────


def test_apply_direction_none_keeps_profile_default():
    terms = (_ResolvedOrderTerm("rating", "desc", "last"),)
    assert _apply_direction(terms, None) == terms


def test_apply_direction_same_direction_no_flip():
    terms = (_ResolvedOrderTerm("rating", "desc", "last"),)
    assert _apply_direction(terms, Direction.DESC) == terms


def test_apply_direction_flip_also_flips_nulls():
    terms = (_ResolvedOrderTerm("rating", "desc", "last"),)
    flipped = _apply_direction(terms, Direction.ASC)
    assert flipped == (_ResolvedOrderTerm("rating", "asc", "first"),)


def test_apply_direction_nulls_none_stays_none_on_flip():
    # non-null column (e.g. PK tie-breaker) — nulls None stays None when flipped
    terms = (_ResolvedOrderTerm("id", "asc", None),)
    flipped = _apply_direction(terms, Direction.DESC)
    assert flipped == (_ResolvedOrderTerm("id", "desc", None),)


def test_apply_direction_accepts_string_value():
    # the GraphQL wire path may deliver a plain string rather than the Enum
    terms = (_ResolvedOrderTerm("rating", "desc", "last"),)
    assert _apply_direction(terms, "ASC") == (_ResolvedOrderTerm("rating", "asc", "first"),)


# ─_resolve_page_orders: single-column constraint ──────────────────────────


def test_resolve_page_orders_rejects_multicolumn_profile():
    class _MultiColEntity(SQLModel, table=True):
        __tablename__ = "nx14_multi_col"
        id: int | None = Field(default=None, primary_key=True)
        rating: int
        created_at: int

    config = BatchPageConfig(
        default_order="BAD",
        orders={
            "BAD": PageOrder(
                [OrderTerm("rating", "desc"), OrderTerm("created_at", "desc")]
            )
        },
    )
    with pytest.raises(ValueError, match="exactly one term"):
        _resolve_page_orders(_MultiColEntity, config)
