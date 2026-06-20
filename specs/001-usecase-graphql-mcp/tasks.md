---

description: "Task list for UseCase Service → GraphQL → MCP (feature 001)"
---

# Tasks: UseCase Service → GraphQL → MCP

**Input**: Design documents from `/specs/001-usecase-graphql-mcp/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/

**Tests**: Tests are explicitly required per spec FR-012. Each user story phase includes test tasks written before implementation (TDD-style).

**Organization**: Tasks grouped by user story. US1 (P1) is MVP. US2 (P2) builds on US1. US3 (P3) is independent (can run in parallel with US1/US2 once foundational phase completes). US4 (P3) is a cross-cutting concern folded into implementation tasks and audited in Polish.

## Format: `[ID] [P?] [Story?] Description (file path)`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1/US2/US3)
- File paths are absolute repo-relative

## Path Conventions

Single-project library layout:
- `src/nexusx/` — main package
- `tests/` — test suite
- `demo/` — demos
- `docs/` — new directory for migration docs

---

## Phase 1: Setup

**Purpose**: Branch, version bump, doc skeleton.

- [X] T001 Create feature branch `001-usecase-graphql-mcp` off `master` (current HEAD has `.specify/` committed)
- [X] T002 [P] Bump `pyproject.toml` version `2.10.1` → `3.0.0` (corrected from plan's 1.0.0→2.0.0; actual pre-feature version was 2.10.1)
- [X] T003 [P] Create `CHANGELOG.md` with `## 3.0.0` section (BREAKING + Added, per contracts/public-api.md C5)
- [X] T004 [P] Create `docs/migrations/3.0-use-case-graphql.md` skeleton (will be filled in US3)

**Checkpoint**: Branch ready, version bumped, doc placeholders exist.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core data structures and exceptions used by ALL user stories.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T005 [P] Implement `TypeInfo` / `FieldInfo` / `TypeRef` / `ArgumentInfo` dataclasses in `src/nexusx/use_case/compose_schema.py` (per data-model.md D1–D4)
- [X] T006 [P] Implement `ComposeSchemaError` exception hierarchy (`DuplicateServiceError`, `DuplicateMethodError`, `DuplicateTypeError`, `UnsupportedTypeError`, `SQLModelInDtoFieldError`, `MissingReturnAnnotationError`) in `src/nexusx/use_case/compose_schema.py`
- [X] T007 Implement `ComposeTypeMapper` class in `src/nexusx/use_case/compose_type_mapper.py` with mapping rules per contracts/schema-builder.md B3 (scalars, containers, Pydantic, enum; reject bytes/Decimal/SQLModel/Any). Document fork rationale vs `type_converter.py` in module docstring (per FR-011, research.md R2)
- [X] T008 Implement `is_from_context_annotation(annotation)` helper in `src/nexusx/use_case/compose_type_mapper.py` (migrated from old `server.py:462-466`, no behavior change)

**Checkpoint**: Foundation ready — schema builder can consume these primitives.

---

## Phase 3: User Story 1 — Schema Generation (Priority: P1) 🎯 MVP

**Goal**: From a list of `UseCaseService` subclasses, derive a real GraphQL schema (registry-based, SDL + introspection renderable, graphql-core-validatable).

**Independent Test**: Define 3 services (list return, single instance return, parameterized, nested DTO) → call `build_compose_schema(app)` → assert SDL round-trips through `graphql.build_schema(schema.render_introspection())` and 3 representative queries execute correctly.

### Tests for User Story 1 (write FIRST, ensure they FAIL)

- [X] T009 [P] [US1] Test scalar/container type mapping in `tests/use_case/test_compose_schema.py` (assert `int→Int!`, `list[T]→[T!]!`, `Optional[T]→T`, etc., per contracts/schema-builder.md B3)
- [X] T010 [P] [US1] Test `FromContext` parameters are filtered out of method args in `tests/use_case/test_compose_schema.py`
- [X] T011 [P] [US1] Test same DTO referenced from multiple services is registered once in `tests/use_case/test_compose_schema.py`
- [X] T012 [P] [US1] Test `@query` and `@mutation` coexistence generates both root types in `tests/use_case/test_compose_schema.py`
- [X] T013 [P] [US1] Test name conflict detection (duplicate service / method / type) raises correct `ComposeSchemaError` subclass in `tests/use_case/test_compose_schema.py`
- [X] T014 [P] [US1] Test missing return annotation raises `MissingReturnAnnotationError` in `tests/use_case/test_compose_schema.py`
- [X] T015 [P] [US1] Test DTO field referencing SQLModel raises `SQLModelInDtoFieldError` in `tests/use_case/test_compose_schema.py`
- [X] T016 [P] [US1] Test introspection JSON round-trips through `graphql.build_schema(...)` (GraphiQL compat) in `tests/use_case/test_compose_schema.py`

