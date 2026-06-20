# Clean Architecture in Python：nexusx 与主流框架对比

> 2026-05 更新

## 什么是 Clean Architecture

Clean Architecture 的核心主张：**业务逻辑不依赖框架、数据库、UI 或任何外部机构**。通过依赖倒置，让高层策略（用例）与低层细节（数据库、API 交付）解耦，使同一业务逻辑可以面向多种交付方式复用。

衡量一个框架的 Clean Architecture 成熟度，关键看三点：

1. **实体定义** — 领域模型是否与基础设施（ORM、序列化框架）解耦？
2. **DTO / 响应组装** — 是否有独立的响应构建层，能从实体模型自动生成对外契约？
3. **多 API 面** — 同一套业务逻辑能否同时服务 REST、GraphQL、MCP 等多种交付方式？

## 框架概览

| 框架 | 实体定义 | DTO 机制 | 业务逻辑 | API 生成 | 多 API 面 | MCP | DI |
|------|----------|----------|----------|----------|-----------|-----|-----|
| **nexusx** | SQLModel + Relationship | DefineSubset 元类自动生成 | UseCaseService + methods.py 分层 | 自动（SDL + REST + MCP） | GraphQL + REST + MCP | 原生 | Loader 注入 + FromContext |
| **Litestar** | SQLAlchemy / Pydantic | DTO 工厂自动生成 | Controller + Service + DI | 半自动（Controller 装饰器） | REST + GraphQL(插件) + WebSocket | 无 | 内建 DI（分层作用域） |
| **Django + DRF** | Django Model | ModelSerializer 自动生成 | Fat Model / Service Layer | 自动（ViewSet + Router） | REST + GraphQL(第三方) + Admin | 无 | 无 DI 容器 |
| **Strawberry** | `@strawberry.type` | Pydantic 集成桥接 | Resolver + DataLoader | 自动（SDL 从代码生成） | 仅 GraphQL | 无 | Extensions |
| **FastAPI + SQLModel** | SQLModel(table=True) | 继承变体手动定义 | Service / Repository 手动组织 | 手动（逐端点定义） | 仅 REST | 无 | Depends |
| **Ariadne** | 外部 ORM | SDL 即 DTO | Resolver 手动绑定 | 手动（SDL 手写） | 仅 GraphQL | 无 | 无 |
| **Tartiflette** | 外部 ORM | SDL 即 DTO | Resolver 手动绑定 | 手动（SDL 手写） | 仅 GraphQL | 无 | Directives |
| **Temporalio** | dataclass / Pydantic | 参数/返回值 | Workflow + Activity 分离 | N/A（工作流引擎） | N/A | N/A | Worker 注册 |

## nexusx 的架构

```
                    ┌──────────────────────────────┐
                    │   交付层（Delivery）           │
                    │   GraphQL / REST / MCP       │
                    └──────────┬───────────────────┘
                               │ 自动生成
                    ┌──────────▼──────────────────┐
                    │   用例层（Use Case）          │
                    │   UseCaseService            │
                    │   @query / @mutation        │
                    └──────────┬──────────────────┘
                               │ 调用
                    ┌──────────▼───────────────────┐
                    │   业务逻辑层（Business Logic） │
                    │   service/<domain>/methods.py│
                    │   独立 async 函数，无框架依赖   │
                    └──────────┬───────────────────┘
                               │ 返回 Model
                    ┌──────────▼───────────────────┐
                    │   DTO 层（Response Assembly） │
                    │   DefineSubset → Resolver    │
                    │   model_validate + BFS 遍历   │
                    └──────────┬───────────────────┘
                               │ 加载关系
                    ┌──────────▼──────────────────┐
                    │   数据层（Data Access）       │
                    │   ErManager + DataLoader    │
                    │   SQLModel Entity           │
                    └─────────────────────────────┘
```

**关键设计决策**：

