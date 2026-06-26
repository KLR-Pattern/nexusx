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


# ──────────────────────────────────────────────────────────
# Experiment: target=list[Agent] (SQLModel) vs target=list[AgentDTO] (DTO)
# Verifies what actually happens when the user uses the SQLModel entity
# directly as the relationship target instead of the DefineSubset DTO.
# ──────────────────────────────────────────────────────────


async def _load_agents_by_oid_raw(keys: list[str]) -> list[list[_Agent]]:
    """Variant loader that returns SQLModel ``_Agent`` instances directly."""
    db = {
        "user-1": [
            _Agent(id=1, owner_oid="user-1", name="A1"),
            _Agent(id=2, owner_oid="user-1", name="A2"),
        ],
    }
    return [db.get(k, []) for k in keys]


class _CurrentUser_TargetAgent(BaseModel):
    """Variant of CurrentUser whose ``agents`` relationship targets the
    SQLModel ``_Agent`` class directly (not AgentDTO)."""

    oid: str
    name: str

    __relationships__ = [
        Relationship(
            fk="oid",
            target=list[_Agent],              # ← SQLModel entity, not DTO
            name="agents",
            loader=_load_agents_by_oid_raw,
        ),
    ]


class TestCustomRelationshipAutoConversion:
    """``target=list[_Agent]`` + ``field: list[AgentDTO]`` + loader returns
    ``_Agent`` — the resolver MUST auto-convert loader output to the field's
    declared DTO type.

    History: this used to silently fail. The resolver skipped conversion
    whenever the loader returned *any* ``BaseModel`` (which ``_Agent`` is,
    via SQLModel), so the field ended up holding raw SQLModel instances
    despite being annotated as a DTO. Schema projection was silently lost.

    Fix: ``resolver.py:_process_auto_loaded_groups`` now checks
    ``isinstance(r, dto_cls)`` instead of ``isinstance(r, BaseModel)``.
    These tests pin the fix.
    """

    async def test_field_type_matches_target_no_conversion_needed(self):
        """Given target=list[_Agent] and field=list[_Agent], the loader's
        output is already the right type — no conversion runs. Sanity baseline.
        """
        # ...Given: a virtual root whose target AND field both use _Agent
        class _Root(_CurrentUser_TargetAgent):
            agents: list[_Agent] = []

        er = ErManager(entities=[_Agent], session_factory=lambda: None)
        er.add_virtual_entities([_Root])
        resolver = er.create_resolver()()

        # ...When: resolver runs
        result = await resolver.resolve(_Root(oid="user-1", name="Alice"))

        # ...Then: field holds _Agent instances, names match loader output
        assert len(result.agents) == 2
        assert {a.name for a in result.agents} == {"A1", "A2"}
        assert all(isinstance(a, _Agent) for a in result.agents)

    async def test_loader_output_converted_to_declared_dto_type(self):
        """Given target=list[_Agent] but field=list[AgentDTO], the resolver
        converts each ``_Agent`` from the loader into an ``AgentDTO`` before
        placing it in the field. Field annotation is honest at runtime.
        """
        # ...Given: target uses SQLModel, field uses DefineSubset DTO
        class _Root(_CurrentUser_TargetAgent):
            agents: list[AgentDTO] = []   # ← not what target says

        er = ErManager(entities=[_Agent], session_factory=lambda: None)
        er.add_virtual_entities([_Root])
        resolver = er.create_resolver()()

        # ...When: resolver runs (loader returns _Agent instances)
        result = await resolver.resolve(_Root(oid="user-1", name="Alice"))

        # ...Then: field holds AgentDTO instances, not _Agent
        assert len(result.agents) == 2
        actual_types = {type(a).__name__ for a in result.agents}
        assert actual_types == {"AgentDTO"}, (
            f"Expected all AgentDTO after auto-conversion; got {actual_types}."
        )
        # Data survives the conversion:
        assert {a.name for a in result.agents} == {"A1", "A2"}

    async def test_dto_only_field_present_after_dump(self):
        """After conversion, ``model_dump()`` reflects the DTO schema, not
        the SQLModel schema. DTO-only fields appear; excluded SQLModel
        fields don't.
        """
        # ...Given: a DTO with an extra field, plus an excluded SQLModel field
        class _AgentDTOWithExtra(DefineSubset):
            __subset__ = (_Agent, ("id", "name"))   # owner_oid excluded
            display_label: str = "n/a"              # DTO-only field

        class _Root(_CurrentUser_TargetAgent):
            agents: list[_AgentDTOWithExtra] = []

        er = ErManager(entities=[_Agent], session_factory=lambda: None)
        er.add_virtual_entities([_Root])
        resolver = er.create_resolver()()

        # ...When: resolver runs and we dump the first agent
        result = await resolver.resolve(_Root(oid="user-1", name="Alice"))
        dumped = result.agents[0].model_dump()

        # ...Then: dump matches DTO schema
        assert "display_label" in dumped, "DTO-only field must survive conversion"
        assert "owner_oid" not in dumped, "Excluded SQLModel field must not leak"

    async def test_excluded_sqlmodel_field_not_accessible(self):
        """A field excluded via ``__subset__`` is genuinely unreachable after
        conversion — not just absent from ``model_dump()``, but ``hasattr``
        returns False. Projection is real, not cosmetic.
        """
        # ...Given: DTO that explicitly drops owner_oid
        class _AgentDTONoOwner(DefineSubset):
            __subset__ = (_Agent, ("id", "name"))

        class _Root(_CurrentUser_TargetAgent):
            agents: list[_AgentDTONoOwner] = []

        er = ErManager(entities=[_Agent], session_factory=lambda: None)
        er.add_virtual_entities([_Root])
        resolver = er.create_resolver()()

        # ...When: resolver runs
        result = await resolver.resolve(_Root(oid="user-1", name="Alice"))

        # ...Then: excluded field is unreachable on the runtime instance
        assert len(result.agents) == 2
        assert not hasattr(result.agents[0], "owner_oid"), (
            "owner_oid was excluded via __subset__ but is still accessible — "
            "projection leaked."
        )


