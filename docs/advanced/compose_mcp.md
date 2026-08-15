# Compose MCP for AI

The compose MCP server exposes your `UseCaseService` methods to AI agents
over the [Model Context Protocol](https://modelcontextprotocol.io/) — with
**progressive disclosure** on the schema side and **field selection** on the
data side. It is the delivery recommended when the MCP consumer is an agent:
instead of preloading dozens of tool definitions, the agent discovers your
application layer by layer and fetches only the fields it needs.

This page covers the how. For the why — context-pressure analysis and an
end-to-end agent interaction — see [MCP & Context Efficiency](../mcp-context-efficiency.md).

## Step 1: Describe the application once

```python
from nexusx import UseCaseAppConfig

project_api = UseCaseAppConfig(
    name="project",
    services=[SprintService],
    description="Project planning operations",
)
```

The same config attaches to every delivery — REST, MCP, CLI — so the MCP
surface never drifts from the rest.

## Step 2: Create and run the MCP server

Install the optional integration first:

```bash
pip install "nexusx[fastmcp]"
```

```python
from nexusx import create_use_case_graphql_mcp_server

mcp = create_use_case_graphql_mcp_server(
    apps=[project_api],       # multiple apps → one server, see below
    name="Project API",
)
mcp.run()                     # stdio by default; pass transport="sse" for HTTP
```

## Step 3: How the agent discovers your app

The server registers four tools, forming a drill-down chain:

```text
list_apps
    -> describe_compose_schema(app_name)
        -> describe_compose_method(app_name, service_name, method_name)
            -> compose_query(app_name, query)
```

1. **`list_apps`** — app names + one-line descriptions. Compact; the agent
   picks an app before anything large enters context.
2. **`describe_compose_schema(app_name)`** — the services and methods of one
   app, still compact.
3. **`describe_compose_method(...)`** — one method's full signature and return
   SDL, fetched only when the agent is about to use it.
4. **`compose_query(app_name, query)`** — execute.

## Step 4: Query syntax

`query` is a GraphQL document against the app's compose schema. Data is
nested by **service**, then **method**:

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

The response is GraphQL-standard `{data, errors}`:

```json
{"data": {"SprintService": {"list_sprints": [...]}}}
```

Three rules worth knowing:

- **Arguments are inline, not variables.** Method parameters are written as
  GraphQL arguments (`list_tasks(limit: 10)`); `$variable` definitions are a
  design-level constraint and are rejected with a clean error. Runtime input
  belongs in the method signature (or `FromContext` for trusted values).
- **Selection shapes the response.** Unselected fields are not serialized —
  asking for `name` returns only `name`. Selection controls response size;
  which columns are queryable is fixed at definition time by the
  `DefineSubset` boundary.
- **Introspection is rejected.** `__schema` / `__type` queries return an
  error — use `describe_compose_schema` / `describe_compose_method` instead,
  so discovery stays on the progressive-disclosure path.

## Multiple apps, one server

Independently packaged applications and databases can be combined into a
single MCP server:

```python
mcp = create_use_case_graphql_mcp_server(
    apps=[project_api, billing_api],
    name="Company API",
)
```

The agent sees both apps in `list_apps` and drills into whichever it needs.

## Compose MCP vs. entity-first MCP

nexusx ships two MCP layers; they answer different questions:

|  | Compose MCP (this page) | [Entity-first MCP](mcp_service.md) |
|---|---|---|
| Exposes | `UseCaseService` methods (operation graph) | SQLModel entities + auto queries (data graph) |
| Discovery | 4-tool progressive disclosure | Schema tool + query/mutation execution |
| Best for | Agents invoking business capabilities | Agents exploring raw data relationships |
| Setup | `UseCaseAppConfig` + one factory | `create_single_app_mcp_server(base, ...)` |

Rule of thumb: **agents that act** → compose MCP; **agents that explore** →
entity-first MCP. Both can run side by side.