### Implementation for User Story 1

- [X] T017 [US1] Implement `build_compose_schema(app: UseCaseAppConfig) -> ComposeSchema` skeleton in `src/nexusx/use_case/compose_schema.py` (orchestrates T018–T022)
- [X] T018 [US1] Implement service iteration + `{Service}Query` / `{Service}Mutation` type construction in `build_compose_schema` (per data-model.md D5, contracts/schema-builder.md B6)
- [X] T019 [US1] Implement method → field conversion (extract args via `inspect.signature`, skip `cls` and `is_from_context_annotation`, build `ArgumentInfo` with defaults) in `build_compose_schema`
- [X] T020 [US1] Implement recursive DTO/enum registration with dedup (use `id(python_class)` to detect same class; raise `DuplicateTypeError` on different-class-same-name) in `build_compose_schema`
- [X] T021 [US1] Implement root `Query` (and optional `Mutation`) type assembly in `build_compose_schema`
- [X] T022 [US1] Implement name conflict detection (service-level, method-level, type-level) at schema-build time in `build_compose_schema`
- [X] T023 [P] [US1] Implement `ComposeSchema.render_sdl()` in `src/nexusx/use_case/compose_schema.py` (per contracts/schema-builder.md B7 ordering: scalars → enums → DTOs → service types → root Query/Mutation)
- [X] T024 [P] [US1] Implement `ComposeSchema.render_introspection()` in `src/nexusx/use_case/compose_schema.py` (returns `__schema` payload; must pass T016 round-trip test)
- [X] T025 [P] [US1] Implement `ComposeSchema.render_method_sdl(service_name, method_name)` in `src/nexusx/use_case/compose_schema.py` (returns method signature + transitive closure of return type)
- [X] T026 [US1] Run US1 tests, ensure all pass: `uv run pytest tests/use_case/test_compose_schema.py -v`

**Checkpoint**: US1 fully functional. `build_compose_schema(...)` produces valid schema. Can be demoed standalone (no MCP yet).

---

## Phase 4: User Story 2 — MCP Server on top of GraphQL Schema (Priority: P2)

**Goal**: Spin up a `FastMCP` server exposing 4 progressive-disclosure tools backed by the US1 schema.

**Independent Test**: Start MCP server with 2 apps × 3 services → call Layer 0→1→2→3 in sequence → assert response shapes match contracts/mcp-tools.md; Layer 3 rejects introspection.

### Tests for User Story 2 (write FIRST, ensure they FAIL)

- [X] T027 [P] [US2] Test `compose_query` happy path (single service, single method) in `tests/use_case/test_compose_executor.py`
- [X] T028 [P] [US2] Test multi-service concurrent execution (asserts `@query` methods run via `asyncio.gather`) in `tests/use_case/test_compose_executor.py`
- [X] T029 [P] [US2] Test field projection returns only requested fields (via `subset.build_subset_model`) in `tests/use_case/test_compose_executor.py`
- [X] T030 [P] [US2] Test `FromContext` injection at execution time (context_extractor plumbing) in `tests/use_case/test_compose_executor.py`
- [X] T031 [P] [US2] Test service method raising business exception → `{data: null, errors: [...]}` with method name in message in `tests/use_case/test_compose_executor.py`
- [X] T032 [P] [US2] Test malformed GraphQL string → `{data: null, errors: [...]}` with parse error in `tests/use_case/test_compose_executor.py`
- [X] T033 [P] [US2] Test Layer 0 `list_apps` returns `{success, data}` envelope with apps list in `tests/use_case/test_compose_mcp_server.py`
- [X] T034 [P] [US2] Test Layer 1 `describe_compose_schema` returns compact services+methods (no args/return types) in `tests/use_case/test_compose_mcp_server.py`
- [X] T035 [P] [US2] Test Layer 2 `describe_compose_method` returns args + return type + SDL fragment in `tests/use_case/test_compose_mcp_server.py`
- [X] T036 [P] [US2] Test Layer 3 `compose_query` returns GraphQL standard `{data, errors}` envelope in `tests/use_case/test_compose_mcp_server.py`
- [X] T037 [P] [US2] Test `__schema` / `__type` / `__typename` queries are rejected with hint in `tests/use_case/test_introspection_rejected.py`

