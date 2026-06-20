# UseCase API 参考

定义 `UseCaseService` 业务服务，通过 3.0+ 的 GraphQL MCP（`create_use_case_graphql_mcp_server`）、FastAPI REST（`create_use_case_router`）、JSON-RPC（`create_jsonrpc_router`）、CLI（`create_use_case_cli`）或独立 GraphQL HTTP endpoint（`build_compose_schema` + `compose_introspect`）对外暴露。

## UseCaseService

使用 `UseCaseService` 作为业务服务基类。子类声明 `async classmethod` 方法，元类自动发现公共方法。

```python
from nexusx.use_case import UseCaseService
from nexusx import query, mutation

class SprintService(UseCaseService):
    """Sprint 管理服务。"""

    @query
    async def list_sprints(cls) -> list[SprintSummary]:
        ...

    @query
    async def get_sprint(cls, sprint_id: int) -> SprintSummary | None:
        ...

    @mutation
    async def create_sprint(cls, name: str) -> SprintSummary:
        ...
```

!!! warning
    遵守以下规则以避免方法发现失败：
    - 方法必须使用 `@query` 或 `@mutation` 装饰器
    - 方法必须是 `async`，第一个参数为 `cls`
    - 方法名以 `_` 开头的不会被自动发现
    - docstring 成为 MCP 工具的描述

### 类方法

| 方法 | 说明 |
|------|------|
| `get_tag_name()` | 返回类名作为标签（如 `"SprintService"`） |

## UseCaseAppConfig

使用 `UseCaseAppConfig` 将一组 UseCaseService 组织为一个应用。

```python
from nexusx.use_case import UseCaseAppConfig

config = UseCaseAppConfig(
    name="project",
    services=[SprintService, TaskService],
    description="Project management API",
)
```

### 参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| `name` | `str` | 是 | 应用名称 |
| `services` | `list[type[UseCaseService]]` | 是 | UseCaseService 子类列表 |
| `description` | `str \| None` | 否 | 应用描述 |
| `context_extractor` | `Callable \| None` | 否 | MCP 上下文提取函数 |

## create_use_case_graphql_mcp_server

使用 `create_use_case_graphql_mcp_server` 创建 UseCase 服务的 MCP 服务端，支持多应用和四层渐进式披露。会从 `UseCaseService` 签名自动生成真正的 GraphQL schema（兼容 GraphiQL）；Layer 3 接收标准 GraphQL 查询字符串。

```python
from nexusx.use_case import create_use_case_graphql_mcp_server, UseCaseAppConfig

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

### 参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| `apps` | `list[UseCaseAppConfig]` | 是 | 应用配置列表 |
| `name` | `str` | 否 | 服务名称 |

### 生成的 MCP 工具

| 工具 | 说明 | 响应信封 |
|------|------|---------|
| `list_apps()` | 列出所有可用应用 | `{success, data}` |
| `describe_compose_schema(app_name)` | 应用下 service + 方法紧凑列表（不含参数和返回类型） | `{success, data}` |
| `describe_compose_method(app_name, service_name, method_name)` | 参数表 + 返回类型 + SDL 片段（含返回类型的传递闭包） | `{success, data}` |
| `compose_query(app_name, query)` | 执行 GraphQL 查询字符串 | `{data, errors}`（GraphQL 标准） |

### Schema 结构（固定三层）

```graphql
type Query {
  SprintService: SprintServiceQuery!
  TaskService: TaskServiceQuery!
}
type SprintServiceQuery {
  list_sprints: [SprintSummary!]!
  get_sprint(sprint_id: Int!): SprintSummary
}
type Mutation {  # 仅当存在 @mutation 方法时
  SprintService: SprintServiceMutation!
}
```

### Layer 3 执行约定

- 接收标准 GraphQL 查询字符串（如 `{ SprintService { list_sprints { id title owner { name } } } }`）
- 字段投影：只返回请求的字段（基于 `subset.build_subset_model`）
- **拒绝内省**（`__schema` / `__type` / `__typename`）—— 用 Layer 1/2 发现 schema。保持 MCP 响应紧凑。
- **不在外层套 `Resolver()`** —— service 方法自己负责 Resolver 调用（需要时在方法体内 `Resolver().resolve(dtos)`）
- `@query` 方法并发（`asyncio.gather`）；`@mutation` 方法按查询顺序串行

### 从 2.x 迁移

3.0 移除了 2.x 的直接调用式 MCP（`create_use_case_mcp_server`、`create_use_case_flat_server`）。完整 before/after 映射见 [`docs/migrations/3.0-use-case-graphql.md`](../migrations/3.0-use-case-graphql.md)。

## build_compose_schema / ComposeSchema / compose_introspect

直接访问 schema，用于非 MCP 场景（如自建 GraphQL HTTP endpoint + GraphiQL）。

```python
from nexusx import build_compose_schema, compose_introspect, UseCaseAppConfig

app_config = UseCaseAppConfig(name="project", services=[SprintService, TaskService])
schema = build_compose_schema(app_config)

# 三种渲染视图（共享同一份 registry）：
schema.render_sdl()                          # 完整 SDL 字符串
schema.render_introspection()                # graphql __schema payload（GraphiQL 兼容）
schema.render_method_sdl("SprintService", "list_sprints")  # 单方法 SDL 片段

# 处理真正的内省查询（给 GraphiQL HTTP endpoint 用）：
compose_introspect(schema, "{ __schema { types { name } } }")
# → {"data": {"__schema": {...}}, "errors": None}
```

完整 FastAPI `/graphql` 示例见 [`demo/use_case/graphql_server.py`](https://github.com/KLR-Pattern/nexusx/blob/master/demo/use_case/graphql_server.py)。

## create_use_case_voyager

使用 `create_use_case_voyager` 创建 Voyager 可视化 ASGI 子应用。

```python
from nexusx.voyager import create_use_case_voyager

voyager = create_use_case_voyager(
    apps=[
        UseCaseAppConfig(
            name="project",
            services=[SprintService, TaskService],
        ),
    ],
)
```

### REST 端点

| 端点 | 说明 |
|------|------|
| `/dot` | DOT 格式服务依赖图 |
| `/dot-search` | 可搜索的 DOT 图 |
| `/er-diagram` | Mermaid ER 图 |
| `/source` | 源代码信息 |

## FromContext

使用 `FromContext` 标记注解，从 MCP 上下文中注入参数。

```python
from typing import Annotated
from nexusx.use_case import FromContext

class SprintService(UseCaseService):
    @query
    async def list_sprints(cls, tenant_id: Annotated[int, FromContext()]) -> list[SprintSummary]:
        ...
```

## build_dto_select

使用 `build_dto_select` 辅助函数构建查询 DTO 所需字段的 SELECT 语句。

```python
from nexusx import build_dto_select

stmt = build_dto_select(SprintSummary)
stmt = build_dto_select(SprintSummary, where=Sprint.id == sprint_id)
```

> **注意：** 当 ORM 关系使用 `lazy="noload"` 时（ErManager + Resolver 的推荐模式），此函数的收益有限，因为裁剪仅限于标量列。可以用 `select(Entity)` + `DTO.model_validate(entity)` 实现相同效果。仅在 DTO 从宽表中选取少量标量列时，列裁剪才有实际价值。
