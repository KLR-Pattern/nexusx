# Quickstart: Resolver `loader_instances`

**Date**: 2026-06-23
**Spec**: [spec.md](./spec.md) | **Contracts**: [contracts/api.md](./contracts/api.md)

Runnable validation scenarios for the `loader_instances` feature. All scenarios are written as pytest cases that extend the existing test files.

## Prerequisites

- Repo at `/home/tangkikodo/nexusx`.
- `uv sync --all-extras` has been run.
- `./scripts/check-ci.sh` is green on `master` before starting.

## Scenario 1 — Pre-priming eliminates a redundant batch call (P1)

**Goal**: Verify that a pre-primed loader value is observed by `resolve_*` and suppresses the batch call for the primed key.

**Test outline** (`tests/test_resolver.py::test_loader_instances_pre_prime`):
1. Define a `DataLoader` subclass `CountingLoader` whose `batch_load_fn` increments a counter.
2. Construct `loader = CountingLoader(); loader.prime(42, expected_dto)`.
3. Build a small DTO tree whose `resolve_*` method calls `loader.load(42)` AND `loader.load(7)` (the unprimed key).
4. Construct `Resolver(loader_instances={CountingLoader: loader})`.
5. `await resolver.resolve(tree)`.

**Command**:
```bash
uv run pytest tests/test_resolver.py::test_loader_instances_pre_prime -xvs
```

**Expected outcome**:
- `tree.field_for_42 == expected_dto` (the primed value).
- `counter` was incremented exactly once (for key 7), not twice.

## Scenario 2 — Supplied instance is used by reference (P2)

**Goal**: Verify that the supplied instance (with its constructor state) is the same object `resolve_*` receives.

**Test outline** (`tests/test_resolver.py::test_loader_instances_by_reference`):
1. Define `class TaggedLoader(DataLoader): def __init__(self, tag, **kw): super().__init__(**kw); self.tag = tag`.
2. Construct `loader = TaggedLoader(tag="abc")`.
3. Build a DTO whose `resolve_*` captures the injected loader on a sentinel attribute.
4. `Resolver(loader_instances={TaggedLoader: loader})` → `await resolver.resolve(dto)`.

**Command**:
```bash
uv run pytest tests/test_resolver.py::test_loader_instances_by_reference -xvs
```

**Expected outcome**:
- `id(captured_loader) == id(loader)`.
- `captured_loader.tag == "abc"`.

## Scenario 3 — Misuse fails fast at construction (P3)

**Goal**: Verify typed errors for non-DataLoader keys and mismatched instance types.

**Test outline** (`tests/test_resolver.py::test_loader_instances_validation_errors`):
1. `with pytest.raises(TypeError): Resolver(loader_instances={dict: object()})`.
2. `with pytest.raises(TypeError): Resolver(loader_instances={TaggedLoader: object()})`.
3. `Resolver(loader_instances={})` and `Resolver()` — no exception.

**Command**:
```bash
uv run pytest tests/test_resolver.py::test_loader_instances_validation_errors -xvs
```

**Expected outcome**: all three sub-assertions pass; construction never reaches the traversal loop on bad input.

## Scenario 4 — Factory forwarding (FR-005)

**Goal**: Verify `ErManager.create_resolver()` returns a Resolver class that accepts and forwards `loader_instances`.

**Test outline** (`tests/test_loader_registry.py::test_create_resolver_forwards_loader_instances`):
1. Build a small ErManager over an in-memory SQLModel subset.
2. `Resolver = er.create_resolver()`.
3. `loader = CountingLoader(); loader.prime(42, expected)`; `r = Resolver(loader_instances={CountingLoader: loader})`.
4. Resolve a DTO tree; assert primed value is observed and counter is not incremented for key 42.

**Command**:
```bash
uv run pytest tests/test_loader_registry.py::test_create_resolver_forwards_loader_instances -xvs
```

**Expected outcome**: identical semantics to Scenario 1, just reached via the factory.

## Scenario 5 — No regression

**Goal**: Existing behavior is unchanged when `loader_instances` is not supplied.

**Command**:
```bash
./scripts/check-ci.sh
```

**Expected outcome**:
- Full existing test suite passes.
- `ruff check src/ tests/` clean.
- `mypy src/` clean.

## Notes

- These tests belong in the existing `tests/test_resolver.py` and `tests/test_loader_registry.py` — they already cover the relevant surfaces and have the necessary fixtures.
- Implementation bodies are out of scope here; see `tasks.md` once generated.
