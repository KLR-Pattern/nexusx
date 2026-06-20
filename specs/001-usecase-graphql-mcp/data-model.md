# Data Model: UseCase Service → GraphQL → MCP

**Feature**: `001-usecase-graphql-mcp` | **Date**: 2026-06-20

本文档定义新特性的核心数据结构与状态。Python 类名仅作设计交流；最终命名以 `contracts/` 与 `tasks.md` 为准。

---

## D1. TypeInfo（GraphQL 类型描述）

**Purpose**：自定义 GraphQL 类型描述对象，与 graphql introspection `__Type` 同构。是 `ComposeSchema` registry 的值类型。

```
TypeInfo:
    name: str                       # GraphQL 类型名（如 "TaskSummary"、"Query"、"SprintServiceQuery"）
    kind: Literal["OBJECT", "ENUM", "INPUT_OBJECT", "SCALAR"]
    description: str | None         # 来自类 docstring 或字段 description
    python_class: type | None       # 对应 Python 类（Pydantic 模型 / enum / 标量类型）
    fields: dict[str, FieldInfo]    # OBJECT 才有
    enum_values: list[str]          # ENUM 才有（枚举名列表）
    input_fields: dict[str, FieldInfo]  # INPUT_OBJECT 才有（v1 暂不生成）
```

**Validation rules**:
- `name` 必须符合 GraphQL Name 正则 `^[_A-Za-z][_0-9A-Za-z]*$`
- 同一 registry 中 `name` 必须唯一（重复注册 = bug）
- OBJECT 至少有 1 个 field（root `Query` 至少有 1 个 service field）
- ENUM 至少有 1 个 value

---

## D2. FieldInfo（字段描述）

```
FieldInfo:
    name: str                       # 字段名
    description: str | None
    type_ref: TypeRef               # 字段类型（含 nullability 与 list 包装）
    args: dict[str, ArgumentInfo]   # 字段参数（方法参数；可为空）
    deprecation_reason: str | None  # 暂不支持，预留
```

---

## D3. TypeRef（类型引用）

```
TypeRef:
    name: str                       # 终端类型名（如 "TaskSummary"）
    kind: Literal["OBJECT", "ENUM", "INPUT_OBJECT", "SCALAR"]
    of_type: TypeRef | None         # 内层类型（用于 NON_NULL / LIST 包装）
    # 包装由外层 TypeRef 的 kind 表达：
    #   NON_NULL.of_type = inner
    #   LIST.of_type = inner
```

**生成规则**（与 R2 命名表对齐）：
- `T`（非 Optional）→ `NON_NULL(T)`
- `Optional[T]` / `T | None` → `T`
- `list[T]` → `NON_NULL(LIST(NON_NULL(T)))`
- 标量直接映射到 `Int`/`Float`/`String`/`Boolean`/`ID`/`DateTime`/`Date`/`Time`

---

## D4. ArgumentInfo（方法参数描述）

```
ArgumentInfo:
    name: str
    description: str | None
    type_ref: TypeRef               # 参数类型（同样含包装）
    has_default: bool
    default_value: Any | None       # 原始 Python 值；序列化到 introspection 时按类型转 GraphQL 字面量
    is_from_context: bool = False   # True 时**不**作为 GraphQL 参数暴露（FR-003）
```

**关键不变量**：`is_from_context=True` 的参数在 `ComposeSchema` 生成的 introspection/SDL 中**完全不出现**。

---

## D5. ComposeSchema（生成的 schema 产物）

**Purpose**：从一组 `UseCaseService` 派生出的 GraphQL schema 产物。承载三种渲染能力。

```
ComposeSchema:
    registry: dict[str, TypeInfo]   # 所有可达类型，含 Query / Mutation / 各 service 类型 / DTO / enum / scalar
    app_name: str

    methods:
        render_introspection() -> dict[str, Any]
            # 返回 __schema payload（与 graphql introspection query 返回结构一致），
            # 可直接喂给 graphql-core 的 GraphQLSchema via build_schema()
            # 或 GraphiQL。

        render_sdl() -> str
            # 完整 SDL 字符串（含 type Query / Mutation / 各 service / DTO / enum / scalar）

        render_method_sdl(service_name: str, method_name: str) -> str | None
            # 单方法 SDL 片段：方法签名 + 返回类型的传递闭包
            # 用于 Layer 2 (describe_compose_method) 工具返回
```

