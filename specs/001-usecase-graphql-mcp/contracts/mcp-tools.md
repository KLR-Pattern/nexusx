# Contract: MCP Tools (4-Layer Progressive Disclosure)

**Feature**: `001-usecase-graphql-mcp` | **Date**: 2026-06-20

本文档定义 `create_use_case_graphql_mcp_server` 返回的 MCP server 暴露的 4 个工具的输入/输出契约。所有 4 个工具都注册在同一个 `FastMCP` 实例上。

---

## 工具列表总览

| Layer | 工具名 | 用途 | 响应信封 |
|-------|--------|------|---------|
| 0 | `list_apps` | 应用发现 | `{success, data}` |
| 1 | `describe_compose_schema` | schema 总览（紧凑） | `{success, data}` |
| 2 | `describe_compose_method` | 方法详情（含 SDL 片段） | `{success, data}` |
| 3 | `compose_query` | 执行 GraphQL 查询 | `{data, errors}` |

---

## T0. `list_apps` (Layer 0)

**Description**: List all available UseCase applications registered on this MCP server.

**Parameters**: 无

**Returns**:
```json
{
  "success": true,
  "data": {
    "apps": [
      {
        "name": "project",
        "description": "Project management with sprints, tasks, users",
        "services_count": 3
      }
    ],
    "hint": "Call describe_compose_schema(app_name=...) to see services and methods for an app."
  }
}
```

**Error cases**: 无（始终成功）

---

## T1. `describe_compose_schema` (Layer 1)

**Description**: List services and methods for an app. Compact: no parameter or return type details (use `describe_compose_method` for those).

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `app_name` | String | Yes | — | App name from `list_apps` |

**Returns (success)**:
```json
{
  "success": true,
  "data": {
    "app_name": "project",
    "services": [
      {
        "name": "UserService",
        "description": "User management service.",
        "methods": [
          { "name": "list_users", "kind": "query", "description": "Get all users." },
          { "name": "get_user", "kind": "query", "description": "Get user by id." }
        ]
      },
      {
        "name": "TaskService",
        "description": "Task management service.",
        "methods": [
          { "name": "list_tasks", "kind": "query", "description": "..." },
          { "name": "create_task", "kind": "mutation", "description": "..." }
        ]
      }
    ],
    "hint": "Call describe_compose_method(app_name=..., service_name=..., method_name=...) for parameter and return type details."
  }
}
```

**Error cases**:
- `app_name` 不存在 → `{success: false, error: "...", error_type: "APP_NOT_FOUND"}`

---

## T2. `describe_compose_method` (Layer 2)

**Description**: Get detailed information for a single method: parameters (name/type/default), return type, and a complete SDL fragment covering the method signature + all reachable DTO types.

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `app_name` | String | Yes | — | App name |
| `service_name` | String | Yes | — | Service name (e.g. "UserService") |
| `method_name` | String | Yes | — | Method name (e.g. "list_users") |

**Returns (success)**:
```json
{
  "success": true,
  "data": {
    "app_name": "project",
    "service_name": "TaskService",
    "method": {
      "name": "get_tasks_by_sprint",
      "kind": "query",
      "description": "Get tasks for a sprint.",
      "args": [
        {
          "name": "sprint_id",
          "type": "Int!",
          "has_default": false,
          "default_value": null,
          "description": null
        }
      ],
      "return_type": "[TaskSummary!]!"
    },
    "sdl": "type TaskServiceQuery {\n  get_tasks_by_sprint(sprint_id: Int!): [TaskSummary!]!\n}\n\ntype TaskSummary {\n  id: Int!\n  title: String!\n  status: String!\n  owner: UserSummary\n}\n\ntype UserSummary {\n  id: Int!\n  name: String!\n}"
  }
}
```

**SDL 片段规则**:
- 包含：`{Service}Query`（或 `{Service}Mutation`）类型上的方法字段
- 包含：返回类型的传递闭包（所有可达 DTO + enum）
- 不包含：root `Query` / `Mutation`、其它 service 的方法、无关类型

