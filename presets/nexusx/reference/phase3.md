<!-- 同步自 skill/phases/phase3.md；如需更新请同步源文件并在 commit message 中说明 -->

# Phase 3: UseCase 响应组装 + MCP

**目标**: 按 API 用例组装响应结构。DefineSubset 隐藏内部字段，UseCaseService 统一业务入口。

**新增/修改文件**:
- `service/<entity>/spec.md` — 服务目的、用途、需求、变更记录
- `service/<entity>/dtos.py` — DefineSubset DTOs
- `service/<entity>/service.py` — UseCaseService
- `main.py` — 用 `create_use_case_router()` 挂载 REST + MCP + Voyager 补充 services

**关键模式**:
- `DefineSubset` + `SubsetConfig` 定义响应 DTO（字段选择、FK 隐藏）
- **3.2+ `DefineSubset.__subset__` 源可以是任意 `pydantic.BaseModel`**（不限于 SQLModel）—— 如果 Phase 0 Step 0-3 选了虚拟实体根（`CurrentUser`、`Page[T]`、第三方 SDK DTO 等），用同一语法从 BaseModel 源字段中选子集。SQLModel 源走 ORM 自动投递（`_orm_to_dto`），BaseModel 源由用户直接构造 DTO 实例，框架不参与数据获取（详见 `docs/guide/virtual_entities.md`）
- `AutoLoad` 标记 DTO 关系字段为自动加载（配合 Resolver implicit auto-load 使用，显式声明自动加载意图）
- **跨层数据流（3.x 新增）**：当 DTO 字段需要从请求上下文（用户身份、trace ID）、父层传值、子层收集结果中拿数据，而非从 ORM 实体——用 `nexusx` 的三个 helper（详见 `docs/api/api_cross_layer.md`）：
  - `ExposeAs(field_name, source=...)` — 从 `FromContext` 暴露的字段取值
  - `SendTo(field_name)` — 父层向子层下发值
  - `Collector(field_name)` — 子层结果聚合回父层
- `ErManager` + `Resolver` 自动加载关系（implicit auto-load）
- `UseCaseService` 统一业务逻辑入口（同时服务 MCP、REST、GraphQL、CLI、JSON-RPC）
- `@query` / `@mutation` 装饰器标记服务方法
- **UseCaseService 方法必须声明返回类型注解**（如 `-> list[ChatSummary]`、`-> ChatSummary | None`），3.0 起 compose schema 生成器强校验，缺注解直接 `MissingReturnAnnotationError` 启动期报错
- **UseCaseService 复用 `service/<domain>/methods.py` 中的核心逻辑，不重新实现**：
  - **query 方法（list）**：调用 methods.py 拿 `list[Model]` → `[DtoType.model_validate(m) for m in models]` → `Resolver().resolve(dtos)`
  - **query 方法（get 单条）**：调用 methods.py 拿 `Model | None` → `DtoType.model_validate(entity)` → `Resolver().resolve(dto)`
  - **mutation 方法**：同 get 单条模式，调用 methods.py 获取 Model 后转换
  - **service.py 不直接操作数据库**（无 `async_session`）。如需直接查询构建 DTO，使用 `build_dto_select(entity, dto_type)` 生成 SQL SELECT 并通过 `dict(row._mapping)` 构造 DTO
- **`build_dto_select(Entity, DtoType)` 查询构建** — 根据 DTO 的 `__subset__` 字段自动生成 SQL SELECT 语句，只查询 DTO 需要的列，避免 `SELECT *`
- **`create_use_case_router()` 自动生成 REST 路由** — 从 UseCaseAppConfig 生成 POST 路由，自动提取 `response_model`、构建 request body model、注册路由。不需要手写 `router/` 目录
  ```python
  from nexusx import UseCaseAppConfig, create_use_case_router
  use_case_router = create_use_case_router(
      UseCaseAppConfig(
          name="project",
          services=[WorkspaceService, AgentService, ChatService],
      ),
  )
  app.include_router(use_case_router)
  ```
- **`create_jsonrpc_router()` JSON-RPC 2.0 路由** — 替代 REST 路由的方案，方法命名为 `ServiceName.method_name`。适用于需要轻量 RPC 协议的场景
  ```python
  from nexusx import create_jsonrpc_router
  app.include_router(create_jsonrpc_router(use_case_config))
  ```
- **`create_use_case_cli()` 生成 Typer CLI** — 将 UseCaseService 方法暴露为 CLI 命令，每个 service 成为一个命令组，每个方法成为子命令
  ```python
  from nexusx import create_use_case_cli
  cli = create_use_case_cli(use_case_config)
  cli()  # python -m myapp user-service list-users
  ```
