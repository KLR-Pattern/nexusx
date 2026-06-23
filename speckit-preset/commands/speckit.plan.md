---
description: Generate plan.md + Phase 1 design artifacts — wraps nexusx Phase 1 (SQLModel schema, ER diagram, mock seed, alembic decision).
---

<!--
  ============================================================================
  nexusx-4phase preset — wrap of speckit.plan
  ============================================================================
  Runs the core /speckit-plan flow, then drives Phase 1 design:
  - Branch on the Step 0-7 DB choice (in-memory vs persistent)
  - Produce SQLModel entity specs with the conventions
  - Produce Voyager wiring and mock seed strategy
  - Define Phase 1 V-model acceptance criteria with the user

  {CORE_TEMPLATE} is replaced at install time with the core plan command.
  ============================================================================
-->

## nexusx Phase 1 Overlay

You are running `/speckit-plan` with the **nexusx-4phase preset** active.
After the core plan workflow writes `plan.md` and the standard design artifacts
(`research.md`, `data-model.md`, `contracts/`, `quickstart.md`), drive the
**Phase 1 schema & DB decisions**.

### Pre-check

Read `specs/<feature>/spec.md` and confirm Step 0-7 is filled in. If any
Phase 0 box is unticked or `[NEEDS CLARIFICATION]` markers remain, STOP and
tell the user to finish Phase 0 first.

### Phase 1 design tasks (write to plan.md, Phase 1 addendum section)

1. **List concrete entities** derived from spec.md Step 0-1 / 0-2. For each:
   - SQLModel class name + table name
   - Fields with types and `Field(description=...)`
   - `Relationship(...)` declarations with `sa_relationship_kwargs={"lazy": "noload"}`
2. **Branch on DB choice**:
   - In-memory → document `init_db()` create_all + mock seed flow.
   - Persistent → document alembic init steps, env.py edits, script.py.mako edit, baseline migration, optional `load_seed.py`.
3. **Document Voyager wiring**: `create_use_case_voyager(services=[], er_manager=er)` mounted at `/voyager`.
4. **Phase 1 pitfalls**: surface the 6 pitfalls from the plan-template addendum as explicit risks to mitigate.
5. **Define Phase 1 acceptance criteria** with the user (V降 — see plan-template addendum) and record in `specs/<feature>/phase1.md`.

### Phase 1 acceptance gate

Phase 1 implementation must NOT start until:

- [ ] `plan.md` Phase 1 addendum is filled
- [ ] `phase1.md` V-model acceptance criteria table is agreed with the user
- [ ] Any alembic-related risk (persistent branch) is called out

### Hand-off

When done, suggest the user run `/speckit-tasks` to break Phase 1 (and later
phases) into actionable tasks.

---

## Core plan workflow

Below this point, the core `/speckit-plan` content runs unchanged.

{CORE_TEMPLATE}
