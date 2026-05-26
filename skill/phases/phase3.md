# Phase 3: UseCase 响应组装 + MCP

**目标**: 按 API 用例组装响应结构。DefineSubset 隐藏内部字段，UseCaseService 统一业务入口。

**新增/修改文件**:
- `service/<entity>/spec.md` — 服务目的、用途、需求、变更记录
- `service/<entity>/dtos.py` — DefineSubset DTOs
- `service/<entity>/service.py` — UseCaseService
- `main.py` — 用 `create_use_case_router()` 挂载 REST + MCP + Voyager 补充 services

**关键模式**:
- `DefineSubset` + `SubsetConfig` 定义响应 DTO（字段选择、FK 隐藏）
- `ErManager` + `Resolver` 自动加载关系（implicit auto-load）
- `UseCaseService` 统一业务逻辑入口（同时服务 MCP 和 FastAPI）
- `@query` / `@mutation` 装饰器标记服务方法
- **UseCaseService 方法必须声明返回类型注解**（如 `-> list[ChatSummary]`、`-> ChatSummary | None`），`create_use_case_router()` 从中提取 `response_model`，使 OpenAPI spec 正确反映 DTO 结构
- **UseCaseService 复用 `service/<domain>/methods.py` 中的核心逻辑，不重新实现**：
  - **query 方法（list）**：调用 methods.py 拿 `list[Model]` → `[DtoType.model_validate(m) for m in models]` → `Resolver().resolve(dtos)`
  - **query 方法（get 单条）**：调用 methods.py 拿 `Model | None` → `DtoType.model_validate(entity)` → `Resolver().resolve(dto)`
  - **mutation 方法**：同 get 单条模式，调用 methods.py 获取 Model 后转换
  - **service.py 不直接操作数据库**（无 `build_dto_select`、`async_session`）
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
- `create_use_case_voyager()` 可视化服务结构
- `create_use_case_mcp_server()` + `UseCaseAppConfig` 暴露给 AI agent（四层渐进式披露：list_apps → list_services → describe_service → call_use_case）
- `create_flat_mcp_server()` + `UseCaseAppConfig` 扁平化 MCP 暴露（每个方法一个 tool，类型定义通过 MCP resource 提供）。适用于方法少（<20 个 tool）、LLM context 充足、需要直接调用的场景
- MCP http_app 必须使用 `transport="streamable-http", stateless_http=True`
- MCP http_app 的 lifespan 必须在 FastAPI lifespan 中通过 `async with mcp_http.lifespan(mcp_http)` 嵌套启动
- MCP http_app 对象必须在 lifespan 函数定义之前创建，以便引用
- **MCP 模式必须在实现时由用户选择** — 向用户展示两种模式的对比，由用户决定：
  | 特性 | `create_use_case_mcp_server`（渐进式） | `create_flat_mcp_server`（扁平化） |
  |------|---------------------------------------|-----------------------------------|
  | 工具数量 | 4 个固定 tool | 每个方法一个 tool |
  | 发现流程 | list_apps → list_services → describe_service → call | 直接调用 tool |
  | 类型定义 | describe_service 返回值 | MCP resource |
  | 适用场景 | 大型 API、多服务（>20 方法） | 小型 API、直接访问 |
  | prompt 支持 | `@mcp.prompt()` | `@mcp.prompt()` |
- **main.py 典型模式 — 三种 API 并存**（GraphQL + REST + MCP）：
  ```python
  from nexusx import (
      UseCaseAppConfig, create_use_case_router,
      create_use_case_mcp_server, create_flat_mcp_server,
      create_use_case_voyager, GraphQLHandler,
  )

  app_config = UseCaseAppConfig(
      name="project",
      services=[UserService, TaskService, SprintService],
  )

  # REST（自动路由，OpenAPI spec）
  app.include_router(create_use_case_router(app_config))

  # GraphQL（辅助开发测试）
  graphql_handler = GraphQLHandler(base=Base, session_factory=async_session)

  # MCP（选一种 — 由用户决定）
  # 渐进式：
  mcp = create_use_case_mcp_server(apps=[app_config], name="API")
  # 扁平化：
  mcp = create_flat_mcp_server(apps=[app_config], name="API")

  # Voyager 可视化
  voyager = create_use_case_voyager(apps=[app_config], er_manager=er)
  ```

