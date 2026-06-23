# Phase 0 Research: Resolver `loader_instances`

**Date**: 2026-06-23
**Spec**: [spec.md](./spec.md)

Resolves the open design questions surfaced during spec writing. No external research needed — all answers derive from the pydantic-resolve reference implementation (`/home/tangkikodo/pydantic-resolve/`) and the existing nexusx codebase.

## R1: Parameter name and type signature

**Decision**: `Resolver.__init__(loader_instances: dict[type[DataLoader], DataLoader] | None = None)`.

**Rationale**: Exact parity with pydantic-resolve (`pydantic_resolve/resolver.py:69`). Keys are DataLoader subclasses; values are instances of the key class. Optional, defaults to `None` (treated as empty dict internally).

**Alternatives considered**:
- Separate `relationship_loader_instances` parameter for custom-Relationship loaders — rejected; see Clarifications session 2026-06-23 in `spec.md`.
- Mixed-key dict (`{Cls: ..., "name": ...}`) — rejected; type ambiguity in dict keys.

## R2: Validation strategy

**Decision**: Validate at `__init__` time. For each `(cls, instance)` pair:
- Raise `TypeError` if not `issubclass(cls, DataLoader)`.
- Raise `TypeError` if not `isinstance(instance, cls)`.

Empty dict `{}` or `None` → no validation, no error.

**Rationale**: Fails fast before traversal. pydantic-resolve uses `AttributeError` (`resolver.py:128-134`); `TypeError` is more idiomatic for Python type mismatches and matches nexusx's existing `TypeError` usage in `relationship.py:88-97`.

**Alternatives considered**:
- `AttributeError` (strict pydantic-resolve parity) — rejected; less idiomatic for Python type-mismatch errors.
- `ValueError` — acceptable but `TypeError` is more specific for "wrong type of argument" cases.
- Defer validation to first `resolve_*` execution — rejected; violates FR-002 "before traversal begins".

## R3: Storage location on Resolver

**Decision**: New private attribute `self._loader_instances: dict[type[DataLoader], DataLoader]` on `Resolver`. Populated in `__init__` from the parameter (after validation). Consulted by `_get_or_create_loader` BEFORE the existing `_loader_cache` fallback.

**Rationale**: Keeps the new path orthogonal to the existing `_loader_cache` (Resolver-created instances). The supplied dict is caller-owned; the cache is Resolver-owned.

**Implementation hook** (for Phase 2 / `tasks.md`):
```python
def _get_or_create_loader(self, loader_cls: type[DataLoader]) -> DataLoader:
    if loader_cls in self._loader_instances:
        return self._loader_instances[loader_cls]
    if loader_cls not in self._loader_cache:
        self._loader_cache[loader_cls] = loader_cls()
    return self._loader_cache[loader_cls]
```

## R4: Cache-clearing semantics across `resolve()` calls

**Decision**: `Resolver.resolve()` continues to clear `self._loader_cache` (Resolver-created instances). It does **NOT** clear `self._loader_instances` (caller-owned). Supplied loaders persist across `resolve()` calls on the same Resolver instance.

**Rationale**: Caller owns the lifecycle of supplied instances. Callers wanting per-request isolation construct a fresh Resolver (or fresh loader instances) per request. Matches pydantic-resolve semantics where the supplied instance is shared.

**Docstring requirement**: the `Resolver` class docstring must note that supplied loader instances are not cleared between `resolve()` calls.

## R5: `ErManager.create_resolver()` forwarding

**Decision**: The factory's inner `BoundResolver.__init__` gains a `loader_instances` keyword that is forwarded to `super().__init__`:

```python
class BoundResolver(_Resolver):
    def __init__(
        self,
        context: dict[str, Any] | None = None,
        loader_instances: dict[type[DataLoader], DataLoader] | None = None,
    ):
        super().__init__(
            loader_registry=er_manager,
            context=context,
            loader_instances=loader_instances,
        )
```

**Rationale**: Satisfies FR-005. Callers using the pre-wired class get the same ergonomics as direct `Resolver(...)` construction.

## R6: Exclusion of async-callable path

**Decision**: `loader_instances` matches by DataLoader **class** only. The `Loader(async_callable)` path (which wraps a function in a fresh `DataLoader(batch_load_fn=fn)` at `resolver.py:414-418`) is unaffected — there is no class to match against.

**Rationale**: pydantic-resolve has the same limitation. Callers wanting to inject a callable-backed loader must wrap it in a class themselves and supply via `loader_instances={WrapperClass: instance}`.

## R7: No interaction with `ErManager.clear_cache()` or auto-load

**Decision**: Supplied instances live on `Resolver`, not `ErManager`. `ErManager.clear_cache()` (called by `Resolver.resolve()` at `resolver.py:1279-1280`) does not affect them. Auto-load (`_batch_auto_load` → `_get_loader` → `ErManager.get_loader_for_entity`) never consults `self._loader_instances` — it goes through ErManager exclusively.

**Rationale**: Confirms the scope decision in Clarifications session 2026-06-23. ORM-native and custom-Relationship loaders are equally unaffected; no special check is needed to distinguish them.

## Summary

No `NEEDS CLARIFICATION` markers remain. All decisions are local; no external research agents were dispatched. Phase 1 can proceed to design artifacts.
