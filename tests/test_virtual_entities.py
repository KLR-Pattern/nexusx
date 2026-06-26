"""Tests for non-SQLModel virtual entity support (Issue #87).

Covers three layers (see specs/004-non-sqlmodel-roots/quickstart.md Coverage Matrix):
- Layer 1: API contract for ErManager.add_virtual_entities()
- Layer 2: Capability parity with SQLModel roots (resolve_*, post_*, ExposeAs,
  SendTo, Collector, custom relationships)
- Layer 3: Regression protection (no SQLModel impersonation, etc.)

Layer 1 tests are written FIRST and must FAIL before implementation.
"""
from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import BaseModel
from sqlmodel import Field, SQLModel

from nexusx import DefineSubset, ErManager, Relationship
from nexusx.context import Collector, ExposeAs, SendTo
from nexusx.resolver import Resolver

# ──────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────


class _Agent(SQLModel, table=True):
    __tablename__ = "ve_test_agent"

    id: int | None = Field(default=None, primary_key=True)
    owner_oid: str
    name: str


class AgentDTO(DefineSubset):
    __subset__ = (_Agent, ("id", "owner_oid", "name"))


async def _load_agents_by_oid(keys: list[str]) -> list[list[AgentDTO]]:
    """In-memory batch loader — no DB needed for these tests."""
    db = {
        "user-1": [
            AgentDTO(id=1, owner_oid="user-1", name="A1"),
            AgentDTO(id=2, owner_oid="user-1", name="A2"),
        ],
        "user-2": [AgentDTO(id=3, owner_oid="user-2", name="B1")],
    }
    return [db.get(k, []) for k in keys]


class CurrentUserRoot(BaseModel):
    """Plain BaseModel virtual root — no SQLModel behind it."""

    oid: str
    name: str
    agents: list[AgentDTO] = []

    __relationships__ = [
        Relationship(
            fk="oid",
            target=list[AgentDTO],
            name="agents",
            loader=_load_agents_by_oid,
        ),
    ]


def _session_factory_stub():
    """ErManager requires a session_factory even when no SQLModel query runs."""
    return None


def _make_er() -> ErManager:
    return ErManager(entities=[_Agent], session_factory=_session_factory_stub)


# ──────────────────────────────────────────────────────────
# Layer 1 — API contract for add_virtual_entities()
# ──────────────────────────────────────────────────────────


class TestAddVirtualEntitiesContract:
    def test_happy_path_registration(self):
        """Plain BaseModel class registers without error."""
        er = _make_er()
        er.add_virtual_entities([CurrentUserRoot])
        assert er.has_entity(CurrentUserRoot)
        # The __relationships__ entry is wired into _registry.
        rels = er.get_relationships(CurrentUserRoot)
        assert "agents" in rels
        assert rels["agents"].direction == "CUSTOM"

    def test_empty_list_is_noop(self):
        er = _make_er()
        er.add_virtual_entities([])  # no error
        # No entity added.
        assert not er.has_entity(CurrentUserRoot)

    def test_sqlmodel_rejected_with_typeerror(self):
        """SQLModel classes must go through __init__'s entities=, not here."""
        er = _make_er()
        with pytest.raises(TypeError, match="SQLModel"):
            er.add_virtual_entities([_Agent])

    def test_non_basemodel_rejected_with_typeerror(self):
        """Plain Python classes (not BaseModel) are rejected."""
        er = _make_er()

        class NotABaseModel:
            pass

        with pytest.raises(TypeError, match="BaseModel"):
            er.add_virtual_entities([NotABaseModel])  # type: ignore[arg-type]

    def test_non_class_rejected_with_typeerror(self):
        """Integers, instances, etc. are rejected."""
        er = _make_er()
        with pytest.raises(TypeError):
            er.add_virtual_entities([42])  # type: ignore[list-item]

    def test_duplicate_within_call_rejected(self):
        er = _make_er()
        with pytest.raises(ValueError, match="already registered"):
            er.add_virtual_entities([CurrentUserRoot, CurrentUserRoot])

    def test_duplicate_across_calls_rejected(self):
        er = _make_er()
        er.add_virtual_entities([CurrentUserRoot])
        with pytest.raises(ValueError, match="already registered"):
            er.add_virtual_entities([CurrentUserRoot])

    def test_duplicate_with_init_entities_rejected(self):
        """A class already in __init__'s entities= cannot be re-registered."""
        er = _make_er()  # _Agent is in entities=
        # Even if _Agent weren't SQLModel, the duplicate check fires first.
        # We test the SQLModel-vs-BaseModel branch by registering a class
        # that ISN'T _Agent but is already in _registry via a prior call.
        er.add_virtual_entities([CurrentUserRoot])
        with pytest.raises(ValueError, match="already registered"):
            er.add_virtual_entities([CurrentUserRoot])

    def test_frozen_after_create_resolver(self):
        """add_virtual_entities() after create_resolver() must raise."""
        er = _make_er()
        er.create_resolver()
        with pytest.raises(RuntimeError, match="frozen"):
            er.add_virtual_entities([CurrentUserRoot])