### Implementation for User Story 2

- [X] T038 [US2] Implement `is_introspection_query(query: str) -> bool` in `src/nexusx/use_case/compose_executor.py` (AST-level `__` prefix detection, per research.md R6)
- [X] T039 [US2] Implement `execute_compose_query(app, query, context) -> {data, errors}` in `src/nexusx/use_case/compose_executor.py` (parse → introspection check → plan → execute service methods → project via `subset.build_subset_model` + `TypeAdapter`; per contracts/schema-builder.md B9)
- [X] T040 [US2] Add concurrent execution: `@query` methods via `asyncio.gather`, `@mutation` methods serial in `execute_compose_query`
- [X] T041 [US2] Add exception mapping (`KeyError` for missing service/method, business exception, parse error → all become `errors` array entries with method name) in `execute_compose_query`
- [X] T042 [US2] Document `FR-004a` enforcement in `execute_compose_query` docstring: do NOT wrap results in `Resolver()`; service methods own that. Add code comment citing spec.md FR-004a.
- [X] T043 [US2] Trim `UseCaseResources` in `src/nexusx/use_case/manager.py`: remove `introspector` field, add `compose_schema: ComposeSchema` field (per data-model.md D7)
- [X] T044 [US2] Update `UseCaseManager` to construct `ComposeSchema` per app at registration time (eager, per research.md R11) in `src/nexusx/use_case/manager.py`
- [X] T045 [US2] Implement `create_use_case_graphql_mcp_server(apps, name) -> FastMCP` skeleton in `src/nexusx/use_case/compose_mcp_server.py` (creates `UseCaseManager`, registers 4 tools)
- [X] T046 [P] [US2] Implement `list_apps` tool (Layer 0) in `src/nexusx/use_case/compose_mcp_server.py` returning `{success, data}` per contracts/mcp-tools.md T0
- [X] T047 [P] [US2] Implement `describe_compose_schema(app_name)` tool (Layer 1) in `src/nexusx/use_case/compose_mcp_server.py` returning compact services+methods
- [X] T048 [P] [US2] Implement `describe_compose_method(app_name, service_name, method_name)` tool (Layer 2) in `src/nexusx/use_case/compose_mcp_server.py` returning args + return type + `render_method_sdl`
- [X] T049 [US2] Implement `compose_query(app_name, query, ctx)` tool (Layer 3) in `src/nexusx/use_case/compose_mcp_server.py`: pulls context via `context_extractor`, calls `execute_compose_query`, returns `{data, errors}`
- [X] T050 [US2] Extend `MCPErrors` enum in `src/nexusx/mcp/types/errors.py` with `APP_NOT_FOUND`, `SERVICE_NOT_FOUND`, `METHOD_NOT_FOUND`, `VALIDATION_ERROR` (per contracts/mcp-tools.md)
- [X] T051 [US2] Update `src/nexusx/use_case/__init__.py`: export `create_use_case_graphql_mcp_server`, `build_compose_schema`, `ComposeSchema`, `ComposeSchemaError` (per contracts/public-api.md C4)
- [X] T052 [US2] Update `src/nexusx/__init__.py`: re-export the 4 new symbols (per contracts/public-api.md C4)
- [X] T053 [US2] Run US2 tests, ensure all pass: `uv run pytest tests/use_case/test_compose_executor.py tests/use_case/test_compose_mcp_server.py tests/use_case/test_introspection_rejected.py -v`

**Checkpoint**: US1 + US2 both functional. Can demo full MCP flow.

---

## Phase 5: User Story 3 — Remove Old MCP + Migration Guide (Priority: P3)

**Goal**: Hard-remove the two old direct-call MCP entries; provide migration guide; ensure orthogonal surfaces (router/voyager/jsonrpc) untouched.

