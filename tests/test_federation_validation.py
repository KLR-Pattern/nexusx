"""US3 — federation init fail-fast validation (FR-013).

Each malformed declaration must be rejected at federate() time (before serving
queries), with an error that locates the offending declaration. Uses a fake
transport that returns canned ER-introspection responses (no real HTTP/DB).
"""

from __future__ import annotations

import pytest
from sqlmodel import Field, SQLModel

from nexusx.federation import RemoteRelationship, RemoteService
from nexusx.federation.contract import (
    EntityFragment,
    ERIntrospectionResponse,
    FieldDescriptor,
    RelDescriptor,
)
from nexusx.federation.manager import FederationError
from nexusx.loader.registry import ErManager

# Remote service roots — referenced by the declarations below. `ghost` is the
# deliberately-unmounted service (no url) in the unknown-prefix test.
reviews = RemoteService("reviews", url="http://reviews")
ghost = RemoteService("ghost")
svcA = RemoteService("svcA", url="http://a")
svcB = RemoteService("svcB", url="http://b")


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


def _er_with(target_ref, join_remote="product_id"):
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
                fk="id", target=list[target_ref],
                name="reviews", join_remote=join_remote,
            ),
        ]

    return ErManager(entities=[P], session_factory=lambda: None)


async def _federate(er, responses):
    await er.initialize(transport=FakeTransport(responses))


@pytest.mark.asyncio
async def test_unknown_service_prefix_rejected():
    er = _er_with(ghost.Review)
    resp = _resp("reviews", _entity("Review", [("id", "int"), ("product_id", "int")]))
    with pytest.raises(FederationError, match=r"Service prefix 'ghost'.*has no endpoint"):
        await _federate(er, {"reviews": resp})


@pytest.mark.asyncio
async def test_missing_typename_rejected():
    er = _er_with(reviews.Review)
    resp = _resp("reviews", _entity("Comment", [("id", "int")]))  # no Review type
    with pytest.raises(FederationError, match="no type"):
        await _federate(er, {"reviews": resp})


@pytest.mark.asyncio
async def test_missing_join_field_rejected():
    er = _er_with(reviews.Review, join_remote="product_id")
    resp = _resp("reviews", _entity("Review", [("id", "int"), ("title", "str")]))  # no product_id
    with pytest.raises(FederationError, match="no scalar field 'product_id'"):
        await _federate(er, {"reviews": resp})


@pytest.mark.asyncio
async def test_missing_batch_root_rejected():
    er = _er_with(reviews.Review)
    resp = _resp(
        "reviews",
        _entity("Review", [("id", "int"), ("product_id", "int")], batch_roots=[]),
    )
    with pytest.raises(FederationError, match="does not expose batch root 'by_product_id_in'"):
        await _federate(er, {"reviews": resp})


@pytest.mark.asyncio
async def test_service_name_mismatch_rejected():
    """FR-013e: mounted service's self-declared name must match the prefix key."""
    er = _er_with(reviews.Review)
    resp = _resp("NOT_reviews", _entity("Review", [("id", "int"), ("product_id", "int")]))
    with pytest.raises(FederationError, match="declares name"):
        await _federate(er, {"reviews": resp})


@pytest.mark.asyncio
async def test_cross_service_barename_duplicate_rejected():
    """FR-013f: two services exposing the same bare typename."""
    # Mount two services, each referencing a type that both name "Shared".
    class P1(SQLModel, table=True):
        __tablename__ = "fed_val_p1"
        id: int | None = Field(default=None, primary_key=True)
        __relationships__ = [RemoteRelationship(
            fk="id", target=svcA.Shared, name="a", join_remote="id")]

    class P2(SQLModel, table=True):
        __tablename__ = "fed_val_p2"
        id: int | None = Field(default=None, primary_key=True)
        __relationships__ = [RemoteRelationship(
            fk="id", target=svcB.Shared, name="b", join_remote="id")]

    er = ErManager(entities=[P1, P2], session_factory=lambda: None)
    resp_a = _resp("svcA", _entity("Shared", [("id", "int")], batch_roots=["by_id_in"]))
    resp_b = _resp("svcB", _entity("Shared", [("id", "int")], batch_roots=["by_id_in"]))
    with pytest.raises(FederationError, match="Cross-service bare-name duplicate"):
        await _federate(er, {"http://a": resp_a, "http://b": resp_b})


