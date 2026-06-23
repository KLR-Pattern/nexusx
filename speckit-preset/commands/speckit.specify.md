---
description: Create a specification and store it in spec.md — wraps nexusx Phase 0 (8-step requirements confirmation).
---

<!--
  ============================================================================
  nexusx-4phase preset — wrap of speckit.specify
  ============================================================================
  This command wraps the core /speckit-specify with Phase 0 requirements
  confirmation. The {CORE_TEMPLATE} placeholder below is replaced at install
  time with the full core speckit.specify command content.

  Workflow:
  1. Run the core specify flow (parse input, create spec.md skeleton)
  2. THEN run the nexusx Phase 0 8-step confirmation with the user
  3. Fill the Phase 0 sections appended to spec-template
  4. Block /speckit-plan until all 8 steps are confirmed
  ============================================================================
-->

## nexusx Phase 0 Overlay

You are running `/speckit-specify` with the **nexusx-4phase preset** active.
After completing the core specify workflow (creating `spec.md` from the user
input), you MUST additionally run the **Phase 0 requirements confirmation**
before reporting completion.

### Phase 0 — 8-step confirmation

After `SPEC_FILE` is written, walk the user through these steps in order. Each
step needs explicit user sign-off before the next one starts. Record every
answer in the corresponding section of `spec.md` (appended by the
nexusx-4phase preset's `spec-template`).

1. **Step 0-1 Entities & Fields** — list every business entity with business
   meaning, core fields (name + type + semantics), and constraints.
2. **Step 0-2 Relationships** — text ER diagram; for each edge: direction
   (1:N / N:1 / M:N), business meaning, whether a join entity is needed.
3. **Step 0-3 Aggregate Roots** — pick the aggregate root(s); explain why.
4. **Step 0-4 Service Partitioning** — ⚠️ propose at least one candidate
   partitioning (by functional domain / by aggregate root / hybrid), explain
   trade-offs, let the user pick. Then list every use-case method per service.
5. **Step 0-5 GraphQL Positioning** — record that GraphQL is an auxiliary
   testing interface; primary APIs (REST/MCP/CLI) are decided in Phase 3.
6. **Step 0-6 Third-Party Libraries** — for each non-business concern (auth,
   realtime, file storage, etc.), recommend a library + rationale + maintenance
   status. Investigate any library the user names.
7. **Step 0-7 DB Persistence & Migration** — ⚠️ user must explicitly select
   one of: in-memory sqlite / file sqlite / docker pg / docker mysql /
   external. Record `DATABASE_URL`, `DATABASE_URL_SYNC`, alembic decision,
   `init_db()` strategy.
8. **Step 0-8 Checklist** — go through the 8 boxes with the user; tick each
   only after explicit confirmation.

### Gate

Do **not** report completion until every box in Step 0-8 is ticked. If the user
defers any step, mark the corresponding section as `[NEEDS CLARIFICATION]` and
list the open question in the Completion Report.

### Completion Report (additional fields)

In addition to the core completion report, include:
- Phase 0 status: `confirmed` / `partial (see open questions)`
- Open questions: list of deferred steps

---

## Core specify workflow

Below this point, the core `/speckit-specify` content runs unchanged.

{CORE_TEMPLATE}
