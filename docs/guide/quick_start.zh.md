# 快速开始

用一个可直接运行的文件，从 SQLModel 实体构建并查询 GraphQL API。

## 安装

```bash
pip install "nexusx[demo]"
```

## 创建应用

创建 `app.py`：

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

`StaticPool` 让内存 SQLite 数据库可以在多个异步 session 之间共享。真实项目中，
可以把 URL 替换为持久化 SQLite 或 PostgreSQL 数据库地址。

## 启动并查询

```bash
uvicorn app:app --reload
```

打开 `http://127.0.0.1:8000/graphql`，执行：

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

响应中会包含启动时写入的 team 和 hero：

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

## nexusx 自动生成了什么

- `AutoQueryConfig()` 为两个实体添加了 `by_id` 和 `by_filter` 查询入口。
- `GraphQLHandler` 根据 SQLModel 类型生成了 GraphQL schema。
- `Team.heroes` 通过 DataLoader 批量加载，不需要手写关系 resolver。

经过测试的源码也可以在
[`examples/quickstart.py`](https://github.com/KLR-Pattern/nexusx/blob/master/examples/quickstart.py)
中找到。

下一步阅读 [GraphQL 模式](./graphql_mode.zh.md)，学习如何定义自定义 query 和
mutation。
