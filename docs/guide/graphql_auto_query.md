# Auto Query

Writing `@query` methods for basic CRUD is repetitive. Auto Query generates `by_id` and `by_filter` for every entity — no decorators needed.

## Step 1: Enable AutoQueryConfig

One parameter on `GraphQLHandler`:

```python
from nexusx import GraphQLHandler, AutoQueryConfig

handler = GraphQLHandler(
    base=SQLModel,
    session_factory=async_session,
    auto_query_config=AutoQueryConfig(),
)
```

`AutoQueryConfig` contains query policy only. The database connection is owned
by `GraphQLHandler`.

You can also add auto queries to an existing handler:

```python
from nexusx import AutoQueryConfig, GraphQLHandler, add_standard_queries

add_standard_queries(
    entities=[User, Post],
    config=AutoQueryConfig(),
    session_factory=async_session,
)
handler = GraphQLHandler(base=SQLModel, session_factory=async_session)
```

## Step 2: Use `by_id` for Single Records

Auto-generated for each entity with exactly one primary key field:

```graphql
{ User { by_id(id: 1) { name email } } }
{ Post { by_id(id: 42) { title author { name } } } }
```

That's it — no `@query` method needed. The framework reads your primary key field and generates the query.

## Step 3: Use `by_filter` for Field Matching

Each entity also gets a `FilterInput` type and a filter query:

```graphql
{ User { by_filter(filter: { name: "Alice" }, limit: 5) { id name email } } }
{ Post { by_filter(filter: { author_id: 1 }, limit: 10) { id title } } }
```

`FilterInput` fields correspond one-to-one with entity fields (excluding relationship fields), supporting exact-match filtering.

!!! tip
    `by_filter` is exact-match only — no `LIKE`, range queries, or ordering. For anything more complex, write a custom `@query` method. Auto and manual queries coexist in the same schema.

## When Auto Queries Fall Short

Auto queries cover common patterns, but they have limits:

| Limitation | Detail |
|------------|--------|
| **Composite primary keys** | `by_id` only supports single PK fields — composite PK entities won't get a `by_id` query |
| **Exact match only** | `by_filter` doesn't support `LIKE`, range queries, or ordering |
| **No joins or aggregation** | These are read-only single-table queries |

When you hit these limits, write a `@query` method — it coexists naturally:

```python
class Post(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str

    @query
    async def get_recent(cls, days: int = 7) -> list['Post']:
        """Get posts from the last N days."""
        ...

handler = GraphQLHandler(
    base=SQLModel,
    session_factory=async_session,
    auto_query_config=AutoQueryConfig(),
)
```

The resulting schema contains all three:

- `Post.by_id`, `Post.by_filter` — auto-generated
- `Post.get_recent` — your custom query

## Recap

- `AutoQueryConfig` generates `by_id` and `by_filter` for every entity with a single primary key
- `by_id` looks up a single record by PK; `by_filter` does exact-match field filtering
- Auto and manual `@query` methods coexist in the same schema
- For complex queries (ranges, joins, aggregation), write a custom `@query`

## Next Steps

- [Core API Mode](./core_api.md) — Build REST responses using the same entity graph
- [GraphQL Pagination](./graphql_pagination.md) — Add pagination to list relationships