- `create_use_case_voyager()` 可视化服务结构
- **`create_use_case_graphql_mcp_server()` (3.0+) — UseCase GraphQL MCP**：4 层渐进披露，Layer 3 (`compose_query`) 接收标准 GraphQL 查询字符串：
  - Layer 0: `list_apps` — 应用发现
  - Layer 1: `describe_compose_schema(app_name)` — service+方法紧凑列表
  - Layer 2: `describe_compose_method(app_name, service_name, method_name)` — 参数表 + 返回类型 + SDL 片段
  - Layer 3: `compose_query(app_name, query)` — GraphQL 字符串执行，返回 `{data, errors}`；**拒绝内省查询**（`__schema`/`__type`/`__typename`），引导用 Layer 1/2
  ```python
  from nexusx import create_use_case_graphql_mcp_server, UseCaseAppConfig
  mcp = create_use_case_graphql_mcp_server(apps=[app_config], name="API")
  ```
- **可选：GraphQL HTTP endpoint（GraphiQL 友好）** — 当需要直接对外暴露 GraphQL（浏览器/curl/Apollo 客户端，非 MCP 协议）时，用 `build_compose_schema` + `compose_introspect` + `execute_compose_query` 自建一个 FastAPI `/graphql` 路由。`compose_introspect` 处理 `__schema` 等 GraphiQL 启动查询，`execute_compose_query` 处理数据查询。注意 import 路径——这三个函数中只有 `build_compose_schema` 和 `compose_introspect` 在顶层 `nexusx` 导出，`execute_compose_query` 和 `is_introspection_query` 需要从子模块拿：

  ```python
  from nexusx import UseCaseAppConfig, build_compose_schema
  from nexusx.graphiql import GRAPHIQL_HTML
  from nexusx.use_case.compose_executor import (
      compose_introspect,
      execute_compose_query,
      is_introspection_query,
  )
  ```

  GraphiQL 启动页 HTML 直接用 `nexusx.graphiql.GRAPHIQL_HTML`（不必自己手写）。参考 `demo/use_case/graphql_server.py`
- MCP http_app 必须使用 `transport="streamable-http", stateless_http=True`
- MCP http_app 的 lifespan 必须在 FastAPI lifespan 中通过 `async with mcp_http.lifespan(mcp_http)` 嵌套启动
- MCP http_app 对象必须在 lifespan 函数定义之前创建，以便引用
- **3.0 起 UseCase 出口形态**（由用户在 Phase 3 决定取舍，按需启用）：
  | 出口 | 入口 | 适用场景 |
  |------|------|---------|
  | MCP（AI agent） | `create_use_case_graphql_mcp_server` | Claude Desktop / Cursor 等 MCP client；4 层渐进披露控制 token |
  | GraphQL HTTP | 自建 `/graphql` + `compose_introspect` | 标准 GraphQL 生态（GraphiQL、Apollo、curl）；需要 schema 内省 |
  | REST | `create_use_case_router` | OpenAPI 友好的传统 HTTP 客户端；自动生成文档 |
  | JSON-RPC | `create_jsonrpc_router` | 轻量 RPC（与 REST 二选一） |
  | CLI | `create_use_case_cli` | 本地调试 / 脚本化任务 |
  | 可视化 | `create_use_case_voyager` | 开发期 ER / 服务结构可视化 |
- **main.py 典型模式 — REST + MCP + Voyager**（按需扩展 GraphQL HTTP / JSON-RPC / CLI）：
  ```python
  from nexusx import (
      UseCaseAppConfig, create_use_case_router,
      create_use_case_graphql_mcp_server, create_use_case_voyager,
      GraphQLHandler,
  )

  app_config = UseCaseAppConfig(
      name="project",
      services=[UserService, TaskService, SprintService],
  )

  # REST（自动路由，OpenAPI spec）
  app.include_router(create_use_case_router(app_config))

  # JSON-RPC（替代 REST 的轻量方案，二选一）
  # app.include_router(create_jsonrpc_router(app_config))

  # CLI（可选，生成 Typer CLI 命令行工具）
  # cli = create_use_case_cli(app_config)

  # GraphQL（基于 SQLModel 实体的辅助开发测试 API）
  graphql_handler = GraphQLHandler(base=Base, session_factory=async_session)

  # MCP（UseCase GraphQL MCP — 4 层渐进披露，Layer 3 接收 GraphQL 字符串）
  mcp = create_use_case_graphql_mcp_server(apps=[app_config], name="API")

  # Voyager 可视化（注意：services 是 UseCaseService 子类列表，不是 apps/UseCaseAppConfig）
  voyager = create_use_case_voyager(
      services=app_config.services,
      er_manager=er,
  )
  app.mount("/voyager", voyager)
  ```

**V 降 — 定义验收标准:**
进入 Phase 3 编码之前，先与用户确认以下验收项并写入 `spec/phase3.md`：

| # | 验收项 | 验证方式 |
|---|--------|----------|
| 1 | 每个 REST 端点返回的响应字段符合 DTO 定义（FK 字段隐藏、关系字段包含） | curl POST endpoint |
| 2 | Voyager 中 service 树展示完整（每个服务的方法可见） | 浏览器打开 Voyager |
| 3 | MCP 4 层工具可用：list_apps → describe_compose_schema → describe_compose_method → compose_query | MCP 客户端调用 |
| 4 | POST body 参数校验生效（参数缺少返回 422） | curl 发送非法请求 |

**实现：**
编写 `dtos.py` → `service.py` → `main.py` 挂载

**V 升 — 逐条回查验收:**

