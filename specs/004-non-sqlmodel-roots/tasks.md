---

description: "Task list for Non-SQLModel Root Objects feature implementation"
---

# Tasks: Non-SQLModel Root Objects

**Input**: Design documents from `/specs/004-non-sqlmodel-roots/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/api.md](./contracts/api.md), [quickstart.md](./quickstart.md)

**Tests**: Test tasks ARE included — quickstart.md defines a 3-layer Coverage Matrix (~34 tests) that maps to spec FRs and Edge Cases. Tests are integral to this feature, not optional.

**Organization**: Tasks grouped by user story (US1 = virtual root + add_virtual_entities, US2 = DefineSubset from BaseModel + composite relationships, US3 = ER/Voyager rendering). Each story is independently testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- File paths are absolute under repo root (`src/nexusx/...`, `tests/...`)

## Path Conventions

Single-project library layout. Source in `src/nexusx/`, tests in `tests/`. Matches existing 002 / 003 specs.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify clean starting state, confirm understanding of design docs.

- [X] T001 Confirm clean git state on `master` and create feature branch `004-non-sqlmodel-roots`
- [X] T002 [P] Re-read [research.md](./research.md) R1–R8 and [contracts/api.md](./contracts/api.md) Contracts 1–6 to confirm touch points before implementation

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Type-widening and infrastructure changes that ALL user stories depend on. MUST complete before any US work begins.

**⚠️ CRITICAL**: US1 / US2 / US3 all build on these. Skipping means rework.

- [X] T003 [P] Widen type annotations on `get_custom_relationships()` (parameter) and `Relationship.target_entity` (return type) from `type[SQLModel]` to `type` / `type[BaseModel]` in `src/nexusx/relationship.py` — pure annotation change, body unchanged (research.md R2)
- [X] T004 [P] Add `self._frozen: bool = False` initialization to `ErManager.__init__` and a `has_entity(entity: type) -> bool` convenience method in `src/nexusx/loader/registry.py` (research.md R3, R5)

**Checkpoint**: Foundation ready — `add_virtual_entities()` and Resolver fallback can now be implemented on top.

---

## Phase 3: User Story 1 — Plain BaseModel Virtual Root (Priority: P1) 🎯 MVP

**Goal**: A backend developer can declare a plain `BaseModel` root (e.g., `CurrentUser`), register it via `er.add_virtual_entities([...])`, and have `Resolver().resolve(root)` populate `resolve_*` / `post_*` / custom-relationship fields — without touching `_subset_registry`.

**Independent Test**: Quickstart S1 + S2 + S3 + S4 + S5 pass. The end-to-end `CurrentUser → AgentDTO` flow from Issue #87's Minimum Acceptance Criteria runs without errors.

### Tests for User Story 1 (Layer 1 — API contract) ⚠️ Write first, must FAIL before implementation

- [X] T005 [P] [US1] Write Layer 1 tests for `add_virtual_entities()` contract in `tests/test_virtual_entities.py`: happy-path registration, post-`create_resolver` RuntimeError, SQLModel input TypeError, duplicate registration ValueError, non-BaseModel input TypeError, empty-list no-op (quickstart S1, S3, S4, S5)

### Implementation for User Story 1

- [X] T006 [US1] Implement `ErManager.add_virtual_entities(entities: list[type[BaseModel]]) -> None` body in `src/nexusx/loader/registry.py` — reads each class's `__relationships__` via widened `get_custom_relationships()`, wires `RelationshipInfo` entries into `self._registry`, validates BaseModel-not-SQLModel / non-duplicate / not-frozen (contracts/api.md Contract 1)
- [X] T007 [US1] Set `self._frozen = True` at top of `ErManager.create_resolver()` in `src/nexusx/loader/registry.py` (research.md R3)
- [X] T008 [US1] Implement unified source-resolution fallback in `Resolver._scan_auto_load_fields` in `src/nexusx/resolver.py` — when `get_subset_source(node_type)` returns None, check `self._registry.has_entity(node_type)` and use `node_type` as source (research.md R5, ~10 LOC)

### Tests for User Story 1 (Layer 2 — Capability parity)

- [X] T009 [P] [US1] Add `resolve_*` and `post_*` on virtual root tests in `tests/test_virtual_entities.py` (quickstart S2) — verify identical behavior to SQLModel-rooted DTOs
- [X] T010 [P] [US1] Add `post_default_handler` on virtual root test in `tests/test_virtual_entities.py` — finalizer fires after all named `post_*` complete
- [X] T011 [P] [US1] Add sequential-`resolve`-no-leak test with virtual roots in `tests/test_virtual_entities.py` — regression for #293 clone semantics across the boundary

**Checkpoint**: Plain BaseModel virtual root fully functional. Quickstart S1, S2, S3, S4, S5 pass. Issue #87 minimum acceptance criteria met for the virtual-root-only path.

---

## Phase 4: User Story 2 — DefineSubset from BaseModel + Composite Roots (Priority: P2)

**Goal**: A developer can declare a `DefineSubset` DTO sourced from a plain `BaseModel` (schema subset of an external model), AND declare custom relationships on virtual roots that span the SQLModel / BaseModel boundary transparently.

**Independent Test**: Quickstart S9 + S10 pass. A `DefineSubset` DTO sourced from a BaseModel works for direct construction; when the BaseModel source is also registered via `add_virtual_entities`, auto-load fires through the source's `__relationships__`.

### Implementation for User Story 2

- [X] T012 [P] [US2] Widen DefineSubset source validation in `src/nexusx/subset.py:544` from `issubclass(entity_kls, SQLModel)` to `issubclass(entity_kls, BaseModel)`; update error message to mention both SQLModel and BaseModel are accepted (research.md R8)
- [X] T013 [P] [US2] Widen `_subset_registry` type annotation in `src/nexusx/subset.py:53` from `dict[type[BaseModel], type[SQLModel]]` to `dict[type[BaseModel], type[BaseModel]]` (research.md R8)
- [X] T014 [US2] Clarify `_orm_to_dto` applicability in `src/nexusx/resolver.py:663` — rename or update docstring to indicate it's only invoked for SQLModel sources; BaseModel sources are constructed directly by the user (research.md R8)

### Tests for User Story 2 (Layer 1 + Layer 2)

- [X] T015 [P] [US2] Write DefineSubset-from-BaseModel Layer 1 tests in `tests/test_definesubset_basemodel.py` (quickstart S9): schema subsetting works, `__subset_fields__` populated, direct construction works, `_orm_to_dto` not invoked
- [X] T016 [P] [US2] Write DefineSubset-from-registered-BaseModel Layer 2 test in `tests/test_definesubset_basemodel.py` (quickstart S10): DTO + registered source + auto-load fires
- [X] T017 [P] [US2] Mirror `TestExposeAs` from `tests/test_context.py` with virtual root in `tests/test_virtual_entities.py` — single-level + multi-level expose
- [X] T018 [P] [US2] Mirror `TestSendToCollector` from `tests/test_context.py` with virtual root in `tests/test_virtual_entities.py` — basic + flat mode + multi-collector
- [X] T019 [P] [US2] Mirror `TestCollectorFlatNest` and `TestCollectorLevelByLevel` with virtual root in `tests/test_virtual_entities.py`
- [X] T020 [P] [US2] Mirror `TestCollectorIdentity` (same alias = same instance) with virtual root in `tests/test_virtual_entities.py`
- [X] T021 [P] [US2] Add virtual→virtual relationship test in `tests/test_virtual_entities.py` (Edge Case A) — both endpoints are BaseModel
- [X] T022 [P] [US2] Add same-BaseModel-referenced-by-multiple-relationships test in `tests/test_virtual_entities.py` (Edge Case H) — verify single virtual node, multiple edges
- [X] T023 [P] [US2] Add subset-field-name + relationship-name collision test in `tests/test_virtual_entities.py` (Edge Case J) — relationship loader takes precedence
- [X] T024 [P] [US2] Add unregistered-BaseModel-source test in `tests/test_definesubset_basemodel.py` (Edge Case I) — schema subsetting works but auto-load does not fire

**Checkpoint**: DefineSubset from BaseModel fully functional. Virtual roots participate in cross-layer flows identically to SQLModel roots. FR-005 satisfied.

---

## Phase 5: User Story 3 — ER / Voyager Virtual Node Rendering (Priority: P3)

**Goal**: A project with mixed SQLModel entities and non-SQLModel roots generates an ER diagram and opens Voyager without exceptions; virtual roots appear as visually-distinguished nodes (`shape=note`, `«virtual»` stereotype, `cluster_virtual` group).

**Independent Test**: Quickstart S6 passes. `ErDiagram` data class carries `virtual_entities: list[type[BaseModel]]`; DOT output contains the virtual node with the right shape/label/cluster; edges between virtual and SQLModel entities are drawn.

### Implementation for User Story 3

- [X] T025 [US3] Add virtual-node branch to `ErDiagram.from_sqlmodel()` (or equivalent entry point) in `src/nexusx/er_diagram.py` — pre-partition input by `isinstance(entity, SQLModel)`; guard `sa_inspect()` to only run on SQLModel entities; virtual entities skip column/FK extraction (research.md R4)
- [X] T026 [P] [US3] Add DOT emission branch for virtual nodes in `src/nexusx/voyager/er_diagram_dot.py` — `shape=note`, `style=filled, fillcolor="#FFF9C4"`, label `«virtual»\n{ClassName}`, grouped in `cluster_virtual` with dashed border (research.md R6)
- [X] T027 [US3] Verify / adjust `voyager/type_helper.py` to handle plain BaseModel sources without crashing — likely no change needed since it already handles `ICollector` and reads `model_fields`, but verify (research.md R4)

### Tests for User Story 3

- [X] T028 [P] [US3] Write ER diagram rendering tests in `tests/test_virtual_entities_er.py` (quickstart S6): mixed SQLModel + virtual generates without exception, virtual node has correct shape/label/cluster, edges drawn between virtual and SQLModel entities
- [X] T029 [P] [US3] Add zero-virtual-entities regression test in `tests/test_virtual_entities_er.py` — output is bit-identical to today's SQLModel-only ER generation
- [X] T030 [P] [US3] Add Voyager integration smoke test in `tests/test_virtual_entities_er.py` — Voyager opens without exception on a mixed graph

**Checkpoint**: All three user stories independently functional. ER/Voyager no longer crashes on virtual roots; visual distinction clear.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Regression protection, performance verification, documentation.

- [X] T031 [P] Add Layer 3 regression tests in `tests/test_virtual_entities.py`: virtual root has no `__table__`, `sa_inspect()` rejects virtual root class, Resolver accepts unregistered plain BaseModel without `__relationships__` (no-op), Resolver behavior on unregistered plain BaseModel with `__relationships__` matches spec Edge Case B
- [X] T032 [P] Run full existing test suite (`pytest tests/`) and verify all 1025 prior tests still pass unchanged (FR-008, SC-003)
- [X] T033 [P] Run resolver benchmarks and verify zero overhead for SQLModel-only paths (i.e., when `add_virtual_entities` is never called, behavior is bit-identical to today) — performance goal from plan.md
- [X] T034 [P] Update `quickstart.md` to reflect actual test names and final scenario numbering (S8 was merged into S11 during planning)
- [X] T035 [P] Update `docs/` (or `CLAUDE.md` if applicable) with the new `add_virtual_entities()` API and the widened `DefineSubset.__subset__` source — point at the migration from `_subset_registry` hack (SC-006)
- [X] T036 Code cleanup: remove any temporary debug logging, run `ruff check --fix` across all touched files, verify `mypy` (if configured) passes

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 — implements `add_virtual_entities` + Resolver fallback
- **US2 (Phase 4)**: Depends on Phase 2 — DefineSubset widening is independent of US1 implementation, but Layer 2 parity tests benefit from US1's runtime path being available
- **US3 (Phase 5)**: Depends on US1 (needs virtual entities registered before they can be rendered)
- **Polish (Phase 6)**: Depends on all desired user stories being complete

### User Story Dependencies

- **US1 (P1)**: Can start after Phase 2 — no dependencies on other stories
- **US2 (P2)**: Can start after Phase 2 in parallel with US1 — DefineSubset widening touches different files; but the cross-boundary parity tests (T017–T024) require US1's `add_virtual_entities` + Resolver fallback to be functional. Recommend: T012–T014 in parallel with US1; T015–T024 after US1 checkpoint.
- **US3 (P3)**: MUST follow US1 — ER rendering needs virtual entities to exist in `_registry`

### Within Each User Story

- Layer 1 tests written first, must FAIL before implementation
- Implementation proceeds in dependency order (registry → resolver → rendering)
- Layer 2 parity tests + checkpoint validation before moving to next priority

### Parallel Opportunities

- Phase 2 tasks T003 + T004 are `[P]` (different files: `relationship.py` vs `loader/registry.py`)
- Phase 3 Layer 2 tests T009, T010, T011 are `[P]` (same file but logically independent test functions; safe to author together)
- Phase 4 implementation T012, T013, T014 are `[P]` within the story
- Phase 4 Layer 2 mirror tests T015–T024 are all `[P]` (different test functions, no shared state)
- Phase 5 rendering tasks T025 (`er_diagram.py`) and T026 (`voyager/er_diagram_dot.py`) are `[P]` (different files)
- Phase 6 polish tasks T031–T035 are all `[P]`

---

## Parallel Example: User Story 2 Layer 2 Mirror Tests

```bash
# After US1 checkpoint, launch all Layer 2 mirror tests in parallel:
Task: "Mirror TestExposeAs with virtual root in tests/test_virtual_entities.py"           # T017
Task: "Mirror TestSendToCollector with virtual root in tests/test_virtual_entities.py"   # T018
Task: "Mirror TestCollectorFlatNest with virtual root in tests/test_virtual_entities.py" # T019
Task: "Mirror TestCollectorIdentity with virtual root in tests/test_virtual_entities.py" # T020
```

Each is a self-contained test function or class — no shared fixtures beyond the standard `session_factory` fixture.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001, T002)
2. Complete Phase 2: Foundational (T003, T004) — CRITICAL, blocks everything
3. Complete Phase 3: User Story 1 (T005–T011)
4. **STOP and VALIDATE**: Run `pytest tests/test_virtual_entities.py -v`; all Layer 1 + Layer 2 tests pass; quickstart S1–S5 verified
5. Merge PR 1 — `add_virtual_entities` is now usable, Issue #87's minimum acceptance criteria met for the virtual-root-only path

### Incremental Delivery

1. Setup + Foundational → Foundation ready (PR base)
2. US1 → Test independently → **PR 1: runtime path MVP**
3. US2 → Test independently → **PR 2: DefineSubset widening + parity tests**
4. US3 → Test independently → **PR 3: ER/Voyager rendering**
5. Polish → **PR 4 (or squash into 3): regression + performance + docs**

### Parallel Team Strategy

With one developer (recommended for this feature — moderate scope): sequential in priority order. With two developers:

- Developer A: US1 → US3 (US3 depends on US1, natural handoff)
- Developer B: US2 (independent of US1 after Phase 2; DefineSubset widening + parity tests)
- Both: Phase 6 polish split by file

---

## Notes

- `[P]` tasks = different files OR different independent test functions, no dependencies
- `[Story]` label maps task to specific user story for traceability
- Layer 1 tests MUST fail before implementation (TDD); Layer 2 / Layer 3 tests can be written alongside or after
- Commit after each task or logical group (suggested: one commit per task, squash within PR)
- Stop at any checkpoint to validate story independently
- Avoid: vague tasks, same-file conflicts within a `[P]` group, cross-story dependencies that break independence

## Coverage Matrix Traceability

Every spec FR is covered by at least one task. Every Edge Case has an explicit test task. Cross-reference:

| Spec FR / Edge | Covered by tasks |
|----------------|------------------|
| FR-001 (BaseModel as Resolver root) | T005, T009 |
| FR-002 (resolve_* on virtual root) | T009 |
| FR-003 (post_* on virtual root, incl. post_default_handler) | T009, T010 |
| FR-004 (custom relationships on virtual root) | T006, T008, T021 |
| FR-005 (cross-layer flows) | T017, T018, T019, T020 |
| FR-006 (official API) | T006 |
| FR-007 (reject ambiguous registrations) | T005, T006 |
| FR-008 (backward compatibility) | T032, T033 |
| FR-009 (ER/Voyager virtual nodes) | T025, T026, T028 |
| FR-010 (no fake SQLModel requirements) | T031 |
| FR-011 (plain BaseModel root, no special class) | T005, T006 |
| FR-012 (__relationships__ on BaseModel) | T006 |
| FR-013 (add_virtual_entities contract) | T005, T006, T007 |
| FR-014 (DefineSubset source widening) | T012, T013, T014, T015, T016 |
| FR-015 (boundary transparent) | T017, T018, T021, T022 |
| FR-016 (no silent SQLModel impersonation) | T031 |
| FR-017 (unified source-resolution) | T008, T016 |
| Edge A (virtual→virtual relationship) | T021 |
| Edge B (unregistered plain BaseModel) | T031 |
| Edge G (cross-boundary SendTo/Collector) | T018, T019, T020 |
| Edge H (same BaseModel across relationships) | T022 |
| Edge I (unregistered BaseModel source) | T024 |
| Edge J (subset field + relationship collision) | T023 |

---

## Phase 7: Convergence

**Purpose**: Close gaps surfaced by `/speckit-converge` after the initial `/speckit-implement` pass. These items trace to spec/plan/contract intent that the first pass marked complete but did not fully deliver.

**Appended**: 2026-06-25 (post-review of branch `004-non-sqlmodel-roots` at commit `b0f6b52`).

- [X] T037 Implement virtual-node visual distinction in DOT/Voyager rendering per FR-009 / Contract 3 (missing). `src/nexusx/voyager/er_diagram_dot.py` and/or `src/nexusx/voyager/render.py` currently render plain BaseModel virtual entities with the same shape, fill, and label as SQLModel entities. Add a virtual-entity branch that emits `shape=note`, `style=filled, fillcolor="#FFF9C4"`, label `«virtual»\n{ClassName}`, grouped in a dashed `cluster_virtual` subgraph. Signal virtual-ness via either (a) `not issubclass(entity, SQLModel)` at render time, or (b) plumbing an `is_virtual` flag from `ErDiagram.EntityInfo` (preferred once T040 lands). Verify against Quickstart S6's assertions (`'shape=note' in dot`, `'«virtual»' in dot`).
- [X] T038 Strengthen ER/Voyager visual-distinction tests to assert the spec'd visual properties per FR-009 / T028 (partial). `tests/test_virtual_entities_er.py::TestVoyagerDotBuilderMixed` currently asserts only that the virtual node's name and fields appear in DOT output. Add assertions that `shape=note`, `«virtual»`, and `cluster_virtual` (or `fillcolor="#FFF9C4"`) appear for virtual entities and do NOT appear for SQLModel entities. Mirror the assertions in Quickstart S6.
- [X] T039 Document the `add_virtual_entities()` API and widened `DefineSubset.__subset__` source per SC-005 / SC-006 / T035 (missing). `grep "add_virtual_entities" docs/ README.md CLAUDE.md` returns zero matches; the new public API is undocumented outside `specs/`. Add a "Virtual Entities" guide under `docs/guide/` (or `docs/reference/`) covering: (a) the API contract, (b) the migration from `_subset_registry[X] = Y` hacks (use Quickstart S11 as the worked example), (c) the widened `DefineSubset.__subset__` source. Update `CLAUDE.md` if the project keeps a public-API index there. SC-005 ("developer reading only official docs…") and SC-006 ("mechanical migration path… documented") are otherwise unmet.
- [X] T040 Reconcile `ErDiagram` data model with Contract 3 — either add the `virtual_entities: list[type[BaseModel]]` field OR update Contract 3 / data-model.md to match the chosen design per Contract 3 / data-model.md / T025 (partial). Current implementation mixes virtual entities into `entities` with `table_name=""` and no `virtual_entities` field. Contract 3 and `data-model.md` both specify the separate field. Pick one direction: (a) add the field + populate it in `ErDiagram._build`, then have DOT/Voyager read from it; OR (b) update `contracts/api.md` Contract 3 and `data-model.md` to document "virtual entities live in `entities` with `table_name == ''` as the signal" as the agreed design. Either way, code and contract must agree before PR.
- [X] T041 Strengthen the zero-virtual-entities regression test OR relax T029's wording per T029 (partial). T029 says "output is bit-identical to today's SQLModel-only ER generation"; the current test only checks entity names. Either (a) add a snapshot/equality assertion comparing `ErDiagram.from_er_manager(er_with_no_virtuals)` against `ErDiagram.from_sqlmodel(...)` for the same entity set, OR (b) reword T029 to "functionally equivalent (same entity names + relationship edges)" and add a one-line note in tasks.md explaining the relaxation.
- [X] T042 Update `_orm_to_dto` docstring to clarify the function is invoked only for SQLModel sources per T014 (partial). `src/nexusx/resolver.py` `_orm_to_dto` body is type-agnostic but its docstring/name still imply ORM-only. Add a one-line docstring note: "Invoked only when the source is a SQLModel (ORM row → DTO). BaseModel sources are constructed directly by the user and never pass through this function." Rename to `_source_to_dto` is OUT OF SCOPE — research.md R8 explicitly defers it. Mark T014's checkbox honestly once done.

---

## Phase 8: Convergence

**Purpose**: Close residual doc-accuracy gaps surfaced by the second `/speckit-converge` pass after T037–T042 landed. Code behaviour is fully converged; remaining items are documentation alignment so users copying public snippets get runnable code.

**Appended**: 2026-06-25 (post-implementation review of T037–T042).

- [X] T043 Update Quickstart S6 to match the actual `add_virtual_entities` / ER-rendering API per tasks.md T034 / Quickstart S6 (partial). `specs/004-non-sqlmodel-roots/quickstart.md:179-184` still references `ErDiagram.from_manager(er)`, `diagram.to_dot()`, and `assert 'shape=note' in dot` — none of which exist in the implementation. Replace with the real API: either `ErDiagram.from_er_manager(er)` (data path) or `ErDiagramDotBuilder(er, show_fields='all').render_dot()` (DOT path). Update the visual-distinction assertions to check for the actual tokens delivered by T037: `cluster_virtual`, `«virtual»\nCurrentUserRoot`, and `#FFF9C4` (or `FFF9C4`). Users copy-pasting S6 today get immediate failures; this task makes the snippet runnable as documented.
- [X] T044 Add a `Virtual Entities` row to the docs index so the new guide is discoverable per SC-005 / tasks.md T035 (partial). `docs/index.md:49-57` and `docs/index.zh.md:49-57` list every existing guide but omit `virtual_entities{,.zh}.md` (added in T039). Insert one row in each index linking to `./guide/virtual_entities.md` and `./guide/virtual_entities.zh.md` respectively. Without this, the guide exists but is reachable only by direct URL — undermining SC-005's "developer reading only the official docs can implement… in under 15 minutes".

