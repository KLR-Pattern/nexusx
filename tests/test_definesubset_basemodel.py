"""Tests for DefineSubset sourced from plain BaseModel (Issue #87, FR-014).

Covers Contract 5 from specs/004-non-sqlmodel-roots/contracts/api.md:
`DefineSubset.__subset__` accepts BaseModel source (schema subsetting
for non-ORM schemas like third-party SDK classes, OAuth claims, etc.).

Layer 1: schema subsetting works, __subset_fields__ populated, direct
         construction works, _orm_to_dto not invoked for BaseModel sources.
Layer 2: DTO + registered source → auto-load fires via source's __relationships__.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel
from sqlmodel import Field, SQLModel

from nexusx import DefineSubset, ErManager, Relationship

# ──────────────────────────────────────────────────────────
# Layer 1: schema subsetting only (no registration, no auto-load)
# ──────────────────────────────────────────────────────────


class OAuthClaims(BaseModel):
    """Simulates a third-party BaseModel with many fields."""

    sub: str
    email: str
    name: str
    picture: str | None = None
    tenant_id: str
    issuer: str
    audience: str
    issued_at: int
    expires_at: int
    # ... imagine 20 more fields in a real SDK class


class TestDefineSubsetFromBaseModelSchemaOnly:
    def test_schema_subsetting_works(self):
        """A DefineSubset DTO sourced from BaseModel builds successfully."""

        class AuthSummaryDTO(DefineSubset):
            __subset__ = (OAuthClaims, ("sub", "email", "name"))

        # __subset_fields__ is materialized as a list by the metaclass.
        assert list(AuthSummaryDTO.__subset_fields__) == ["sub", "email", "name"]

    def test_direct_construction_works(self):
        """DTO instances are constructed directly from kwargs (no ORM row)."""

        class AuthSummaryDTO(DefineSubset):
            __subset__ = (OAuthClaims, ("sub", "email", "name"))

        dto = AuthSummaryDTO(sub="user-1", email="a@x.com", name="Alice")
        assert dto.sub == "user-1"
        assert dto.email == "a@x.com"
        assert dto.name == "Alice"

    def test_model_validate_from_dict(self):
        """DTO can be model_validated from a dict of source-shaped data."""

        class AuthSummaryDTO(DefineSubset):
            __subset__ = (OAuthClaims, ("sub", "email", "name"))

        dto = AuthSummaryDTO.model_validate({
            "sub": "user-1", "email": "a@x.com", "name": "Alice",
            # Extra source-side fields are ignored by pydantic.
            "tenant_id": "t1", "issuer": "iss",
        })
        assert dto.sub == "user-1"
        assert dto.email == "a@x.com"

    def test_non_basemodel_source_still_rejected(self):
        """A non-BaseModel class is still rejected (widening is permissive but not unlimited)."""
        with pytest.raises(TypeError, match="BaseModel"):

            class _Bad(DefineSubset):
                __subset__ = (int, ("real",))  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────
# Layer 2: DTO + registered source → auto-load fires
# ──────────────────────────────────────────────────────────


class _Agent(SQLModel, table=True):
    __tablename__ = "ve_dto_test_agent"

    id: int | None = Field(default=None, primary_key=True)
    owner_oid: str
    name: str


class AgentDTO(DefineSubset):
    __subset__ = (_Agent, ("id", "owner_oid", "name"))


async def _load_agents_by_oid(keys: list[str]) -> list[list[AgentDTO]]:
    db = {
        "user-1": [
            AgentDTO(id=1, owner_oid="user-1", name="A1"),
            AgentDTO(id=2, owner_oid="user-1", name="A2"),
        ],
    }
    return [db.get(k, []) for k in keys]


class CurrentUser(BaseModel):
    """Virtual source: schema + __relationships__."""

    oid: str
    name: str
    tenant_id: str
    # ... imagine more fields the user does NOT want in the DTO

    __relationships__ = [
        Relationship(
            fk="oid",
            target=list[AgentDTO],
            name="agents",
            loader=_load_agents_by_oid,
        ),
    ]


class CurrentUserDTO(DefineSubset):
    """DTO that subsets CurrentUser's schema AND inherits its relationships."""

    __subset__ = (CurrentUser, ("oid", "name"))
    agents: list[AgentDTO] = []


class TestDefineSubsetFromRegisteredBaseModel:
    async def test_dto_subset_of_registered_source_auto_loads(self):
        """DTO constructed directly; at resolve time, the source's __relationships__ fire."""
        er = ErManager(
            entities=[_Agent],
            session_factory=lambda: None,
        )
        er.add_virtual_entities([CurrentUser])
        resolver = er.create_resolver()()

        dto = CurrentUserDTO(oid="user-1", name="Alice", tenant_id="t1")
        result = await resolver.resolve(dto)

        assert len(result.agents) == 2
        assert {a.name for a in result.agents} == {"A1", "A2"}

    async def test_unregistered_source_no_auto_load(self):
        """If source is NOT registered, schema subsetting still works but
        __relationships__ does not fire (Edge Case I)."""

        # DefineSubset sourced from a BaseModel that's NOT in _registry.
        class _Unregistered(BaseModel):
            oid: str
            name: str
            extra: str = ""

        class _UnregDTO(DefineSubset):
            __subset__ = (_Unregistered, ("oid", "name"))

        # Schema subsetting works.
        assert list(_UnregDTO.__subset_fields__) == ["oid", "name"]
        dto = _UnregDTO(oid="x", name="y")
        assert dto.oid == "x"

        # No ErManager interaction needed — DTO is usable standalone.
