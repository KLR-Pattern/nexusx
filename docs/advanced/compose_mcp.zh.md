# 面向 AI 的 Compose MCP

Compose MCP 服务器把你的 `UseCaseService` 方法通过
[Model Context Protocol](https://modelcontextprotocol.io/) 暴露给 AI 代理——
schema 侧**渐进披露**、数据侧**字段选择**。当 MCP 的消费者是 agent 时，
推荐这一层交付：agent 不再预载几十个工具定义，而是逐层发现你的应用、
只取所需的字段。

本页讲怎么做；至于为什么——context 压力分析与一段端到端的 agent 交互
——见 [MCP 与 context 效率](../mcp-context-efficiency.md)。

## Step 1：把应用描述一次

```python
from nexusx import UseCaseAppConfig

project_api = UseCaseAppConfig(
    name="project",
    services=[SprintService],
    description="Project planning operations",
)
```

同一份配置可挂到所有交付——REST、MCP、CLI——MCP 面因此永远不会和其他
交付漂移。

## Step 2：创建并运行 MCP 服务器

先安装可选集成：

```bash
pip install "nexusx[fastmcp]"
```

```python
from nexusx import create_use_case_graphql_mcp_server

mcp = create_use_case_graphql_mcp_server(
    apps=[project_api],       # 多个 app → 一个服务器，见下文
    name="Project API",
)
mcp.run()                     # 默认 stdio；HTTP 场景传 transport="sse"
```

## Step 3：agent 如何发现你的应用

服务器注册四个工具，构成一条下钻链：

```text
list_apps
    -> describe_compose_schema(app_name)
        -> describe_compose_method(app_name, service_name, method_name)
            -> compose_query(app_name, query)
```

1. **`list_apps`** —— app 名 + 一行描述。极紧凑；agent 先选 app，大块
   内容此时还没进 context。
2. **`describe_compose_schema(app_name)`** —— 一个 app 的服务与方法列表，
   仍然紧凑。
3. **`describe_compose_method(...)`** —— 单个方法的完整签名与返回 SDL，
   只在 agent 真要用时才拉取。
4. **`compose_query(app_name, query)`** —— 执行。

## Step 4：查询语法

`query` 是针对该 app compose schema 的 GraphQL 文档。数据按**服务**、
再按**方法**嵌套：

```graphql
query {
  SprintService {
    list_sprints {
      name
      task_count
      tasks {
        title
        owner { name }
      }
    }
  }
}
```

响应是 GraphQL 标准的 `{data, errors}`：

```json
{"data": {"SprintService": {"list_sprints": [...]}}}
```

三条值得记住的规则：

- **参数内联，不走 variables。** 方法参数写成 GraphQL 参数
  （`list_tasks(limit: 10)`）；`$variable` 是设计层面的约束，会被干净地
  报错拒绝。运行期输入属于方法签名（可信值则走 `FromContext`）。
- **Selection 决定响应形状。** 没选的字段不会序列化——要 `name` 就只返回
  `name`。Selection 控制的是响应大小；哪些列可查询由 `DefineSubset`
  边界在定义时固定。
- **内省被拒绝。** `__schema` / `__type` 查询返回错误——请用
  `describe_compose_schema` / `describe_compose_method`，让发现始终走
  渐进披露的路径。

## 多 app 一个服务器

独立打包的应用与数据库可以合并进一个 MCP 服务器：

```python
mcp = create_use_case_graphql_mcp_server(
    apps=[project_api, billing_api],
    name="Company API",
)
```

agent 在 `list_apps` 里同时看到两个 app，按需下钻。

## Compose MCP vs. entity-first MCP

nexusx 提供两层 MCP，回答不同的问题：

|  | Compose MCP（本页） | [entity-first MCP](mcp_service.md) |
|---|---|---|
| 暴露什么 | `UseCaseService` 方法（操作图） | SQLModel 实体 + 自动查询（数据图） |
| 发现方式 | 四工具渐进披露 | Schema 工具 + query/mutation 执行 |
| 最适合 | 调用业务能力的 agent | 探索原始数据关系的 agent |
| 接入 | `UseCaseAppConfig` + 一个工厂 | `create_single_app_mcp_server(base, ...)` |

经验法则：**会"做事"的 agent** → compose MCP；**会"探索"的 agent** →
entity-first MCP。两者可以并行运行。
