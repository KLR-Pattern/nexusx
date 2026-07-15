# 数据模型：业务应用（Application）自包含数据库连接信息

**功能**：[spec.md](./spec.md) · **计划**：[plan.md](./plan.md) · **契约**：[contracts/](./contracts/)

> 本特性不涉及持久化数据（无 DB 表新增/修改），只涉及**运行时对象模型**。下文描述各对象类的字段、关系、生命周期、所有权语义。

---

## 1. 核心对象图

```text
                              ┌──────────────────────────────────────┐
                              │         create_mcp_server            │
                              │  (apps: list[Application|AppConfig]) │
                              └─────────────────┬────────────────────┘
                                                │ 构造 MultiAppManager
                                                ▼
                              ┌──────────────────────────────────────┐
                              │         MultiAppManager              │
                              │  _applications: list[Application]    │
                              │  apps: dict[str, AppResources]       │
                              │  aliases: dict[str, str]             │
                              └─────────────────┬────────────────────┘
                                                │ 1..N 持有
                                                ▼
                              ┌──────────────────────────────────────┐
                              │           Application                │
                              │  name / base / description / ...     │
                              │  _engine: AsyncEngine | None         │
                              │  _session_factory: Callable | None   │
                              │  _owns_engine: bool                  │
                              │  _resources: AppResources            │
                              └─────────────────┬────────────────────┘
                                                │ 1 持有
                                                ▼
                              ┌──────────────────────────────────────┐
                              │           AppResources               │
                              │  name / description                 │
                              │  handler: GraphQLHandler             │
                              │  tracer: TypeTracer                  │
                              │  sdl_generator: SDLGenerator         │
                              └──────────────────────────────────────┘
```

---

## 2. 实体定义

### 2.1 `Application`（新增）

**职责**：nexusx 中可独立导出、可合并的最小业务单元。封装业务模型 + 数据库连接 + GraphQL 元数据。

**关键字段**（构造期 immutable）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | `str` | ✓ | 唯一标识（如 "blog"、"shop"）；用于 mcp 工具的 `app_name` 路由 |
| `base` | `type[SQLModel]` | ✓ | 业务模型基类；`EntityDiscovery` 从此派生所有 entity |
| `url` | `str \| None` | ✗ | 数据库 URL 字符串。提供时 `Application` 自造 engine 并拥有 |
| `engine` | `AsyncEngine \| None` | ✗ | 外部已构造的异步引擎。提供时 `Application` 包装不拥有 |
| `session_factory` | `Callable \| None` | ✗ | 外部 session 工厂（兼容旧用法）。提供时 `Application` 包装不拥有 |
| `description` | `str` | ✗ | 人类可读描述（默认空串） |
| `query_description` | `str \| None` | ✗ | GraphQL Query 类型描述 |
| `mutation_description` | `str \| None` | ✗ | GraphQL Mutation 类型描述 |
| `aliases` | `list[str] \| None` | ✗ | 备用路由名（不可与 name 重名、不可跨 app 冲突） |
| `engine_kwargs` | `dict \| None` | ✗ | 自造 engine 时的额外参数（echo、pool_size 等） |

**互斥规则**：`url` / `engine` / `session_factory` 至多提供一个；同时提供 ≥2 个时构造期 `ValueError`。三者全缺时进入 schema-only 模式。

**内部字段**（构造期计算）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_engine` | `AsyncEngine \| None` | 自造或包装的引擎；schema-only 模式下为 None |
| `_session_factory` | `Callable \| None` | 自造或包装的工厂；schema-only 模式下为 None |
| `_owns_engine` | `bool` | 是否拥有引擎（仅当通过 `url=` 自造时为 True） |
| `_resources` | `AppResources` | 构造期 eager 填充，包含 handler/tracer/sdl_generator |
| `_disposed` | `bool` | dispose 幂等标记，初始 False |

**生命周期状态机**：

```text
       ┌──────────────────┐
       │   Unconstructed  │
       └────────┬─────────┘
                │ __init__(成功)
                ▼
       ┌──────────────────┐
       │     Active       │  ← 可正常访问 .resources / .session_factory
       └────────┬─────────┘
                │ await dispose()  (幂等：可多次调用)
                ▼
       ┌──────────────────┐
       │    Disposed      │  ← _engine 已 dispose (如拥有)；_resources 仍可读
       └──────────────────┘     但再执行 GraphQL 查询会失败