- [ ] 1. REST 响应：`curl /api/sprint_service/list_sprints -X POST` 返回字段符合 DTO
- [ ] 2. FK 隐藏：返回数据中不包含 FK 字段（如 `owner_id`）
- [ ] 3. Voyager：service 节点和 method 方法都可见
- [ ] 4. MCP 4 层工具：
  - `list_apps` 返回应用列表
  - `describe_compose_schema(app_name=...)` 返回 services + methods 紧凑列表
  - `describe_compose_method(app_name=..., service_name=..., method_name=...)` 返回参数表 + 返回类型 + SDL 片段
  - `compose_query(app_name=..., query="{ ServiceName { method_name { fields } } }")` 返回 `{data, errors}`，含字段投影
- [ ] 5. 参数校验：缺少必填参数返回 422

## 踩坑经验

1. **不要在 DefineSubset 文件中使用 `from __future__ import annotations`** — 会使类型注解变字符串，SubsetMeta 无法检测 Annotated 元数据
2. **DTO 字段类型必须用 DTO 类型** — 不能直接用 SQLModel 实体，3.0 起 compose schema 生成器会主动报 `SQLModelInDtoFieldError`（项目约定 #7）
3. **ErManager base 和 entities 互斥** — 不能同时提供
4. **UseCaseService 只有被 @query/@mutation 装饰的 async classmethod 会被发现** — 普通方法不会暴露
5. **build_dto_select → dict(row._mapping) → DTO 构造** — 这是 Core API 的标准查询模式
6. **每个 service 子目录必须包含 spec.md** — 记录服务目的、用途、方法需求、DTO 说明和变更记录，方便团队理解服务边界
7. **fastmcp>=3.2.4 挂载到 FastAPI 需要 lifespan 合并** — `app.mount("/mcp", mcp.http_app(path="/"))` 会报 `Task group is not initialized`。必须：(1) 使用 `transport="streamable-http", stateless_http=True`；(2) 在 lifespan 函数定义之前创建 MCP http_app 对象；(3) 将 MCP http_app 的 lifespan 嵌套到 FastAPI lifespan 中（`async with mcp_http.lifespan(mcp_http):`）
8. **Use `create_use_case_router()` 而非手写路由** — 手写路由无法声明 `response_model`，导致 OpenAPI spec 中响应类型为空（`unknown`），TS SDK 无法生成有效类型。`create_use_case_router()` 从 UseCaseService 方法的返回类型注解（如 `-> list[ChatSummary]`）自动提取 `response_model`，使 FastAPI 在 OpenAPI spec 中正确描述响应结构
9. **UseCaseService 方法必须声明返回类型注解** — 3.0 起 compose schema 生成器（`build_compose_schema`）强校验，缺注解的方法在 MCP server 构造时抛 `MissingReturnAnnotationError`；同时 `create_use_case_router()` 也通过 `get_type_hints(method).get("return")` 提取返回类型作为 `response_model`
10. **methods.py 返回 Model，service.py 负责 DTO 转换** — methods.py 是纯业务逻辑层，所有方法（query + mutation）返回 ORM Model 实体。service.py 统一调用 methods.py，DTO 转换在 service.py 中进行：(1) list 方法调 methods 拿 `list[Model]` → `[DtoType.model_validate(m) for m in models]` → `Resolver().resolve(dtos)`；(2) 单条 get 方法调 methods 拿 `Model | None` → `DtoType.model_validate(entity)` → `Resolver().resolve(dto)`；(3) mutation 方法同单条 get。service.py 不直接操作数据库
11. **`create_use_case_graphql_mcp_server()` 返回 FastMCP 实例，可直接添加 `@mcp.prompt()`** — 如果项目需要 MCP prompt 功能，这个挂载点很方便
12. **`create_jsonrpc_router()` 提供轻量 RPC 协议** — 方法命名为 `ServiceName.method_name`，适合不需要 REST 语义的场景。与 `create_use_case_router()` 二选一
13. **`create_use_case_cli()` 生成 Typer CLI 命令行工具** — 每个 service 成为一个命令组，每个方法成为子命令。适合需要本地调试脚本的场景。需要额外依赖 `typer`
14. **3.0 起 UseCase MCP 只有 GraphQL 模式**（`create_use_case_graphql_mcp_server`）。老的两套直接调用式 MCP（`create_use_case_mcp_server` 4 层 + `create_use_case_flat_server` 扁平）已**移除**，迁移见 `docs/migrations/3.0-use-case-graphql.md`。GraphQL 模式下 Layer 3 (`compose_query`) 接收标准 GraphQL 字符串而非 JSON 参数表，支持字段投影、嵌套查询、参数透传；同时**拒绝内省**保持 MCP 响应紧凑
15. **GraphQL HTTP endpoint 与 MCP 是两条独立通道** — MCP 走 MCP 协议（4 层渐进披露，Layer 3 拒绝内省）；GraphQL HTTP endpoint 走标准 GraphQL over HTTP（接受内省以兼容 GraphiQL）。两者共用同一个 `ComposeSchema`，但路由不同：MCP 的内省走 Layer 1/2 工具，HTTP 的内省走 `compose_introspect`
