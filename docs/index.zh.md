---
template: home.html
home:
  hero:
    badge: "次世代业务建模工具 · AI 原生 · SQLModel"
    title: "一次业务建模，<br>人与 AI 共享。"
    subtitle: "把业务实体、关系与用例建模一次，GraphQL、REST、MCP、CLI 与 TS SDK 全部派生。数据是一张图，工具只是它的投影视图。"
    install: "pip install nexusx"
    primary: {label: "快速开始", ref: "guide/quick_start"}
    secondary: {label: "GitHub", url: "https://github.com/allmonday/nexusx"}
  sections:
    # ── AI 原生集成 ──
    - type: cards
      muted: true
      two: true
      title: "AI 原生集成，而非外挂"
      subtitle: "同一份类型化业务模型，AI 代理与开发者都是一级消费者。"
      cards:
        - icon: "🤖"
          title: "面向 AI —— 一等公民"
          text: "MCP 是原生协议：强类型，底层是 GraphQL。"
          bullets:
            - text: "<strong>Context 效率</strong> —— agent 按需选字段，一次调用返回无 N+1 的嵌套数据树，且只要所求内容"
            - text: "<strong>渐进披露</strong> —— list_apps → describe_compose_schema → describe_compose_method → compose_query，schema 按需分片进入上下文"
            - {label: "MCP 与 context 效率 →", ref: "mcp-context-efficiency"}
        - icon: "🧑‍💻"
          title: "面向人类 —— 同一模型"
          text: "只需编写 SQLModel 实体和类型化 DTO，这就是全部工作量。"
          bullets:
            - text: "REST 路由、GraphQL schema、CLI 与 TS SDK 零样板"
            - text: "业务逻辑改一处，所有协议同步更新"

    # ── 可维护难题 ──
    - type: cards
      title: "大模型都能写出应用，难的是可维护、可理解。"
      subtitle: "大模型生成代码很快——但缺乏结构约束时，技术债会在几周后浮现：逻辑重复、组件互相渗透、调试靠猜。业界称之为 vibe coding 的代价。"
      lead: "nexusx 把 AI 的书写面收窄为<strong>声明式模型</strong>——实体、关系与类型化用例方法。结构不靠 AI 发挥，由模型保证。"
      cards:
        - icon: "✍️"
          title: "小而强类型的生成面"
          text: "AI 只写模型与用例方法，不写散落各处的胶水代码——diff 小，人可审。"
        - icon: "📌"
          title: "单一事实源"
          text: "业务规则改一处，所有协议同步更新——维护成本不随交付协议数翻倍。"
        - icon: "👁️"
          title: "构造即可理解"
          text: "类型化契约，加上 Voyager：实体、关系、用例及其依赖渲染为一张实时 ER 图——不用先读代码就能掌握整个项目，无论你是新加入的人，还是一个新的 AI 会话。"
          link: {label: "Voyager →", ref: "advanced/voyager"}

    # ── 一次建模，六种交付 ──
    - type: comparison
      muted: true
      stack: true
      title: "一次建模，六种交付"
      subtitle: "语义级同构 —— 每种协议都从同一个类型化模型生成，而不是在复制品外面套一层包装。"
      bad:
        title: "同一操作，三份拷贝"
        code: |-
          # "list sprints" — written once per protocol

          @app.get("/sprints")
          async def rest_list_sprints() -> list[SprintOut]:
              ...  # query + assembly, again

          @strawberry.field
          async def graphql_sprints(self) -> list[SprintType]:
              ...  # types + loaders, again

          @mcp.tool()
          async def sprints_for_agents() -> str:
              ...  # JSON dumping, again

          # ↑ change the rule → fix every copy
      good:
        title: "一个 UseCaseService 方法"
        code: |-
          class SprintService(UseCaseService):
              """Sprint planning operations."""

              @query
              async def list_sprints(cls) -> list[SprintSummary]:
                  """List sprints with tasks, owners, and task count."""
                  return await load_sprints()

          # six deliveries, one model ↓
      deliveries:
        - {icon: "🌐", title: "REST + OpenAPI", text: "类型化 FastAPI 路由，进入 OpenAPI。", code: "create_use_case_router(api)"}
        - {icon: "🟣", title: "GraphQL · 数据图", text: "实体成为 by_id / by_filter 查询根，浏览切片关联数据。", code: "Sprint { by_filter(limit: 10) { ... } }"}
        - {icon: "🟣", title: "GraphQL · 操作图", text: "用例方法经 compose schema 成为类型化字段。", code: "compose_query(app, query, args)"}
        - {icon: "🤖", title: "MCP", text: "AI 代理渐进式发现。", code: "create_use_case_graphql_mcp_server([api])"}
        - {icon: "⌨️", title: "CLI", text: "服务即命令组。", code: "list_sprints --select \"name task_count\""}
        - {icon: "📘", title: "TS SDK", text: "从 compose schema 生成类型化客户端。", code: "sprintService.listSprints()"}

    # ── 一个模型，两张图 ──
    - type: cards
      title: "一个模型，两张图"
      subtitle: "两个 GraphQL 面，各司其职 —— 任选其一，或两者并用。"
      two: true
      cards:
        - icon: "🧭"
          title: "数据图 —— 浏览与切片"
          text: "SQLModel 实体与关系变成 by_id / by_filter 查询根。无需编写关系 resolver —— DataLoader 批量加载保证遍历全程无 N+1。"
          chip: "GraphQLHandler"
        - icon: "⚙️"
          title: "操作图 —— 调用能力"
          text: "类型化业务方法向 Web 客户端、集成方与 AI 代理暴露稳定的业务能力 —— 一份定义，REST / MCP / CLI / SDK 多端服务。"
          chip: "UseCaseService"

    # ── 声明式构建响应 DTO ──
    - type: comparison
      muted: true
      title: "声明式构建响应 DTO"
      subtitle: "实体不等于 API 契约。DefineSubset 隐藏内部列、自动加载关系、计算派生字段。"
      bad:
        title: "手写查询 + 手动拼装"
        code: |-
          # Per-endpoint: manual SQL, N+1, dict munging
          async def get_sprints():
              sprints = await session.exec(select(Sprint))
              result = []
              for s in sprints:
                  tasks = await session.exec(
                      select(Task).where(Task.sprint_id == s.id))
                  for t in tasks:
                      t.owner = await session.get(User, t.owner_id)

          # N+1 queries, fragile dict construction
      good:
        title: "声明式 DTO + 自动加载"
        code: |-
          from nexusx import DefineSubset, ErManager, build_dto_select

          class UserDTO(DefineSubset):
              __subset__ = (User, ("id", "name"))

          class TaskDTO(DefineSubset):
              __subset__ = (Task, ("id", "title", "owner_id"))
              owner: UserDTO | None = None   # auto-loaded

          class SprintDTO(DefineSubset):
              __subset__ = (Sprint, ("id", "name"))
              tasks: list[TaskDTO] = []      # auto-loaded

          er = ErManager(entities=[User, Sprint, Task], session_factory=async_session)
          Resolver = er.create_resolver()

          async def load_sprints() -> list[SprintDTO]:
              stmt = build_dto_select(SprintDTO)          # root columns only
              async with async_session() as session:
                  rows = (await session.exec(stmt)).all()
              dtos = [SprintDTO(**dict(r._mapping)) for r in rows]
              return await Resolver().resolve(dtos)       # tree filled, batched

          # 1 query per relationship, zero N+1

    # ── 不止一个数据库 ──
    - type: cards
      title: "不止一个数据库"
      subtitle: "同一个关系模型，延伸到更复杂的架构。"
      cards:
        - {icon: "⚡", title: "构造级性能", text: "DataLoader 批量加载、SQL 列裁剪、窗口函数分页；total_count 只在响应请求时才计算。"}
        - {icon: "🔀", title: "派生字段与跨层", text: "post_* 计算派生字段，ExposeAs / SendTo 实现跨层数据流。"}
        - {icon: "🧲", title: "虚拟实体", text: "普通 Pydantic 模型作为非表图根 —— Redis、搜索、SDK 支撑的数据进同一张图。"}
        - {icon: "🌐", title: "实体联邦", text: "无中心网关组合多个 nexusx 数据图 —— 同构联邦，只组 nexusx 服务。"}
        - {icon: "🧱", title: "组合与 DTO 联邦", text: "ComposedErManager 单进程组合多引擎；DTO 联邦跨服务加载 public DTO 树。"}
        - {icon: "🗃️", title: "多应用 MCP", text: "独立打包的应用与数据库，合并为一个 MCP 服务。"}

    # ── 三个想法 ──
    - type: cards
      muted: true
      title: "nexusx 背后的三个想法"
      subtitle: "决定每个 API 形态的设计原则。"
      cards:
        - {icon: "🎯", title: "Selection 是一等公民", text: "一次字段选择同时决定：GraphQL 响应形状、SQL 加载的列、拷贝进 DTO 的字段、MCP 返回、CLI --select，以及 total_count 是否计算。"}
        - {icon: "🌉", title: "关系不限于 ORM", text: "Redis、搜索引擎、其他数据库、外部 API —— 声明一个带异步批量函数的 Relationship，即可加入同一套 loader、DTO、GraphQL 与 ER 图基础设施。"}
        - {icon: "📦", title: "交付后置分层", text: "业务方法不依赖任何协议对象 —— 构建器检查类型化签名后挂上 REST / MCP / CLI / SDK 适配器。FromContext 注入可信值（用户、租户），不暴露为客户端参数。"}

    # ── Agent 陪建 ──
    - type: cards
      title: "不用啃 API 文档 —— 让 Agent 陪你建模"
      subtitle: "把 4-phase skill 装进你的编码 Agent（Claude Code、Codex、Cursor 等），用自然语言描述你的应用。Agent 驱动流程，你只需审视模型。"
      command: "npx skills add KLR-Pattern/nexusx -s nexusx-4phase -a claude-code"
      cards:
        - {icon: "🗺️", title: "Phase 0 —— 领域建模", text: "先和你确认领域模型与持久化策略，再动代码。"}
        - {icon: "🏗️", title: "Phase 1–3 —— 逐层实现", text: "实体与关系、GraphQL 辅助接口、UseCase 的 REST / MCP / CLI 交付。"}
        - {icon: "🚀", title: "Phase 4 —— 生成 SDK", text: "可选从 compose schema 生成类型化 TypeScript SDK。"}

    # ── 技术栈 ──
    - type: integrations
      title: "为你的技术栈而建"
      subtitle: "与你现有的框架和工具无缝集成。"
      badges:
        - {icon: "🌍", label: "GraphQL", ref: "guide/graphql_mode"}
        - {icon: "⚡", label: "FastAPI", ref: "guide/core_api"}
        - {icon: "🤖", label: "MCP", ref: "advanced/mcp_service"}
        - {icon: "🗂", label: "SQLAlchemy", ref: "guide/er_diagram"}
        - {icon: "👁", label: "Voyager", ref: "advanced/voyager"}
        - {icon: "📄", label: "TypeScript SDK", ref: "guide/graphql_mode"}

    # ── CTA ──
    - type: cta
      title: "从实体开始，而不是样板代码"
      subtitle: "声明一次模型 —— 数据图、响应 DTO 与所有交付随之而来。"
      primary: {label: "阅读指南", ref: "guide/quick_start"}
      secondary: {label: "查看 GitHub", url: "https://github.com/allmonday/nexusx"}
