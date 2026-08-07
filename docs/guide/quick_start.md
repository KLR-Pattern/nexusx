# Quick Start

From SQLModel entities to a working GraphQL API in 30 seconds.

## Installation

```bash
pip install nexusx
```

## Step 1: Define SQLModel Entities

Create your entities just like you normally would with SQLModel:

```python
from sqlmodel import SQLModel, Field, Relationship, select

class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str
    posts: list["Post"] = Relationship(back_populates="author")

class Post(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="user.id")
    author: User | None = Relationship(back_populates="posts")
```

Nothing new here — these are standard SQLModel classes with relationships.

## Step 2: Add `@query` and `@mutation`

Add query and mutation methods directly on your entities. nexusx will discover them automatically:

```python
from nexusx import query, mutation

class Post(SQLModel, table=True):
    # ... fields as above ...

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

!!! tip
    The first parameter must be `cls` — the decorator converts it to a classmethod automatically. The method's docstring becomes the GraphQL field description.

## Step 3: Create GraphQLHandler

Wire everything up with a `GraphQLHandler`:

```python
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from nexusx import GraphQLHandler

handler = GraphQLHandler(base=SQLModel, session_factory=async_session)

class GraphQLRequest(BaseModel):
    query: str

app = FastAPI()

@app.get("/graphql", response_class=HTMLResponse)
async def graphiql():
    return handler.get_graphiql_html()

@app.post("/graphql")
async def graphql(req: GraphQLRequest):
    return await handler.execute(req.query)
```

!!! warning
    `session_factory` is **required** — DataLoader needs it to execute batch queries. Without it, relationship resolution won't work.

## Step 4: Run and Query

```bash
uvicorn app:app
```

Open http://localhost:8000/graphql and try this query:

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

The framework traverses the GraphQL selection tree, collects FK values layer by layer, and batch-loads relationships via DataLoader. **No matter how many records are returned, each relationship requires only one query.**

## Recap

- You define standard SQLModel entities — no framework-specific base class needed
- `@query` and `@mutation` decorators turn methods into GraphQL fields
- `GraphQLHandler` auto-discovers entities and generates the full GraphQL schema
- DataLoader resolves relationships automatically with batch loading — no N+1

## Next Steps

Now that you have a working API, learn about the full capabilities of [GraphQL Mode](./graphql_mode.md).
