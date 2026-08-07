# GraphQL Mode

The full picture of how nexusx turns your SQLModel entities into a complete GraphQL API — SDL auto-generation, entity discovery, and DataLoader batch loading.

You've seen the basics in [Quick Start](./quick_start.md). This page explains how each piece works.

## Step 1: How Operations Are Grouped

`@query` and `@mutation` methods keep their Python names and are grouped under
their entity:

| Entity | Method | GraphQL Path |
|--------|--------|--------------|
| `Post` | `get_all` | `Query.Post.get_all` |
| `Post` | `create` | `Mutation.Post.create` |
| `User` | `get_by_id` | `Query.User.get_by_id` |

### Method definition rules

```python
from nexusx import query, mutation
from sqlmodel import SQLModel, Field, Relationship, select

class Post(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="user.id")
    author: User | None = Relationship()

    @query
    async def get_all(cls, limit: int = 10) -> list['Post']:
        """Get all posts."""
        async with get_session() as session:
            return (await session.exec(select(cls).limit(limit))).all()

    @mutation
    async def create(cls, title: str, author_id: int) -> 'Post':
        """Create a new post."""
        async with get_session() as session:
            post = cls(title=title, author_id=author_id)
            session.add(post)
            await session.commit()
            await session.refresh(post)
            return post
```

- The first parameter must be `cls` — the decorator converts it to a classmethod
- The method's docstring becomes the GraphQL field description
- `query_meta` parameters are internal only — they don't appear in the SDL

!!! tip
    If you want to skip writing `@query` methods entirely, see [Auto Query](./graphql_auto_query.md) — it auto-generates `by_id` and `by_filter` for every entity.

## Step 2: How Entities Get Discovered

You don't need to register entities manually. nexusx discovers them through two rules:

1. **Direct discovery**: SQLModel subclasses with `@query` or `@mutation` are found automatically
2. **Recursive inclusion**: Entities referenced via relationships are pulled in, even without decorators

```python
# User has no @query methods — but it still appears in the schema
# because Post.author references it
class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str

class Post(SQLModel, table=True):
    @query
    async def get_all(cls) -> list['Post']:
        ...
    author: User | None = Relationship()  # → User is included
```

!!! info
    Entities without decorators **and** without relationship references from other discovered entities are **not** included in the schema.

## Step 3: How Relationships Resolve Automatically

This is the core value of GraphQL mode. Try querying a relationship:

```graphql
{
  Post {
    get_all(limit: 5) {
      id
      title
      author { name email }
    }
  }
}
```

### What happens behind the scenes

The framework resolves this in layers:

1. Execute `Post.get_all` — fetch 5 Posts
2. Collect `author_id` from those 5 Posts
3. **One** batch query to load all referenced Users
4. Map each User back to its Post

```
Post[author_id=1] ──┐
Post[author_id=2] ──┤  collect    batch load     map back
Post[author_id=1] ──┤  ──────→   ─────────→     ────────→  response
Post[author_id=3] ──┤  [1,2,3]   Users query     author
Post[author_id=2] ──┘
```

**No matter how many results, each relationship executes only one query.** This is the DataLoader pattern — N+1 prevention is built in.

### Supported relationship types

| Type | Direction | Example |
|------|-----------|---------|
| `MANYTOONE` | Post → User via FK | `Post.author` |
| `ONETOMANY` | User → Posts via Relationship | `User.posts` |
| `MANYTOMANY` | Via intermediate table | `Post.tags` |

All types work the same way: collect keys, batch load, map back.

## Step 4: Explore with GraphiQL

Add an interactive query interface:

```python
from fastapi.responses import HTMLResponse

@app.get("/graphql", response_class=HTMLResponse)
async def graphiql():
    return handler.get_graphiql_html()
```

Visit `/graphql` in your browser to get:
- Schema exploration with autocomplete
- Query history
- Real-time response preview

## Execution Flow

The full pipeline from query string to response:

```
GraphQL query string
  → QueryParser: parse into FieldSelection tree
  → Execute root fields (@query methods)
  → Traverse selection tree layer by layer
  → Collect FK values → DataLoader batch loads
  → Assemble response JSON
```

Each layer resolves in parallel — all relationships at the same depth are batch-loaded together.

## Recap

- Operations are grouped by entity — for example `Post.get_all` and `User.get_by_id`
- Entity discovery is recursive — related entities are included even without `@query`
- Relationships resolve automatically via DataLoader — one query per relationship, no N+1
- All three relationship types (many-to-one, one-to-many, many-to-many) are supported

## Next Steps

- [GraphQL Pagination](./graphql_pagination.md) — Add `limit`/`offset` pagination for list relationships
- [Auto Query](./graphql_auto_query.md) — Skip `@query` and auto-generate `by_id` / `by_filter`
- [Core API Mode](./core_api.md) — Build REST responses using the same DataLoader infrastructure
