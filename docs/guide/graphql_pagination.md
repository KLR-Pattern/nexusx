# GraphQL Pagination

List relationships can return hundreds or thousands of records. Pagination lets clients request only what they need — with `limit` / `offset` / `fetchAll` parameters on any list relationship.

**2026-11 pagination contract:** volume intent is mandatory — every paginated
field query declares `limit` **or** `fetchAll`; there is no default page size.
`fetchAll: true` overrides `limit`/`offset` (literal wins) and is bounded by a
server-side hard cap (`max_fetch_all`, default 10000 — errors, never truncates).
This mirrors GitHub's GraphQL API, which likewise requires an explicit page size.

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

## Step 2: Query with `limit` (or `fetchAll`)

Declaring `order_by` IS the opt-in — the field automatically becomes a
paginated field with `{ items, pagination }` shape and volume parameters
(no global toggle; the former `enable_pagination` flag was removed):

```graphql
{
  User {
    get_all {
      name
      posts(limit: 3) {          # volume intent is REQUIRED — no default page size
        items { title }
        pagination { has_more total_count }
      }
    }
  }
}
```

Fetching everything, explicitly:

```graphql
posts(fetchAll: true) { items { title } pagination { total_count } }   # overrides limit/offset
```

Omitting both raises a validation error with guidance — a list query never
silently truncates to a hidden default.

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
| `limit` | `Int` | Number of items per page (required unless `fetchAll`) |
| `offset` | `Int` | Starting position, 0-based (defaults to 0) |
| `fetchAll` | `Boolean` | Fetch the entire collection — overrides limit/offset (bounded by `max_fetch_all`) |

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

- Add `order_by` to list relationships — required, must use `"Entity.column"` string format; declaring it IS the opt-in
- Query with `limit` or `fetchAll` (volume intent is mandatory — no default page size)
- Each paginated field returns `{ items, pagination }`
- Use `has_more` for "load more" UI, `total_count` for progress indicators
- `fetchAll` for explicit full fetches; agents should check `total_count` first

## Next Steps

- [Auto Query](./graphql_auto_query.md) — Skip `@query` and auto-generate `by_id` / `by_filter`
- [Core API Mode](./core_api.md) — Build REST responses using the same DataLoader infrastructure
