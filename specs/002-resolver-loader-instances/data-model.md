# Data Model: Resolver `loader_instances`

**Date**: 2026-06-23
**Spec**: [spec.md](./spec.md)

This feature does **not** introduce new persistent entities, tables, or relationships. It modifies the in-memory API surface of two existing classes.

## Modified classes

### `nexusx.Resolver`

**File**: `src/nexusx/resolver.py`

**Existing constructor** (`resolver.py:350-354`):

```python
def __init__(
    self,
    loader_registry: Any = None,
    context: dict[str, Any] | None = None,
):
```

**After change**:

```python
def __init__(
    self,
    loader_registry: Any = None,
    context: dict[str, Any] | None = None,
    loader_instances: dict[type[DataLoader], DataLoader] | None = None,
):
```

**New private attribute**: `self._loader_instances: dict[type[DataLoader], DataLoader]` — populated after validation in `__init__`, empty dict when parameter is `None` or `{}`.

**New private method**: `_validate_loader_instances(loader_instances)` — iterates items, raises `TypeError` per R2 in `research.md`. Called from `__init__` when the parameter is non-None and non-empty.

**Modified private method**: `_get_or_create_loader(loader_cls)` (`resolver.py:408-412`) — consults `self._loader_instances` first; on miss, falls back to the existing `self._loader_cache` path.

### `nexusx.ErManager` (via `create_resolver()`)

**File**: `src/nexusx/loader/registry.py`

**Existing factory inner class** (`registry.py:511-513`):

```python
class BoundResolver(_Resolver):
    def __init__(self, context: dict[str, Any] | None = None):
        super().__init__(loader_registry=er_manager, context=context)
```

**After change**: `BoundResolver.__init__` gains a `loader_instances` keyword that is forwarded to `super().__init__`. See R5 in `research.md` for the exact signature.

## Unchanged

- `aiodataloader.DataLoader` — used as-is, no subclass added.
- `nexusx.Loader` / `nexusx.Depends` — the dependency-declaration surface is unchanged. `Loader(Cls)` continues to work exactly as today; the only difference is that `_resolve_dep` → `_get_or_create_loader` may now return a caller-supplied instance.
- `ErManager.__init__`, `_loader_instances` (internal cache), `get_loader`, `get_loader_for_entity`, `clear_cache` — all unchanged. The internal `_loader_instances` field on ErManager is unrelated to the new Resolver-side parameter and is not touched.
- Auto-load path (`_batch_auto_load`, `_get_loader`) — unchanged. Custom `__relationships__` loaders and ORM-native SQLModel relationship loaders both continue to flow through ErManager exclusively.

## Validation rules

| Input | Behavior |
|---|---|
| `loader_instances=None` (default) | No validation; `self._loader_instances = {}`. |
| `loader_instances={}` | No validation; `self._loader_instances = {}`. |
| `loader_instances={UserLoader: UserLoader()}` | Validated; stored. |
| `loader_instances={dict: object()}` | `TypeError` at construction ("dict must be a subclass of DataLoader"). |
| `loader_instances={UserLoader: object()}` | `TypeError` at construction ("loader instance is not of type UserLoader"). |

## State transitions

None. Resolver remains a request-scoped object: each `resolve()` call clears `_loader_cache` and `_node_collectors` (existing behavior) and traverses the input tree. The new `_loader_instances` is set once at construction and read-only thereafter.
