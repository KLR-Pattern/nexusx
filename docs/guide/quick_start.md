# Quick Start

Build and query a GraphQL API from SQLModel entities in one runnable file.

## Install

```bash
pip install "nexusx[demo]"
```

## Create the Application

Create `app.py`:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Relationship, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx import AutoQueryConfig, GraphQLHandler


class BaseEntity(SQLModel):
    pass


class Team(BaseEntity, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    heroes: list["Hero"] = Relationship(back_populates="team")


class Hero(BaseEntity, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    team_id: int | None = Field(default=None, foreign_key="team.id")
    team: Team | None = Relationship(back_populates="heroes")


engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
)
session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
handler = GraphQLHandler(
    base=BaseEntity,
    session_factory=session_factory,
    auto_query_config=AutoQueryConfig(),
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)

    async with session_factory() as session:
        team = Team(name="Avengers")
        session.add(team)
        await session.flush()
        session.add(Hero(name="Spider-Man", team_id=team.id))
        await session.commit()

    try:
        yield
    finally:
        await handler.aclose()
        await engine.dispose()


app = FastAPI(lifespan=lifespan)


class GraphQLRequest(BaseModel):
    query: str


@app.get("/graphql", response_class=HTMLResponse)
async def graphiql() -> str:
    return handler.get_graphiql_html()


@app.post("/graphql")
async def graphql(request: GraphQLRequest):
    return await handler.execute(request.query)
```

`StaticPool` keeps the in-memory SQLite database shared across async sessions.
For a real application, replace the URL with a persistent SQLite or PostgreSQL
database URL.

## Run and Query

```bash
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000/graphql` and run:

```graphql
{
  Team {
    by_filter {
      id
      name
      heroes {
        id
        name
      }
    }
  }
}
```

The response contains the seeded team and hero:

```json
{
  "data": {
    "Team": {
      "by_filter": [
        {
          "id": 1,
          "name": "Avengers",
          "heroes": [{"id": 1, "name": "Spider-Man"}]
        }
      ]
    }
  }
}
```

## What nexusx Generated

- `AutoQueryConfig()` added `by_id` and `by_filter` query roots for both entities.
- `GraphQLHandler` generated the GraphQL schema from the SQLModel types.
- The `Team.heroes` relationship is loaded through DataLoader batching, without
  a hand-written relationship resolver.

The tested source is also available at
[`examples/quickstart.py`](https://github.com/allmonday/nexusx/blob/master/examples/quickstart.py).

Next, read [GraphQL Mode](./graphql_mode.md) to define custom queries and
mutations.
