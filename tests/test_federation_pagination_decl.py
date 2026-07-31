"""US5 (T024): pagination fail-fast — to-one declares sort_field, or sort_field
is not a member scalar field. Both rejected at federate() (_validate_declarations).
"""

import pytest
from sqlmodel import Field, SQLModel

from nexusx.federation import RemoteRelationship, RemoteService
from nexusx.federation.contract import BatchRoot, EntityFragment, FieldDescriptor
from nexusx.federation.manager import FederationError, _validate_declarations
from nexusx.loader.registry import ErManager

users = RemoteService("users")


class _DeclToOne(SQLModel, table=True):
    __tablename__ = "fed_pag_decl_toone"
    id: int | None = Field(default=None, primary_key=True)
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=users.User, name="u", join_remote="id",
            sort_field="name",  # to-one + sort_field → illegal
        ),
    ]


class _DeclMany(SQLModel, table=True):
    __tablename__ = "fed_pag_decl_many"
    id: int | None = Field(default=None, primary_key=True)
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[users.User], name="u", join_remote="id",
            sort_field="nonexistent",  # not a member scalar → illegal
        ),
    ]


def _frag_with_id_root() -> EntityFragment:
    return EntityFragment(
        typename="User",
        scalar_fields=[FieldDescriptor(name="id", type_name="int")],
        batch_roots=[BatchRoot(name="by_id_in", arg_name="id_list")],
    )


def test_to_one_with_sort_field_rejected():
    """FR-002: to-one RemoteRelationship declaring sort_field → fail-fast."""
    er = ErManager(entities=[_DeclToOne], session_factory=lambda: None)
    with pytest.raises(FederationError, match="to-one"):
        _validate_declarations(er, {"users": "http://u"}, {})


def test_illegal_sort_field_rejected():
    """FR-012b: sort_field not a member scalar field → fail-fast."""
    er = ErManager(entities=[_DeclMany], session_factory=lambda: None)
    fragments = {"users.User": _frag_with_id_root()}
    with pytest.raises(FederationError, match="sort_field"):
        _validate_declarations(er, {"users": "http://u"}, fragments)
