# Implementation Plan: Resolver `loader_instances` Parameter

**Branch**: `002-resolver-loader-instances` | **Date**: 2026-06-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/002-resolver-loader-instances/spec.md`

## Summary

Add a `loader_instances` parameter to `Resolver.__init__` that accepts pre-created (typically pre-primed) DataLoader instances keyed by DataLoader class, matching pydantic-resolve's API. The parameter only affects the explicit `Loader(DataLoaderClass)` Depends path; auto-loaded relationship loaders (both custom `__relationships__` and ORM-native SQLModel) are unaffected. `ErManager.create_resolver()` is updated to forward the new parameter. Backward-compatible — all existing call sites behave identically.

## Technical Context

**Language/Version**: Python >= 3.10

**Primary Dependencies**: sqlmodel, graphql-core, fastapi, aiodataloader (already in tree; no new deps)

**Storage**: N/A (in-memory parameter plumbing only)

**Testing**: pytest + pytest-asyncio (`asyncio_mode=auto`); ruff (`line-length=100`, rules `E/F/I/UP/B`, ignore `B008`); mypy strict

**Target Platform**: Any Python 3.10+ host (Linux / macOS / Windows)

**Project Type**: library

**Performance Goals**: N/A — correctness-focused; no regression to existing traversal timings.

**Constraints**: Must not break existing public Resolver/ErManager APIs. Must not regress the existing test suite. Must not introduce a new dependency.

**Scale/Scope**: ~2 source files touched (`resolver.py`, `loader/registry.py`); ~5 new tests across `tests/test_resolver.py` and `tests/test_loader_registry.py`.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Status**: N/A — `.specify/memory/constitution.md` is the unfilled template; no principles to gate against. Project-level `CLAUDE.md` conventions still apply (do not write mirror sources into `uv.lock`, mypy strict, ruff `line-length=100`, no `B008`).

## Project Structure

### Documentation (this feature)

```text
specs/002-resolver-loader-instances/
├── spec.md              # /speckit-specify output (Phase 0 SKIPPED — library API addition)
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── api.md           # Phase 1 output (public API surface)
└── tasks.md             # /speckit-tasks output (not yet created)
```

### Source Code (repository root)

```text
src/nexusx/
├── resolver.py             # Resolver.__init__ gains loader_instances parameter
│                           # _validate_loader_instances (new) called from __init__
│                           # _get_or_create_loader consults supplied dict first
└── loader/
    └── registry.py         # ErManager.create_resolver() forwards loader_instances
                            # to BoundResolver.__init__ → super().__init__

tests/
├── test_resolver.py        # New: pre-prime, by-reference, validation-error cases
└── test_loader_registry.py # New: create_resolver() forwarding case
```

**Structure Decision**: Single-project library layout. Only `src/nexusx/resolver.py` and `src/nexusx/loader/registry.py` are touched on the source side; tests extend the existing files that already cover Resolver / ErManager.

## nexusx-4phase Phase 1 Overlay — SKIPPED

The nexusx-4phase preset's Phase 1 addendum (concrete SQLModel entities, alembic / `init_db()` branching, Voyager wiring, Phase 1 V-model acceptance criteria) targets **application builds**. For this library API addition, all of it is N/A:

- **Step 0-7 DB choice**: N/A — no persistence layer touched.
- **Entity list (Step 0-1)**: N/A — no new entities; `Resolver` and `ErManager` are existing classes whose constructor surface changes by one optional parameter.
- **Voyager wiring**: N/A — internal Resolver API, not a use-case service.
- **Alembic**: N/A — no schema change.

Consistent with the Phase 0 skip recorded in `spec.md`. Phase 1 addendum is therefore intentionally empty; the plan proceeds to standard Phase 1 design artifacts (data-model.md, contracts/, quickstart.md) only.

## Complexity Tracking

No constitution violations to justify. Table left empty.