```

**关键方法**：详见 [contracts/application-public-api.md](./contracts/application-public-api.md)。

---

### 2.2 `AppResources`（沿用现有，不改）

**职责**：封装 mcp 工具调用所需的运行时资源。

**字段**：保持 `src/nexusx/mcp/managers/app_resources.py:14-46` 现状——`name`、`description`、`handler`、`tracer`、`sdl_generator`、`entity_names` (property)。

**变化**：从"由 `MultiAppManager._create_app_resources()` 构造"变为"由 `Application` 构造期构造并暴露为 `.resources` 属性"。

---

### 2.3 `MultiAppManager`（重构）

**职责**：管理多个 `Application`，提供按 name/alias 路由到 `AppResources` 的能力。

**关键字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `_applications` | `list[Application]` | coerce 后的 Application 列表 |
| `apps` | `dict[str, AppResources]` | name → resources 的查找表（同步 eager 填充） |
| `aliases` | `dict[str, str]` | alias → name 的查找表 |

**关键变化**（对比 `src/nexusx/mcp/managers/multi_app_manager.py:16-50`）：
- 构造函数签名：`__init__(self, apps: list[Application | AppConfig])`（接受两种形式）
- 内部 coerce：每个元素经 `_coerce_to_application()` 统一为 `Application`；dict 路径触发 `DeprecationWarning`
- AppResources 填充：从 `_create_app_resources()` 改为直接读 `app.resources`
- 跨 app 校验（unique name/alias、alias 冲突）：保留在 manager，操作于 Application 对象
- 新增 `async def dispose(self)`：循环调每个 Application 的 dispose（幂等）
- 新增 `async def __aenter__/__aexit__`

**保持不变**：
- `get_app(name) -> AppResources`（按 name 或 alias 查找，找不到 `ValueError`）
- `list_apps() -> list[str]`

---

### 2.4 `AppConfig`（TypedDict，弃用）

**状态**：保留作为兼容输入，但所有 dict 路径触发 `DeprecationWarning`。

**字段**：保持 `src/nexusx/mcp/types/app_config.py:12-31` 现状，新增可选字段：
- `url: str`（与 base 同等支持）
- `engine: AsyncEngine`（与 base 同等支持）

**生命终点**：在 PR5（文档）之后的某个 minor 版本完全移除。spec 假设段已锁定"兼容期为一个 minor 发布周期"。

---

## 3. 跨对象关系与所有权

| 关系 | 基数 | 所有权 | 处置责任 |
|---|---|---|---|
| `MultiAppManager` → `Application` | 1:N | manager 持有引用，不"拥有"（Application 可独立存在） | manager.dispose() 调每个 app.dispose()，但每个 app 自己决定是否真正释放 engine |
| `Application` → `AsyncEngine` | 1:0..1 | 当 `_owns_engine=True` 时拥有；否则仅持有引用 | 仅当拥有时 dispose |
| `Application` → `AppResources` | 1:1 | 拥有 | AppResources 内部不持有需要 dispose 的资源（GraphQLHandler 不持有 engine） |
| `MultiAppManager` → `AppResources` | 1:N（经 Application） | 不直接持有；通过 `Application.resources` 间接访问 | 不直接 dispose |

**幂等性约定**：所有 `dispose()` 方法必须幂等。重复调用、并发调用、异常路径下重复触发——都不抛异常、不重复释放。

---

## 4. 校验规则汇总（构造期）

| 规则 | 触发位置 | 错误信息样例 |
|---|---|---|
| 至少一个 app | `MultiAppManager.__init__` | `"At least one app configuration is required"` |
| app 必须有 `name` | `MultiAppManager.__init__` | `"App config at index {i} is missing required field 'name'"` |
| app 必须有 `base` | `MultiAppManager.__init__` | `"App '{name}' is missing required field 'base'"` |
| 名称不重复 | `MultiAppManager.__init__` | `"Duplicate app name '{name}' is not allowed"` |
| 别名不重复 | `MultiAppManager.__init__` | `"Alias '{alias}' is already used by another app"` |
| 别名不与名冲突 | `Application.__init__` | `"Alias '{alias}' conflicts with own name '{name}'"` |
| 别名是字符串列表 | `Application.__init__` | `"'aliases' must be a list of non-empty strings"` |
| 连接字段至多一个 | `Application.__init__` | `"Provide at most one of: url, engine, session_factory"` |
| dict 输入触发弃用警告 | `_coerce_to_application` | `DeprecationWarning("Passing AppConfig dict is deprecated...")` |

---

## 5. 与现有对象的兼容性

| 现有对象 | 影响 | 兼容策略 |
|---|---|---|
| `AppResources` | 字段不变 | 完全兼容 |
| `GraphQLHandler` | 字段不变；仍接收 `session_factory=None` | 完全兼容 |
| `MultiAppManager.apps` | 类型不变（`dict[str, AppResources]`）；填充时机不变（同步 eager） | 现有 18 个测试断言全部保持 |
| `MultiAppManager.get_app()` | 签名不变 | 完全兼容 |
| `create_mcp_server(apps=...)` | 签名扩展为 `list[Application | AppConfig]`；返回类型 `FastMCP` 不变 | 字典输入仍工作（带 DeprecationWarning） |
| `create_simple_mcp_server` | 不动 | 完全兼容 |
| `UseCaseAppConfig` | 不动 | 完全兼容（roadmap 处理） |
