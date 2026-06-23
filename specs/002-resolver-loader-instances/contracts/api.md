# Public API Contract: Resolver `loader_instances`

**Date**: 2026-06-23
**Spec**: [spec.md](../spec.md)

This feature is a backward-compatible addition to the public API of `nexusx.Resolver` and the factory `nexusx.ErManager.create_resolver()`. No existing signatures change.

## `Resolver.__init__`

### Signature (after change)

```python
def __init__(
    self,
    loader_registry: Any = None,
    context: dict[str, Any] | None = None,
    loader_instances: dict[type[DataLoader], DataLoader] | None = None,
) -> None
```

### Parameter contract

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `loader_registry` | `Any` | No | `None` | ErManager instance (existing). |
| `context` | `dict[str, Any] \| None` | No | `None` | Context dict for `context=` injection in `resolve_*` / `post_*` methods (existing). |
| `loader_instances` | `dict[type[DataLoader], DataLoader] \| None` | No | `None` | Pre-created DataLoader instances, keyed by class. When a `resolve_*` method declares `loader=Loader(Cls)` and `Cls` is in this dict, Resolver returns the supplied instance instead of creating a fresh one. |

### Behavior guarantees

1. **Backward compatibility**: Calling `Resolver()` or `Resolver(loader_registry=er)` without `loader_instances` behaves identically to today.
2. **First-match wins**: `_get_or_create_loader(Cls)` consults `self._loader_instances` first; on miss, falls back to creating a fresh instance in `self._loader_cache`.
3. **By reference**: Supplied instances are stored and used by reference (no copy). Mutations from `resolve_*` (e.g., `loader.clear()`, `loader.prime(...)`) are visible to the caller after `resolve()` returns.
4. **No clear between resolves**: `Resolver.resolve()` clears `self._loader_cache` and `self._node_collectors` (existing behavior) but does NOT clear `self._loader_instances`. Supplied loaders persist for the lifetime of the Resolver instance. Callers wanting per-request isolation construct a fresh Resolver (or fresh loader instances) per request.
5. **Auto-load isolation**: `loader_instances` does NOT affect auto-loaded relationship fields. The auto-load path (`_batch_auto_load` → `_get_loader` → `ErManager.get_loader_for_entity`) uses ErManager exclusively and never consults `self._loader_instances`.
6. **Callable-path isolation**: `Loader(async_callable)` Depends (which wrap a function in a fresh `DataLoader(batch_load_fn=fn)`) are unaffected. There is no class to match against.

### Errors raised at construction

| Condition | Error | Message pattern |
|-----------|-------|-----------------|
| A key is not a `DataLoader` subclass | `TypeError` | `f"{cls.__name__} must be a subclass of DataLoader"` |
| A value is not an instance of its key class | `TypeError` | `f"loader instance is not of type {cls.__name__}"` |
| Empty dict `{}` or `None` | (no error) | — |

## `ErManager.create_resolver()`

### Signature (unchanged)

```python
def create_resolver(self) -> type
```

### Returned class constructor (after change)

The returned `Resolver` subclass accepts:

```python
def __init__(
    self,
    context: dict[str, Any] | None = None,
    loader_instances: dict[type[DataLoader], DataLoader] | None = None,
) -> None
```

Both parameters are forwarded to the underlying `Resolver.__init__`. The `loader_registry` is pre-bound to the ErManager instance that produced the class.

### Usage

```python
from nexusx import ErManager

er = ErManager(base=SQLModel, session_factory=async_session)
Resolver = er.create_resolver()

# Per request
loader = UserLoader()
loader.prime(current_user.id, current_user_dto)
resolver = Resolver(
    context={"user_id": current_user.id},
    loader_instances={UserLoader: loader},
)
result = await resolver.resolve(dtos)
```

## Out of scope

Per Clarifications session 2026-06-23 in `spec.md`:

- Overriding ErManager-managed custom-Relationship loaders (`__relationships__`).
- Overriding ORM-native SQLModel relationship loaders.
- `loader_params`, `global_loader_param`, Resolver-level `split_loader_by_type`.

These restrictions are NOT enforced by `loader_instances` itself — the parameter simply has no effect on those code paths because they go through ErManager's name-based lookup, not Resolver's class-based lookup.