- **methods.py 是纯函数**：不依赖 `cls`、不依赖 `nexusx` 装饰器，可独立测试
- **DefineSubset 是声明式 DTO**：从 SQLModel 实体元数据自动生成 Pydantic 模型，隐藏 FK、裁剪字段
- **Resolver 是模型驱动的响应构建器**：通过 BFS 遍历对象树，自动批量加载关系数据
- **同一份 methods.py 服务多种 API**：通过 `_mount()` 桥接到 GraphQL Entity，通过 UseCaseService 桥接到 REST/MCP

## 各框架详细分析

### Litestar — 最接近 nexusx 理念

Litestar 的 DTO 工厂模式与 nexusx 的 DefineSubset 思路相似：从 SQLAlchemy/Pydantic 模型自动生成请求/响应 Schema，支持字段排除和重命名。但 Litestar 的 DTO 仅服务于 REST，不支持 GraphQL 或 MCP 的统一生成。

**优势**：
- DTO 是一等公民，自动从模型生成，支持字段级控制
- 内建 DI 容器，支持分层作用域（transient / scoped / singleton）
- 插件系统可扩展（SQLAlchemy、Redis 等）
- 支持多种序列化后端（Pydantic、msgspec、attrs）

**劣势**：
- GraphQL 需通过 Strawberry 插件集成，无法统一生成
- 无 MCP 支持
- DTO 工厂主要面向 OpenAPI schema，不是面向多 API 面的响应组装
- 社区规模较小，生产案例有限

**适用场景**：REST-only 项目，重视 DTO 自动化和 DI。

### Django + DRF — 自动化程度最高

Django 的 Model → ModelSerializer → ModelViewSet → Router 四步即可生成完整 CRUD REST API + Admin UI。这是所有框架中自动化程度最高的方案。

**优势**：
- ModelSerializer 从 Django Model 自动生成序列化器
- ModelViewSet + Router 自动生成 CRUD 端点
- Django Admin 自动生成管理界面（无可替代的生产力工具）
- graphene-django 可从 Model 自动生成 GraphQL Schema
- 生态成熟，生产案例极多

**劣势**：
- Django Model 与 ORM 强耦合，领域模型无法独立于数据库
- 无内建 DI 容器，依赖模块级导入（反 Clean Architecture）
- Clean Architecture 改造成本高，需要手动引入 Service Layer
- 无 MCP 支持
- Fat Model 模式导致业务逻辑与数据访问混合

**适用场景**：快速交付 CRUD 为主的项目，不追求严格分层。

### Strawberry — GraphQL 生态最佳

Strawberry 是 Python GraphQL 生态中最成熟的代码优先方案。Pydantic 集成可以自动桥接模型，DataLoader 内建支持防止 N+1。

**优势**：
- 代码优先，SDL 从 Python 代码自动生成
- Pydantic 集成（`strawberry.experimental.pydantic.type`）自动桥接模型
- 内建 DataLoader，批量加载防止 N+1
- 支持 Relay 规范（游标分页）、Subscription、Federation 2.x
- 社区活跃，文档质量高

**劣势**：
- 仅 GraphQL，无 REST 或 MCP 支持
- Pydantic 桥接需要手动定义 `strawberry.type`（不像 nexusx 的 DefineSubset 完全自动）
- 无内建 DI（依赖 FastAPI 的 Depends）
- 响应组装需要手动编写 Resolver 逻辑

**适用场景**：GraphQL-only 项目，重视类型安全和开发体验。

### FastAPI + SQLModel — 最小框架约束

这是最"无框架"的方案：SQLModel 单类充当 ORM 模型和 Pydantic 验证模型，FastAPI 从类型注解自动生成 OpenAPI 文档。Clean Architecture 完全靠开发者手动实现。

**优势**：
- 学习曲线低，FastAPI 文档丰富
- SQLModel 单类多角色，减少样板代码
- FastAPI 的 `Depends` 提供轻量 DI
- OpenAPI 文档自动生成
- 社区最大，生态最丰富

