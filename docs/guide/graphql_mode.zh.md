# GraphQL 模式

从 SQLModel 实体到完整的 GraphQL API——SDL 自动生成、关系自动解析、DataLoader 批量加载。

## 从 GraphQLHandler 开始

```python
from nexusx import GraphQLHandler

handler = GraphQLHandler(
    base=SQLModel,          # SQLModel 基类，用于自动发现实体
    session_factory=async_session,  # 异步 session 工厂（必须提供）
)
```

!!! warning
    `session_factory` 是**必须的**——DataLoader 需要它来执行批量查询。如果不提供，关系加载会失败。

## `@query` 和 `@mutation` 装饰器

在 SQLModel 实体上标记查询和变更方法：

```python
from nexusx import query, mutation

class Post(SQLModel, table=True):
    # ... 字段定义 ...

    @query
    async def get_all(cls, limit: int = 10) -> list['Post']:
        async with get_session() as session:
            return (await session.exec(select(cls).limit(limit))).all()

    @mutation
    async def create(cls, title: str, author_id: int) -> 'Post':
        async with get_session() as session:
            post = cls(title=title, author_id=author_id)
            session.add(post)
            await session.commit()
            await session.refresh(post)
            return post
```

### 操作分组规则

`@query` / `@mutation` 方法保留 Python 方法名，并按实体分组：

| 实体 | 方法 | GraphQL 路径 |
|------|------|-------------|
| `Post` | `get_all` | `Query.Post.get_all` |
| `Post` | `create` | `Mutation.Post.create` |
| `User` | `get_by_id` | `Query.User.get_by_id` |

### 方法定义规则

- 第一个参数必须是 `cls`——装饰器会自动将其转为 classmethod
- 方法的 docstring 会成为 GraphQL 字段的描述
- `query_meta` 参数不会出现在 SDL 中（内部机制）

!!! tip
    如果你想完全跳过写 `@query` 方法，看看[自动查询](./graphql_auto_query.zh.md)——它会为每个实体自动生成 `by_id` 和 `by_filter` 查询。

## 实体发现规则

nexusx 自动发现实体：

1. 有 `@query` 或 `@mutation` 的 SQLModel 子类会被发现
2. 通过 Relationship 关联的实体会被递归纳入
3. 没有装饰器**且**没有关系引用的实体**不会**被纳入 schema

这意味着即使 `User` 实体没有 `@query` 方法，只要 `Post` 通过关系引用了 `User`，`User` 也会出现在 schema 中。

## 关系自动解析

试试查询一个关系：

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

幕后发生了什么：

1. 执行 `Post.get_all` 查询，获取 5 条 Post
2. 收集这些 Post 的所有 `author_id`
3. 通过 DataLoader **一次性批量**查询 User
4. 将 User 映射回对应的 Post

**无论结果有多少条，每个关系只执行一次查询。** 这就是 DataLoader 模式——你免费获得了 N+1 预防。

### 支持的关系类型

- `MANYTOONE`：Post → User（通过 FK）
- `ONETOMANY`：User → Posts（通过 Relationship）
- `MANYTOMANY`：需要中间表

## GraphiQL 集成

给你的应用添加交互式查询界面：

```python
@app.get("/graphql", response_class=HTMLResponse)
async def graphiql():
    return handler.get_graphiql_html()
```

你会得到一个完整的 GraphiQL 界面，支持 schema 浏览、自动补全和查询历史。

## 执行流程

```
GraphQL 查询字符串
  → QueryParser 解析为 FieldSelection 树
  → 执行根字段（@query 方法）
  → 逐层遍历选择树
  → 收集 FK 值，DataLoader 批量加载
  → 组装响应 JSON
```

## 回顾

- `GraphQLHandler` 扫描你的 SQLModel 实体并自动生成 GraphQL schema
- 操作按实体分组，例如 `Post.get_all` 和 `User.get_by_id`
- 关系通过 DataLoader 自动解析——不需要手动 join，没有 N+1
- 实体发现是递归的——关联的实体即使没有装饰器也会被纳入

## 下一步

- [GraphQL 分页](./graphql_pagination.zh.md) — 为列表关系添加分页支持
- [自动查询](./graphql_auto_query.zh.md) — 跳过 `@query`，自动生成 `by_id` / `by_filter`
- [Core API 模式](./core_api.zh.md) — 在 GraphQL 之外构建 REST 响应
