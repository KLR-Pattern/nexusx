# Contract: ComposeSchema Builder API

**Feature**: `001-usecase-graphql-mcp` | **Date**: 2026-06-20

本文档定义 schema 构建器（internal API）的输入/输出契约。这是 `create_use_case_graphql_mcp_server` 与 `build_compose_schema` 内部使用的能力，**不**作为顶层公共 API 暴露（除非通过 `build_compose_schema` 包装）。

---

## B1. 模块组织

```
src/nexusx/use_case/
├── compose_schema.py        # 主入口：build_compose_schema(app_config) -> ComposeSchema
├── compose_type_mapper.py   # Python type -> TypeRef / TypeInfo
└── compose_executor.py      # Layer 3 执行：parse + plan + execute + project
```

---

## B2. `build_compose_schema`

```python
def build_compose_schema(app: UseCaseAppConfig) -> ComposeSchema:
    """从 UseCaseAppConfig 派生 ComposeSchema。

    步骤：
    1. 为每个 UseCaseService 构造 {Service}Query（和 {Service}Mutation 如果有 mutation 方法）
    2. 为每个方法提取参数（过滤 FromContext）与返回类型
    3. 递归注册所有可达 Pydantic DTO / enum / scalar
    4. 检查名字冲突（service、方法、DTO）
    5. 构造 root Query（和可选 Mutation）类型

    Raises:
        ComposeSchemaError 及子类
    """
```

---

## B3. 类型映射契约（compose_type_mapper）

### 标量

| Python | GraphQL name | 备注 |
|--------|--------------|------|
| `int` | `Int` | |
| `float` | `Float` | |
| `str` | `String` | |
| `bool` | `Boolean` | |
| `bytes` | — | **拒绝**，`UnsupportedTypeError` |
| `datetime.datetime` | `DateTime` | 自定义标量（在 introspection 中以 SCALAR 形式注册） |
| `datetime.date` | `Date` | 同上 |
| `datetime.time` | `Time` | 同上 |
| `uuid.UUID` | `ID` | |
| `decimal.Decimal` | — | **拒绝**，`UnsupportedTypeError`（v1） |

### 容器

| Python | TypeRef |
|--------|---------|
| `T`（非 Optional） | `NON_NULL(T)` |
| `Optional[T]` | `T` |
| `T \| None` | `T` |
| `list[T]` | `NON_NULL(LIST(NON_NULL(T)))` |
| `Optional[list[T]]` | `LIST(NON_NULL(T))` |
| `list[Optional[T]]` | `NON_NULL(LIST(T))`（v1 不推荐，但支持） |

### 复合

| Python | TypeInfo |
|--------|----------|
| Pydantic `BaseModel` 子类 | OBJECT，name = 类名 |
| `enum.Enum` 子类 | ENUM，name = 类名，values = 枚举成员名 |
| SQLModel 子类 | — | **拒绝**，`SQLModelInDtoFieldError`（违反既有 DTO 约定） |
| `dict[str, Any]` / `Any` / `typing.Any` | — | **拒绝**，`UnsupportedTypeError`（v1） |

---

## B4. 方法参数处理（FR-003）

对每个 `@query` / `@mutation` 方法：

1. 用 `inspect.signature(method.__func__)` 取签名
2. 跳过 `cls` 参数
3. 跳过任何 `Annotated[T, FromContext(...)]` 参数（`is_from_context_annotation` 检测）
4. 跳过 `*args`, `**kwargs`（v1 不支持；触发了就 `UnsupportedTypeError`）
5. 剩余参数转 `ArgumentInfo`：
   - `name`：参数名
   - `type_ref`：参数类型映射（无 Optional 包装则 NON_NULL）
   - `has_default`：`param.default is not Parameter.empty`
   - `default_value`：原始 Python 值
   - `description`：从 `Annotated[T, Field(description="...")]` 提取（如有）

---

## B5. 返回类型处理（FR-004）

对每个方法的 `return_annotation`：

- 缺失 → `MissingReturnAnnotationError`
- `None` / `type(None)` → `MissingReturnAnnotationError`（视为缺失）
- 否则：走 compose_type_mapper → 注册可达类型到 registry

---

## B6. 名字冲突检测

### Service 名冲突

跨 app 内 service 名必须唯一（同 app 内）：
- 检测时机：构造 root Query 之前
- 冲突时：`DuplicateServiceError(f"Service name '{name}' appears twice in app '{app_name}'")`

### 方法名冲突

同 service 内方法名（含跨继承的方法）必须唯一：
- 冲突时：`DuplicateMethodError(...)`

### DTO / enum 名冲突

DTO/enum 类名在整个 registry 中必须唯一（同一 DTO 类被多个 service 引用应只注册一次；不同 DTO 类同名 = 冲突）：
- 用 `id(python_class)` 去重（同一类多次引用 → 复用既有 TypeInfo）
- 不同类同名 → `DuplicateTypeError(...)`