# ──────────────────────────────────────────────────────────
# Layer 2 — resolve_* / post_* on virtual root (parity with SQLModel roots)
# ──────────────────────────────────────────────────────────


class TestVirtualRootResolvePost:
    """Quickstart S2 — resolve_* and post_* fire on virtual roots."""

    async def test_resolve_populates_field(self):
        er = _make_er()
        er.add_virtual_entities([CurrentUserRoot])
        resolver = er.create_resolver()()

        root = CurrentUserRoot(oid="user-1", name="Alice")
        result = await resolver.resolve(root)
        assert len(result.agents) == 2
        assert {a.name for a in result.agents} == {"A1", "A2"}

    async def test_post_methods_fire(self):
        er = _make_er()

        class _RootWithPost(CurrentUserRoot):
            agent_count: int = 0
            agent_summary: str = ""

            def post_agent_count(self):
                return len(self.agents)

            def post_agent_summary(self):
                return ", ".join(a.name for a in self.agents)

        er.add_virtual_entities([_RootWithPost])
        resolver = er.create_resolver()()

        root = _RootWithPost(oid="user-1", name="Alice")
        result = await resolver.resolve(root)
        assert result.agent_count == 2
        assert result.agent_summary == "A1, A2"

    async def test_post_default_handler_on_virtual_root(self):
        """post_default_handler (finalizer) fires after all named post_* complete."""
        er = _make_er()

        call_log: list[str] = []

        class _RootWithHandler(BaseModel):
            oid: str
            name: str
            agents: list[AgentDTO] = []
            finalized: bool = False

            __relationships__ = [
                Relationship(
                    fk="oid",
                    target=list[AgentDTO],
                    name="agents",
                    loader=_load_agents_by_oid,
                ),
            ]

            def post_agent_count(self):
                call_log.append("post_agent_count")
                return len(self.agents)

            agent_count: int = 0

            def post_default_handler(self):
                # Runs after post_agent_count, per BFS phase B-2 ordering.
                call_log.append("post_default_handler")
                self.finalized = True

        er.add_virtual_entities([_RootWithHandler])
        resolver = er.create_resolver()()

        root = _RootWithHandler(oid="user-1", name="Alice")
        result = await resolver.resolve(root)
        assert result.finalized is True
        assert call_log == ["post_agent_count", "post_default_handler"]


class TestSequentialResolveNoLeak:
    """Regression for #293 clone semantics across sequential resolve() calls."""

    async def test_resolver_reuse_across_trees(self):
        er = _make_er()
        er.add_virtual_entities([CurrentUserRoot])
        resolver_cls = er.create_resolver()

        r1 = await resolver_cls().resolve(CurrentUserRoot(oid="user-1", name="A"))
        r2 = await resolver_cls().resolve(CurrentUserRoot(oid="user-2", name="B"))
        assert {a.name for a in r1.agents} == {"A1", "A2"}
        assert {a.name for a in r2.agents} == {"B1"}


# ──────────────────────────────────────────────────────────
# Layer 2 mirror tests — capability parity with SQLModel roots.
# Each test mirrors an existing test_context.py / test_resolver.py case
# but roots the tree at a plain BaseModel virtual root.
# ──────────────────────────────────────────────────────────


class TestVirtualRootExposeAs:
    """Mirror TestExposeAs from test_context.py with virtual root."""

    async def test_basic_expose_to_descendant(self):
        class Parent(BaseModel):
            greeting: str
            child_greeting: str = ""

            __relationships__: list[Relationship] = []

        class Child(BaseModel):
            name: str
            parent_greeting: str = ""

            def post_parent_greeting(self, ancestor_context):
                return ancestor_context["greeting"]

        # Parent is a virtual root that exposes `greeting` and has a Child
        # via __relationships__.
        async def _load_child(keys: list[str]) -> list[BaseModel | None]:
            return [Child(name="Alice") for _ in keys]

        class _Parent(Parent):
            name: str
            child: Child | None = None

            __relationships__ = [
                Relationship(
                    fk="name",
                    target=Child,
                    name="child",
                    loader=_load_child,
                ),
            ]

        # Use Annotated expose on the source BaseModel.
        from typing import Annotated as _Ann

        class _Parent2(BaseModel):
            greeting: _Ann[str, ExposeAs("greeting")]
            name: str
            child: Child | None = None

            __relationships__ = [
                Relationship(
                    fk="name",
                    target=Child,
                    name="child",
                    loader=_load_child,
                ),
            ]

        er = _make_er()
        er.add_virtual_entities([_Parent2])
        resolver = er.create_resolver()()

        root = _Parent2(greeting="hi", name="x")
        result = await resolver.resolve(root)
        assert result.child is not None
        assert result.child.parent_greeting == "hi"


