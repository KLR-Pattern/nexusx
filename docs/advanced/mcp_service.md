# MCP Service

Expose your SQLModel entity graph to AI agents via the Model Context Protocol. An AI agent can query your data through GraphQL — with schema discovery, query execution, and relationship traversal all handled automatically.

> This is the **entity-first** layer (data graph). If your agents should invoke
> `UseCaseService` business methods instead — with progressive disclosure and
> field selection — see [Compose MCP for AI](compose_mcp.md). The two layers
> can run side by side.

## Step 1: Create an MCP Server

Install the MCP dependency first:

```bash
pip install nexusx[fastmcp]
```

Then create a server from your SQLModel base class:

```python
from nexusx.mcp import create_single_app_mcp_server

mcp = create_single_app_mcp_server(
    base=SQLModel,
    name="My API",
    session_factory=async_session,  # Needed when operations access the database
)
```

By default, your AI agent gets a minimal read-only surface:

| Tool | Purpose |
|------|---------|
| `get_schema()` | Get the GraphQL schema |
| `graphql_query(query)` | Execute a GraphQL query |

Enable mutations explicitly when the agent must write data:

```python
mcp = create_single_app_mcp_server(
    base=SQLModel,
    session_factory=async_session,
    allow_mutation=True,
)
```

This adds `graphql_mutation(mutation)` and includes mutations in the schema
returned by `get_schema()`.

The AI agent can discover your schema, then query it with full relationship traversal — the same DataLoader batch loading that powers GraphQL mode works under the hood.

## Step 2: Run the Server

Two transport modes:

```python
# stdio — for CLI-based AI tools (Claude Desktop, Cursor)
mcp.run()

# HTTP — for web-based AI agents running as a separate service
mcp.run(transport="streamable-http", host="0.0.0.0", port=8003)
```

!!! tip
    Use **stdio** when integrating with desktop AI tools. Use **HTTP** when your AI agent runs as a separate service.

## Step 3: Multi-App Mode

When your AI agent needs to work across multiple databases or domains:

```python
from nexusx.mcp import Application, create_multi_app_mcp_server

mcp = create_multi_app_mcp_server(
    apps=[
        Application(
            name="blog",
            base=BlogBase,
            url="sqlite+aiosqlite:///blog.db",
            description="Blog API",
        ),
        Application(
            name="shop",
            base=ShopBase,
            url="sqlite+aiosqlite:///shop.db",
            description="Shop API",
        ),
    ],
    name="Multi-App API",
)
mcp.run()
```

Each `Application` owns its database connection, so the merging project does not
need to provide `session_factory` or any other connection resource — `pip install`
a subproject's package, import its `Application`, and pass it to `create_multi_app_mcp_server`.

Multi-app adds app-level navigation tools:

| Tool | Purpose |
|------|---------|
| `list_apps()` | List all available apps |
| `list_queries(app_name)` | List queries for an app |
| `get_query_schema(entity, method, app_name)` | Get one grouped query's schema |
| `graphql_query(query, app_name)` | Execute query |

Passing `allow_mutation=True` adds `list_mutations`,
`get_mutation_schema`, and `graphql_mutation`. Mutation tools are not
registered in the default read-only mode.

!!! tip
    Use `create_single_app_mcp_server` for single-app scenarios — fewer tool calls, simpler interaction. Only reach for `create_multi_app_mcp_server` when the AI agent genuinely needs to cross domain boundaries.

## Step 4: Exporting Apps as Standalone Packages

Because each `Application` is self-contained, you can ship it as a Python package
and assemble multiple subprojects into a single MCP gateway:

```python
# In subproject blog_app/__init__.py
from nexusx.mcp import Application
blog = Application(name="blog", base=BlogBase, url=BLOG_DATABASE_URL)

# In the gateway project
from blog_app import blog
from shop_app import shop
from nexusx.mcp import create_multi_app_mcp_server

mcp = create_multi_app_mcp_server(apps=[blog, shop], name="Gateway")
mcp.run()
```

The gateway project's full source for assembling three subprojects is typically
under 10 lines — `pip install blog-app shop-app auth-app`, import, pass to
`create_multi_app_mcp_server`, run.

!!! note
    The legacy `AppConfig` dict form (`{"name": ..., "base": ..., "session_factory": ...}`)
    still works but emits a `DeprecationWarning`. Prefer `Application(...)` for
    new code.

## Recap

- `create_single_app_mcp_server` — single app, 2 tools by default; opt in to mutations
- `create_multi_app_mcp_server` — multiple apps via `Application` instances, app-level navigation for cross-domain queries
- `Application` — self-contained, independently-exportable unit (URL/engine/session_factory at most one)
- Both MCP constructors support `stdio` (CLI) and `streamable-http` (HTTP) transport
- `session_factory` is needed when your operations or relationship loaders access the database

## Next Steps

- [UseCase Service](./use_case_service.md) — Business logic services for MCP + REST dual-mode
- [GraphQL Mode](../guide/graphql_mode.md) — The GraphQL API used under the hood by MCP
