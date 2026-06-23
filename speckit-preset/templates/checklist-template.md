<!--
  ============================================================================
  nexusx-4phase preset — checklist-template (replaces core)
  ============================================================================
  Two sections:
  1. Phase V-model acceptance (V降 + V升 per phase)
  2. spec/ directory completeness (from spec-management.md)

  Replace [FEATURE NAME] / [DATE] placeholders. Delete phase rows that don't
  apply to the current feature.
  ============================================================================
-->

# nexusx 4-Phase Checklist: [FEATURE NAME]

**Purpose**: Verify V-model completion for every phase + spec/ directory completeness before delivery.
**Created**: [DATE]
**Feature**: [Link to spec.md]

## Phase 0 — Requirements Confirmation

- [ ] CHK001 Step 0-1: All entities + fields listed with types and constraints
- [ ] CHK002 Step 0-2: ER diagram has correct directions and cardinalities
- [ ] CHK003 Step 0-3: Aggregate root(s) explicitly named with rationale
- [ ] CHK004 Step 0-4: Service partitioning is **confirmed by user** (not unilaterally decided)
- [ ] CHK005 Step 0-4b: Use-case methods cover the main business scenarios; logic is self-consistent
- [ ] CHK006 Step 0-5: GraphQL positioned as auxiliary testing interface
- [ ] CHK007 Step 0-6: Third-party libraries selected; maintenance status investigated
- [ ] CHK008 Step 0-7: DB type + migration strategy **explicitly confirmed by user**
- [ ] CHK009 Step 0-8: All 8 boxes above ticked

## Phase 1 — Schema + ER + Mock Seed (V降 + V升)

- [ ] CHK010 V降 acceptance criteria table written in `phase1.md`
- [ ] CHK011 Each Entity appears in Voyager ER with correct relationship directions
- [ ] CHK012 `models.py` has only fields + Relationship (no `@query`/`@mutation`, no `nexusx` import)
- [ ] CHK013 Every `Relationship` has `sa_relationship_kwargs={"lazy": "noload"}`
- [ ] CHK014 Every `Model` has docstring; every `Field` has `description`
- [ ] CHK015 Mock seed data has reasonable volume, relationships, boundary cases
- [ ] CHK016 `pyproject.toml` has `packages = ["src"]` under `[tool.hatch.build.targets.wheel]`
- [ ] CHK017 (persistent) alembic baseline `upgrade head` succeeds; `alembic_version` row exists
- [ ] CHK018 (persistent) `env.py` has `import src.models`; `script.py.mako` has `import sqlmodel`
- [ ] CHK019 (persistent) `var/` is in `.gitignore`
- [ ] CHK020 V升 all rows in `phase1.md` ticked with user

## Phase 2 — Method Implementation + Entity Mount (V降 + V升)

- [ ] CHK021 V降 acceptance table written; covers normal + boundary scenario per method
- [ ] CHK022 `src/service/<domain>/methods.py` exists for every service from Step 0-4
- [ ] CHK023 `methods.py` functions are plain async functions (no `cls`, no `@query`/`@mutation` decorator)
- [ ] CHK024 `mount_method()` in `src/models.py` uses delayed import + `@functools.wraps`
- [ ] CHK025 `main.py` calls `mount_method()` BEFORE creating `GraphQLHandler`
- [ ] CHK026 GraphiQL: every mounted method returns expected data
- [ ] CHK027 Error scenarios return observable errors (not "no error")
- [ ] CHK028 `pytest tests/` passes
- [ ] CHK029 V升 all rows in `phase2.md` ticked with user

## Phase 3 — UseCase Composition + MCP (V降 + V升)

- [ ] CHK030 V降 acceptance table written in `phase3.md`
- [ ] CHK031 `service/<domain>/dtos.py` defines DTOs via `DefineSubset` (no `from __future__ import annotations`)
- [ ] CHK032 DTO fields use DTO types (no SQLModel entity types — would raise `SQLModelInDtoFieldError`)
- [ ] CHK033 `service/<domain>/service.py` reuses `methods.py` (no direct DB access)
- [ ] CHK034 Every `UseCaseService` exposed method has a return type annotation
- [ ] CHK035 `service/<domain>/spec.md` documents purpose, methods, DTO, changelog
- [ ] CHK036 `main.py` wires `create_use_case_router` (or `create_jsonrpc_router`) for REST
- [ ] CHK037 `main.py` wires `create_use_case_graphql_mcp_server` for MCP
- [ ] CHK038 `main.py` wires `create_use_case_voyager` for service tree visualization
- [ ] CHK039 (optional) `create_use_case_cli` for Typer CLI
- [ ] CHK040 MCP http_app uses `transport="streamable-http"`, `stateless_http=True`
- [ ] CHK041 MCP http_app lifespan nested inside FastAPI lifespan
- [ ] CHK042 curl `/api/<service>/<method>` returns DTO shape (FK hidden)
- [ ] CHK043 Missing required param returns 422
- [ ] CHK044 MCP 4-layer tools work: `list_apps` → `describe_compose_schema` → `describe_compose_method` → `compose_query`
- [ ] CHK045 V升 all rows in `phase3.md` ticked with user

## Phase 4 — OpenAPI → TS SDK (V降 + V升)

- [ ] CHK046 V降 acceptance table written in `phase4.md`
- [ ] CHK047 `fe/openapi-ts.config.ts` input points to running server's `/openapi.json`
- [ ] CHK048 `fe/package.json` has `generate-client` script using `@hey-api/openapi-ts`
- [ ] CHK049 `@hey-api/sdk` configured with `operations: { strategy: "byTags" }` (not deprecated `asClass`)
- [ ] CHK050 `fe/src/sdk/types.gen.ts` covers every DTO return type
- [ ] CHK051 Field names preserve snake_case (no camelCase conversion)
- [ ] CHK052 Nested relations produce correct recursive TS types
- [ ] CHK053 V升 all rows in `phase4.md` ticked with user

## spec/ Directory Completeness

> From `spec-management.md` — verify before declaring "done".

- [ ] CHK060 `specs/<feature>/story.md` non-empty (original user requirement + Overview Design)
- [ ] CHK061 `specs/<feature>/phase0.md` non-empty (all 8 steps recorded)
- [ ] CHK062 `specs/<feature>/phase1.md` non-empty (V降 + 实现 + V升)
- [ ] CHK063 `specs/<feature>/phase2.md` non-empty (V降 + 实现 + V升)
- [ ] CHK064 `specs/<feature>/phase3.md` non-empty (V降 + 实现 + V升)
- [ ] CHK065 `specs/<feature>/phase4.md` non-empty (V降 + 实现 + V升)
- [ ] CHK066 Quick check: `wc -l specs/<feature>/*.md` — every file > 0 lines

## Notes

- Tick boxes only after explicit user confirmation (V-model).
- For iteration on existing projects, confirm only the delta but do NOT skip
  writing the affected `phaseN.md` sections.
- Empty `phaseN.md` at delivery = incomplete.
