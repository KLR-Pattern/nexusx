# GraphQLHandler API

Core entry point for GraphQL mode — generate SDL, execute queries, and integrate GraphiQL.

## GraphQLHandler

Create a handler to manage GraphQL schema generation and query execution.

```python
from nexusx import GraphQLHandler

handler = GraphQLHandler(
    base=SQLModel,                    # SQLModel base class (auto-discover entities)
    session_factory=async_session,    # Async session factory (required)
    enable_pagination=False,          # Enable list relationship pagination
    auto_query_config=None,           # AutoQueryConfig for auto queries
)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `base` | `type` | — | SQLModel base class for auto-discovering entities |
| `session_factory` | `Callable` | — | Async session factory function |
| `enable_pagination` | `bool` | `False` | Enable list relationship pagination |
| `auto_query_config` | `AutoQueryConfig` | `None` | Auto query configuration |

!!! warning
    You must provide `session_factory` — without it, DataLoader cannot load relationship data and queries will fail.

!!! tip
    Enable `auto_query_config` to automatically generate `by_id` and `by_filter` queries for all your entities. This is especially useful during development and for CRUD operations.

### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `execute` | `async execute(query, variables=None, operation_name=None) -> dict` | Execute a GraphQL operation |
| `get_sdl` | `get_sdl(include_mutations: bool = True) -> str` | Render the current SDL |
| `get_graphiql_html` | `get_graphiql_html(endpoint: str = "/graphql") -> str` | Get GraphiQL HTML |

## @query Decorator

Mark a method as a GraphQL query field.

```python
from nexusx import query

class Post(SQLModel, table=True):
    @query
    async def get_all(cls, limit: int = 10) -> list['Post']:
        """Get all posts."""
        ...
```

- The decorator automatically converts the method to a classmethod
- The docstring becomes the GraphQL field description
- The first parameter must be `cls`
- `query_meta` parameters do not appear in the SDL

## @mutation Decorator

Mark a method as a GraphQL mutation field.

```python
from nexusx import mutation

class Post(SQLModel, table=True):
    @mutation
    async def create(cls, title: str, author_id: int) -> 'Post':
        """Create a new post."""
        ...
```

Follows the same rules as `@query`.

## AutoQueryConfig

Configure automatic query generation for standard CRUD operations.

```python
from nexusx import AutoQueryConfig

config = AutoQueryConfig()
```

Auto-generates `by_id` and `by_filter` queries for all entities. Requires entities to have exactly one primary key field.

!!! tip
    Use `AutoQueryConfig` when you want quick CRUD access without manually writing `@query` methods for each entity. You can always add custom queries alongside the auto-generated ones.

## QueryParser

Parse GraphQL query strings into `FieldSelection` trees. Typically not used directly — the handler invokes this automatically during query execution.

## FieldSelection

Represents a field and its sub-selections in a GraphQL selection set. This is the output type from `QueryParser` and is used internally during query execution.

## add_standard_queries

Register standard query methods on entity classes before building a handler.

```python
from nexusx import add_standard_queries

add_standard_queries(
    entities=[User, Post],
    config=AutoQueryConfig(),
    session_factory=async_session,
)
handler = GraphQLHandler(base=SQLModel, session_factory=async_session)
```
