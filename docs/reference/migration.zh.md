# 迁移指南

## `_subset_registry` hack → `add_virtual_entities()`（非 SQLModel 根）

在非 SQLModel 根支持落地之前，需要非 SQLModel 根的项目（如由 OIDC claims 组装的 `CurrentUser`、页面级 wrapper、第三方 SDK DTO）通过直接改 NexusX 内部状态绕过限制：

```python
# ❌ 旧 hack——脆弱、未文档化、版本升级容易崩
from nexusx.subset import _subset_registry
_subset_registry[CurrentUserRootDTO] = CurrentUserRoot
```

请用官方 API 替换。完整契约见 [虚拟实体指南](../guide/virtual_entities.zh.md)。速查表：

| Hack 形态 | 官方替代 |
|-----------|----------|
| `_subset_registry[X] = Y`，其中 `Y` 有 `__relationships__` 或需要在 ER 图可见 | 在 `ErManager(...)` 之后调用 `er.add_virtual_entities([Y])` |
| `_subset_registry[X] = Y`，其中 `X` 是 `Y` schema 的子集 | `class X(DefineSubset): __subset__ = (Y, ("fields",))`（Y 现在可以是 BaseModel） |
| `_subset_registry[X] = Y`，其中 `X` *就是* `Y`（根本身就是 schema） | 把 `X` 改成普通 `BaseModel`，然后 `er.add_virtual_entities([X])` |

迁移是机械的（可搜索替换）。`ErManager.__init__` 签名不变；现有 DTO 层级不需要重写。

---

## rpc → use_case 重构（当前版本）

RPC 模块已全面重构为 UseCase 模式。

!!! warning
    这是一个破坏性变更。升级前需要更新所有 import 和类名。

### 名称变化

| 旧名称 | 新名称 |
|--------|--------|
| `RpcService` | `UseCaseService` |
| `create_rpc_mcp_server` | `create_use_case_mcp_server` |
| `create_rpc_voyager` | `create_use_case_voyager` |
| `RpcVoyager` | `UseCaseVoyager` |

### MCP 工具变化

从三层改为四层，增加 `list_apps` 层支持多应用管理：

| 旧工具 | 新工具 |
|--------|--------|
| `list_services()` | `list_apps()` → `list_services(app_name)` |
| `describe_service(service_name)` | `describe_service(app_name, service_name)` |
| `call_rpc(service_name, method_name, params)` | `call_use_case(app_name, service_name, method_name, params)` |

### 代码迁移

```python
# Before (rpc)
from nexusx.rpc import RpcService, create_rpc_mcp_server

class SprintService(RpcService):
    ...

mcp = create_rpc_mcp_server(
    services=[SprintService, TaskService],
    name="Project API",
)

# After (use_case)
from nexusx.use_case import UseCaseService, UseCaseAppConfig, create_use_case_mcp_server

class SprintService(UseCaseService):
    ...

mcp = create_use_case_mcp_server(
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

### 新功能

- **多应用管理**：通过 `UseCaseAppConfig` 组织多个应用
- **FromContext**：支持从 MCP 上下文注入参数
- **大小写不敏感查找**：app_name 查找不区分大小写

## 1.3.x → 1.4.0: RpcServiceConfig 移除（历史）

`create_rpc_mcp_server` 和 `create_rpc_voyager` 不再接受 `RpcServiceConfig` 配置字典，直接传 `RpcService` 子类列表。

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

## 1.3.2 → 1.3.3: Loader(str) 移除

`Loader('relationship_name')` 字符串查找模式已移除。

```python
# Before (1.3.2)
def resolve_owner(self, loader=Loader("owner")):
    return loader.load(self.owner_id)

# After (1.3.3) — 使用 DataLoader 类或异步函数
def resolve_owner(self, loader=Loader(UserLoader)):
    return loader.load(self.owner_id)
```

!!! tip
    隐式自动加载已覆盖常见场景。当字段名匹配关系且类型兼容时，不需要手写 `resolve_*` 方法：

    ```python
    class TaskDTO(DefineSubset):
        __subset__ = (Task, ("id", "title", "owner_id"))
        owner: UserDTO | None = None   # 自动加载，无需 resolve_*
    ```