**劣势**：
- 无 DTO 自动生成机制（需手动定义 Create/Update/Read 变体）
- 无业务逻辑组织模式（需手动引入 Service/Repository 层）
- 每个端点手动定义，重复性高
- 无 GraphQL、MCP 支持
- Clean Architecture 需要大量手动实现

**适用场景**：中小型项目，团队已有 FastAPI 经验，不追求严格分层。

### Ariadne / Tartiflette — Schema-first GraphQL

两者都是 Schema-first（SDL 优先）方案：先写 GraphQL Schema，再绑定 Resolver。与 nexusx 的模型驱动（代码优先）理念相反。

**优势**（Ariadne）：
- SDL 是前后端的契约，协作清晰
- Ariadne Codegen 可从 Schema 生成客户端代码（Pydantic 模型）
- 框架无关，可集成 Django、Flask、FastAPI

**劣势**：
- SDL 需手动编写，维护成本高
- Resolver 手动绑定，大量样板代码
- 无 DTO 转换层，Resolver 直接操作 Python 对象
- 无 REST 或 MCP 支持
- Tartiflette 社区活跃度存疑

**适用场景**：前后端团队需要 SDL 作为协作契约的 GraphQL 项目。

### Temporalio — 工作流编排的 Clean Architecture

Temporalio 的 Workflow/Activity 分离天然实现了依赖倒置：Workflow 是确定性的编排层（类似 Use Case），Activity 是有副作用的业务层（类似 Repository/Gateway）。

**优势**：
- Workflow/Activity 分离强制执行依赖倒置
- 事件溯源自动持久化状态
- 天然支持长时间运行、重试、超时
- 幂等性是设计约束，不是可选实践

**劣势**：
- 不是 API 框架，无法直接生成 REST/GraphQL/MCP
- Workflow 必须确定性（不能有随机数、网络调用、时间获取）
- 学习曲线陡峭
- 需要 Temporal Server 基础设施

**适用场景**：长时间运行的工作流编排（订单处理、审批流、数据处理管道），需与 API 框架配合使用。

## 核心维度对比

### 1. 实体与 DTO 的解耦

| 框架 | 实体→DTO 方式 | 自动化程度 |
|------|---------------|------------|
| **nexusx** | DefineSubset 元类从 SQLModel 元数据自动生成 Pydantic DTO | 高（声明式） |
| **Litestar** | DTO 工厂从 SQLAlchemy/Pydantic 模型自动生成 | 高（工厂模式） |
| **Django** | ModelSerializer 从 Django Model 自动生成 | 高（反射） |
| **Strawberry** | Pydantic 集成桥接，需手动定义 `@strawberry.type` | 中（半自动） |
| **FastAPI** | 手动定义 Create/Update/Read 继承变体 | 低（纯手动） |
| **Ariadne** | SDL 手写，无 DTO 层 | 无 |

nexusx 和 Litestar 在 DTO 自动化上领先。nexusx 的 DefineSubset 更进一步——它同时控制了 DTO 生成和关系加载策略（通过 Resolver），形成了一个完整的响应组装管线。

### 2. 多 API 面统一

| 框架 | REST | GraphQL | MCP | 统一程度 |
|------|------|---------|-----|----------|
| **nexusx** | `create_use_case_router()` | `GraphQLHandler` | `create_use_case_graphql_mcp_server()` | 三面统一 |
| **Litestar** | 原生 | Strawberry 插件 | 无 | 两面（非统一） |
| **Django** | DRF | graphene-django | 无 | 两面（非统一） |
| **Strawberry** | 无（需 FastAPI） | 原生 | 无 | 单面 |
| **FastAPI** | 原生 | 需第三方 | 无 | 单面 |

nexusx 是唯一实现三面（REST + GraphQL + MCP）统一自动生成的框架。其他框架在多 API 面时需要为每个面分别编写适配代码。

### 3. 响应组装复杂度

当 API 响应需要组装嵌套关系数据时（如"返回 Sprint 及其包含的 Task 列表，每个 Task 包含负责人信息"）：