@pytest.mark.asyncio
async def test_batch_root_without_arg_name_rejected():
    """P1a: a batch root whose arg name can't be introspected fails fast."""
    er = _er_with(reviews.Review)
    frag = _entity(
        "Review", [("id", "int"), ("product_id", "int")],
        batch_roots=[{"name": "by_product_id_in", "arg_name": "", "arg_type": ""}],
    )
    resp = _resp("reviews", frag)
    with pytest.raises(FederationError, match="no determinable argument name"):
        await _federate(er, {"reviews": resp})


def test_introspection_suppresses_target_endpoint_unless_exposed():
    """P1b: the target_endpoint URL is suppressed unless expose_mounted_endpoints=True."""
    from aiodataloader import DataLoader

    from nexusx.federation.introspect import serialize_er_introspection
    from nexusx.loader.registry import ErManager, RelationshipInfo

    class _L(DataLoader):
        async def batch_load_fn(self, keys):
            return keys

    class E(SQLModel, table=True):
        __tablename__ = "fed_p1b_expose"
        id: int | None = Field(default=None, primary_key=True)

    er = ErManager(entities=[E], session_factory=lambda: None, service_name="svc")
    er._mounted_services = {"users": "http://secret-users:8020"}
    er._registry[E]["author"] = RelationshipInfo(
        name="author", direction="MANYTOONE", fk_field="author_id",
        target_entity=E, is_list=False, loader=_L, target_service="users",
    )

    payload = serialize_er_introspection(er).model_dump()
    rel = payload["entities"][0]["relationships"][0]
    assert rel["target_service"] == "users"  # name still carried
    assert rel["target_endpoint"] is None    # URL suppressed by default

    er._expose_mounted_endpoints = True
    payload2 = serialize_er_introspection(er).model_dump()
    rel2 = payload2["entities"][0]["relationships"][0]
    assert rel2["target_endpoint"] == "http://secret-users:8020"


@pytest.mark.asyncio
async def test_custom_transport_is_pluggable():
    """federate() accepts ANY FederationTransport impl, not just GraphQLTransport.

    Locks in that nexusx depends on the transport Protocol, not on httpx — so a
    user can plug in mTLS / signing / per-host creds without nexusx knowing.
    """
    from nexusx.federation.transport import FederationTransport

    calls = {"gets": 0}

    class MyTransport:
        async def post_json(self, url, body):
            return {"data": {}}

        async def get_json(self, url):
            calls["gets"] += 1
            return _resp(
                "reviews",
                _entity(
                    "Review", [("id", "int"), ("product_id", "int")],
                    batch_roots=["by_product_id_in"],
                ),
            )

        async def close(self):
            pass

    transport = MyTransport()
    assert isinstance(transport, FederationTransport)  # structurally conforms
    er = _er_with(reviews.Review)
    await er.initialize(transport=transport)
    assert calls["gets"] >= 1  # our transport actually drove the introspection fetch


@pytest.mark.asyncio
async def test_cycle_terminates_via_visited_set():
    """FR-013g: A→B→A cycle must terminate (visited-set), not hang or crash."""
    class P(SQLModel, table=True):
        __tablename__ = "fed_val_pcyc"
        id: int | None = Field(default=None, primary_key=True)
        # Declare both cycle members so initialize() derives both endpoints
        # (svcA and svcB carry their urls via RemoteService).
        __relationships__ = [
            RemoteRelationship(fk="id", target=svcA.A, name="a", join_remote="id"),
            RemoteRelationship(fk="id", target=svcB.B, name="b", join_remote="id"),
        ]

    er = ErManager(entities=[P], session_factory=lambda: None)
    a_rel = RelDescriptor(
        name="toB", direction="MANYTOONE", fk_field="id",
        target_typename="B", target_service="svcB")
    b_rel = RelDescriptor(
        name="toA", direction="MANYTOONE", fk_field="id",
        target_typename="A", target_service="svcA")
    resp_a = _resp("svcA", _entity("A", [("id", "int")], batch_roots=["by_id_in"], rels=(a_rel,)))
    resp_b = _resp("svcB", _entity("B", [("id", "int")], batch_roots=["by_id_in"], rels=(b_rel,)))
    # Should complete without hanging (visited-set caps the traversal).
    await _federate(er, {"http://a": resp_a, "http://b": resp_b})
