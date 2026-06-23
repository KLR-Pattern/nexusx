---

description: "Task list for Resolver loader_instances parameter"
---

# Tasks: Resolver `loader_instances` Parameter

**Input**: Design documents from `/specs/002-resolver-loader-instances/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/api.md](./contracts/api.md), [quickstart.md](./quickstart.md)

**Tests**: Included — the spec's user stories are acceptance scenarios that must be verified by runnable tests (see `quickstart.md`).

**Organization**: Foundational implementation first (one cohesive change across `resolver.py` + `loader/registry.py`), then per-user-story tests in parallel, then polish.

## nexusx-4phase Phase Grouping — SKIPPED

The nexusx-4phase preset expects Phase 2 (`methods.py` + `mount_method`), Phase 3 (`dtos.py` + `service.py` + main.py wiring), Phase 4 (TS SDK via `@hey-api/openapi-ts`). All N/A for a library API addition — no services, no DTOs, no REST/MCP/CLI wiring, no frontend. Consistent with the Phase 0 skip in `spec.md` and the Phase 1 addendum skip in `plan.md`. Tasks below use the standard speckit phase structure instead.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1 / US2 / US3 from `spec.md`)
- File paths are absolute under the repo root

---

## Phase 1: Setup (Baseline)

**Purpose**: Confirm green baseline before any change. No project initialization needed (existing library).

- [ ] T001 Run `./scripts/check-ci.sh` from repo root and confirm green baseline. Capture the pre-change state so any later regression is unambiguous.

---

## Phase 2: Foundational (Core Parameter Plumbing)

**Purpose**: The cohesive source change that backs FR-001 through FR-007. MUST be complete before any user-story test can be written meaningfully.

**⚠️ CRITICAL**: All test tasks (Phase 3+) depend on this phase.

- [ ] T002 Add `loader_instances: dict[type[DataLoader], DataLoader] | None = None` parameter to `Resolver.__init__` in `src/nexusx/resolver.py`. Populate `self._loader_instances = {}` when None/empty, else call new `_validate_loader_instances` and store. Follow R1 + R3 in `research.md`.
- [ ] T003 Add `_validate_loader_instances(self, loader_instances)` private method to `Resolver` in `src/nexusx/resolver.py`. Iterate items; raise `TypeError` per R2 in `research.md` when key is not a `DataLoader` subclass or value is not an instance of its key. Empty/None short-circuits without error.
- [ ] T004 Modify `_get_or_create_loader(self, loader_cls)` in `src/nexusx/resolver.py` (`resolver.py:408-412`) to consult `self._loader_instances` first; on miss, fall back to the existing `self._loader_cache` path. Follow R3 in `research.md`.
- [ ] T005 Forward `loader_instances` through `ErManager.create_resolver()` factory in `src/nexusx/loader/registry.py` (`registry.py:511-513`). `BoundResolver.__init__` gains a `loader_instances` keyword that is forwarded to `super().__init__`. Follow R5 in `research.md`.

**Checkpoint**: Resolver now accepts and uses `loader_instances`. Existing call sites (no `loader_instances`) behave identically. Re-run `./scripts/check-ci.sh` — must still be green.

---

## Phase 3: User Story 1 — Pre-priming (Priority: P1) 🎯 MVP

**Goal**: Caller can pre-prime a DataLoader and Resolver observes the primed value, suppressing the batch call for that key.

**Independent Test**: `uv run pytest tests/test_resolver.py::test_loader_instances_pre_prime -xvs`

### Tests for User Story 1

- [ ] T006 [US1] Write `test_loader_instances_pre_prime` in `tests/test_resolver.py`. Define a `DataLoader` subclass with a counting batch function. Prime key 42, leave key 7 unprimed. Pass the loader via `Resolver(loader_instances={CountingLoader: loader})`. Resolve a tree that loads both keys. Assert: key 42 returns the primed value; counter incremented exactly once (for key 7), not twice. Maps to `quickstart.md` Scenario 1 and FR-006.

**Checkpoint**: User Story 1 (the primary motivation for the feature) is fully functional and testable independently.

---

## Phase 4: User Story 2 — By-Reference Instance (Priority: P2)

**Goal**: Caller can supply a custom-configured DataLoader instance; Resolver uses it by reference (same `id()`, preserved constructor state).

**Independent Test**: `uv run pytest tests/test_resolver.py::test_loader_instances_by_reference -xvs`

### Tests for User Story 2

- [ ] T007 [P] [US2] Write `test_loader_instances_by_reference` in `tests/test_resolver.py`. Define `class TaggedLoader(DataLoader)` whose `__init__` stores a `tag` kwarg. Construct an instance, supply via `loader_instances`. The DTO's `resolve_*` captures the injected loader on a sentinel attribute. Assert `id(captured) == id(supplied)` and `captured.tag == "abc"`. Maps to `quickstart.md` Scenario 2 and FR-004.

**Checkpoint**: User Stories 1 AND 2 work independently.

---

## Phase 5: User Story 3 — Misuse / Fail-Fast Validation (Priority: P3)

**Goal**: Malformed `loader_instances` raises a typed `TypeError` at construction, never reaching the traversal loop.

**Independent Test**: `uv run pytest tests/test_resolver.py::test_loader_instances_validation_errors -xvs`

### Tests for User Story 3

- [ ] T008 [P] [US3] Write `test_loader_instances_validation_errors` in `tests/test_resolver.py`. Three sub-assertions: (a) `Resolver(loader_instances={dict: object()})` raises `TypeError` mentioning "subclass of DataLoader"; (b) `Resolver(loader_instances={TaggedLoader: object()})` raises `TypeError` mentioning the expected class name; (c) `Resolver(loader_instances={})` and `Resolver()` succeed without error. Maps to `quickstart.md` Scenario 3 and FR-002.

**Checkpoint**: All three user stories independently verifiable.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Docstring, factory-forwarding test (FR-005), and full regression.

- [ ] T009 [P] Update `Resolver` class docstring in `src/nexusx/resolver.py` (the module docstring at `resolver.py:1-33` and the class docstring around `resolver.py:323-338`) to document `loader_instances`: parameter description, lifetime semantics (not cleared between `resolve()` calls — caller owns lifecycle), and the auto-load isolation rule.
- [ ] T010 [P] Write `test_create_resolver_forwards_loader_instances` in `tests/test_loader_registry.py`. Build a small ErManager over an in-memory SQLModel subset. `Resolver = er.create_resolver(); r = Resolver(loader_instances={CountingLoader: loader})`. Resolve a DTO tree; assert primed value observed and counter not incremented for primed key (mirrors T006 semantics via the factory). Maps to `quickstart.md` Scenario 4 and FR-005.
- [ ] T011 Run `./scripts/check-ci.sh` from repo root. Expected outcome: full existing suite passes, `ruff check src/ tests/` clean, `mypy src/` clean. Maps to `quickstart.md` Scenario 5 and SC-002.
- [ ] T012 [P] Add `loader_instances` to the public API list in `CLAUDE.md` (top-level, under `## 公共 API`) if not already present, so it's documented alongside `Loader` and `ErManager`.

