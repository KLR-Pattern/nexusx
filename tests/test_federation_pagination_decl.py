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
            order="UNKNOWN",
        ),
    ]


def _frag_with_id_root() -> EntityFragment:
    return EntityFragment(
        typename="User",
        scalar_fields=[FieldDescriptor(name="id", type_name="int")],
        batch_roots=[
            BatchRoot(
                name="page_by_id_in",
                arg_name="id_list",
                arg_type="list[int]",
                page=BatchPageCapability(
                    default_order="NEWEST",
                    orders=[PageOrderDescriptor(name="NEWEST")],
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


def test_unknown_order_profile_rejected():
    er = ErManager(entities=[_DeclMany], session_factory=lambda: None)
    source_entity, rrel = er._pending_remote_rels[0]
    fragments = {"users.User": _frag_with_id_root()}
    with pytest.raises(FederationError, match="UNKNOWN"):
        # fed_registry/transport are None — validation raises before wiring.
        _validate_and_wire_remote_relationship(
            er, source_entity, rrel, {"users": "http://u"}, None, fragments, None,
        )


def test_order_requires_pagination():
    with pytest.raises(ValueError, match="pagination=True"):
        RemoteRelationship(
            fk="id",
            target=list[users.User],
            name="u",
            join_remote="id",
            order="NEWEST",
        )
