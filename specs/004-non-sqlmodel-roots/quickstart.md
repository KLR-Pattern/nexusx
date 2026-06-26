# Quickstart: Non-SQLModel Root Objects

**Date**: 2026-06-25
**Spec**: [spec.md](./spec.md) | **Contracts**: [contracts/api.md](./contracts/api.md)

Runnable validation scenarios that prove the feature works end-to-end. Each scenario is self-contained — copy-paste-runnable in a test file or a Python REPL with `pytest` + `pytest-asyncio`. **No real database needed**; loaders use in-memory dicts.

## Prerequisites

- Python 3.10+
- nexusx installed (or repo on `PYTHONPATH`)
- pytest, pytest-asyncio

## Setup (shared fixture)

```python
# conftest.py or top of test file
from __future__ import annotations
import asyncio
from typing import Annotated
import pytest
from pydantic import BaseModel
from sqlmodel import SQLModel, Field
from nexusx import ErManager, Relationship, DefineSubset

# --- SQLModel entity (the SQLModel side of the boundary) ---
class Agent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_oid: str
    name: str

# --- DefineSubset DTO sourced from Agent ---
class AgentDTO(DefineSubset):
    __subset__ = (Agent, ("id", "owner_oid", "name"))

# --- In-memory async batch loader (no DB) ---
async def load_agents_by_user_oid(keys: list[str]) -> list[list[AgentDTO]]:
    db = {
        "user-1": [AgentDTO(id=1, owner_oid="user-1", name="A1"),
                   AgentDTO(id=2, owner_oid="user-1", name="A2")],
        "user-2": [AgentDTO(id=3, owner_oid="user-2", name="B1")],
    }
    return [db.get(k, []) for k in keys]

# --- The virtual entity itself (plain BaseModel + __relationships__) ---
class CurrentUserRoot(BaseModel):
    oid: str
    name: str
    agents: list[AgentDTO] = []

    __relationships__ = [
        Relationship(
            fk="oid",
            target=list[AgentDTO],
            name="agents",
            loader=load_agents_by_user_oid,
        ),
    ]

@pytest.fixture
def session_factory():
    # In-memory or test DB session factory; see existing tests/conftest.py
    # for the pattern used by tests/test_db.py. For this quickstart we
    # stub it because no SQLModel-side query is exercised.
    return lambda: None
```

## Scenario 1: Happy path — virtual entity as Resolver root

Validates FR-001, FR-002, FR-004, FR-011, FR-013.

```python
@pytest.mark.asyncio
async def test_virtual_root_resolves(session_factory):
    er = ErManager(entities=[Agent], session_factory=session_factory)
    er.add_virtual_entities([CurrentUserRoot])
    resolver = er.create_resolver()

    root = CurrentUserRoot(oid="user-1", name="Alice")
    result = await resolver.resolve(root)

    assert len(result.agents) == 2
    assert {a.name for a in result.agents} == {"A1", "A2"}
```

**Expected outcome**: `result.agents` is populated with 2 AgentDTOs via `load_agents_by_user_oid`. No exceptions. No mutation of `_subset_registry`.

**Fails today because**: `ErManager.add_virtual_entities()` does not exist; `CurrentUserRoot`'s `__relationships__` is never read.

## Scenario 2: `resolve_*` and `post_*` on virtual root

Validates FR-002, FR-003.

```python
class CurrentUserRoot(BaseModel):
    oid: str
    name: str
    agent_count: int = 0
    agent_summary: str = ""
    agents: list[AgentDTO] = []

    __relationships__ = [
        Relationship(fk="oid", target=list[AgentDTO], name="agents",
                     loader=load_agents_by_user_oid),
    ]

    def resolve_greeting(self):
        return f"Hello, {self.name}!"

    def post_agent_count(self):
        return len(self.agents)

    def post_agent_summary(self):
        return ", ".join(a.name for a in self.agents)

@pytest.mark.asyncio
async def test_virtual_root_resolve_and_post(session_factory):
    er = ErManager(entities=[Agent], session_factory=session_factory)
    er.add_virtual_entities([CurrentUserRoot])
    resolver = er.create_resolver()

    root = CurrentUserRoot(oid="user-1", name="Alice")
    result = await resolver.resolve(root)

    assert result.agent_count == 2
    assert result.agent_summary == "A1, A2"
```

**Expected outcome**: `resolve_*` populates `agents`; `post_*` methods see the populated `agents` and compute derived fields.

## Scenario 3: Lifecycle — `add_virtual_entities` after `create_resolver` raises

Validates FR-013 (RuntimeError guard).