**Checkpoint**: Feature complete, documented, and CI-green.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately.
- **Phase 2 (Foundational)**: Depends on Phase 1.
  - T002 before T003 (validator is invoked by constructor).
  - T002 before T004 (`_get_or_create_loader` reads `_loader_instances` populated by `__init__`).
  - T002 before T005 (factory forwards the new parameter).
- **Phases 3–5 (User Story tests)**: All depend on Phase 2 completion. Independent of each other — different test functions in the same file (`tests/test_resolver.py`), so technically not `[P]` for the file-edit definition, but logically independent and can be written in any order.
- **Phase 6 (Polish)**: T009 + T010 depend on Phase 2. T011 depends on all prior test tasks. T012 is independent of code changes.

### Parallel Opportunities

- T003 and T004 are in the same file but different functions; if scoped tightly they can be reviewed together but should land sequentially (T003 sets up storage, T004 reads it).
- T006, T007, T008 — once Phase 2 lands, all three tests can be drafted in parallel (different test functions, but same file — coordinate to avoid merge conflicts, or do them sequentially).
- T009, T010, T012 are independent of each other and can run in parallel.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 (T001) — confirm green baseline.
2. Phase 2 (T002–T005) — land the cohesive source change. Re-run CI; must still be green.
3. Phase 3 (T006) — write the pre-prime test. Run it; must pass.
4. **STOP and VALIDATE**: User Story 1 is the primary motivation (skip redundant query via pre-priming). If T006 passes, the feature is functionally shippable.
5. Continue with Phase 4–6 in any order.

### Incremental Delivery

1. Phase 1 + Phase 2 → core plumbing ready, no behavior change for existing callers.
2. Add Phase 3 (US1) → ship P1 use case.
3. Add Phase 4 (US2) → ship P2 use case.
4. Add Phase 5 (US3) → ship P3 use case.
5. Add Phase 6 → docstring + factory test + full regression + CLAUDE.md update.

---

## Notes

- All `[P]` tasks touch different concerns; verify no merge conflicts before running truly in parallel.
- `[Story]` labels map to `spec.md` user stories (US1 = pre-priming P1, US2 = by-reference P2, US3 = misuse P3).
- Factory-forwarding test (T010) is in Phase 6 because FR-005 is not tied to a specific user story — it's an ergonomics-parity concern (SC-004).
- No new dependencies; no schema changes; no migrations; no breaking changes to existing public API.
- After T011 (final CI run), the feature is ready for commit / PR.