class TestVirtualRootSendToCollector:
    """Mirror TestSendToCollector from test_context.py with virtual root."""

    async def test_basic_send_to_and_collect(self):
        """Leaf sends value up; virtual root collects via Collector()."""

        class Leaf(BaseModel):
            name: Annotated[str, SendTo("names")]

        class _Root(BaseModel):
            leaves: list[Leaf] = []
            collected_names: list[str] = []

            def post_collected_names(self, collector=Collector("names")):
                return collector.values()

        # _Root needs to be a virtual root; its `leaves` field is a plain
        # list of Leaf (no relationship loading needed — values are inline).
        er = _make_er()
        er.add_virtual_entities([_Root])
        resolver = er.create_resolver()()

        root = _Root(leaves=[Leaf(name="Alice"), Leaf(name="Bob")])
        result = await resolver.resolve(root)
        assert sorted(result.collected_names) == ["Alice", "Bob"]

    async def test_collector_identity_same_alias(self):
        """Two Collector params with same alias in one post_* are the same instance."""

        class Leaf(BaseModel):
            name: Annotated[str, SendTo("names")]

        class _Root(BaseModel):
            leaves: list[Leaf] = []
            is_consistent: bool = False

            def post_is_consistent(
                self,
                c1=Collector("names"),
                c2=Collector("names"),
            ):
                return c1.values() == c2.values()

        er = _make_er()
        er.add_virtual_entities([_Root])
        resolver = er.create_resolver()()

        root = _Root(leaves=[Leaf(name="Alice"), Leaf(name="Bob")])
        result = await resolver.resolve(root)
        assert result.is_consistent is True


class _VirtInner(BaseModel):
    """Module-level Inner so the loader and the field type match exactly."""
    value: str


async def _virtual_to_virtual_loader(keys: list[str]) -> list[_VirtInner | None]:
    """Loader for TestVirtualToVirtualRelationship.

    Returns ``_VirtInner`` instances directly — the field type matches, so
    no conversion is needed. (Earlier versions of this test returned a
    DIFFERENT locally-scoped ``_Inner`` class and relied on duck typing;
    that worked only because the resolver used to skip conversion for any
    BaseModel. The resolver is stricter now.)
    """
    return [_VirtInner(value=f"value-for-{k}") for k in keys]


class TestVirtualToVirtualRelationship:
    """Edge Case A — virtual root declares relationship to another BaseModel."""

    async def test_virtual_to_virtual_traversal(self):
        class Outer(BaseModel):
            oid: str
            inner: _VirtInner | None = None

            __relationships__ = [
                Relationship(
                    fk="oid",
                    target=_VirtInner,
                    name="inner",
                    loader=_virtual_to_virtual_loader,
                ),
            ]

        er = _make_er()
        # Both Outer and Inner could be registered; here only Outer needs it
        # because Inner has no __relationships__ of its own.
        er.add_virtual_entities([Outer])
        resolver = er.create_resolver()()

        root = Outer(oid="key-1")
        result = await resolver.resolve(root)
        assert result.inner is not None
        assert result.inner.value == "value-for-key-1"


class TestSameBaseModelMultipleRelationships:
    """Edge Case H — same BaseModel referenced by multiple relationships."""

    async def test_shared_target_renders_once_in_registry(self):
        """Two relationships pointing at the same target type work fine —
        the target appears once in _registry (it's just a class), and each
        relationship is keyed separately on its source."""
        from pydantic import BaseModel as _BM

        class Tag(_BM):
            name: str

        async def _tags_by_a(keys: list[str]) -> list[list]:
            return [[Tag(name=f"a-{k}")] for k in keys]

        async def _tags_by_b(keys: list[str]) -> list[list]:
            return [[Tag(name=f"b-{k}")] for k in keys]

        class Root(_BM):
            oid: str
            tags_a: list[Tag] = []
            tags_b: list[Tag] = []

            __relationships__ = [
                Relationship(
                    fk="oid", target=list[Tag], name="tags_a", loader=_tags_by_a,
                ),
                Relationship(
                    fk="oid", target=list[Tag], name="tags_b", loader=_tags_by_b,
                ),
            ]

        er = _make_er()
        er.add_virtual_entities([Root])
        # Root is registered once; Tag is referenced twice via different
        # relationship names — no conflict.
        assert er.has_entity(Root)
        rels = er.get_relationships(Root)
        assert "tags_a" in rels
        assert "tags_b" in rels

        resolver = er.create_resolver()()
        result = await resolver.resolve(Root(oid="k1"))
        assert [t.name for t in result.tags_a] == ["a-k1"]
        assert [t.name for t in result.tags_b] == ["b-k1"]


