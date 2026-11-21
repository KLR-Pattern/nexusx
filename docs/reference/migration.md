# Migration Guide

## `_subset_registry` hack → `add_virtual_entities()` (Non-SQLModel Roots)

Before non-SQLModel root support landed, projects that needed a non-SQLModel root
(e.g. `CurrentUser` assembled from OIDC claims, page wrappers, third-party SDK DTOs)
worked around the limitation by mutating NexusX internals directly:

```python
# ❌ Old hack — fragile, undocumented, breaks on version bumps
from nexusx.subset import _subset_registry
_subset_registry[CurrentUserRootDTO] = CurrentUserRoot
```

Replace with the official API. See [Virtual Entities guide](../guide/virtual_entities.md)
for the full contract. Quick mapping:

| Hack shape | Official replacement |
|------------|---------------------|
| `_subset_registry[X] = Y` where `Y` has `__relationships__` or should be ER-visible | `er.add_virtual_entities([Y])` after `ErManager(...)` |
| `_subset_registry[X] = Y` where `X` is a subset of `Y`'s schema | `class X(DefineSubset): __subset__ = (Y, ("fields",))` (Y may now be a BaseModel) |
| `_subset_registry[X] = Y` where `X` *is* `Y` (root is its own schema) | Make `X` a plain `BaseModel` and `er.add_virtual_entities([X])` |

The migration is mechanical (search-and-replaceable). `ErManager.__init__` signature is
unchanged; existing DTO hierarchies don't need to be rewritten.

---

## 1.6.0 → 1.7.0: Voyager ER Diagram Relationship Field Refactor

The Voyager ER diagram changed from FK-field-based to relationship-name-based display.

### What Changed

| Aspect | Old Behavior | New Behavior |
|--------|-------------|-------------|
| Relationship fields in node | Shows FK field (e.g. `user_id`) marked as `is_object` | Shows relationship name + target type (e.g. `owner: User`) |
| Edge source | Starts from FK field (e.g. `user_id`) | Starts from relationship field (e.g. `owner`) |
| Toggle "Object fields" | Shows FK fields | Shows relationship fields |

### Impact

- Only affects `ErDiagramDotBuilder` (Voyager visualization)
- `ErDiagram` (Mermaid generator) is not affected
- No public API changes — no code migration needed

## rpc → use_case Refactor

The RPC module has been fully refactored into the UseCase pattern.

!!! warning
    This is a breaking change. Update all imports and class names before upgrading.

### Name Changes

| Old Name | New Name |
|----------|----------|
| `RpcService` | `UseCaseService` |
| `create_rpc_mcp_server` | `create_use_case_graphql_mcp_server` |
| `create_rpc_voyager` | `create_use_case_voyager` |
| `RpcVoyager` | `UseCaseVoyager` |

### MCP Tool Changes

The current UseCase MCP uses GraphQL and four progressive-disclosure layers:

| Old Tool | New Tool |
|----------|----------|
| `list_services()` | `list_apps()` → `describe_compose_schema(app_name)` |
| `describe_service(service_name)` | `describe_compose_method(app_name, service_name, method_name)` |
| `call_rpc(service_name, method_name, params)` | `compose_query(app_name, query)` |

### Code Migration

```python
# Before (rpc)
from nexusx.rpc import RpcService, create_rpc_mcp_server

class SprintService(RpcService):
    ...

mcp = create_rpc_mcp_server(
    services=[SprintService, TaskService],
    name="Project API",
)

# After (current UseCase GraphQL MCP)
from nexusx import (
    UseCaseAppConfig,
    UseCaseService,
    create_use_case_graphql_mcp_server,
)

class SprintService(UseCaseService):
    ...

mcp = create_use_case_graphql_mcp_server(
    apps=[
        UseCaseAppConfig(
            name="project",
            services=[SprintService, TaskService],
            description="Project management",
        ),
    ],
    name="Project UseCase API",
)
```

### New Features

- **Multi-app management**: Organize multiple apps via `UseCaseAppConfig`
- **FromContext**: Support parameter injection from MCP context
- **GraphQL execution**: Layer 3 accepts standard GraphQL query strings

For the direct 2.x → 3.0 mapping, see
[UseCase GraphQL MCP migration](../migrations/3.0-use-case-graphql.md).

## 1.3.x → 1.4.0: RpcServiceConfig Removal (Historical)

`create_rpc_mcp_server` and `create_rpc_voyager` no longer accept `RpcServiceConfig` configuration dicts — pass `RpcService` subclass lists directly.

```python
# Before (1.3.x)
from nexusx import RpcServiceConfig, create_rpc_mcp_server

mcp = create_rpc_mcp_server(
    services=[
        RpcServiceConfig(name="task", service=TaskService, description="..."),
        RpcServiceConfig(name="sprint", service=SprintService, description="..."),
    ],
)

# After (1.4.0)
from nexusx import create_rpc_mcp_server

mcp = create_rpc_mcp_server(
    services=[TaskService, SprintService],
)
```

## 1.3.2 → 1.3.3: Loader(str) Historical Removal

Version 1.3.3 removed the `Loader('relationship_name')` lookup pattern:

```python
# Before (1.3.2)
def resolve_owner(self, loader=Loader("owner")):
    return loader.load(self.owner_id)

# After (1.3.3) — use DataLoader class or async function
def resolve_owner(self, loader=Loader(UserLoader)):
    return loader.load(self.owner_id)
```

!!! tip
    Current NexusX releases support `Loader("relationship_name")` again through
    `ErManager`'s relationship registry. The typed DataLoader class/callable
    form remains useful when no registered relationship exists or a global
    name lookup would be ambiguous.

    Implicit auto-loading already covers common scenarios. When the field name matches a relationship and the type is compatible, you don't need to write `resolve_*` methods:

    ```python
    class TaskDTO(DefineSubset):
        __subset__ = (Task, ("id", "title", "owner_id"))
        owner: UserDTO | None = None   # Auto-loaded, no resolve_* needed
    ```
