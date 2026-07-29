"""US1 — RemoteRelationship declaration, parsing, and target_service wiring."""

from __future__ import annotations

import pytest

from nexusx.federation import (
    RemoteEdge,
    RemoteRelationship,
    RemoteService,
    parse_qualified_name,
)
from nexusx.federation.relationship import parse_edge_source
from nexusx.loader.registry import ErManager, RelationshipInfo
from nexusx.relationship import get_custom_relationships

# Remote service root — referenced by the declarations below.
reviews = RemoteService("reviews")


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
        name="reviews", target=reviews.Review,
        join_local="id", join_remote="product_id", is_list=True,
    )
    # RemoteRef input is normalized to the "srv.typename" marker string.
    assert r.target == "reviews.Review"
    assert r.is_list is True


def test_remote_edge_normalizes_remote_ref_target():
    """RemoteEdge.target takes a RemoteRef too; source stays a 3-part string."""
    e = RemoteEdge(
        source="reviews.Review.author", target=reviews.User,
        join_local="author_id", join_remote="id", is_list=False,
    )
    assert e.target == "reviews.User"
    assert e.source == "reviews.Review.author"


def test_remote_relationship_captures_service_url():
    """RemoteRelationship carries the service url from RemoteService, so
    federation can derive endpoints from the declarations alone."""
    with_url = RemoteService("reviews", url="http://reviews:8021")
    no_url = RemoteService("ghost")
    r1 = RemoteRelationship(
        name="reviews", target=with_url.Review,
        join_local="id", join_remote="product_id",
    )
    r2 = RemoteRelationship(
        name="g", target=no_url.Missing,
        join_local="id", join_remote="id",
    )
    assert r1.target_url == "http://reviews:8021"
    assert r1.target == "reviews.Review"
    assert r2.target_url is None  # no url → transitive-only / unmounted


def test_resolve_deferred_subset_returns_materialized_class():
    """Regression: _resolve_ref must return the materialized class when the
    source resolves — it used to fall through to None, raising
    'Source entity must be a BaseModel class, got None' (broke the catalog demo,
    which declares DefineSubset DTOs over resolved remote types).

    Isolated: snapshots/restores the process-global pending-subset registry so
    it neither pollutes other tests nor is polluted by them.
    """
    from nexusx.federation.contract import EntityFragment, FieldDescriptor
    from nexusx.federation.registry import FederatedTypeRegistry
    from nexusx.federation.remote_ref import (
        clear_pending_subsets,
        get_pending_subsets,
        register_pending_subset,
        resolve_deferred_subsets,
    )
    from nexusx.subset import DefineSubset

    saved = list(get_pending_subsets())
    clear_pending_subsets()
    try:
        reg = FederatedTypeRegistry()
        reg.materialize({
            "reviews.Review": EntityFragment(
                typename="Review",
                scalar_fields=[
                    FieldDescriptor(name="title", type_name="str"),
                    FieldDescriptor(name="rating", type_name="int"),
                ],
            )
        })
        register_pending_subset(
            "RDTO", DefineSubset, reviews.Review, ["title", "rating"],
            {"__module__": __name__, "__annotations__": {}},
        )

        resolved = resolve_deferred_subsets(reg)
        cls = next(c for c in resolved if c.__name__ == "RDTO")
        inst = cls(title="x", rating=5)
        assert inst.title == "x" and inst.rating == 5
    finally:
        clear_pending_subsets()
        for entry in saved:
            register_pending_subset(*entry)


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
            name="reviews", target=reviews.Review,
            join_local="id", join_remote="product_id", is_list=True,
        ),
    ]


@pytest.fixture
def tmp_module(monkeypatch):
    """Expose _LocalEntity under a stable name for the module-level tests."""
    return type("_M", (), {"LocalEntity": _LocalEntity})
