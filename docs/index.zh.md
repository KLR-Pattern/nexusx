---
template: home.html
---

# nexusx

**nexusx** 是一个渐进式 SQLModel 扩展库。你从 ORM 实体出发，添加非 ORM 关系，自动生成 GraphQL API，并用 `DefineSubset` 声明式构建响应 DTO。所有实体关系都可以通过 ER 图可视化。

## 你能得到什么

| 你想要... | 你写... | nexusx 负责... |
|------|----------|--------------|
| 一个 GraphQL API | `@query` / `@mutation` 装饰器 | SDL 生成、DataLoader 批量加载 |
| REST 或用例 DTO | `DefineSubset` + 字段声明 | 隐式自动加载、N+1 预防、ORM→DTO 转换 |
| 派生字段 | `post_*` 方法 | 在嵌套数据就绪后自动执行 |
| 跨层传递数据 | `ExposeAs`、`SendTo`、`Collector` | 向下传上下文，向上聚合结果 |
| 非 ORM 关系 | `Relationship(...)` | 同一 DataLoader 基础设施，支持自动加载 |
| 一个 AI 就绪的 API | `create_simple_mcp_server(base=...)` | 渐进式 MCP 工具暴露 |

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
| [ER 图可视化](./guide/er_diagram_visual.zh.md) | 生成和嵌入 Mermaid ER 图 |

### 进阶指南

| 页面 | 你将学到什么 |
|---|---|
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
