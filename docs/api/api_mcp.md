# MCP API Reference

Create MCP services for AI agent integration with GraphQL-based tools.

## create_single_app_mcp_server

Create a single-app MCP service with GraphQL-based tools.

```python
from nexusx.mcp import create_single_app_mcp_server

mcp = create_single_app_mcp_server(
    base=SQLModel,
    name="My API",
    session_factory=async_session,
    allow_mutation=False,
)
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `base` | `type` | Yes | SQLModel base class |
| `name` | `str` | No | Service name; defaults to `"nexusx API"` |
| `desc` | `str \| None` | No | Query and mutation schema description |
| `allow_mutation` | `bool` | No | Register mutation support; defaults to `False` |
| `session_factory` | `Callable \| None` | No | Async session factory for database-backed loaders |
| `enable_pagination` | `bool` | No | Wrap list relationships with pagination metadata |
| `auto_query_config` | `AutoQueryConfig \| None` | No | Generate standard `by_id` / `by_filter` queries |

!!! tip
    Use the simple server for a single application. It is read-only by default; opt in to mutation tools only when the agent needs write access.

### Generated Tools

| Tool | Description |
|------|-------------|
| `get_schema()` | Get GraphQL schema |
| `graphql_query(query)` | Execute GraphQL query |

With `allow_mutation=True`, the server additionally registers
`graphql_mutation(mutation)`.

## create_multi_app_mcp_server

Create a multi-app MCP service that manages multiple applications.

```python
from nexusx.mcp import Application, create_multi_app_mcp_server

mcp = create_multi_app_mcp_server(
    apps=[
        Application(name="blog", base=BlogBase, url=BLOG_DATABASE_URL),
        Application(name="shop", base=ShopBase, url=SHOP_DATABASE_URL),
    ],
    name="Multi-App API",
)
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `apps` | `list[Application \| dict]` | Yes | Applications; dict entries are deprecated |
| `name` | `str` | No | Service name |
| `allow_mutation` | `bool` | No | Register mutation navigation and execution tools |

!!! tip
    Use the multi-app server when you have multiple distinct domains or bounded contexts (like a blog API and a shop API) that you want to expose as separate apps. This keeps tools organized and allows agents to discover and query each domain independently.

### Generated Tools

| Tool | Description |
|------|-------------|
| `list_apps()` | List all applications |
| `list_queries(app_name)` | List queries for an app |
| `get_query_schema(entity, method, app_name, response_type="sdl")` | Get query schema |
| `graphql_query(query, app_name)` | Execute query |

With `allow_mutation=True`, the server also registers `list_mutations`,
`get_mutation_schema`, and `graphql_mutation`.

## Application

`Application` is the self-contained, independently-exportable unit for multi-app scenarios.
Each `Application` owns its SQLModel `base` plus a complete database connection
(URL / engine / session factory — at most one), so an app can be packaged as a
Python distribution and assembled into a merging project's MCP server without
re-declaring connection resources.

```python
from nexusx.mcp import Application, create_multi_app_mcp_server

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

mcp = create_multi_app_mcp_server(apps=[blog, shop], name="Multi-App API")
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

## Legacy dict configuration

Multi-app configuration type that defines each application's structure.

> **Deprecated**: prefer `Application` instances. The dict form is accepted for
> backward compatibility and triggers a `DeprecationWarning`.

The `apps` parameter still accepts dictionaries with these fields:

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Application name |
| `base` | `type` | SQLModel base class |
| `description` | `str` | Application description |
| `session_factory` | `Callable` | Session factory |
| `url` | `str` | Database URL (alternative to `session_factory`) |
| `engine` | `AsyncEngine` | External engine (alternative to `session_factory`) |
| `aliases` | `list[str]` | Optional routing aliases |