```python
def test_add_after_create_raises(session_factory):
    er = ErManager(entities=[Agent], session_factory=session_factory)
    resolver = er.create_resolver()  # freezes registry
    with pytest.raises(RuntimeError, match="frozen"):
        er.add_virtual_entities([CurrentUserRoot])
```

**Expected outcome**: `RuntimeError` with "frozen" in the message. No mutation of `_registry`.

## Scenario 4: Type validation — SQLModel rejected with TypeError

Validates FR-013 (TypeError for SQLModel input).

```python
def test_add_sqlmodel_rejected(session_factory):
    er = ErManager(entities=[Agent], session_factory=session_factory)
    with pytest.raises(TypeError, match="SQLModel"):
        er.add_virtual_entities([Agent])  # Agent is SQLModel
```

## Scenario 5: Duplicate registration rejected with ValueError

Validates FR-007, FR-013.

```python
def test_duplicate_rejected(session_factory):
    er = ErManager(entities=[Agent], session_factory=session_factory)
    er.add_virtual_entities([CurrentUserRoot])
    with pytest.raises(ValueError, match="already registered"):
        er.add_virtual_entities([CurrentUserRoot])  # second call — duplicate
```

## Scenario 6: ER diagram renders virtual node without crashing

Validates FR-009, SC-004.

```python
def test_er_diagram_with_virtual_entity(session_factory):
    from nexusx import ErDiagram
    from nexusx.voyager.er_diagram_dot import ErDiagramDotBuilder

    er = ErManager(entities=[Agent], session_factory=session_factory)
    er.add_virtual_entities([CurrentUserRoot])

    # Data path — inspect entities and relationships (no DOT rendering).
    diagram = ErDiagram.from_er_manager(er)
    virtual = next(e for e in diagram.entities if e.name == "CurrentUserRoot")
    assert virtual.is_virtual is True          # FR-009 visual signal carried in data
    assert virtual.fk_fields == []             # no SQLAlchemy mapper → no FKs

    # DOT path — render to graphviz and assert Contract 3 visual distinction.
    builder = ErDiagramDotBuilder(er, show_fields="all")
    builder.analysis()
    dot = builder.render_dot()

    # Virtual node appears, with the four Contract 3 signals:
    assert "CurrentUserRoot" in dot
    assert "cluster_virtual" in dot               # separate dashed cluster
    assert "«virtual»\\nCurrentUserRoot" in dot    # UML stereotype label
    assert "FFF9C4" in dot                         # light yellow header fill
    # Edge to Agent / AgentDTO is drawn.
    assert "Agent" in dot
```

**Expected outcome**: `ErDiagram.from_er_manager(er)` returns an `EntityInfo` with `is_virtual=True`; the DOT output groups `CurrentUserRoot` into a dashed `cluster_virtual` subgraph with a yellow header (`#FFF9C4`) and the `«virtual»\n` stereotype prefix. Edges to `Agent` are drawn with the same arrow style as SQLModel-to-SQLModel edges.

**Implementation note**: the original plan called for `shape=note`, but the existing renderer uses HTML labels (`shape=plain`) for *all* nodes — switching shape for one node type would break the HTML label rendering. The visual distinction is therefore carried by **fill color** + **stereotype label prefix** + **separate cluster**, which collectively satisfy FR-009. See `contracts/api.md` Contract 3 for the agreed rules.

## Scenario 7: Backward compatibility — pure SQLModel path unchanged

Validates FR-008, SC-003.

```python
@pytest.mark.asyncio
async def test_pure_sqlmodel_still_works(session_factory):
    # No add_virtual_entities call — bit-identical to today's behavior.
    er = ErManager(entities=[Agent], session_factory=session_factory)
    resolver = er.create_resolver()

    # ... existing Agent-only resolution ...
    # (use an existing test from tests/ as a smoke check)
```

**Expected outcome**: passes. The `_frozen` flag is `True` after `create_resolver`, but no `add_virtual_entities` call is made, so the guard never fires.

## Scenario 9: DefineSubset sourced from a BaseModel

Validates FR-014 (widened) — schema subsetting works for BaseModel sources.

```python
from oauth_sdk import OAuthClaims   # third-party BaseModel, 28 fields

class AuthSummaryDTO(DefineSubset):
    __subset__ = (OAuthClaims, ('sub', 'email', 'name'))
    # AuthSummaryDTO has only 3 of OAuthClaims's 28 fields

def test_definesubset_from_basemodel_schema():
    # The DTO class is built successfully with subset fields.
    assert AuthSummaryDTO.__subset_fields__ == ('sub', 'email', 'name')
    # Direct construction works (no ORM row needed).
    dto = AuthSummaryDTO(sub='user-1', email='a@x.com', name='Alice')
    assert dto.sub == 'user-1'
```

