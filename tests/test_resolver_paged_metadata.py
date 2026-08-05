"""specs/018 T012 — US2 Resolver._extract_paged_metadata 工具方法单测。

验证 Resolver 能从 build_response_model 产出的字段（pydantic FieldInfo）
以及裸 typing hint 上拿到 ``Paged`` metadata。这是 US3 BFS 搬迁后 entity-first
dynamic model field 走 page_loader 链路的前提（T013）。
"""

from typing import Annotated

from pydantic import BaseModel, create_model

from nexusx.loader.pagination import Paged
from nexusx.resolver import Resolver


class InnerStub(BaseModel):
    """Reusable inner pydantic type for Annotated wrapping in T013 tests."""
    title: str = ""


# ──────────────────────────────────────────────────────────
# Test entities (minimal — actual entity class doesn't matter for field-level extraction)
# ──────────────────────────────────────────────────────────


def test_extract_paged_metadata_from_fieldinfo_metadata_list():
    """直接构造 pydantic FieldInfo（模拟 build_response_model 输出形态）."""
    from pydantic import create_model
    Inner = create_model("Inner", title=(str, ...))
    paged = Paged(limit=5, order="HIGHEST_RATING")
    Model = create_model(
        "M",
        reviews=(Annotated[Inner, paged], ...),
    )
    field_info = Model.model_fields["reviews"]
    extracted = Resolver._extract_paged_metadata(field_info)
    assert extracted is not None
    assert extracted.limit == 5
    assert extracted.order == "HIGHEST_RATING"


def test_extract_paged_metadata_from_typing_annotated_directly():
    """Passing an Annotated alias directly (no FieldInfo wrapper) also works."""
    Inner = type("Inner", (), {})
    paged = Paged(limit=10)
    hint = Annotated[Inner, paged]  # type: ignore[valid-type]
    extracted = Resolver._extract_paged_metadata(hint)
    assert extracted is paged


def test_extract_paged_metadata_returns_none_for_plain_field():
    """Plain field (no Annotated, no metadata) → None."""
    from pydantic import create_model
    Model = create_model("M", name=(str, ...))
    field_info = Model.model_fields["name"]
    assert Resolver._extract_paged_metadata(field_info) is None


def test_extract_paged_metadata_returns_none_for_other_metadata():
    """Annotated with non-Paged metadata → None (don't accidentally pick up
    unrelated markers like pydantic Field constraints)."""
    from pydantic import Field, create_model
    Model = create_model("M", name=(str, Field(min_length=1)))
    field_info = Model.model_fields["name"]
    assert Resolver._extract_paged_metadata(field_info) is None


# ──────────────────────────────────────────────────────────
# T013: _resolve_paged_for_dynamic_field — field metadata + caller context merge
# ──────────────────────────────────────────────────────────


def test_resolve_paged_for_dynamic_field_metadata_only():
    """Field has Paged(limit=5), no caller context → Paged(limit=5)."""
    paged = Paged(limit=5)
    Model = create_model("M", reviews=(Annotated[InnerStub, paged], ...))
    field_info = Model.model_fields["reviews"]
    r = _make_resolver(context=None)._resolve_paged_for_dynamic_field(field_info, "reviews")
    assert r is not None
    assert r.limit == 5


def test_resolve_paged_for_dynamic_field_caller_overrides_metadata():
    """Field metadata Paged(limit=5) + caller {limit: 10} → Paged(limit=10).

    Caller overrides win per-attribute (mirrors γ _merge_paged semantics).
    """
    paged = Paged(limit=5, order="RATING")
    Model = create_model("M", reviews=(Annotated[InnerStub, paged], ...))
    field_info = Model.model_fields["reviews"]
    r = _make_resolver(
        context={"reviews": {"limit": 10}}
    )._resolve_paged_for_dynamic_field(field_info, "reviews")
    assert r.limit == 10  # caller wins
    assert r.order == "RATING"  # metadata preserved (caller didn't override)


def test_resolve_paged_for_dynamic_field_returns_none_when_no_pagination():
    """Plain field + no caller context → None (→ no page_loader dispatch)."""
    Model = create_model("M", reviews=(int, ...))
    field_info = Model.model_fields["reviews"]
    r = _make_resolver(context=None)._resolve_paged_for_dynamic_field(field_info, "reviews")
    assert r is None


# Helper placed at end so test functions can reference it (Python's late
# binding for top-level names inside function bodies makes this work).
def _make_resolver(context: dict | None = None) -> Resolver:
    # Resolver rejects empty dict context (validates non-empty); pass None
    # straight through when caller has no page-params context.
    return Resolver(loader_registry=None, context=context)