**Independent Test**: Importing `create_use_case_mcp_server` / `create_use_case_flat_server` from any path raises `ImportError` with hint pointing to new entry; `demo/use_case/fastapi.py` and `demo/use_case/voyager_demo.py` continue to run without changes.

**NOTE**: US3 can run in parallel with US1/US2 once Phase 2 completes. The deletion of old code only requires that the new entry points exist (T051/T052) before the exports are stripped — so US3's deletion tasks (T058/T059) depend on US2's export tasks.

### Tests for User Story 3 (write FIRST, ensure they FAIL)

- [X] T054 [P] [US3] Test 6 old import paths raise `ImportError` (`from nexusx import ...`, `from nexusx.use_case import ...`, `from nexusx.use_case.server import ...`, `from nexusx.use_case.flat_server import ...`) in `tests/use_case/test_old_api_removed.py`
- [X] T055 [P] [US3] Test error message mentions `create_use_case_graphql_mcp_server` as replacement in `tests/use_case/test_old_api_removed.py`

### Implementation for User Story 3

- [X] T056 [US3] Fill `docs/migrations/2.0-use-case-graphql.md` (skeleton from T004): for each old entry, document "what it did → how new entry does it → concrete before/after code example". Cover `create_use_case_mcp_server` and `create_use_case_flat_server` separately.
- [X] T057 [US3] Fill `CHANGELOG.md` `## 2.0.0` section (skeleton from T003) with BREAKING + Added entries per contracts/public-api.md C5
- [X] T058 [US3] **Depends on T051, T052**: Remove `create_use_case_mcp_server` and `create_use_case_flat_server` from `src/nexusx/__init__.py` and `src/nexusx/use_case/__init__.py`
- [X] T059 [US3] **Depends on T058**: Delete `src/nexusx/use_case/server.py` (old 4-layer MCP)
- [X] T060 [US3] **Depends on T058**: Delete `src/nexusx/use_case/flat_server.py` (old flat MCP)
- [~] T061 [US3] **SKIPPED**: introspector.py is still used by jsonrpc.py + voyager/use_case_voyager.py (FR-010a says these stay). Only server.py + flat_server.py deleted.
- [X] T062 [US3] Grep for residual references: `grep -rn "create_use_case_mcp_server\|create_use_case_flat_server\|ServiceIntrospector" src/` — confirm zero hits
- [X] T063 [US3] Update `demo/use_case/mcp_server.py` to use `create_use_case_graphql_mcp_server` (keep filename for continuity; behavior switches to new MCP)
- [X] T064 [P] [US3] Create `demo/use_case/mcp_server_graphql.py` as an explicit new-entry-point demo (per plan.md project structure)
- [X] T065 [US3] Smoke test orthogonal surfaces: run `demo/use_case/fastapi.py` (uses `create_use_case_router`) and confirm unchanged behavior; run `demo/use_case/voyager_demo.py` (uses `create_use_case_voyager`) and confirm unchanged behavior. No code changes expected.
- [X] T066 [US3] Run US3 tests: `uv run pytest tests/use_case/test_old_api_removed.py -v`

**Checkpoint**: All 3 user stories independently functional. Old code gone, migration guide published, orthogonal surfaces intact.

---

## Phase 6: Polish & Cross-Cutting Concerns (incl. US4 audit)

**Purpose**: Cross-story validation, documentation, US4 (reuse decision audit).

