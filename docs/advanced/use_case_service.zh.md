# UseCase 服务

将业务逻辑定义一次为服务类——同时服务于 MCP（AI 代理）和 FastAPI（REST API），无需重复。

## 设计理念

```
UseCaseService 子类 ──┬── MCP server（AI 代理，四层渐进式发现）
                      └── FastAPI routes（REST API，OpenAPI 文档）
```

一个服务类。两种呈现模式。零重复。

## 定义 UseCaseService

继承 `UseCaseService`，声明 `async classmethod` 方法。元类自动发现公共方法：

```python
from nexusx.use_case import UseCaseService

class SprintService(UseCaseService):
    """Sprint 管理服务。"""

    @classmethod
    async def list_sprints(cls) -> list[SprintSummary]:
        """获取所有 sprint 及其任务数。"""
        stmt = build_dto_select(SprintSummary)
        async with async_session() as session:
            rows = (await session.exec(stmt)).all()
        dtos = [SprintSummary(**dict(row._mapping)) for row in rows]
        return await Resolver().resolve(dtos)

    @classmethod
    async def get_sprint(cls, sprint_id: int) -> SprintSummary | None:
        """按 ID 获取 sprint。"""
        stmt = build_dto_select(SprintSummary, where=Sprint.id == sprint_id)
        async with async_session() as session:
            rows = (await session.exec(stmt)).all()
        if not rows:
            return None
        dto = SprintSummary(**dict(rows[0]._mapping))
        return await Resolver().resolve(dto)
```

!!! tip
    每个方法的 docstring 会成为 MCP 工具的描述——写清楚它们，让 AI 代理知道何时该用哪个方法。

## 暴露到 MCP

3.0+ 的入口是 `create_use_case_graphql_mcp_server` —— 从 `UseCaseService` 签名自动生成真正的 GraphQL schema，再通过四层渐进披露 MCP 暴露：应用发现 → schema 总览 → 方法详情 → GraphQL 执行。

```python
from nexusx.use_case import UseCaseAppConfig, create_use_case_graphql_mcp_server

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
mcp.run()  # stdio 模式
```

### MCP 工具

| 工具 | 用途 | 响应信封 |
|------|------|---------|
| `list_apps()` | 发现可用应用 | `{success, data}` |
| `describe_compose_schema(app_name)` | 应用下 service + 方法紧凑列表（不含参数和返回类型） | `{success, data}` |
| `describe_compose_method(app_name, service_name, method_name)` | 参数表 + 返回类型 + SDL 片段（含返回类型传递闭包） | `{success, data}` |
| `compose_query(app_name, query)` | 执行 GraphQL 查询字符串 | `{data, errors}`（GraphQL 标准） |

### compose_query 示例

Layer 3（`compose_query`）接收标准 GraphQL 查询字符串，agent 可以在一个 round-trip 里组合多 service 查询 + 字段选择：

```graphql
{
  SprintService {
    list_sprints {
      id
      name
      tasks { id title owner { id name } }
    }
  }
  TaskService {
    list_tasks { id title }
  }
}
```

返回是 GraphQL 标准的 `{data, errors}`。字段投影意味着只返回请求的字段——agent 可以通过少选字段来压缩响应。

**内省查询（`__schema` / `__type` / `__typename`）在 Layer 3 被拒绝**，以保持 MCP 响应紧凑——agent 应该用 Layer 1/2 发现 schema。如果需要一个处理内省的 GraphQL HTTP endpoint（GraphiQL 友好），直接用 `compose_introspect`；完整示例见 `demo/use_case/graphql_server.py`。

### 从 2.x 迁移

3.0 移除了 2.x 的直接调用式 MCP 入口（`create_use_case_mcp_server`、`create_use_case_flat_server`）。完整 before/after 映射见 [`docs/migrations/3.0-use-case-graphql.md`](../migrations/3.0-use-case-graphql.md)。

## 回顾

- `UseCaseService` 子类将业务逻辑定义为 `async classmethod` 方法
- 元类自动发现公共方法——以下划线 `_` 开头的私有方法会被排除
- `create_use_case_graphql_mcp_server` 创建四层渐进披露的 GraphQL MCP 服务
- 方法的 docstring 成为 AI 代理看到的 MCP 工具描述

## 下一步

- [UseCase + FastAPI](./use_case_fastapi.zh.md) — 同一服务类嵌入 FastAPI
- [MCP 服务](./mcp_service.zh.md) — 纯 MCP 集成（GraphQL 模式）
