# GraphQL Pagination

List relationships can return hundreds or thousands of records. Pagination lets clients request only what they need — with `limit` and `offset` parameters on any list relationship.

## The Problem

Without pagination, a query like this returns **every** post for every user:

```graphql
{
  User {
    get_all {
      name
      posts { title }
    }
  }
}
```

If Alice has 200 posts, all 200 come back. For 50 users with 200 posts each, that's 10,000 records in a single response.

## Step 1: Add `order_by` to Your Relationship

Pagination requires a deterministic sort order. Add `order_by` to the list relationship using the `"Entity.column"` string format:

```python
from sqlmodel import SQLModel, Field, Relationship

class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    posts: list["Post"] = Relationship(
        back_populates="author",
        sa_relationship_kwargs={"order_by": "Post.id"},
    )
```

!!! warning
    Relationships **without** `order_by` will not generate pagination support. You must use the `"Entity.column"` string format — column objects are not supported.

## Step 2: Enable Pagination in GraphQLHandler

One parameter turns it on globally:

```python
from nexusx import GraphQLHandler

handler = GraphQLHandler(
    base=SQLModel,
    session_factory=async_session,
    enable_pagination=True,
)
```

## Step 3: Query with `limit` and `offset`

Now list relationships accept pagination arguments:

```graphql
{
  User {
    get_all {
      name
      posts(limit: 3, offset: 0) {
        items { title }
        pagination { has_more total_count }
      }
    }
  }
}
```

### Response structure

Each paginated relationship returns `{ items, pagination }`:

```json
{
  "User": {
    "get_all": [
      {
        "name": "Alice",
        "posts": {
          "items": [
            { "title": "First Post" },
            { "title": "Second Post" },
            { "title": "Third Post" }
          ],
          "pagination": {
            "has_more": true,
            "total_count": 15
          }
        }
      }
    ]
  }
}
```

| Field | Type | Meaning |
|-------|------|---------|
| `items` | `[Type]` | The records for this page |
| `pagination.has_more` | `Boolean!` | Whether more data exists beyond this page |
| `pagination.total_count` | `Int!` | Total record count across all pages |
| `limit` | `Int` | Number of items per page (query parameter) |
| `offset` | `Int` | Starting position, 0-based (query parameter) |

Use `has_more` to decide whether to fetch the next page. Use `total_count` to display "showing 1-3 of 15".

## How It Works

??? info "Technical Details"
    The framework uses SQL `ROW_NUMBER()` window function for pagination:

    ```sql
    SELECT * FROM (
      SELECT *, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY id) as rn
      FROM post
      WHERE user_id IN (...)
    ) WHERE rn > offset AND rn <= offset + limit
    ```

    This approach fetches both paginated data and total count in a single query — and works correctly even when multiple parents are being resolved simultaneously (each user gets its own `PARTITION BY` group).

## Recap

- Add `order_by` to list relationships — required, must use `"Entity.column"` string format
- Set `enable_pagination=True` on `GraphQLHandler` — one-time configuration
- Query with `limit` and `offset` — each paginated field returns `{ items, pagination }`
- Use `has_more` for "load more" UI, `total_count` for progress indicators

## Next Steps

- [Auto Query](./graphql_auto_query.md) — Skip `@query` and auto-generate `by_id` / `by_filter`
- [Core API Mode](./core_api.md) — Build REST responses using the same DataLoader infrastructure