# ──────────────────────────────────────────────────────────
# BaseModel source + __relationships__ fk auto-include
# ──────────────────────────────────────────────────────────


class _BMStub(SQLModel, table=True):
    """ErManager requires ≥1 SQLModel entity in __init__."""
    __tablename__ = "bm_fk_stub"

    id: int | None = Field(default=None, primary_key=True)


class _BMTarget(BaseModel):
    """Plain BaseModel relationship target."""
    target_id: str
    payload: str


async def _bm_target_loader(keys: list[str]) -> list[list[_BMTarget]]:
    """In-memory loader keyed by source.key."""
    db = {
        "k1": [_BMTarget(target_id="t1", payload="P1"),
               _BMTarget(target_id="t2", payload="P2")],
        "k2": [_BMTarget(target_id="t3", payload="P3")],
    }
    return [db.get(k, []) for k in keys]


class _BMSource(BaseModel):
    """Plain BaseModel source with a relationship that uses ``key`` as fk."""
    key: str
    name: str
    items: list[_BMTarget] = []

    __relationships__ = [
        Relationship(
            fk="key",
            target=list[_BMTarget],
            name="items",
            loader=_bm_target_loader,
        ),
    ]


class TestBaseModelSourceFkAutoInclude:
    """Plain BaseModel sources have no SQLAlchemy metadata, so the auto-include
    of PK/FK fields (which works for SQLModel) cannot fire. The framework
    must therefore read fk field names from ``__relationships__`` declarations
    on the source and auto-include them in DTO ``model_fields``.

    Without this, a DTO that excludes the fk field silently breaks the
    relationship load — ``getattr(dto, fk, None)`` returns None, the loader
    is never called, and the field stays empty. No error is raised.
    """

    def test_fk_field_auto_included_in_model_fields(self):
        """DTO that excludes ``key`` from ``__subset__`` still has it
        in ``model_fields`` because the source declares ``Relationship(
        fk="key", ...)``."""
        class _SourceDTO(DefineSubset):
            __subset__ = (_BMSource, ("name",))   # 'key' intentionally excluded
            items: list[_BMTarget] = []

        assert "key" in _SourceDTO.model_fields, (
            "fk field declared via __relationships__ must be auto-included"
        )
        assert "key" in _SourceDTO.__subset_fields__, (
            "Auto-included fk should also appear in __subset_fields__"
        )

    def test_fk_field_excluded_from_model_dump(self):
        """The auto-included fk is tracked in ``__subset_auto_excluded__``
        so it does not leak into API responses via ``model_dump()``.
        """
        class _SourceDTO(DefineSubset):
            __subset__ = (_BMSource, ("name",))
            items: list[_BMTarget] = []

        assert "key" in _SourceDTO.__subset_auto_excluded__
        dto = _SourceDTO(name="Alice", key="k1")
        dumped = dto.model_dump()
        assert "key" not in dumped, "Auto-included fk must not appear in dump"
        assert dumped["name"] == "Alice"

    def test_user_listed_fk_is_not_auto_excluded(self):
        """If the user explicitly lists the fk in ``__subset__``, it's their
        choice — do NOT auto-exclude from dump. Mirrors SQLModel PK behavior.
        """
        class _SourceDTO(DefineSubset):
            __subset__ = (_BMSource, ("key", "name"))   # key explicitly listed
            items: list[_BMTarget] = []

        assert "key" not in _SourceDTO.__subset_auto_excluded__
        dto = _SourceDTO(name="Alice", key="k1")
        assert "key" in dto.model_dump()

    def test_user_omitted_fk_is_respected(self):
        """If the user uses ``SubsetConfig(omit_fields=["key"])`` to drop the
        fk entirely, the framework does not re-add it.
        """
        from nexusx.subset import SubsetConfig

        class _SourceDTO(DefineSubset):
            __subset__ = SubsetConfig(
                kls=_BMSource,
                omit_fields=["key"],
            )
            # `items` field still declared, but key is gone — relationship
            # load will silently fail. User's explicit choice.
            items: list[_BMTarget] = []

        assert "key" not in _SourceDTO.model_fields

    async def test_relationship_loads_after_auto_include(self):
        """End-to-end: a DTO that excludes ``key`` from ``__subset__`` still
        loads the relationship at resolve time, because the auto-included
        ``key`` is readable on the runtime instance.
        """
        class _SourceDTO(DefineSubset):
            __subset__ = (_BMSource, ("name",))
            items: list[_BMTarget] = []

        er = ErManager(entities=[_BMStub], session_factory=lambda: None)
        er.add_virtual_entities([_BMSource])
        resolver = er.create_resolver()()

        # DTO built with the (auto-included) key — user provides it via kwargs.
        dto = _SourceDTO(name="Alice", key="k1")
        result = await resolver.resolve(dto)

        assert [t.target_id for t in result.items] == ["t1", "t2"]
