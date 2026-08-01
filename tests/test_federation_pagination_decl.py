"""Federation pagination declaration and capability validation."""

import pytest
from sqlmodel import Field, SQLModel

from nexusx.federation import RemoteRelationship, RemoteService
from nexusx.federation.contract import (
    BatchPageCapability,
    BatchRoot,
    EntityFragment,
    FieldDescriptor,
    PageOrderDescriptor,
)
from nexusx.federation.manager import FederationError, _validate_and_wire_remote_relationship
from nexusx.loader.registry import ErManager

users = RemoteService("users")


class _DeclToOne(SQLModel, table=True):
    __tablename__ = "fed_pag_decl_toone"
    id: int | None = Field(default=None, primary_key=True)
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=users.User, name="u", join_remote="id",
            pagination=True,
        ),
    ]


class _DeclMany(SQLModel, table=True):
    __tablename__ = "fed_pag_decl_many"
    id: int | None = Field(default=None, primary_key=True)
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[users.User], name="u", join_remote="id",
            pagination=True,
        ),
    ]


def _frag_with_id_root(
    *,
    default_order: str = "NEWEST",
    orders: list[PageOrderDescriptor] | None = None,
) -> EntityFragment:
    if orders is None:
        orders = [PageOrderDescriptor(name="NEWEST")]
    return EntityFragment(
        typename="User",
        scalar_fields=[FieldDescriptor(name="id", type_name="int")],
        batch_roots=[
            BatchRoot(
                name="page_by_id_in",
                arg_name="id_list",
                arg_type="list[int]",
                page=BatchPageCapability(
                    default_order=default_order,
                    orders=orders,
                ),
            )
        ],
    )


def test_to_one_with_pagination_rejected():
    er = ErManager(entities=[_DeclToOne], session_factory=lambda: None)
    source_entity, rrel = er._pending_remote_rels[0]
    with pytest.raises(FederationError, match="to-one"):
        # fed_registry/transport are None — validation raises before wiring.
        _validate_and_wire_remote_relationship(
            er, source_entity, rrel, {"users": "http://u"}, None, {}, None,
        )


def test_empty_orders_rejected():
    """FR-010: a member that advertises no order profiles fails fast at federate
    time (the mounter has no enum to render). specs/014.
    """
    er = ErManager(entities=[_DeclMany], session_factory=lambda: None)
    source_entity, rrel = er._pending_remote_rels[0]
    fragments = {"users.User": _frag_with_id_root(orders=[])}
    with pytest.raises(FederationError, match="no order profiles"):
        # fed_registry/transport are None — validation raises before wiring.
        _validate_and_wire_remote_relationship(
            er, source_entity, rrel, {"users": "http://u"}, None, fragments, None,
        )


def test_unknown_default_order_rejected():
    """The member's default_order must be one of its advertised profiles
    (the mounter falls back to it when the caller omits ``order``)."""
    er = ErManager(entities=[_DeclMany], session_factory=lambda: None)
    source_entity, rrel = er._pending_remote_rels[0]
    fragments = {
        "users.User": _frag_with_id_root(
            default_order="NEWEST", orders=[PageOrderDescriptor(name="OLDEST")],
        )
    }
    with pytest.raises(FederationError, match="default_order"):
        _validate_and_wire_remote_relationship(
            er, source_entity, rrel, {"users": "http://u"}, None, fragments, None,
        )
