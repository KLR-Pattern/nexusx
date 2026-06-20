# Research: UseCase Service → GraphQL → MCP

**Feature**: `001-usecase-graphql-mcp` | **Date**: 2026-06-20

调研目标：解决 spec/plan 中每个"新建 vs 复用"选择，固化 schema 表示、执行链、移除范围、版本号策略。

---

## R1. Schema 表示：自定义 TypeInfo registry vs graphql-core GraphQLSchema

### Decision
采用**自定义 `TypeInfo` registry**（`dict[str, TypeInfo]`），与 pydantic-resolve 一致；**不**直接构建 graphql-core `GraphQLSchema` 对象。registry 同时支持渲染为：
- 标准 introspection JSON（喂给 GraphiQL）
- SDL 字符串（人类阅读、Layer 2 工具返回）
- 单方法 SDL 片段（Layer 3 `describe_compose_method` 返回）

### Rationale
- 直接构建 `GraphQLSchema` 需要写完整的 graphql-core `ObjectType`/`Field`/`Argument` 节点，工作量大且执行时仍要回退到自定义 executor（graphql-core 默认 executor 无法直接调用 nexusx 的 service 方法）。
- TypeInfo registry 与 graphql introspection `__schema` 结构同构，渲染成本极低；执行端只需自己解析 GraphQL 字符串 → 找到对应 service 方法 → 调用 → 投影。
- pydantic-resolve 已验证此路径可行，且测试套件覆盖 GraphiQL 兼容性（`test_canonical_graphiql_introspection_query_works`）。

### Alternatives considered
- **A. 直接 graphql-core `GraphQLSchema`**：被否决。优点是免费获得 graphql-core 的执行器；缺点是 graphql-core 执行器调用 resolver 函数时无法干净注入 `FromContext` 与 `context_extractor`，且会让 GraphQL schema 与 service 方法的耦合方式接近 `GraphQLHandler`（强耦合 SQLModel 那条路）。
- **B. 完全跳过 schema，直接用 service 方法签名做 introspection**：被否决。无法通过 graphql-core 的 `build_schema`/`validate_schema` 校验（违反 SC-002），也无法喂给 GraphiQL。

---

## R2. 类型映射：复用 `type_converter.py` vs 新建 `compose_type_mapper.py`

### Decision
**新建 `compose_type_mapper.py`**（fork），只处理 Pydantic BaseModel + Python 标量 + enum + `list[T]`/`Optional[T]`/`T | None` 容器；**不**处理 SQLModel 实体、SQLAlchemy `Mapped`/`relationship`。命名规则（`Int`、`[T!]!`、`Boolean` 等）与既有 `type_converter.py` 保持一致以减少学习成本。

### Rationale
- `type_converter.py` 现有方法 `is_mapped_wrapper()`、`is_relationship()` 直接依赖 SQLAlchemy 内省，无法在 UseCase（纯 Pydantic）路径上安全复用。
- 即便"挑选性复用"（只 import 部分函数），也会把 SQLAlchemy import 拖进 UseCase 执行链，违反"两种模式正交"原则。
- 新写的 type mapper 约 100–150 行，可控；同时保留与既有命名规则一致，让用户跨模式切换时无认知摩擦。

### Alternatives considered
- **A. 复用 `type_converter.py`**：被否决（见 Rationale）。
- **B. 把 `type_converter.py` 拆成 `scalar_converter.py` + `sqlmodel_converter.py`**：被否决。重构既有稳定模块超出本特性范围，应作为独立重构 PR。

### 命名规则（与 `type_converter.py` 对齐）

| Python | GraphQL |
|--------|---------|
| `int` | `Int` |
| `float` | `Float` |
| `str` | `String` |
| `bool` | `Boolean` |
| `bytes` | (拒绝，schema 生成期报错) |
| `datetime.datetime` | `DateTime` |
| `datetime.date` | `Date` |
| `datetime.time` | `Time` |
| `uuid.UUID` | `ID` |
| `enum.Enum` 子类 | `<EnumName>`，值为枚举名 |
| `list[T]` | `[T!]!` |
| `Optional[T]` / `T \| None` | `T`（nullable） |
| `T`（非 Optional） | `T!`（non-null） |
| Pydantic `BaseModel` 子类 | `<ModelName>` OBJECT |
| 其它 | schema 生成期报错（清晰消息） |