**V 降 — 定义验收标准:**
进入 Phase 3 编码之前，先与用户确认以下验收项并写入 `spec/phase3.md`：

| # | 验收项 | 验证方式 |
|---|--------|----------|
| 1 | 每个 REST 端点返回的响应字段符合 DTO 定义（FK 字段隐藏、关系字段包含） | curl POST endpoint |
| 2 | Voyager 中 service 树展示完整（每个服务的方法可见） | 浏览器打开 Voyager |
| 3 | MCP 模式由用户选择并可用：渐进式（4 层发现）或扁平化（直接 tool + resource） | MCP 客户端调用 |
| 4 | POST body 参数校验生效（参数缺少返回 422） | curl 发送非法请求 |

**实现：**
编写 `dtos.py` → `service.py` → `main.py` 挂载

**V 升 — 逐条回查验收:**

- [ ] 1. REST 响应：`curl /api/sprint_service/list_sprints -X POST` 返回字段符合 DTO
- [ ] 2. FK 隐藏：返回数据中不包含 FK 字段（如 `owner_id`）
- [ ] 3. Voyager：service 节点和 method 方法都可见
- [ ] 4. MCP（按用户选择的模式验证）：
  - 渐进式：依次调用 list_apps → list_services → describe_service → call_use_case
  - 扁平化：直接调用 `{ServiceName}_{method_name}` tool + 读取 `nexusx://{app_name}` resource
- [ ] 5. 参数校验：缺少必填参数返回 422

## 踩坑经验

1. **不要在 DefineSubset 文件中使用 `from __future__ import annotations`** — 会使类型注解变字符串，SubsetMeta 无法检测 Annotated 元数据
2. **DTO 字段类型必须用 DTO 类型** — 不能直接用 SQLModel 实体，否则 TypeError
3. **ErManager base 和 entities 互斥** — 不能同时提供
4. **UseCaseService 只有被 @query/@mutation 装饰的 async classmethod 会被发现** — 普通方法不会暴露
5. **build_dto_select → dict(row._mapping) → DTO 构造** — 这是 Core API 的标准查询模式
6. **每个 service 子目录必须包含 spec.md** — 记录服务目的、用途、方法需求、DTO 说明和变更记录，方便团队理解服务边界
7. **fastmcp>=3.2.4 挂载到 FastAPI 需要 lifespan 合并** — `app.mount("/mcp", mcp.http_app(path="/"))` 会报 `Task group is not initialized`。必须：(1) 使用 `transport="streamable-http", stateless_http=True`；(2) 在 lifespan 函数定义之前创建 MCP http_app 对象；(3) 将 MCP http_app 的 lifespan 嵌套到 FastAPI lifespan 中（`async with mcp_http.lifespan(mcp_http):`）
8. **Use `create_use_case_router()` 而非手写路由** — 手写路由无法声明 `response_model`，导致 OpenAPI spec 中响应类型为空（`unknown`），TS SDK 无法生成有效类型。`create_use_case_router()` 从 UseCaseService 方法的返回类型注解（如 `-> list[ChatSummary]`）自动提取 `response_model`，使 FastAPI 在 OpenAPI spec 中正确描述响应结构
9. **UseCaseService 方法必须声明返回类型注解** — `create_use_case_router()` 通过 `get_type_hints(method).get("return")` 提取返回类型作为 `response_model`。缺少返回注解的方法，其响应类型在 OpenAPI spec 中为空
10. **methods.py 返回 Model，service.py 负责 DTO 转换** — methods.py 是纯业务逻辑层，所有方法（query + mutation）返回 ORM Model 实体。service.py 统一调用 methods.py，DTO 转换在 service.py 中进行：(1) list 方法调 methods 拿 `list[Model]` → `[DtoType.model_validate(m) for m in models]` → `Resolver().resolve(dtos)`；(2) 单条 get 方法调 methods 拿 `Model | None` → `DtoType.model_validate(entity)` → `Resolver().resolve(dto)`；(3) mutation 方法同单条 get。service.py 不直接操作数据库（无 `build_dto_select`、`async_session`）
11. **`create_flat_mcp_server()` 返回 FastMCP 实例，可直接添加 `@mcp.prompt()`** — 如果项目需要 MCP prompt 功能，flat server 和渐进式 server 都提供了方便的挂载点，两者返回的都是标准 FastMCP 对象
