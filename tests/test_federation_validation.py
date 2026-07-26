"""US3 — federation init fail-fast validation (FR-013).

Each malformed declaration must be rejected at federate() time (before serving
queries), with an error that locates the offending declaration. Uses a fake
transport that returns canned ER-introspection responses (no real HTTP/DB).
"""

from __future__ import annotations

import pytest
from sqlmodel import Field, SQLModel

from nexusx.federation import RemoteRelationship
from nexusx.federation.contract import (
    ERIntrospectionResponse,
    EntityFragment,
    FieldDescriptor,
    RelDescriptor,
)
from nexusx.federation.manager import FederationError, federate
from nexusx.loader.registry import ErManager


class FakeTransport:
    """Returns canned ER-introspection responses keyed by a URL substring."""

    def __init__(self, responses):
        self.responses = responses  # {url_substring: ERIntrospectionResponse-as-dict}

    async def get_json(self, url):
        for key, resp in self.responses.items():
            if key in url:
                return resp
        msg = f"unexpected GET {url}"
        raise AssertionError(msg)

    async def post_json(self, url, body):
        return {"data": {}}


def _resp(service_name, *entities):
    return ERIntrospectionResponse(service_name=service_name, entities=list(entities)).model_dump()


def _entity(typename, scalars, batch_roots=(), rels=()):
    return EntityFragment(
        typename=typename,
        scalar_fields=[FieldDescriptor(name=n, type_name=t) for n, t in scalars],
        batch_roots=list(batch_roots),
        relationships=list(rels),
    )


class ValProduct(SQLModel, table=True):
    __tablename__ = "fed_val_product"
    id: int | None = Field(default=None, primary_key=True)
    name: str


_er_with_counter = 0


def _er_with(rrel_target, join_remote="product_id"):
    """Build an ErManager whose entity has a pending RemoteRelationship."""
    global _er_with_counter
    _er_with_counter += 1
    n = _er_with_counter

    class P(SQLModel, table=True):
        __tablename__ = f"fed_val_p_{n}"
        id: int | None = Field(default=None, primary_key=True)
        name: str
        __relationships__ = [
            RemoteRelationship(
                name="reviews", target=rrel_target,
                join_local="id", join_remote=join_remote, is_list=True,
            ),
        ]

    return ErManager(entities=[P], session_factory=lambda: None)


async def _federate(er, services, responses):
    await federate(er, services, transport=FakeTransport(responses))


@pytest.mark.asyncio
async def test_unknown_service_prefix_rejected():
    er = _er_with("ghost.Review")
    services = {"reviews": "http://reviews"}
    resp = _resp("reviews", _entity("Review", [("id", "int"), ("product_id", "int")]))
    with pytest.raises(FederationError, match="Unknown service prefix 'ghost'"):
        await _federate(er, services, {"reviews": resp})


@pytest.mark.asyncio
async def test_missing_typename_rejected():
    er = _er_with("reviews.Review")
    services = {"reviews": "http://reviews"}
    resp = _resp("reviews", _entity("Comment", [("id", "int")]))  # no Review type
    with pytest.raises(FederationError, match="no type"):
        await _federate(er, services, {"reviews": resp})


@pytest.mark.asyncio
async def test_missing_join_field_rejected():
    er = _er_with("reviews.Review", join_remote="product_id")
    services = {"reviews": "http://reviews"}
    resp = _resp("reviews", _entity("Review", [("id", "int"), ("title", "str")]))  # no product_id
    with pytest.raises(FederationError, match="no scalar field 'product_id'"):
        await _federate(er, services, {"reviews": resp})


@pytest.mark.asyncio
async def test_missing_batch_root_rejected():
    er = _er_with("reviews.Review")
    services = {"reviews": "http://reviews"}
    resp = _resp(
        "reviews",
        _entity("Review", [("id", "int"), ("product_id", "int")], batch_roots=[]),  # no by_product_id_in
    )
    with pytest.raises(FederationError, match="does not expose batch root 'by_product_id_in'"):
        await _federate(er, services, {"reviews": resp})


@pytest.mark.asyncio
async def test_service_name_mismatch_rejected():
    """FR-013e: mounted service's self-declared name must match the prefix key."""
    er = _er_with("reviews.Review")
    services = {"reviews": "http://reviews"}
    resp = _resp("NOT_reviews", _entity("Review", [("id", "int"), ("product_id", "int")]))
    with pytest.raises(FederationError, match="declares name"):
        await _federate(er, services, {"reviews": resp})


@pytest.mark.asyncio
async def test_cross_service_barename_duplicate_rejected():
    """FR-013f: two services exposing the same bare typename."""
    # Mount two services, each referencing a type that both name "Shared".
    class P1(SQLModel, table=True):
        __tablename__ = "fed_val_p1"
        id: int | None = Field(default=None, primary_key=True)
        __relationships__ = [RemoteRelationship(
            name="a", target="svcA.Shared", join_local="id", join_remote="id")]

    class P2(SQLModel, table=True):
        __tablename__ = "fed_val_p2"
        id: int | None = Field(default=None, primary_key=True)
        __relationships__ = [RemoteRelationship(
            name="b", target="svcB.Shared", join_local="id", join_remote="id")]

    er = ErManager(entities=[P1, P2], session_factory=lambda: None)
    services = {"svcA": "http://a", "svcB": "http://b"}
    resp_a = _resp("svcA", _entity("Shared", [("id", "int")], batch_roots=["by_id_in"]))
    resp_b = _resp("svcB", _entity("Shared", [("id", "int")], batch_roots=["by_id_in"]))
    with pytest.raises(FederationError, match="Cross-service bare-name duplicate"):
        await _federate(er, services, {"http://a": resp_a, "http://b": resp_b})


@pytest.mark.asyncio
async def test_cycle_terminates_via_visited_set():
    """FR-013g: A→B→A cycle must terminate (visited-set), not hang or crash."""
    class P(SQLModel, table=True):
        __tablename__ = "fed_val_pcyc"
        id: int | None = Field(default=None, primary_key=True)
        __relationships__ = [RemoteRelationship(
            name="a", target="svcA.A", join_local="id", join_remote="id", is_list=False)]

    er = ErManager(entities=[P], session_factory=lambda: None)
    services = {"svcA": "http://a", "svcB": "http://b"}
    a_rel = RelDescriptor(
        name="toB", direction="MANYTOONE", fk_field="id",
        target_typename="B", target_service="svcB")
    b_rel = RelDescriptor(
        name="toA", direction="MANYTOONE", fk_field="id",
        target_typename="A", target_service="svcA")
    resp_a = _resp("svcA", _entity("A", [("id", "int")], batch_roots=["by_id_in"], rels=(a_rel,)))
    resp_b = _resp("svcB", _entity("B", [("id", "int")], batch_roots=["by_id_in"], rels=(b_rel,)))
    # Should complete without hanging (visited-set caps the traversal).
    await _federate(er, services, {"http://a": resp_a, "http://b": resp_b})