---

## R3. 字段投影：复用 `query_parser.FieldSelection` + `subset.build_subset_model()`

### Decision
- **解析**：复用 `query_parser.QueryParser.parse_document(document)` 拿到 `dict[str, FieldSelection]` 树。
- **投影**：复用 `subset.build_subset_model(dto_cls, selection)` 构造子集 Pydantic 模型；执行后用 `pydantic.TypeAdapter` 验证结果。
- 这条路径与 pydantic-resolve 完全一致（`compose.py:400-405`）。

### Rationale
- `query_parser.py` 已经 graphql-core AST-aware，与 GraphQL 字符串解析天然兼容。
- `subset.py` 已有 `build_subset_model`，用于 Core API 模式的字段选择；直接复用避免造重复轮子。
- 投影后用 TypeAdapter 验证 → 自动屏蔽未请求字段 + 类型校验。

### Alternatives considered
- **A. 自己写投影逻辑（手动遍历 FieldSelection + setattr）**：被否决。重复实现且容易漏处理 Optional/list 嵌套。

---

## R4. 多应用路由：复用 `UseCaseManager`

### Decision
- 保留 `UseCaseManager` 类与 `UseCaseResources` dataclass 的核心字段（`name`、`description`、`services`、`context_extractor`、`enable_mutation`）。
- 删除 `UseCaseResources.introspector` 字段（被新的 `ComposeSchema` 取代）。
- 案例不敏感的 `get_app(name)` 查找、`context_extractor` 异步 plumage 全部保留。
- `UseCaseManager` 在新模块中实例化，由 `create_use_case_graphql_mcp_server` 内部使用，**不**作为公共 API 变化。

### Rationale
- `UseCaseManager` 的多应用路由逻辑（dict + case-insensitive lookup）与 MCP 多应用范式天然契合；重新写就是重复劳动。
- `context_extractor` 的 awaitable 处理逻辑在老 server.py 中已经稳定，直接迁移。

### Alternatives considered
- **A. 引入类似 `mcp/managers/multi_app_manager.py:MultiAppManager` 的并行类**：被否决。两个 manager 解决同一问题，无价值。
- **B. 把多应用能力下沉到新的 `ComposeAppManager`**：被否决。会让 `UseCaseManager` 变成"半废弃"，违反"不引入被废弃代码"原则。

---

## R5. 执行链：service 方法 → 投影；**不**外包 Resolver

### Decision
Layer 3 `compose_query` 执行步骤：

1. `graphql.parse(query)` → `DocumentNode`
2. introspection 检测（见 R6）→ 命中则报错
3. `QueryParser.parse_document(document)` → `dict[op_name, FieldSelection]`
4. 对每个根字段（service 名）：找 service 类 → 找方法 → 解析方法参数（从 GraphQL 字段参数）→ 调用 service 方法
5. service 方法返回 DTO（**service 方法内部已 `Resolver().resolve(dtos)`**，外层不再套）
6. 对每个方法返回值，用 `subset.build_subset_model` + `TypeAdapter` 做字段投影
7. 拼装 `{service: {method: projected_result}}` → 作为 GraphQL `data` 返回
8. 任一步异常 → 进入 `errors` 数组

### Rationale
- FR-004a 明确禁止外层 Resolver；service 方法已经在内部决定 Resolver 调用时机与方式。
- 并发：多个 `@query` 方法可用 `asyncio.gather` 并行；`@mutation` 方法串行（与 pydantic-resolve 一致）。

### Alternatives considered
- **A. GraphQL 执行后自动套 Resolver**：被否决（违反 FR-004a，且会重复处理 DTO 上的 `resolve_*`）。
- **B. 让 graphql-core 执行器调度**：被否决（graphql-core 执行器无法注入 FromContext）。

---

## R6. Introspection 拒绝机制

### Decision
- 在 Layer 3 入口（`compose_query` 函数体最前面），对 `query` 字符串做 AST 级检测：
  ```python
  def is_introspection_query(query: str) -> bool:
      document = parse(query)
      for node in document.selections:  # 简化伪代码
          if _selection_uses_introspection(node):
              return True
      return False
  ```