---

## B7. SDL 渲染规则

### 完整 SDL（`render_sdl()`）

顺序：
1. 自定义标量（`scalar DateTime`、`scalar Date`、`scalar Time`）
2. ENUM 类型（按 registry 字母序）
3. OBJECT 类型：DTO（按 registry 字母序）→ service query/mutation types → root Query → root Mutation

示例片段：
```graphql
scalar DateTime

enum TaskStatus {
  PENDING
  IN_PROGRESS
  DONE
}

type TaskSummary {
  id: Int!
  title: String!
  status: TaskStatus!
  owner: UserSummary
  due: DateTime
}

type UserSummary {
  id: Int!
  name: String!
}

type TaskServiceQuery {
  list_tasks: [TaskSummary!]!
  get_task(task_id: Int!): TaskSummary
}

type UserServiceQuery {
  list_users: [UserSummary!]!
}

type Query {
  TaskService: TaskServiceQuery!
  UserService: UserServiceQuery!
}
```

### 方法 SDL 片段（`render_method_sdl(service, method)`）

只包含：
1. 该方法所在的 `{Service}Query`（或 `{Service}Mutation`）类型，且只含该方法（不含同 service 的其它方法）
2. 返回类型 + 所有可达 DTO/enum/scalar 的传递闭包

用途：Layer 2 工具返回；让 agent 拿到一段"刚好够理解这个方法"的 SDL，不需要全 schema。

---

## B8. Introspection JSON 渲染

`render_introspection()` 返回的 dict 结构与 graphql introspection query 的 `__schema` 字段一致：

```json
{
  "queryType": { "name": "Query" },
  "mutationType": { "name": "Mutation" },  // 若无 mutation 方法则为 null
  "subscriptionType": null,
  "types": [
    { "kind": "OBJECT", "name": "Query", "description": "...", "fields": [...] },
    { "kind": "OBJECT", "name": "TaskSummary", "fields": [...] },
    ...
  ],
  "directives": []
}
```

**关键不变量**：
- 此 JSON 可被 `graphql.build_schema(...)` 反向构造为 `GraphQLSchema`（保证 GraphiQL 兼容）
- `SC-002` 测试会用此不变量做断言

---

## B9. 执行器契约（compose_executor.py）

```python
async def execute_compose_query(
    app: UseCaseResources,
    query: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """执行 GraphQL compose query，返回 {data, errors}。

    步骤（与 R5 对齐）：
    1. graphql.parse(query) -> DocumentNode
    2. introspection 检测 -> 命中即返回 {data: null, errors: [...]}
    3. QueryParser.parse_document(document) -> {op_name: FieldSelection}
    4. 对每个根 selection（service 名）：
       a. 从 app.services 找 service class
       b. 对 service 下每个方法 selection：
          i.   从 method.__use_case_methods__ 找方法
          ii.  从 selection.arguments 提取 GraphQL 参数；从 context 提取 FromContext 参数
          iii. await method(...)
          iv.  用 subset.build_subset_model + TypeAdapter 投影
    5. 聚合到 {data: {<service>: {<method>: <projected>}}}
    6. 任一步异常 -> errors 数组
    """
```

**并发**:
- 同一 query 内的 `@query` 方法用 `asyncio.gather` 并发
- `@mutation` 方法串行（按 query 出现顺序）

**异常映射**:
- `KeyError`(service not found) → `{data: null, errors: [{message: "Service 'X' not found"}]}`
- `KeyError`(method not found) → 同上
- 业务异常 → `{data: null, errors: [{message: "<Service>.<method> raised <ExcType>: <msg>"}]}`
- 解析异常 → `{data: null, errors: [{message: "Failed to parse query: <detail>"}]}`

---

## B10. 内部 vs 公共边界

| 内部 API（不导出） | 公共 API |
|-------------------|----------|
| `build_compose_schema(app_config)` | 同名（既被内部用，也被公共用） |
| `TypeInfo` / `FieldInfo` / `TypeRef` / `ArgumentInfo` | 不导出（实现细节） |
| `ComposeSchemaBuilder`（如有类抽象） | 不导出 |
| `execute_compose_query` | 不导出（只被 `compose_query` MCP tool 调用） |
| `is_introspection_query` | 不导出 |
| `is_from_context_annotation` | 不导出（既有 use_case/server.py 实现可迁移过来） |

`TypeInfo` 等数据类虽然不导出，但类型签名会出现在 `ComposeSchema.registry: dict[str, TypeInfo]` 上。为了让 `mypy --strict` 通过，需要在 `nexusx.use_case` 命名空间内可见；通过 `from nexusx.use_case.compose_schema import ComposeSchema` 时，TypeInfo 等作为类型提示出现即可，不需要专门 re-export。