**Expected outcome**: DefineSubset accepts the BaseModel source. `__subset_fields__` is populated from OAuthClaims's `model_fields`. No exception raised.

**Fails today because**: `subset.py:544` rejects the source with `"DefineSubset source must be a SQLModel subclass"`.

## Scenario 10: DefineSubset from BaseModel + registered virtual entity

Validates FR-014 + FR-013 + FR-017 together — DTO subset of a registered BaseModel source, with auto-load firing through the source's `__relationships__`.

```python
class CurrentUser(BaseModel):       # plain BaseModel
    oid: str
    name: str
    tenant_id: str
    # ... 20 more fields from your auth context

    __relationships__ = [
        Relationship(
            fk="oid",
            target=list[AgentDTO],
            name="agents",
            loader=load_agents_by_user_oid,
        ),
    ]

class CurrentUserDTO(DefineSubset):
    __subset__ = (CurrentUser, ('oid', 'name'))   # subset of CurrentUser's schema
    agents: list[AgentDTO] = []                    # declared on the DTO — auto-loaded via source's relationship

@pytest.mark.asyncio
async def test_definesubset_from_registered_basemodel(session_factory):
    er = ErManager(entities=[Agent], session_factory=session_factory)
    er.add_virtual_entities([CurrentUser])         # register source
    resolver = er.create_resolver()

    dto = CurrentUserDTO(oid="user-1", name="Alice")
    result = await resolver.resolve(dto)

    assert len(result.agents) == 2
    assert {a.name for a in result.agents} == {"A1", "A2"}
```

**Expected outcome**: The DTO is constructed directly (no ORM). At resolve time, `_scan_auto_load_fields` finds source = `CurrentUser` via `get_subset_source(CurrentUserDTO)`, then `_registry.get_relationships(CurrentUser)` returns the `agents` relationship, which auto-loads.

## Scenario 11: Migration from `_subset_registry` hack

Validates SC-006 (mechanical migration).

## Running the scenarios

```bash
# Save scenarios as tests/test_virtual_entities.py and run:
pytest tests/test_virtual_entities.py -v

# Or run a single scenario:
pytest tests/test_virtual_entities.py::test_virtual_root_resolves -v
```

All scenarios should pass after the feature is implemented (Phase 2). Today, Scenarios 1–6, 9, 10 fail; 7 is N/A; 11 is documentation-only.

## Coverage Matrix

The 11 scenarios above are the **happy paths and lifecycle** validations. They are not the full test surface. The matrix below maps every spec FR / Edge Case to a test category and indicates which layer owns it. `/speckit-tasks` should split work along these three layers.

### Layer 1 — API contract & lifecycle (foundation)

The quickstart scenarios in this layer validate the **public API surface itself** — that `add_virtual_entities()` exists, accepts/rejects the right inputs, freezes at the right moment. Must pass before any other layer is meaningful.

| Test | Source | FR / Edge covered |
|------|--------|-------------------|
| Happy path registration + resolve | S1 | FR-001, FR-011, FR-013 |
| `resolve_*` / `post_*` on virtual root | S2 | FR-002, FR-003 |
| `add_virtual_entities` post-freeze → RuntimeError | S3 | FR-013 (lifecycle) |
| SQLModel in `add_virtual_entities` → TypeError | S4 | FR-013 (type validation) |
| Duplicate registration → ValueError | S5 | FR-007, FR-013 |
| Non-BaseModel class → TypeError | (new) | FR-013 (type validation, second arm) |
| Empty list `[]` → no-op, no error | (new) | FR-013 (edge) |

**~7 tests. Maps to PR 1.**

### Layer 2 — Capability parity with SQLModel roots

This is the layer that proves "virtual root behaves like SQLModel root". The principle: **every behavior tested for SQLModel-rooted trees in the existing suite should have a virtual-rooted counterpart.** Without this layer, FR-015 ("boundary transparent") is an assertion, not a fact.

For each row below, the existing SQLModel-side test is the reference; the virtual-side test is what's new.

