"""US1 — RemoteRelationship declaration, parsing, and target_service wiring."""

from __future__ import annotations

import pytest

from nexusx.federation import RemoteRelationship, parse_qualified_name
from nexusx.federation.relationship import parse_edge_source
from nexusx.loader.registry import ErManager, RelationshipInfo
from nexusx.relationship import get_custom_relationships


def test_parse_qualified_name_roundtrip():
    assert parse_qualified_name("reviews.Review") == ("reviews", "Review")


@pytest.mark.parametrize("bad", ["", "noDot", "a.b.c", ".x", "x.", "x.."])
def test_parse_qualified_name_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_qualified_name(bad)


def test_parse_edge_source_roundtrip():
    assert parse_edge_source("reviews.Review.author") == ("reviews", "Review", "author")


def test_remote_relationship_dataclass_fields():
    r = RemoteRelationship(
        name="reviews", target="reviews.Review",
        join_local="id", join_remote="product_id", is_list=True,
    )
    assert r.target == "reviews.Review"
    assert r.is_list is True


def test_get_custom_relationships_returns_remote_entries(tmp_module):
    """__relationships__ with a RemoteRelationship is recognized (not rejected)."""
    rels = get_custom_relationships(tmp_module.LocalEntity)
    names = [getattr(r, "name", None) for r in rels]
    assert "reviews" in names
    # The RemoteRelationship instance passes through unchanged.
    remote = [r for r in rels if isinstance(r, RemoteRelationship)]
    assert len(remote) == 1
    assert remote[0].target == "reviews.Review"


def test_target_service_default_none_on_local_relationship_info():
    """Existing local RelationshipInfo construction is unaffected (target_service=None)."""
    ri = RelationshipInfo(
        name="tags", direction="ONETOMANY", fk_field="id",
        target_entity=int, is_list=True, loader=type,
    )
    assert ri.target_service is None


def test_ermanager_collects_pending_remote_rels(tmp_module):
    """RemoteRelationships are collected as pending (deferred to federate), not built."""
    er = ErManager(entities=[tmp_module.LocalEntity], session_factory=lambda: None)
    assert len(er._pending_remote_rels) == 1
    src, rrel = er._pending_remote_rels[0]
    assert src is tmp_module.LocalEntity
    assert rrel.name == "reviews"
    # And NOT registered as a built relationship yet.
    assert "reviews" not in er.get_relationships(tmp_module.LocalEntity)


# ── Shared fixture entity ────────────────────────────────────────────────

from sqlmodel import Field, SQLModel  # noqa: E402


class _LocalEntity(SQLModel, table=True):
    __tablename__ = "fed_decl_local"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    __relationships__ = [
        RemoteRelationship(
            name="reviews", target="reviews.Review",
            join_local="id", join_remote="product_id", is_list=True,
        ),
    ]


@pytest.fixture
def tmp_module(monkeypatch):
    """Expose _LocalEntity under a stable name for the module-level tests."""
    return type("_M", (), {"LocalEntity": _LocalEntity})
