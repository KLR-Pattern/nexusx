# Implementation Plan: Non-SQLModel Root Objects

**Branch**: `004-non-sqlmodel-roots` | **Date**: 2026-06-25 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-non-sqlmodel-roots/spec.md`

## Summary

Make plain `pydantic.BaseModel` subclasses first-class participants in NexusX resolution and ER visualization, without requiring them to inherit from any NexusX-specific base class. Two orthogonal APIs, both serving real scenarios:

1. **`ErManager.add_virtual_entities([...])`** — registers plain BaseModel classes as virtual entities in the ER graph (called after `ErManager()` construction but before the first `create_resolver()`). Use case: a BaseModel class that **is itself the root schema** (`CurrentUser`, page wrappers, etc.).
2. **`DefineSubset.__subset__` source widening** — accepts any BaseModel, not just SQLModel. "Subset" is understood as **schema subset** (a selection of `model_fields`). Use case: a DTO that is a **subset of an external BaseModel schema** (third-party SDK class, response shape from another service, etc.).

The two compose cleanly — a BaseModel class can be registered as virtual (path 1), used as DefineSubset source (path 2), both, or neither.

Runtime Resolver behavior is **unified**: "find the source class for this `node_type`, then look up its relationships". `get_subset_source()` returns the source for DefineSubset DTOs (SQLModel or BaseModel — both work after the widening); for plain BaseModel roots not in `_subset_registry`, the Resolver falls back to checking `_registry` directly. The subsequent `_registry.get_relationships(source)` is source-type-agnostic.

`ErManager.__init__`'s `base=` / `entities=` requirement is unchanged. The capability is purely additive.

## Technical Context

**Language/Version**: Python 3.10+ (per `pyproject.toml` `requires-python = ">=3.10"`)

**Primary Dependencies**:
- `pydantic >= 2.0` — BaseModel, the foundation for virtual entities
- `sqlmodel >= 0.0.14` — used by `ErManager` today; remains required for the SQLModel entity path
- `sqlalchemy >= 2.0` (transitive via sqlmodel) — only touched on the SQLModel entity path; explicitly NOT used for virtual entities
- `aiodataloader >= 0.4.3` — DataLoader base, used by custom relationship loaders
- `fastapi >= 0.135.1` — runtime integration target (Spinoff benefit; no FastAPI-specific code needed)

**Storage**: N/A — virtual entities have no persistence. This feature adds no storage surface.

**Testing**: `pytest >= 7.0` with `pytest-asyncio`. Existing suite: 1025 passing / 6 skipped (3.14-only). Style follows existing `tests/test_*.py` flat layout.

**Target Platform**: Linux / macOS / Windows (Python library, no platform-specific code).

**Project Type**: library (single-package layout under `src/nexusx/`).

**Performance Goals**: Virtual entity registration at startup must complete in <100 ms for typical projects (<50 virtual entities). Runtime resolution must have **zero** overhead for trees that don't include virtual entities (i.e., when `add_virtual_entities` is never called, behavior is bit-identical to today).

**Constraints**:
- **Backward compatibility is non-negotiable**: every existing test must pass without modification (spec FR-008, SC-003).
- **`ErManager.__init__` signature is unchanged**: `base=` / `entities=` requirement stays (user-confirmed).
- **No new dependencies**: feature must be expressible with the existing stack.
- **No silent impersonation**: virtual entities must NOT acquire `__table__`, must NOT be accepted by SQLAlchemy inspection, must NOT be subclassed into SQLModel (spec FR-016).

**Scale/Scope**: ~200–350 source LOC across:
- `loader/registry.py`: `add_virtual_entities()` method + `_frozen` flag (~60 LOC)
- `subset.py`: DefineSubset source validation widening (`issubclass(SQLModel)` → `issubclass(BaseModel)`) and DefineSubset-from-BaseModel path in `_orm_to_dto` (~30 LOC)
- `relationship.py`: type annotation widening on `get_custom_relationships` and `Relationship.target_entity` (~10 LOC)
- `resolver.py`: unified source-resolution in `_scan_auto_load_fields` (~15 LOC — fallback to `_registry` lookup when `get_subset_source` returns None)
- `er_diagram.py` + `voyager/`: virtual node rendering branch (~100–150 LOC)
- Plus ~30–40 new tests (~300–500 LOC)

Roughly 2–3 PRs of work — recommended split:
1. `add_virtual_entities` + Resolver unification + DefineSubset widening (runtime path)
2. ER/Voyager virtual node rendering
3. Cross-boundary test sweep + edge cases

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Status**: N/A — `.specify/memory/constitution.md` is still the unfilled template (10 unfilled `[PRINCIPLE_*]` placeholders). No principles to gate against. Re-check after Phase 1 design will similarly be N/A until the constitution is filled by a separate `/speckit-constitution` run.

**Recommendation**: Do not block this feature on filling the constitution. If the team later ratifies principles that conflict with this design (e.g., "no public mutability" → challenges `add_virtual_entities()`), revisit then.

## Project Structure

### Documentation (this feature)

```text
specs/004-non-sqlmodel-roots/
├── plan.md              # This file
├── research.md          # Phase 0 output — R1..R4 resolved design questions
├── data-model.md        # Phase 1 output — ErManager state, virtual entity shape
├── quickstart.md        # Phase 1 output — runnable validation scenarios
├── contracts/
│   └── api.md           # Phase 1 output — public API contracts (add_virtual_entities, Relationship)
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/nexusx/
├── loader/
│   └── registry.py          # ErManager — add_virtual_entities(), _frozen flag
├── subset.py                # DefineSubset source validation: BaseModel, not just SQLModel
├── relationship.py          # get_custom_relationships() + Relationship.target_entity type widening
├── resolver.py              # _scan_auto_load_fields: unified source resolution
├── er_diagram.py            # ErDiagram branch for virtual nodes (no sa_inspect)
└── voyager/
    ├── er_diagram_dot.py    # DOT rendering branch for virtual nodes
    └── type_helper.py       # (may need touch) handling non-SQLModel sources

tests/
├── test_virtual_entities.py          # NEW — virtual entity registration + lifecycle
├── test_definesubset_basemodel.py    # NEW — DefineSubset sourced from BaseModel
├── test_virtual_entities_er.py       # NEW — ER/Voyager rendering with virtual nodes
└── (existing tests unchanged)
```

**Structure Decision**: Single-project library layout (`src/nexusx/` + flat `tests/`). Matches existing 003 / 002 specs' structure. No new packages, no new top-level modules — feature slots into existing files.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

N/A — Constitution Check is unfilled template, no violations to justify.