| 框架 | 处理方式 | N+1 解决 |
|------|----------|----------|
| **nexusx** | Resolver BFS 遍历 + DataLoader 批量加载 | 自动（ErManager） |
| **Litestar** | SQLAlchemy eager load / DTO 手动控制 | 手动（selectinload） |
| **Django** | `select_related` / `prefetch_related` | 手动（需记住加） |
| **Strawberry** | DataLoader 手动集成 | 内建 DataLoader |
| **FastAPI** | 手动写查询 + Pydantic 序列化 | 手动 |

nexusx 的 Resolver + ErManager 组合是唯一实现"声明式 DTO 定义 + 自动批量关系加载"的方案。其他框架要么需要手动控制加载策略（Django、Litestar、FastAPI），要么需要手动编写 DataLoader 逻辑（Strawberry）。

### 4. 业务逻辑与交付的分离

| 框架 | 分离方式 | 复用程度 |
|------|----------|----------|
| **nexusx** | methods.py（纯函数）→ UseCaseService / Entity 挂载 | 高（一套逻辑，三面复用） |
| **Litestar** | Service 通过 DI 注入到 Controller | 中（Service 可复用，但 Controller 需分别写） |
| **Django** | Fat Model / Service Layer | 低（View/Serializer 中混入逻辑） |
| **Strawberry** | Resolver 绑定 | 中（Resolver 可复用，但 GraphQL-only） |
| **FastAPI** | 手动组织 Service 层 | 中（Service 可复用，但需手动接线） |
| **Temporalio** | Activity 独立实现 | 高（Workflow 编排 Activity） |

nexusx 的 `methods.py → _mount() → Entity/UseCaseService` 模式实现了业务逻辑的完全解耦。methods.py 是纯 async 函数，不导入任何 nexusx 代码，可独立测试。挂载逻辑在 models.py 中集中管理。

## nexusx 的独特定位

### 做到了其他框架没做到的

1. **三面统一生成**：一套 SQLModel 实体 + methods.py 业务逻辑 → 自动生成 GraphQL + REST + MCP
2. **声明式响应组装**：DefineSubset 定义"要什么"，Resolver + ErManager 自动解决"怎么拿"
3. **MCP 作为一等公民**：AI Agent 可通过四层渐进式披露（list_apps → describe_compose_schema → describe_compose_method → compose_query）发现和调用 API，这在其他框架中完全没有
4. **模型驱动的端到端**：从 SQLModel 实体到 OpenAPI spec 到 TypeScript SDK，全链路自动生成

### 需要注意的取舍

1. **SQLModel 绑定**：实体层与 SQLModel/SQLAlchemy 耦合，不如 Litestar 支持多种 ORM 后端灵活
2. **Python 生态位**：nexusx 定位在"SQLModel + FastAPI"生态内，不如 Django 的"batteries-included"覆盖面广
3. **社区规模**：作为新兴框架，生产案例和社区资源不如 FastAPI/Django 丰富
4. **学习曲线**：DefineSubset + Resolver + ErManager + UseCaseService 的概念较多，初次使用有一定门槛

## 选型建议

| 场景 | 推荐框架 | 理由 |
|------|----------|------|
| 新项目，需要 GraphQL + REST + MCP | **nexusx** | 三面统一生成，唯一支持 MCP |
| REST-only，重视 DI 和 DTO 自动化 | **Litestar** | DTO 工厂 + 内建 DI 最完善 |
| 快速 CRUD + Admin 后台 | **Django + DRF** | 自动化程度最高，Admin 无可替代 |
| GraphQL-only，重视类型安全 | **Strawberry** | Python GraphQL 生态最佳 |
| 轻量 API，团队熟悉 FastAPI | **FastAPI + SQLModel** | 学习曲线最低，社区最大 |
| 长时间运行的工作流编排 | **Temporalio** | Workflow/Activity 天然依赖倒置 |
| 前后端 SDL 协作 | **Ariadne** | Schema-first，Codegen 支持客户端生成 |
