# nexusx-4phase preset

A spec-kit preset that layers the nexusx **4-phase V-model workflow** on top of
the standard spec-kit pipeline (`specify → plan → tasks → implement`).

## When to use

Use this preset when the project follows the nexusx 4-phase methodology:

| Phase | What happens | Output |
|-------|-------------|--------|
| **Phase 0** | Requirements confirmation (8 steps, with user) | `spec.md` (entities, relationships, aggregate roots, service split, DB choice) |
| **Phase 1** | Schema + ER diagram + mock seed | `src/models.py`, `src/db.py`, `src/database.py`, Voyager, optional alembic |
| **Phase 2** | Method implementation + Entity mount | `src/service/<domain>/methods.py`, `mount_method()` |
| **Phase 3** | UseCase composition + MCP | `dtos.py`, `service.py`, `create_use_case_router`, MCP, CLI |
| **Phase 4** | OpenAPI → TS SDK | `fe/src/sdk/*.gen.ts` |

Each phase follows a **V-model**: write acceptance criteria → implement →
verify each criterion with the user before moving on.

## What it overrides

### Templates (composition)

| Template | Strategy | Effect |
|----------|----------|--------|
| `spec-template` | `append` | Adds Phase 0 sections (entities, relationships, service split, DB strategy) |
| `plan-template` | `append` | Adds Phase 1 sections (SQLModel, Voyager, alembic decisions) |
| `phase-template` | (new) | Per-phase V-model spec: V降 / implementation / V升 |
| `checklist-template` | `replace` | V-model acceptance checklist + `spec/` directory completeness check |

### Commands (composition)

| Command | Strategy | Effect |
|---------|----------|--------|
| `speckit.specify` | `wrap` | Runs Phase 0's 8-step requirements confirmation |
| `speckit.plan` | `wrap` | Runs Phase 1 schema/ER/DB decisions |
| `speckit.tasks` | `wrap` | Partitions tasks by Phase (2/3/4) |
| `speckit.implement` | `wrap` | Runs V-model loop per phase |
| `speckit.nexusx.phase` | (new) | Enter a specific phase explicitly |

### Scaffold

`scaffold/` contains the code skeleton (`pyproject.toml` + `src/`) that
`speckit.plan` references when bootstrapping a new project.

## Install

```bash
# From local directory (development)
specify preset add --dev ./speckit-preset

# Verify resolution
specify preset resolve spec-template
specify preset resolve speckit.specify

# Remove
specify preset remove nexusx-4phase
```

## Workflow

```bash
# 1. Phase 0 — requirements confirmation
/speckit-specify <feature description>
# → spec.md with Phase 0 sections filled

# 2. Phase 1 — schema decisions
/speckit-plan
# → plan.md with Phase 1 (SQLModel, ER, DB choice, alembic decision)

# 3. Phase 2-4 — implementation
/speckit-tasks
# → tasks.md grouped by Phase 2/3/4

/speckit-implement
# → V-model loop per Phase: pause for user verification after each phase

# Or enter a specific phase directly
/speckit-nexusx-phase 3
```

## Status

Work in progress — see `../skill/` for the canonical 4-phase methodology this
preset is being migrated from.

## License

MIT