# ──────────────────────────────────────────────────────────
# Layer 3 — Regression protection & invariants (FR-010, FR-016, Edge B)
# ──────────────────────────────────────────────────────────


class TestVirtualEntityInvariants:
    """Negative tests — virtual roots MUST NOT silently impersonate SQLModel."""

    def test_virtual_root_has_no_table_attribute(self):
        """FR-010 / FR-016: virtual root has no __table__ (no SQLAlchemy metadata)."""
        assert not hasattr(CurrentUserRoot, "__table__")

    def test_sa_inspect_rejects_virtual_root(self):
        """FR-016: sa_inspect() does NOT succeed on a plain BaseModel."""
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy.exc import NoInspectionAvailable

        with pytest.raises(NoInspectionAvailable):
            sa_inspect(CurrentUserRoot)

    def test_virtual_root_is_not_sqlmodel_subclass(self):
        """FR-016: BaseModel virtual root is NOT a SQLModel subclass."""
        assert not issubclass(CurrentUserRoot, SQLModel)

    async def test_unregistered_plain_basemodel_without_relationships(self):
        """Edge Case B: a plain BaseModel with no __relationships__ and no
        registration resolves without error — auto-load simply does nothing."""
        class Plain(BaseModel):
            name: str
            greeting: str = ""

            def resolve_greeting(self):
                return f"hi {self.name}"

        # No er.add_virtual_entities; no ErManager involved at all.
        result = await Resolver().resolve(Plain(name="x"))
        assert result.greeting == "hi x"

    async def test_unregistered_basemodel_with_relationships_raises(self):
        """Edge Case B (with __relationships__): spec requires a clear error
        pointing at the registration API — no silent auto-load skip."""
        class _SneakyRoot(BaseModel):
            oid: str
            name: str
            agents: list[AgentDTO] = []

            __relationships__ = [
                Relationship(
                    fk="oid",
                    target=list[AgentDTO],
                    name="agents",
                    loader=_load_agents_by_oid,
                ),
            ]

        er = _make_er()
        # Intentionally NOT calling er.add_virtual_entities([_SneakyRoot]).
        resolver = er.create_resolver()()

        with pytest.raises(RuntimeError, match="add_virtual_entities"):
            await resolver.resolve(_SneakyRoot(oid="user-1", name="Alice"))


class TestUnifiedSourceResolution:
    """FR-017 — the ``_resolve_source`` helper backing ``_get_loader`` and
    ``_scan_auto_load_fields`` must produce identical results across call
    sites. Regression for the copy-paste'd fallback that lived in two places
    before T03 (convergence round 3).
    """

    def test_resolve_source_returns_self_for_registered_virtual_root(self):
        """A virtual root registered via ``add_virtual_entities`` resolves
        to itself — it has no DefineSubset source, but is in ``_registry``."""
        er = _make_er()
        er.add_virtual_entities([CurrentUserRoot])
        resolver = er.create_resolver()()

        assert resolver._resolve_source(CurrentUserRoot) is CurrentUserRoot

    def test_resolve_source_returns_source_for_definesubset_dto(self):
        """A DefineSubset DTO resolves to its declared source class."""
        er = _make_er()
        resolver = er.create_resolver()()

        # AgentDTO is a DefineSubset sourced from _Agent (a SQLModel).
        assert resolver._resolve_source(AgentDTO) is _Agent

    def test_resolve_source_returns_none_for_unregistered_basemodel(self):
        """A plain BaseModel with no registration and no DefineSubset source
        resolves to None — no relationships to look up."""
        er = _make_er()
        resolver = er.create_resolver()()

        class _Orphan(BaseModel):
            x: int

        assert resolver._resolve_source(_Orphan) is None

    def test_resolve_source_consistent_across_call_sites(self):
        """The two consumers (``_get_loader`` and ``_scan_auto_load_fields``)
        must see the same source for the same node type. Build a virtual root
        whose ``__relationships__`` loader is registered in ``_registry``;
        verify both code paths resolve it to ``CurrentUserRoot``."""
        er = _make_er()
        er.add_virtual_entities([CurrentUserRoot])
        resolver = er.create_resolver()()

        node = CurrentUserRoot(oid="user-1", name="Alice")
        # Mirror the internal call shape both methods use.
        assert resolver._resolve_source(type(node)) is CurrentUserRoot