- [ ] T067 [P] Audit code comments for FR-011 compliance: each new module (`compose_schema.py`, `compose_type_mapper.py`, `compose_executor.py`, `compose_mcp_server.py`) must have docstring referencing reuse decisions from `research.md` (R1–R5). Add missing comments.
- [ ] T068 [P] Add "Removed" section to top-level `README.md` mentioning the 2 removed entries + link to migration guide
- [ ] T069 [P] Add "Added" section to `README.md` mentioning `create_use_case_graphql_mcp_server` with a 5-line usage example
- [ ] T070 Run `uv run ruff check src/ tests/` — fix any violations
- [ ] T071 Run `uv run ruff check --fix src/ tests/` if auto-fixable issues remain
- [ ] T072 Run `uv run mypy src/` — fix any type errors (strict mode)
- [ ] T073 Run full test suite: `uv run pytest` — ensure no regression in existing tests
- [ ] T074 Run `./scripts/check-ci.sh` — must be green
- [ ] T075 Execute `quickstart.md` Q1–Q8 manually — verify each step works as documented
- [ ] T076 Final review: confirm all spec FR-001..FR-012a are satisfied. Map each FR to its implementing task(s) in a final review note.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies. T001 must complete before any other task (need branch).
- **Foundational (Phase 2)**: Depends on Phase 1. **BLOCKS** all user stories.
- **US1 (Phase 3)**: Depends on Phase 2. No dependencies on other stories. **MVP target.**
- **US2 (Phase 4)**: Depends on Phase 2 + US1 (consumes `ComposeSchema`).
- **US3 (Phase 5)**: Depends on Phase 2. T058–T061 additionally depend on T051/T052 (don't strip old exports until new ones are in place). T056/T057 (migration guide + changelog) can run in parallel with US1/US2.
- **Polish (Phase 6)**: Depends on all user stories being complete.

### Critical Path

```
T001 → T005/T006/T007/T008 (Phase 2)
     → T017–T026 (US1)
     → T038–T053 (US2)
     → T058–T066 (US3, deletion part)
     → T067–T076 (Polish)
```

### Parallel Opportunities

- **Phase 1**: T002/T003/T004 are `[P]` (different files)
- **Phase 2**: T005/T006 are `[P]` (different concerns in same file but logically independent). T007/T008 sequential after T005.
- **US1 tests (T009–T016)**: All `[P]` — independent test cases in same file but logically separate. May be written in parallel by splitting per test.
- **US1 `ComposeSchema` render methods (T023–T025)**: All `[P]` — different methods, can be implemented concurrently after T022.
- **US2 tests (T027–T037)**: All `[P]`.
- **US2 MCP tools (T046–T049)**: T046/T047/T048 are `[P]`; T049 depends on executor (T038–T042).
- **US3 tests (T054/T055)**: `[P]`.
- **US3 doc writing (T056/T057)**: `[P]` and can run alongside US1/US2 implementation.
- **Polish (T067–T069)**: All `[P]`.

### Cross-Story Parallelism

US3 documentation tasks (T056/T057) can run in parallel with US1 implementation. US3 deletion tasks (T058–T061) must wait for US2 to finish.

---

## Parallel Example: User Story 1

```bash
# Write US1 tests in parallel (8 tests, independent):
Task: T009 — scalar/container type mapping test
Task: T010 — FromContext filtering test
Task: T011 — DTO dedup test
Task: T012 — query+mutation coexistence test
Task: T013 — name conflict detection test
Task: T014 — missing return annotation test
Task: T015 — SQLModel in DTO field test
Task: T016 — introspection round-trip test

# Then implement render methods in parallel (after T022):
Task: T023 — render_sdl()
Task: T024 — render_introspection()
Task: T025 — render_method_sdl()
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (Setup)
2. Complete Phase 2 (Foundational) — **CRITICAL**, blocks all stories
3. Complete Phase 3 (US1)
4. **STOP and VALIDATE**: Run US1 tests, manually verify `build_compose_schema(...)` works for 3 demo services
5. At this point, the feature already delivers standalone value (real GraphQL schema from UseCaseService).

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. Add US1 → schema generation works → validate (MVP)
3. Add US2 → MCP server works end-to-end → validate
4. Add US3 → old code removed, migration published → validate
5. Polish → CI green, docs updated, quickstart verified

### Single-Developer Strategy (Recommended)

Given the cross-file dependencies (US2 needs US1's ComposeSchema; US3 deletion needs US2's new exports), sequential delivery in priority order is the natural path. The `[P]` markers within each phase still allow test-writing or render-method implementation to be parallelized if a second contributor is available.

---

## Notes

- `[P]` tasks = different files OR different functions within the same file with no sequential dependency
- `[Story]` label maps task to user story for traceability
- US4 (reuse decisions) is enforced via:
  - Code-level: T007/T042/T067 require documented decisions in code
  - Plan-level: research.md R1–R5 already records the decisions
- Commit cadence: after each task or logical group (e.g., one commit per test+implementation pair in US1)
- Stop at any checkpoint (T026 / T053 / T066 / T074) to validate independently
- Avoid: editing `src/nexusx/handler.py`, `src/nexusx/mcp/`, or `src/nexusx/execution/` — those are out of scope (FR-010a, Assumptions)