- 检测目标：任何字段名以 `__` 开头（即 `__schema`、`__type`，含嵌套）。
- 命中即返回：
  ```python
  {
      "data": None,
      "errors": [{
          "message": "GraphQL introspection is not available via compose_query. "
                     "Use list_services / describe_compose_method to discover schema.",
      }]
  }
  ```

### Rationale
- AST 级检测比字符串 substring 检测更稳健（不会误命中注释或字符串字面量）。
- 拒绝信息明确指引到 Layer 1/2（FR-008）。

### Alternatives considered
- **A. 执行后过滤掉 introspection 字段**：被否决。会让 introspection 隐形失败，agent 困惑。
- **B. 字符串 substring 匹配 `__schema`**：被否决。脆弱。

---

## R7. 老 MCP 移除范围（FR-010 / FR-010a 边界）

### Decision
**硬移除**（导入失败，不留 shim）：

| 文件 | 处置 | 原因 |
|------|------|------|
| `src/nexusx/use_case/server.py` | **DELETE** | 老 4 层 MCP（直接方法调用范式），被新 GraphQL MCP 完全替代 |
| `src/nexusx/use_case/flat_server.py` | **DELETE** | 老扁平 MCP（一方法一 tool），同上 |
| `src/nexusx/use_case/introspector.py` | **DELETE** | 仅生成 SDL 风格字符串供老 MCP 使用；被 `compose_schema.py` 取代 |
| `src/nexusx/use_case/manager.py` | **TRIM** | 保留 `UseCaseManager` + `UseCaseResources` 核心；删除 `introspector` 字段、删除只服务于老 MCP 的辅助方法 |
| `src/nexusx/use_case/__init__.py` | **MODIFY** | 移除 `create_use_case_mcp_server`、`create_use_case_flat_server` 导出；新增 `create_use_case_graphql_mcp_server`、`build_compose_schema` 导出 |
| `src/nexusx/__init__.py` | **MODIFY** | 同步更新 re-exports |

**保留不动**（FR-010a）：

| 文件 | 处置 | 原因 |
|------|------|------|
| `src/nexusx/use_case/router.py` | UNCHANGED | FastAPI REST 路由，与 GraphQL/MCP 正交 |
| `src/nexusx/use_case/jsonrpc.py` | UNCHANGED | JSON-RPC over HTTP，与 MCP 正交 |
| `src/nexusx/voyager/create_voyager.py` 中的 `create_use_case_voyager` | UNCHANGED | Voyager 可视化，与 GraphQL/MCP 正交 |
| `src/nexusx/use_case/business.py` | UNCHANGED | `UseCaseService` 基类，新模块复用 |
| `src/nexusx/use_case/context.py` | UNCHANGED | `FromContext` 标注，新模块复用 |
| `src/nexusx/use_case/types.py` | UNCHANGED | `UseCaseAppConfig`，新模块复用 |

### 移除验证测试
`tests/use_case/test_old_api_removed.py` 断言以下导入都失败（`ImportError`）：
- `from nexusx import create_use_case_mcp_server`
- `from nexusx import create_use_case_flat_server`
- `from nexusx.use_case import create_use_case_mcp_server`
- `from nexusx.use_case import create_use_case_flat_server`
- `from nexusx.use_case.server import create_use_case_mcp_server`
- `from nexusx.use_case.flat_server import create_use_case_flat_server`

---

## R8. 版本号策略

### Decision
**1.0.0 → 2.0.0**（major bump）。`pyproject.toml` 的 `version` 字段更新为 `2.0.0`。

### Rationale
- 严格 semver：移除公共 API = breaking change = major bump。
- 1.x 的版本号空间留给"在 1.0 API 表面基础上的增强"；2.0 信号是"老 MCP 入口已不再可用，需要迁移"。

### Alternatives considered
- **A. 1.1.0（minor bump）**：被否决。违反 semver，会让依赖 `nexusx>=1.0,<2` 的下游项目静默炸掉。
- **B. 立即跳到 2.0.0 + 长期废弃 1.x 分支**：被否决。本特性没有意愿维护废弃分支；硬移除即"读迁移文档，一步到位"。