---


# nexusx

**nexusx** 是一款深度集成 AI 的次世代业务建模工具。把业务实体、关系与用例建模一次，GraphQL、REST、MCP、CLI 与 TS SDK 全部由此派生，共享同一个 DataLoader 批量加载的查询图（无 N+1）和一套类型化 DTO（`DefineSubset`）：语义级同构，而非传输层包装。

## 60 秒运行起来

安装依赖：

```bash
pip install "nexusx[demo]"
```

创建 `app.py`：

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Relationship, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx import AutoQueryConfig, GraphQLHandler


class BaseEntity(SQLModel):
    pass


class Team(BaseEntity, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    heroes: list["Hero"] = Relationship(back_populates="team")


class Hero(BaseEntity, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    team_id: int | None = Field(default=None, foreign_key="team.id")
    team: Team | None = Relationship(back_populates="heroes")


engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
)
session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
handler = GraphQLHandler(
    base=BaseEntity,
    session_factory=session_factory,
    auto_query_config=AutoQueryConfig(),
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)

    async with session_factory() as session:
        team = Team(name="Avengers")
        session.add(team)
        await session.flush()
        session.add(Hero(name="Spider-Man", team_id=team.id))
        await session.commit()

    try:
        yield
    finally:
        await handler.aclose()
        await engine.dispose()


app = FastAPI(lifespan=lifespan)


class GraphQLRequest(BaseModel):
    query: str


@app.get("/graphql", response_class=HTMLResponse)
async def graphiql() -> str:
    return handler.get_graphiql_html()


@app.post("/graphql")
async def graphql(request: GraphQLRequest):
    return await handler.execute(request.query)
```

启动服务：

```bash
uvicorn app:app --reload
```

打开 `http://127.0.0.1:8000/graphql`，执行：

```graphql
{
  Team {
    by_filter {
      id
      name
      heroes {
        id
        name
      }
    }
  }
}
```

至此已经得到自动生成的 GraphQL schema 和批量关系加载。完整说明见
[快速开始](./guide/quick_start.zh.md)。

## 你能得到什么

| 你想要... | 你写... | nexusx 负责... |
|------|----------|--------------|
| 一个 GraphQL API | `@query` / `@mutation` 装饰器 | SDL 生成、DataLoader 批量加载 |
| REST 或用例 DTO | `DefineSubset` + 字段声明 | 隐式自动加载、N+1 预防、ORM→DTO 转换 |
| 派生字段 | `post_*` 方法 | 在嵌套数据就绪后自动执行 |
| 跨层传递数据 | `ExposeAs`、`SendTo`、`Collector` | 向下传上下文，向上聚合结果 |
| 非 ORM 关系 | `Relationship(...)` | 同一 DataLoader 基础设施，支持自动加载 |
| 一个 AI 就绪的 API | `create_single_app_mcp_server(base=...)` | 渐进式 MCP 工具暴露 |
| 拆成微服务 | `RemoteRelationship` / `federation_public` DTO | 同构联邦：读模型跨服务组合，entity 主体不动 |

## 适合谁

- **后端开发者**：从 SQLModel 实体快速构建 GraphQL 和 REST API
- **团队**：模型稳定后自动生成 API，不再手写 schema
- **项目**：同时需要 GraphQL 的灵活性和 REST 的交付能力
- **AI 集成**：将同一套模型通过 MCP 暴露给 AI 代理

## 学习路径

```mermaid
flowchart LR
    p1["P1: ER Diagram<br/>SQLModel 实体 + 非 ORM 关系<br/>+ 可视化 ER 图"]
    --> p2["P2: GraphQL API<br/>@query / @mutation<br/>SDL 自动生成 + DataLoader"]
    --> p3["P3: Core API<br/>DefineSubset DTOs<br/>隐式自动加载 + post_*"]
    --> p4["MCP / UseCase<br/>AI 代理 + 业务服务"]
```

所有指南复用同一套业务场景，你可以跟着一步步操作：

```mermaid
erDiagram
    Sprint ||--o{ Task : "has many"
    Task }o--|| User : "owner"
```

### 指南（教程路径）

| 页面 | 你将学到什么 |
|---|---|
| [快速开始](./guide/quick_start.zh.md) | 30 秒跑起来一个 GraphQL API |
| [ER 图与非 ORM 关系](./guide/er_diagram.zh.md) | 声明和可视化实体关系 |
| [GraphQL 模式](./guide/graphql_mode.zh.md) | 从 SQLModel 到 GraphQL API 的完整流程 |
| [GraphQL 分页](./guide/graphql_pagination.zh.md) | 列表关系的分页支持 |
| [自动查询](./guide/graphql_auto_query.zh.md) | 跳过 `@query`，自动生成 `by_id` / `by_filter` |
| [Core API 模式](./guide/core_api.zh.md) | 用 `DefineSubset` + 隐式自动加载构建 REST 响应 |
| [Core API 进阶](./guide/core_api_advanced.zh.md) | 使用 `resolve_*` / `post_*` / 跨层数据流 |
| [自定义关系](./guide/custom_relationship.zh.md) | 声明和使用非 ORM 关系 |
| [虚拟实体](./guide/virtual_entities.zh.md) | 通过 `add_virtual_entities()` 使用普通 `BaseModel` 根（`CurrentUser`、页面 wrapper、第三方 DTO） |
| [ER 图可视化](./guide/er_diagram_visual.zh.md) | 生成和嵌入 Mermaid ER 图 |

### 进阶指南

| 页面 | 你将学到什么 |
|---|---|
| [跨服务联邦](./advanced/federation.zh.md) | 同构联邦：单体渐进演化成微服务，读模型跨服务组合（β 实体图 / γ DTO） |
| [MCP 服务](./advanced/mcp_service.zh.md) | 将 SQLModel API 暴露给 AI 代理 |
| [UseCase 服务](./advanced/use_case_service.zh.md) | 定义业务服务，同时服务于 MCP 和 REST |
| [UseCase + FastAPI](./advanced/use_case_fastapi.zh.md) | 同一服务类嵌入 FastAPI 路由 |
| [Voyager 可视化](./advanced/voyager.zh.md) | 交互式 ERD 浏览 |

### API 参考

- [GraphQLHandler](./api/api_graphql_handler.zh.md) — GraphQL 入口 + SDL 生成
- [Core API](./api/api_core.zh.md) — ErManager / Resolver / DefineSubset / Loader
- [跨层数据流](./api/api_cross_layer.zh.md) — ExposeAs / SendTo / Collector
- [关系与 ER 图](./api/api_relationship.zh.md) — Relationship / ErDiagram
- [MCP API](./api/api_mcp.zh.md) — MCP 服务配置
- [UseCase API](./api/api_use_case.zh.md) — UseCaseService / create_use_case_graphql_mcp_server
