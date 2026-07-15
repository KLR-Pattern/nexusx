# MCP API Reference

Create MCP services for AI agent integration with GraphQL-based tools.

## create_simple_mcp_server

Create a single-app MCP service with GraphQL-based tools.

```python
from nexusx.mcp import create_simple_mcp_server

mcp = create_simple_mcp_server(
    base=SQLModel,              # SQLModel base class
    name="My API",              # Service name
    session_factory=async_session,  # Session factory
)
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `base` | `type` | Yes | SQLModel base class |
| `name` | `str` | Yes | Service name |
| `session_factory` | `Callable` | No | Session factory |

!!! tip
    Use the simple server when you have a single application or are just getting started with MCP integration. It provides a straightforward interface with three core tools: schema inspection, query execution, and mutation execution.

### Generated Tools

| Tool | Description |
|------|-------------|
| `get_schema()` | Get GraphQL schema |
| `graphql_query(query)` | Execute GraphQL query |
| `graphql_mutation(mutation)` | Execute GraphQL mutation |

## create_mcp_server

Create a multi-app MCP service that manages multiple applications.

```python
from nexusx.mcp import create_mcp_server

mcp = create_mcp_server(
    apps=[
        {"name": "blog", "base": BlogBase, "description": "Blog API"},
        {"name": "shop", "base": ShopBase, "description": "Shop API"},
    ],
    name="Multi-App API",
)
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `apps` | `list[dict]` | Yes | Application configuration list |
| `name` | `str` | Yes | Service name |

!!! tip
    Use the multi-app server when you have multiple distinct domains or bounded contexts (like a blog API and a shop API) that you want to expose as separate apps. This keeps tools organized and allows agents to discover and query each domain independently.

### Generated Tools

| Tool | Description |
|------|-------------|
| `list_apps()` | List all applications |
| `list_queries(app_name)` | List queries for an app |
| `get_query_schema(name, app_name)` | Get query schema |
| `graphql_query(query, app_name)` | Execute query |

## Application

`Application` is the self-contained, independently-exportable unit for multi-app scenarios.
Each `Application` owns its SQLModel `base` plus a complete database connection
(URL / engine / session factory — at most one), so an app can be packaged as a
Python distribution and assembled into a merging project's MCP server without
re-declaring connection resources.

```python
from nexusx.mcp import Application, create_mcp_server

blog = Application(
    name="blog",
    base=BlogBaseEntity,
    url="postgresql+asyncpg://user:pass@host/blog",  # app owns the engine
    description="Blog system API",
)
shop = Application(
    name="shop",
    base=ShopBaseEntity,
    url="postgresql+asyncpg://user:pass@host/shop",
)

mcp = create_mcp_server(apps=[blog, shop], name="Multi-App API")
```

### Standalone usage (no MCP server required)

An `Application` can also be used independently — for documentation generation,
schema introspection, or scripts that need direct GraphQL access:

```python
from nexusx.mcp import Application

# Schema-only mode: no database connection needed for SDL/introspection
app = Application(name="blog", base=BlogBaseEntity)
print(app.resources.sdl_generator.generate())   # GraphQL SDL
print(app.resources.entity_names)               # set of entity class names

# With a database URL, the Application owns its engine
async with Application(name="blog", base=BlogBaseEntity,
                       url="sqlite+aiosqlite:///blog.db") as app:
    async with app.session_factory() as session:
        # Use the session directly for queries
        ...
    # engine.dispose() called automatically on context exit
```

### Resource ownership

| Construction mode | Owns engine? | `dispose()` behavior |
|---|---|---|
| `url="..."` | Yes | `await engine.dispose()` (idempotent) |
| `engine=<existing>` | No | No-op (caller owns the engine) |
| `session_factory=<existing>` | No | No-op |
| None provided (schema-only) | N/A | No-op |

### URL credential redaction

When constructed with `url=`, the password is automatically redacted in
`repr(app)`, error messages, and logs (FR-013):

```
Application(name='blog', url='postgresql+asyncpg://user:***@host/blog', owned=True)
```

## AppConfig

Multi-app configuration type that defines each application's structure.

> **Deprecated**: prefer `Application` instances. The dict form is accepted for
> backward compatibility and triggers a `DeprecationWarning`.

The `apps` parameter in `create_mcp_server` accepts a list of dictionaries with these fields:

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Application name |
| `base` | `type` | SQLModel base class |
| `description` | `str` | Application description |
| `session_factory` | `Callable` | Session factory |
| `url` | `str` | Database URL (alternative to `session_factory`) |
| `engine` | `AsyncEngine` | External engine (alternative to `session_factory`) |
| `aliases` | `list[str]` | Optional routing aliases |

