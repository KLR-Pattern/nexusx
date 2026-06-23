---
description: Execute tasks.md — wrap nexusx V-model loop (acceptance → implement → verify) per Phase.
---

<!--
  ============================================================================
  nexusx-4phase preset — wrap of speckit.implement
  ============================================================================
  The core /speckit-implement runs every task in dependency order. The nexusx
  overlay enforces the V-model at each phase boundary:

    V降 — re-confirm acceptance criteria for the current Phase with the user
    实现 — run tasks belonging to the current Phase
    V升 — verify each criterion tick-by-tick with the user
    Gate — pause for explicit user sign-off before next Phase

  Phases in scope: 1 / 2 / 3 / 4 (Phase 0 is handled by /speckit-specify).
  ============================================================================
-->

## nexusx V-Model Implementation Overlay

You are running `/speckit-implement` with the **nexusx-4phase preset** active.
Execution proceeds **phase by phase**, not task-by-task across the whole
`tasks.md`.

### Per-phase execution loop

For each Phase (1 → 2 → 3 → 4):

1. **V降** — open `specs/<feature>/phaseN.md`. If the V降 acceptance criteria
   table is empty or has unchecked `[NEEDS CLARIFICATION]` rows, run the
   criteria definition conversation with the user FIRST. Do not start coding.
2. **Filter tasks** — pick only tasks labeled `[PN]` from `tasks.md`.
3. **Implement** — execute tasks in dependency order. Use the phase-specific
   reference docs:
   - Phase 1: `plan.md` Phase 1 addendum (SQLModel, alembic, Voyager).
   - Phase 2: tasks.md Phase 2 block + nexusx `mount_method()` pattern.
   - Phase 3: tasks.md Phase 3 block + UseCaseService / create_use_case_router
     / create_use_case_graphql_mcp_server patterns.
   - Phase 4: tasks.md Phase 4 block + `@hey-api/openapi-ts` config.
4. **V升** — for each row in `phaseN.md`'s V降 table, run the verification
   method with the user. Tick the corresponding V升 box only after explicit
   user confirmation.
5. **Gate** — announce "Phase N complete, awaiting sign-off" and STOP. Do not
   start Phase N+1 tasks until the user explicitly says so (e.g. "go ahead
   with Phase 3" or `/speckit-nexusx-phase 3`).

### Phase-specific verification cheatsheet

| Phase | Typical verification |
|-------|---------------------|
| 1 | Open Voyager; check ER shape; verify mock seed row counts; (persistent) `alembic upgrade head` |
| 2 | GraphiQL: run every mounted `@query` / `@mutation`; confirm seed data still queryable; `pytest tests/` |
| 3 | `curl /api/<service>/<method>` returns DTO shape (no FK fields); Voyager shows service tree; MCP 4-layer tools: `list_apps` → `describe_compose_schema` → `describe_compose_method` → `compose_query`; missing-param returns 422 |
| 4 | `fe/src/sdk/types.gen.ts` covers every DTO; field names are snake_case; nested relations produce correct TS types |

### Phase 3 specifically — Service layer rules

When implementing Phase 3 tasks:

- `methods.py` returns ORM `Model` instances (pure business logic).
- `service.py` calls `methods.py`, then converts: `[DtoType.model_validate(m) for m in models]` → `Resolver().resolve(dtos)`.
- `service.py` MUST NOT touch the DB directly. If you need a custom SELECT,
  use `build_dto_select(Entity, DtoType)` → `dict(row._mapping)` → DTO.
- Every `UseCaseService` method that is exposed via `@query` / `@mutation`
  MUST declare a return type annotation. Missing annotation →
  `MissingReturnAnnotationError` at server build time.
- MCP http_app: `transport="streamable-http"`, `stateless_http=True`, and
  nest `mcp_http.lifespan(mcp_http)` inside the FastAPI lifespan.

### Iteration handling

If the user is iterating on an existing project (not a fresh 4-phase build):

- Confirm only the delta with Phase 0 (spec.md changes).
- Implementation MAY merge Phase 1-3 into a single coding pass, but the
  `phaseN.md` spec files MUST still be back-filled with V降 + V升 before
  reporting completion.
- Before "done", verify `specs/<feature>/phase*.md` are all non-empty
  (`wc -l specs/<feature>/phase*.md`).

---

## Core implement workflow

Below this point, the core `/speckit-implement` content runs unchanged.

{CORE_TEMPLATE}