**生命周期**：
- 在 `create_use_case_graphql_mcp_server` 调用时为每个 `UseCaseAppConfig` eager 构造一次。
- 构造失败（同名 service、同名方法、不支持的类型、SQLModel 引用等）立即抛出，启动期就能看到错误。
- 一旦构造完成，运行期只读、不可变。

---

## D6. UseCaseAppConfig（既有，**不变**）

**Status**: UNCHANGED（FR-009）

```
UseCaseAppConfig(BaseModel):
    name: str
    services: list[type[UseCaseService]]
    description: str | None = None
    enable_mutation: bool = True
    context_extractor: Callable[[Any], dict | Awaitable[dict]] | None = None
```

新模块直接消费此既有类型，**不**新增字段。

---

## D7. UseCaseResources（既有，**裁剪**）

**Status**: TRIMMED

```
UseCaseResources（裁剪后）:
    name: str
    description: str
    services: dict[str, type[UseCaseService]]
    context_extractor: Callable | None
    enable_mutation: bool
    compose_schema: ComposeSchema   # 新增字段（替代被删的 introspector）
```

被移除字段：`introspector: ServiceIntrospector`（其能力被 `ComposeSchema` 取代）。

---

## D8. UseCaseManager（既有，**保留核心**）

**Status**: KEPT

```
UseCaseManager:
    apps: dict[str, UseCaseResources]
    
    methods:
        get_app(name: str) -> UseCaseResources
            # 案例不敏感查找；找不到抛 KeyError 或返回 None（按既有行为）
```

新 `compose_mcp_server.py` 内部实例化此 manager，不暴露为公共 API。

---

## D9. MCP 工具响应信封（既有，**复用**）

### Layer 0–2（meta 工具）

成功（既有 `mcp/types/errors.py:create_success_response`）：
```json
{ "success": true, "data": <payload> }
```

失败（既有 `mcp/types/errors.py:create_error_response`）：
```json
{ "success": false, "error": "<message>", "error_type": "<MCPErrors value>" }
```

### Layer 3（GraphQL 执行）

成功（GraphQL 标准）：
```json
{ "data": { "<service>": { "<method>": <result> } } }
```

部分失败：
```json
{
  "data": null,
  "errors": [
    { "message": "<error message>" }
  ]
}
```

introspection 拒绝（FR-008）：
```json
{
  "data": null,
  "errors": [
    {
      "message": "GraphQL introspection is not available via compose_query. Use list_services / describe_compose_method to discover schema."
    }
  ]
}
```

---

## D10. 状态转换：无（library 特性）

本特性不引入运行期持久化状态。所有"状态"（schema registry）在启动期一次性构造后不可变。

唯一的动态行为是 MCP 工具调用时的瞬时上下文：
1. MCP request 到达 → 调用对应工具函数
2. 函数读 `UseCaseManager.apps[app_name]` 拿到 `UseCaseResources`
3. 执行业务（直接返回 meta 信息，或调 service 方法 + 投影）
4. 返回响应信封
5. 无状态保留

---

## D11. 实体关系图

```
UseCaseAppConfig ──contains──> list[UseCaseService]
                                      │
                                      │ (BusinessMeta 元类收集 @query/@mutation)
                                      ▼
                              __use_case_methods__ dict
                                      │
                                      ▼
                          ┌──────────────────────┐
                          │  ComposeSchemaBuilder │
                          └──────────────────────┘
                                      │
                          (消费 UseCaseService + compose_type_mapper)
                                      │
                                      ▼
                                 ComposeSchema
                          ┌──────────────────────┐
                          │ registry: dict       │
                          │  "Query" → TypeInfo  │
                          │  "Mutation" → TypeInfo (可选)
                          │  "<Svc>Query" → ...  │
                          │  "<DTO>" → ...       │
                          │  "<Enum>" → ...      │
                          └──────────────────────┘
                                      │
                          (被 UseCaseResources 持有)
                                      │
                                      ▼
                              UseCaseResources
                                      │
                          (被 UseCaseManager.apps 持有)
                                      │
                                      ▼
                                FastMCP server
                          (4 个 @mcp.tool 注册)
                                      │
                          ┌───────────┴───────────┐
                          ▼                       ▼
                  Layer 0–2 tools            Layer 3 tool
                  (meta 信息，                (GraphQL 执行，
                   {success, data})           {data, errors})
```
