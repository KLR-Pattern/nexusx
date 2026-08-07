# 快速开始

30 秒内从 SQLModel 实体到可运行的 GraphQL API。

## 安装

```bash
pip install nexusx
```

## 第 1 步：定义 SQLModel 实体

像平常一样创建你的实体：

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

没有什么特别的——这些都是标准的 SQLModel 类。

## 第 2 步：添加 `@query` 和 `@mutation`

直接在实体上添加查询和变更方法，nexusx 会自动发现它们：

```python
from nexusx import query, mutation

class Post(SQLModel, table=True):
    # ... 字段同上 ...

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
    第一个参数必须是 `cls`——装饰器会自动将它转为 classmethod。方法的 docstring 会成为 GraphQL 字段的描述。

## 第 3 步：创建 GraphQLHandler

用 `GraphQLHandler` 把一切串起来：

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
    `session_factory` 是**必须的**——DataLoader 需要它来执行批量查询。没有它，关系加载将无法工作。

## 第 4 步：启动并查询

```bash
uvicorn app:app
```

打开 http://localhost:8000/graphql，试试这个查询：

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

框架会遍历 GraphQL 选择树，逐层收集 FK 值，并通过 DataLoader 批量加载关系。**无论返回多少条记录，每个关系只需一次查询。**

## 回顾

- 你定义的是标准 SQLModel 实体——不需要任何框架特定的基类
- `@query` 和 `@mutation` 装饰器将方法变成 GraphQL 字段
- `GraphQLHandler` 自动发现实体并生成完整的 GraphQL schema
- DataLoader 通过批量加载自动解析关系——没有 N+1 问题

## 下一步

现在你有了一个可运行的 API，接下来了解 [GraphQL 模式](./graphql_mode.zh.md)的完整能力。
