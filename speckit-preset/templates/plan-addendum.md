<!--
  ============================================================================
  nexusx-4phase preset — Phase 1 addendum (appended to plan-template)
  ============================================================================
  Phase 1 = Schema + ER Diagram + mock seed. The sections below capture the
  concrete technical decisions: SQLModel entities, Relationship declarations,
  Voyager visualization, and alembic setup (conditional on Phase 0 Step 0-7).
  ============================================================================
-->

## Phase 1: Schema + ER + Mock Seed (nexusx)

**Goal**: pure entity models (fields + relationship declarations) + mock seed
data, visualized in Voyager for team review. **No business methods yet.**

### Files to Create

| File | Purpose |
|------|---------|
| `src/db.py` | engine + `async_session` factory. Must NOT import `models` (avoid circular). URL comes from Phase 0 Step 0-7. |
| `src/models.py` | Pure SQLModel entities + `Relationship`. No methods, no `nexusx` import. Every `Relationship` must add `sa_relationship_kwargs={"lazy": "noload"}`. |
| `src/database.py` | `init_db()` lifecycle hook called from FastAPI lifespan. Implementation depends on Step 0-7. |
| `src/main.py` | FastAPI app + Voyager ER diagram. |

### Models Conventions

- Every `Model` class has a docstring explaining its business meaning.
- Every `Field` has a `description=...` explaining the field semantics (this
  propagates to OpenAPI spec).
- All `Relationship(...)` declarations use `sa_relationship_kwargs={"lazy": "noload"}` — the project relies on explicit Resolver + DataLoader, not ORM
  lazy-load, and `noload` prevents `DetachedInstanceError` during
  `model_validate(entity)` after session close.
- Directory names must NOT start with a digit (Python module rule).

### DB Persistence Branch

Branch on the Step 0-7 selection:

#### In-memory SQLite

- `db.py`: `engine = create_async_engine("sqlite+aiosqlite://")`
- `database.py`: `init_db()` runs `SQLModel.metadata.create_all` + mock seed.
- No alembic, no docker-compose.

#### Persistent (file SQLite / docker / external)

- `database.py`: `init_db()` becomes a no-op (signature preserved; both
  `main.py` lifespan and `tests/conftest.py` import it). Schema is owned by
  alembic; data by `scripts/load_seed.py`.
- Add `alembic>=1.13` to `pyproject.toml` plus the matching async driver
  (`asyncpg` for postgresql, `aiomysql` for mysql).
- `alembic init alembic`, then:
  - `alembic/env.py`: `import src.models  # noqa: F401` (else `SQLModel.metadata` is empty and autogenerate produces empty migrations), `target_metadata = SQLModel.metadata`, sync URL via env var, `render_as_batch=True` for SQLite.
  - `alembic/script.py.mako`: add `import sqlmodel` (else `AutoString` reference fails).
  - `alembic.ini`: leave `sqlalchemy.url =` empty; env.py overrides.
  - `.gitignore`: add `var/` for file SQLite.
- `alembic revision --autogenerate -m "init schema"` → review → `alembic upgrade head`.
- (Optional) `scripts/load_seed.py`: one-shot seed loader that preserves IDs and timestamps.

### Voyager Visualization

`create_use_case_voyager(services=[], er_manager=er)` exposes the ER diagram
at `/voyager`. This is the primary Phase 1 deliverable for team review.

### Phase 1 Pitfalls (record in plan.md, avoid in impl)

1. `engine` / `session` MUST be in `db.py` separately — putting them with models causes circular import.
2. `pyproject.toml` MUST set `packages = ["src"]` under `[tool.hatch.build.targets.wheel]`.
3. In-memory SQLite is process-local — switching to file mid-flight requires dumping via MCP/HTTP first.
4. Under `uvicorn --reload`, editing `db.py` URL triggers an immediate reload that can run `init_db()` against the new path → autogenerate sees existing tables and produces an empty migration. Dump data first, then edit.
5. alembic autogenerate producing empty `upgrade()` = `env.py` forgot `import src.models`.
6. `alembic upgrade` raising `NameError: name 'sqlmodel' is not defined` = `script.py.mako` forgot `import sqlmodel`.

### Phase 1 V-Model Acceptance Criteria

Before entering Phase 1 implementation, agree these criteria with the user and
record them under `specs/<feature>/phase1.md`:

| # | Criterion | Verification |
|---|-----------|--------------|
| 1 | Every Entity appears in Voyager ER with correct relationship directions | Open Voyager in browser |
| 2 | `models.py` contains only fields + Relationship (no `@query` / `@mutation`, no `nexusx` import) | Code review |
| 3 | Mock seed data has reasonable volume, relationships, and boundary cases | Query row counts |
| 4 | (Persistent branch) alembic baseline migration is generated and `upgrade head` succeeds | `alembic upgrade head` + check `alembic_version` table |