**Error cases**:
- `app_name` 不存在 → `APP_NOT_FOUND`
- `service_name` 不存在 → `SERVICE_NOT_FOUND`
- `method_name` 不存在 → `METHOD_NOT_FOUND`

---

## T3. `compose_query` (Layer 3)

**Description**: Execute a GraphQL query against the UseCase compose schema. Multiple services and methods can be combined in one query. Field selection is supported (only requested fields are returned). **Introspection queries (`__schema`, `__type`, `__typename`) are rejected** — use `describe_compose_schema` / `describe_compose_method` for schema discovery.

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `app_name` | String | Yes | — | App name |
| `query` | String | Yes | — | Standard GraphQL query string |

**Query shape (固定三层)**:
```graphql
query {
  <ServiceName> {              # Layer 1: service
    <methodName>(<args>) {     # Layer 2: method
      <DTO fields>             # Layer 3: 字段选择
    }
  }
}
```

**示例 query**:
```graphql
query {
  TaskService {
    get_tasks_by_sprint(sprint_id: 42) {
      id
      title
      owner {
        id
        name
      }
    }
  }
  UserService {
    list_users {
      id
      name
    }
  }
}
```

**Returns (success)**:
```json
{
  "data": {
    "TaskService": {
      "get_tasks_by_sprint": [
        { "id": 1, "title": "...", "owner": { "id": 7, "name": "Alice" } },
        { "id": 2, "title": "...", "owner": { "id": 7, "name": "Alice" } }
      ]
    },
    "UserService": {
      "list_users": [
        { "id": 7, "name": "Alice" },
        { "id": 8, "name": "Bob" }
      ]
    }
  }
}
```

**Returns (introspection rejected, FR-008)**:
```json
{
  "data": null,
  "errors": [
    {
      "message": "GraphQL introspection is not available via compose_query. Use describe_compose_schema(app_name=...) and describe_compose_method(app_name=..., service_name=..., method_name=...) to discover the schema."
    }
  ]
}
```

**Returns (partial failure, e.g. one method throws)**:
```json
{
  "data": null,
  "errors": [
    { "message": "TaskService.get_task raised ValueError: task not found" }
  ]
}
```

**Returns (parse error)**:
```json
{
  "data": null,
  "errors": [
    { "message": "Failed to parse query: Syntax Error GraphQL request: ..." }
  ]
}
```

**Execution contract (FR-004a)**:
- 多个 `@query` 方法并发执行（`asyncio.gather`）
- 多个 `@mutation` 方法**串行**执行（按 query 中出现顺序）
- 每个 service 方法的返回值**不**在外层再套 Resolver（service 方法内部已经显式 `Resolver().resolve()`）
- 字段投影：调用 `subset.build_subset_model(dto_cls, method_selection)` → `TypeAdapter(projected_anno).validate_python(result)`
- `FromContext` 参数从 `context_extractor(ctx)` 注入，**不**从 GraphQL 参数取

**Error cases**:
- `app_name` 不存在 → 仍走 `{data: null, errors: [...]}` 信封（GraphQL 风格），消息含 `APP_NOT_FOUND` 语义
- 查询字符串非法 → `{data: null, errors: [...]}`
- Service / method 不存在 → `{data: null, errors: [...]}`
- 方法内部异常 → `{data: null, errors: [...]}`，消息含 service.method 名 + 异常类型与消息

---

## 错误类型枚举（扩展 `MCPErrors`）

在既有 `src/nexusx/mcp/types/errors.py:MCPErrors` 基础上新增（如果尚不存在）：

| Value | 用于 |
|-------|------|
| `APP_NOT_FOUND` | Layer 1/2: `app_name` 不存在 |
| `SERVICE_NOT_FOUND` | Layer 2: `service_name` 不存在 |
| `METHOD_NOT_FOUND` | Layer 2: `method_name` 不存在 |
| `VALIDATION_ERROR` | Layer 3: 查询解析失败 / introspection 命中 |
| `INTERNAL_ERROR` | 兜底 |

Layer 3 不复用 `MCPErrors` 字段（因为响应信封是 `{data, errors}`，不带 `error_type`）；只在 errors 数组的 `extensions` 里可选填（保留扩展点）。
