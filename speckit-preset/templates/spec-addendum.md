<!--
  ============================================================================
  nexusx-4phase preset — Phase 0 addendum (appended to spec-template)
  ============================================================================
  The sections below are added by the nexusx-4phase preset. They capture the
  Phase 0 requirements confirmation (entities, relationships, aggregate roots,
  service split, DB strategy) that must be agreed with the user BEFORE entering
  Phase 1 implementation.

  Fill each section with the user before marking the spec ready for /speckit-plan.
  ============================================================================
-->

## Phase 0: Requirements Confirmation (nexusx)

> **Gate**: Phase 0 must be fully confirmed with the user before /speckit-plan.
> Every subsection below needs explicit user sign-off.

### Step 0-1: Entities & Fields

For each business entity, list business meaning, core fields (name + type +
semantics), and field constraints (unique / not-null / enum / composite-unique).

| Entity | Business Meaning | Core Fields | Constraints |
|--------|------------------|-------------|-------------|
| [Entity 1] | [one sentence] | [name: type — semantics] | [unique / not-null / enum] |
| [Entity 2] | ... | ... | ... |

### Step 0-2: Relationships

Text ER diagram. Each edge: direction (1:N / N:1 / M:N), business meaning,
whether a join entity is needed.

```
[Entity A] ──1:N──→ [Entity B]   # [business meaning]
[Entity C] ──M:N──→ [Entity D]   # via [join entity]
```

### Step 0-3: Aggregate Roots

Which entity (or entities) is the aggregate root? The aggregate root determines:
- Primary business entry points
- Where `@query` / `@mutation` methods attach
- How Phase 3 services are partitioned

**Aggregate root(s)**: [entity name(s)] + [rationale]

### Step 0-4: Service Partitioning

> ⚠️ The service split must be agreed with the user — do NOT decide unilaterally.
> Present at least one candidate partitioning, explain trade-offs, let the user
> pick or amend.

**Chosen partitioning**: [by-functional-domain / by-aggregate-root / hybrid]

**Services and their methods**:

| Service | Method | Business Intent | Mount Entity | Key Params |
|---------|--------|-----------------|--------------|------------|
| [domain] | [verb_xxx] | [one sentence] | [Entity] | [param1, param2] |
| ... | ... | ... | ... | ... |

### Step 0-5: GraphQL Positioning

GraphQL is an **auxiliary testing interface**, not the primary API. Business
methods live in `service/<domain>/methods.py` and are mounted onto both Entity
classes (for GraphQL) and UseCaseService classes (for REST/MCP/CLI).

- GraphQL: dev testing + AI evaluation
- REST / JSON-RPC / MCP / CLI: primary APIs (decided in Phase 3)

### Step 0-6: Third-Party Library Selection

For each non-business concern (auth, realtime, file storage, migration, …),
list the recommended library + rationale + maintenance status.

| Concern | Recommended | Reason | Notes |
|---------|-------------|--------|-------|
| [auth] | [library] | [why] | [maintenance status / alternative] |
| ... | ... | ... | ... |

> nexusx-covered concerns (ORM, GraphQL, MCP) are out of scope here.

### Step 0-7: DB Persistence & Migration Strategy

> ⚠️ Must be explicitly selected by the user. Determines Phase 1 `db.py` /
> `database.py` shape and whether alembic is introduced.

**Selection** (one of):

| Option | Async URL | Persists | Alembic | Extra Deps |
|--------|-----------|----------|---------|------------|
| In-memory SQLite | `sqlite+aiosqlite://` | ❌ process exit | ❌ | `aiosqlite` |
| File SQLite | `sqlite+aiosqlite:///./var/<name>.db` | ✅ file | ✅ | `aiosqlite` |
| Docker PostgreSQL | `postgresql+asyncpg://…` | ✅ volume | ✅ | `asyncpg` + compose |
| Docker MySQL | `mysql+aiomysql://…` | ✅ volume | ✅ | `aiomysql` + compose |
| External DB | varies | ✅ | ✅ | driver-dependent |

**Selected**:
- DB type: [in-memory sqlite / file sqlite / docker pg / docker mysql / external ___]
- async `DATABASE_URL`: ______
- sync `DATABASE_URL_SYNC` (for alembic + load_seed): ______
- Introduce alembic: [yes / no]
- Need docker-compose: [yes / no]
- `init_db()` strategy: [create_all+seed / no-op+alembic / other]

### Step 0-8: Phase 0 Checklist

- [ ] All entities and fields are complete; constraints are clear
- [ ] Relationship directions and cardinalities are correct
- [ ] Aggregate root is explicit
- [ ] Service partitioning is **confirmed by the user**
- [ ] Core use cases cover the main business scenarios; logic is self-consistent
- [ ] Third-party libraries are selected; maintenance status investigated
- [ ] DB choice + migration strategy is **explicitly confirmed by the user**
- [ ] No obvious gaps or edge cases left undiscussed

> All boxes must be ticked before /speckit-plan.
