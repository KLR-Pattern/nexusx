---
description: Generate tasks.md — wrap nexusx Phase 2/3/4 task partitioning onto the core /speckit-tasks flow.
---

<!--
  ============================================================================
  nexusx-4phase preset — wrap of speckit.tasks
  ============================================================================
  The core /speckit-tasks groups tasks by user story. The nexusx overlay
  additionally requires tasks to be grouped by Phase (2 / 3 / 4), because the
  V-model verification pauses at each phase boundary.

  Mapping:
    Phase 2 = service/<domain>/methods.py + models.mount_method()
    Phase 3 = service/<domain>/{dtos,service}.py + main.py wiring (REST/MCP/CLI/Voyager)
    Phase 4 = fe/ SDK generation (@hey-api/openapi-ts)
  ============================================================================
-->

## nexusx Task Partitioning Overlay

You are running `/speckit-tasks` with the **nexusx-4phase preset** active.
After the core tasks workflow, additionally ensure `tasks.md` is grouped by
**nexusx Phase**, not just by user story.

### Required Phase grouping

```text
Phase 1 — Schema & mock seed
  (tasks derived from plan.md Phase 1 addendum)

Phase 2 — Method implementation + Entity mount
  - For each service in spec.md Step 0-4:
    - Create src/service/<domain>/methods.py with the service's async functions
    - Wire mount_method() in src/models.py (delayed import + functools.wraps)
  - Verify GraphQL can query each method (GraphiQL)

Phase 3 — UseCase composition + MCP
  - For each service:
    - Create src/service/<domain>/dtos.py (DefineSubset DTOs)
    - Create src/service/<domain>/service.py (UseCaseService subclass)
    - Each UseCaseService method must declare return annotation
      (e.g. -> list[ChatSummary]) — compose schema generator requires it
    - service.py reuses methods.py (no DB access in service.py)
    - service/<domain>/spec.md documenting the service's purpose & evolution
  - main.py: wire create_use_case_router / create_jsonrpc_router (二选一) /
    create_use_case_cli / create_use_case_graphql_mcp_server /
    create_use_case_voyager as decided in Phase 0

Phase 4 — OpenAPI → TS SDK
  - fe/openapi-ts.config.ts (input = http://localhost:8000/openapi.json)
  - fe/package.json with @hey-api/openapi-ts + scripts.generate-client
  - Run npm install + npm run generate-client
  - Verify fe/src/sdk/{sdk.gen.ts, types.gen.ts} cover every DTO
```

### V-model task pattern

For each Phase, also generate the V-model task pair:

```text
- [ ] [Px] Define V降 acceptance criteria in specs/<feature>/phaseN.md
- [ ] [Px] Implement Phase N tasks
- [ ] [Px] Run V升 verification — tick each criterion with the user
- [ ] [Px] Phase N gate — pause for user sign-off before Phase N+1
```

### Task labeling convention

Prefix each task with `[P1]` / `[P2]` / `[P3]` / `[P4]` to identify the phase
it belongs to. Keep the core `[P]` (parallel-safe) marker where relevant:

```text
- [ ] T015 [P2] [P] Create methods.py for chat service in src/service/chat/methods.py
- [ ] T020 [P3] Create dtos.py for chat service in src/service/chat/dtos.py
- [ ] T030 [P4] Generate TS SDK via @hey-api/openapi-ts in fe/
```

### Phase gate enforcement

When the core `/speckit-implement` reaches a phase boundary, it MUST pause and
wait for explicit user sign-off before moving to the next phase. The
`/speckit-implement` wrap enforces this.

---

## Core tasks workflow

Below this point, the core `/speckit-tasks` content runs unchanged.

{CORE_TEMPLATE}