### 配套
- `CHANGELOG.md`（如不存在则新建）的 `2.0.0` 段落写明 BREAKING：列出 2 个被移除的入口 + 替代入口 + 迁移文档链接。
- `docs/migrations/2.0-use-case-graphql.md` 给出逐个老入口的迁移步骤（含 before/after 代码示例）。

---

## R9. 命名约定

为减少与 pydantic-resolve 的认知摩擦，新公共 API 命名尽量与 pydantic-resolve 对齐：

| nexusx 新 API | pydantic-resolve 对应 | 备注 |
|---------------|----------------------|------|
| `create_use_case_graphql_mcp_server(apps, name)` | `create_use_case_graphql_mcp_server(apps, name)` | 完全同名 |
| `build_compose_schema(app_config)` → `ComposeSchema` | `build_compose_schema(app)` → `dict[str, TypeInfo]` | nexusx 包装成 `ComposeSchema` 类（携带 registry + introspection + sdl 三种渲染方法） |
| MCP Layer 0: `list_apps` | `list_apps` | 同名 |
| MCP Layer 1: `describe_compose_schema` | `describe_compose_schema` | 同名 |
| MCP Layer 2: `describe_compose_method` | `describe_compose_method` | 同名 |
| MCP Layer 3: `compose_query` | `compose_query` | 同名 |

---

## R10. 测试套件覆盖（与 SC-002 对齐）

| 测试文件 | 覆盖场景 |
|---------|---------|
| `tests/use_case/test_compose_schema.py` | (a) 标量/容器/嵌套 DTO 类型映射；(b) `FromContext` 参数被过滤；(c) 同一 DTO 多 service 引用只注册一次；(d) `@query` + `@mutation` 同时存在；(e) 同名 service / 同名方法报错；(f) 无返回注解的方法报错；(g) DTO 字段引用 SQLModel 实体报错；(h) 生成的 introspection JSON 能通过 graphql-core `build_schema` 校验 |
| `tests/use_case/test_compose_executor.py` | (a) 单 service 单方法执行；(b) 多 service 并发执行；(c) 字段投影（只返回请求字段）；(d) 嵌套 DTO 投影；(e) `FromContext` 注入；(f) 方法抛业务异常 → `errors` 数组；(g) 非法 GraphQL 字符串 → 解析错误 |
| `tests/use_case/test_compose_mcp_server.py` | 4 层工具 happy path：(a) `list_apps` 返回多应用；(b) `describe_compose_schema` 返回紧凑列表；(c) `describe_compose_method` 返回参数表+SDL；(d) `compose_query` 返回 `{data, errors}`；(e) Layer 0–2 响应 shape 是 `{success, data}`；(f) Layer 3 响应 shape 是 `{data, errors}` |
| `tests/use_case/test_introspection_rejected.py` | (a) `__schema` 查询被拒绝；(b) `__type(name:...)` 查询被拒绝；(c) 嵌套字段含 `__typename` 被拒绝；(d) 错误消息明确指引到 Layer 1/2 |
| `tests/use_case/test_old_api_removed.py` | (a) 6 个被移除的导入路径都抛 `ImportError`；(b) 错误消息包含指向 `create_use_case_graphql_mcp_server` 的提示 |

---

## R11. 残余开放项（Deferred to tasks.md / implementation）

以下不阻塞 plan 通过，留给 tasks.md 处理：

- **Pydantic 模型作为方法参数（GraphQL input type）**：v1 只支持标量/标量列表/枚举参数；Pydantic input 类型作为 v1.1 跟进。`compose_type_mapper.py` 留 hook 点。
- **Schema 生成时机**：默认 eager（`create_use_case_graphql_mcp_server` 调用时为每个 app 一次性生成），lazy 留待性能问题出现再优化。
- **方法参数默认值的 GraphQL 序列化**：JSON 标量直接 `json.dumps`，datetime/UUID 等转字符串（与 graphql-core 行为一致）。
- **迁移指南文档放置**：放 `docs/migrations/2.0-use-case-graphql.md`（与 `docs/` 既有结构对齐）。
