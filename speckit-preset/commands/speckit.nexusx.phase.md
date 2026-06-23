---
description: Enter a specific nexusx phase (0/1/2/3/4) — load phase instructions and run the V-model cycle.
---

## User Input

```text
$ARGUMENTS
```

The argument is a single phase number (`0` / `1` / `2` / `3` / `4`). Parse it
and dispatch to the corresponding flow below. If empty, print a phase picker:

```text
Which phase?
  0 — Requirements confirmation (entities / relationships / service split / DB)
  1 — Schema + ER diagram + mock seed
  2 — Method implementation + Entity mount
  3 — UseCase composition + MCP + REST/CLI
  4 — OpenAPI → TS SDK
```

## Setup

1. Read `.specify/feature.json` to resolve `feature_directory`.
   - If missing, ERROR: "Run /speckit-specify first."
2. Read `specs/<feature>/spec.md` to confirm Phase 0 is complete.
   - For phases 1-4: if any Phase 0 box is unticked, STOP and tell the user
     to finish Phase 0 first.
3. Ensure `specs/<feature>/phaseN.md` exists; create it from the
   `phase-template` if not.

## Phase 0 — Requirements confirmation

If argument is `0`:

1. Open `specs/<feature>/spec.md` Phase 0 addendum.
2. Walk the 8 steps with the user in order:
   - 0-1 Entities & Fields
   - 0-2 Relationships
   - 0-3 Aggregate Roots
   - 0-4 Service Partitioning (propose candidates, let user pick)
   - 0-5 GraphQL Positioning
   - 0-6 Third-Party Libraries
   - 0-7 DB Persistence & Migration (must be explicit)
   - 0-8 Checklist
3. Tick boxes in step 0-8 as the user confirms each item.
4. When all 8 boxes are ticked, suggest `/speckit-plan`.

## Phase 1 — Schema + ER + mock seed

If argument is `1`:

1. Read `specs/<feature>/plan.md` Phase 1 addendum (V降 acceptance criteria).
2. If V降 table is empty, run the criteria definition conversation first.
3. Implement: `db.py`, `models.py`, `database.py`, `main.py` (+ alembic +
   `load_seed.py` for persistent branch).
4. Run Voyager verification with the user.
5. Tick every V升 box in `phase1.md`.
6. Pause for sign-off. Do NOT start Phase 2 automatically.

## Phase 2 — Methods + Entity mount

If argument is `2`:

1. Open `specs/<feature>/phase2.md` V降 table.
2. For each service in spec.md Step 0-4:
   - Create `src/service/<domain>/methods.py` with the service's async functions.
   - Wire `mount_method()` in `src/models.py` (delayed import, `@functools.wraps`).
3. Restart the server, run every `@query` / `@mutation` in GraphiQL with the user.
4. Tick V升 boxes.
5. Pause.

## Phase 3 — UseCase composition + MCP

If argument is `3`:

1. Open `specs/<feature>/phase3.md` V降 table.
2. For each service:
   - Create `dtos.py` (DefineSubset DTOs, no `from __future__ import annotations`).
   - Create `service.py` (UseCaseService, return annotations required).
   - Create `service/<domain>/spec.md`.
3. Wire `main.py`: `create_use_case_router` (or `create_jsonrpc_router`) +
   `create_use_case_graphql_mcp_server` + `create_use_case_voyager` (+ optional
   `create_use_case_cli`).
4. Verify with the user:
   - curl returns DTO-shaped responses (FK hidden).
   - Voyager shows service tree.
   - MCP 4-layer tools work end-to-end.
   - Missing params → 422.
5. Tick V升 boxes.
6. Pause.

## Phase 4 — OpenAPI → TS SDK

If argument is `4`:

1. Open `specs/<feature>/phase4.md` V降 table.
2. Create `fe/openapi-ts.config.ts` and `fe/package.json`.
3. `cd fe && npm install && npm run generate-client`.
4. Verify with the user:
   - Every DTO has a matching TS type in `fe/src/sdk/types.gen.ts`.
   - Field names are snake_case (preserve backend names).
   - Nested relations produce correct recursive TS types.
5. Tick V升 boxes.

## Completion Report

Report the phase that ran, the count of V升 boxes ticked, and any unresolved
acceptance criteria. Suggest the next phase if appropriate.
