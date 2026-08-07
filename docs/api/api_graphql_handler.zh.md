# GraphQLHandler API

GraphQL 模式的核心入口——SDL 生成、查询执行、GraphiQL 集成。

## GraphQLHandler

使用 `GraphQLHandler` 来生成 GraphQL SDL 并执行查询。这是你与 GraphQL 模式交互的主要入口。

```python
from nexusx import GraphQLHandler

handler = GraphQLHandler(
    base=SQLModel,                    # SQLModel 基类（自动发现实体）
    session_factory=async_session,    # 异步 session 工厂（必需）
    enable_pagination=False,          # 启用列表关系分页
    auto_query_config=None,           # AutoQueryConfig 自动查询
)
```

### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `base` | `type` | — | SQLModel 基类，用于自动发现实体 |
| `session_factory` | `Callable` | — | 异步 session 工厂函数 |
| `enable_pagination` | `bool` | `False` | 启用列表关系分页 |
| `auto_query_config` | `AutoQueryConfig` | `None` | 自动查询配置 |

!!! warning
    必须提供 `session_factory`，否则 DataLoader 无法加载关系数据。

!!! tip
    使用 `AutoQueryConfig` 可以为所有实体自动生成 `by_id` 和 `by_filter` 查询，无需手写 `@query` 方法。

### 方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `execute` | `async execute(query, variables=None, operation_name=None) -> dict` | 执行 GraphQL 操作 |
| `get_sdl` | `get_sdl(include_mutations: bool = True) -> str` | 渲染当前 SDL |
| `get_graphiql_html` | `get_graphiql_html(endpoint: str = "/graphql") -> str` | 获取 GraphiQL HTML |

## @query 装饰器

使用 `@query` 装饰器将 SQLModel 类方法标记为 GraphQL 查询字段。

```python
from nexusx import query

class Post(SQLModel, table=True):
    @query
    async def get_all(cls, limit: int = 10) -> list['Post']:
        """Get all posts."""
        ...
```

- 自动转为 classmethod
- docstring 成为 GraphQL 字段描述
- 第一个参数必须是 `cls`
- `query_meta` 参数不出现在 SDL 中

## @mutation 装饰器

使用 `@mutation` 装饰器将 SQLModel 类方法标记为 GraphQL 变更字段。

```python
from nexusx import mutation

class Post(SQLModel, table=True):
    @mutation
    async def create(cls, title: str, author_id: int) -> 'Post':
        """Create a new post."""
        ...
```

规则与 `@query` 相同。

## AutoQueryConfig

使用 `AutoQueryConfig` 为所有实体自动生成标准查询。

```python
from nexusx import AutoQueryConfig

config = AutoQueryConfig()
```

为所有实体自动生成 `by_id` 和 `by_filter` 查询。要求实体有且仅有一个主键字段。

!!! tip
    如果你不需要为所有实体手写查询方法，`AutoQueryConfig` 是一个快速启动的选择。它特别适合原型开发和简单 CRUD 场景。

## QueryParser

GraphQL 查询字符串解析为 `FieldSelection` 树。通常不直接使用。

## FieldSelection

查询解析结果类型，表示 GraphQL 选择集中的一个字段及其子选择。

## add_standard_queries

在构造 GraphQLHandler 之前，向实体类注册标准查询方法：

```python
from nexusx import add_standard_queries

add_standard_queries(
    entities=[User, Post],
    config=AutoQueryConfig(),
    session_factory=async_session,
)
handler = GraphQLHandler(base=SQLModel, session_factory=async_session)
```