| Capability | SQLModel-side reference | Virtual-side test to add | FR / Edge covered |
|------------|-------------------------|--------------------------|-------------------|
| ExposeAs ancestor-context passing | `tests/test_context.py::TestExposeAs` | mirror, root is virtual | FR-005, FR-015 |
| Multi-level ExposeAs | `TestExposeAs::test_multi_level_expose` | mirror, intermediate node is virtual | FR-005, FR-015 |
| SendTo + Collector aggregation | `TestSendToCollector` | mirror, leaf is virtual, collector on virtual root | FR-005, Edge G |
| Collector flat mode | `TestSendToCollector::test_collector_flat_mode` | mirror | FR-005 |
| Multi-collector SendTo | `TestSendToMultiCollector` | mirror | FR-005 |
| Collector identity (same alias = same instance) | `TestCollectorIdentity` | mirror | FR-005 |
| Flat nested collection | `TestCollectorFlatNest` | mirror | FR-005 |
| Multi-level collector | `TestCollectorLevelByLevel` | mirror | FR-005 |
| Multi-field SendTo (same collector) | `TestMultiFieldSendTo` | mirror | FR-005 |
| `post_default_handler` on root | (various) | virtual root with `post_default_handler` | FR-003 |
| Loader + Collector in `post_*` | `TestPostLoaderCollectorLimitation` | mirror | FR-005 |
| AutoLoad via `__relationships__` | `tests/test_autoload.py` | mirror, source is virtual | FR-004, FR-012, FR-017 |
| DefineSubset from BaseModel (schema subset only) | S9 | (already a quickstart scenario) | FR-014 |
| DefineSubset from BaseModel + registered source | S10 | (already a quickstart scenario) | FR-013, FR-014, FR-017 |
| AutoLoad doesn't fire for unregistered BaseModel source | (new) | DTO with `__subset__ = (UnregisteredBaseModel, ...)`; verify no auto-load | Edge I |
| Virtual root → virtual root relationship | (new) | both endpoints are BaseModel | Edge A |
| Same BaseModel referenced by multiple relationships | (new) | verify single virtual node, multiple edges | Edge H |
| Subset field name + relationship name collision | (new) | relationship loader takes precedence (matches SQLModel behavior) | Edge J |
| Sequential resolve on same Resolver instance | `tests/test_resolver.py` (existing pattern) | mirror with virtual roots | regression for #293 |

**~18 tests. Maps to PR 1 (the parity-critical subset) + PR 3 (full sweep).**

### Layer 3 — Regression protection & invariants

This layer guards against future changes that would silently break the spec's invariants. Mostly negative tests ("this MUST NOT happen").

| Test | What it asserts | FR / Edge covered |
|------|------------------|-------------------|
| Virtual root has no `__table__` attribute | `not hasattr(CurrentUserRoot, "__table__")` | FR-010, FR-016 |
| `sa_inspect(virtual_root_class)` raises | SQLAlchemy inspection rejects the class | FR-016 |
| Resolver.resolve(unregistered plain BaseModel) without `__relationships__` | Returns the model unchanged (no error, no auto-load) — establishes baseline | Edge B |
| Resolver.resolve(plain BaseModel with `__relationships__`) without `add_virtual_entities` | Spec says "clear error pointing at registration API" — verify error or document silent-skip | Edge B |
| ER diagram generation with mixed SQLModel + virtual | No exception, both kinds present in DOT output | FR-009, SC-004 |
| ER diagram generation with zero virtual entities | Bit-identical to today's output | FR-008 |
| Voyager opens with mixed graph | No exception | FR-009 |
| Pure SQLModel test suite still passes (1025 existing tests) | All green, no modification | FR-008, SC-003 |
| Resolver benchmarks: zero overhead when no virtual entities registered | Bench result within noise of baseline | performance goal |

**~9 tests. Maps to PR 2 (ER/Voyager subset) + PR 3 (invariant subset).**

### Summary

| Layer | Test count | Primary PR | What "done" means |
|-------|-----------|------------|-------------------|
| 1 — API contract | ~7 | PR 1 | `add_virtual_entities` is usable and validates correctly |
| 2 — Capability parity | ~18 | PR 1 + PR 3 | Virtual roots behave identically to SQLModel roots for every documented cross-layer capability |
| 3 — Regression protection | ~9 | PR 2 + PR 3 | Future changes can't silently break invariants or regress SQLModel-only workflows |
| **Total** | **~34** | | |

The 11 quickstart scenarios above are a subset of Layer 1 + parts of Layer 2 (S6 touches Layer 3 too). The matrix expands coverage to the full surface.

## What this quickstart does NOT cover

For full implementation details, see `tasks.md` (generated by `/speckit-tasks` — not yet created). Specifically:

- Implementation of `add_virtual_entities()` body
- Implementation of ER/Voyager rendering branch
- Type widening of `get_custom_relationships` / `Relationship.target_entity`
- Internal `_frozen` flag wiring on `create_resolver()`
- DefineSubset source validation widening in `subset.py`
- Resolver `_scan_auto_load_fields` unified source-resolution fallback

These are the **what users can verify** scenarios. The **how to build** scenarios belong in `tasks.md`.
