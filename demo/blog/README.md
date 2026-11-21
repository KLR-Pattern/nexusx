# nexusx Blog Demo

A complete blog API — Users, Posts, Comments, and favorites — built with nexusx. You'll see how `@query` / `@mutation` decorators turn SQLModel entities into a working GraphQL API with zero boilerplate.

## Run the Demo

```bash
# From project root
uv sync --extra demo

# Start the server
uv run uvicorn demo.blog.app:app --reload
```

Then open **http://localhost:8000/graphql** in your browser. You'll see the GraphiQL interface.

## Try It

### Query users and their posts

```graphql
{
  userGetUsers(limit: 10) {
    id
    name
    email
    posts(limit: 5) {
      items {
        id
        title
        content
      }
    }
  }
}
```

### Query posts with author info

```graphql
{
  postGetPosts(limit: 10) {
    id
    title
    content
    author {
      id
      name
      email
    }
    comments(limit: 3) {
      items {
        content
        author {
          name
        }
      }
    }
  }
}
```

### Create a user and a post

```graphql
mutation {
  userCreateUser(name: "Charlie", email: "charlie@example.com") {
    id
    name
  }
}

mutation {
  postCreatePost(title: "Hello nexusx", content: "My first post!", authorId: 1) {
    id
    title
    author {
      name
    }
  }
}
```

### Add a post to favorites (many-to-many)

```graphql
mutation {
  userAddFavorite(userId: 1, postId: 1) {
    id
    name
    favoritePosts {
      id
      title
    }
  }
}
```

!!! tip
    All mutations in this demo are **idempotent** — running them twice won't create duplicates. This makes it safe to experiment in the GraphiQL interface.

## What You'll See in This Demo

| Feature | Where to look |
|---------|---------------|
| `@query` / `@mutation` decorators | `models.py` — each entity has its own queries |
| Auto-generated queries | `app.py` — `AutoQueryConfig` adds `by_id` / `by_filter` for free |
| DataLoader batch loading | Every query with nested relationships — no N+1 |
| Many-to-many relationships | `User ↔ Post` via `UserFavoritePost` link table |
| GraphiQL UI | `http://localhost:8000/graphql` |

## How It Works

The demo has three files:

```
demo/blog/
├── models.py     # SQLModel entities with @query / @mutation decorators
├── app.py        # GraphQLHandler + FastAPI app + GraphiQL
└── database.py   # Database setup and seed data
```

1. **You define entities** in `models.py` — standard SQLModel classes with `@query` and `@mutation` methods
2. **`GraphQLHandler` scans** all entities and auto-generates the GraphQL schema (SDL)
3. **When a query arrives**, the handler parses it and calls the matching methods
4. **Relationships are resolved** level-by-level via DataLoader — no matter how many records, each relationship requires only one SQL query

## Endpoints

| URL | Description |
|-----|-------------|
| `GET /graphql` | GraphiQL interactive UI |
| `POST /graphql` | GraphQL query endpoint |
| `GET /schema` | SDL schema in plain text |
| `GET /docs` | FastAPI auto-generated docs |
| `GET /` | Usage instructions and example queries |

## What's Next

- [Quick Start](../../docs/guide/quick_start.md) — Build your own GraphQL API from scratch
- [GraphQL Mode](../../docs/guide/graphql_mode.md) — Deep dive into the full workflow
- [Core API Mode](../../docs/guide/core_api.md) — Build REST responses with `DefineSubset`
