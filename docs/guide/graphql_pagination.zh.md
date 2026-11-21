# GraphQL 分页

列表关系支持自动分页，通过 SQL `ROW_NUMBER()` 窗口函数实现。

## 启用分页

你需要两件事：

1. 在列表关系上添加 `order_by`
2. 创建 `GraphQLHandler` 时启用分页

```python
class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    posts: list["Post"] = Relationship(
        back_populates="author",
        sa_relationship_kwargs={"order_by": "Post.id"},
    )

handler = GraphQLHandler(
    base=SQLModel,
    session_factory=async_session,
)
```

!!! warning
    **没有** `order_by` 的关系不会生成分页支持。必须使用 `"Entity.column"` 字符串格式。

## 查询语法

```graphql
{
  User {
    get_all {
      name
      posts(limit: 3) {          # 量意图必填——没有默认页大小
        items { title }
        pagination { has_more total_count }
      }
    }
  }
}
```

显式获取全部：

```graphql
posts(fetchAll: true) { items { title } pagination { total_count } }   # 覆盖 limit/offset
```

两者都不带会触发带指引的校验错误——列表查询绝不会静默截断到某个隐藏默认值。

### 响应结构

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

## 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `limit` | `Int` | 每页条数 |
| `offset` | `Int` | 偏移量（从 0 开始） |

## Pagination 类型

| 字段 | 类型 | 说明 |
|------|------|------|
| `has_more` | `Boolean!` | 是否还有更多数据 |
| `total_count` | `Int!` | 总记录数 |

??? info "技术细节"
    框架使用 SQL `ROW_NUMBER()` 窗口函数实现分页：

    ```sql
    SELECT * FROM (
      SELECT *, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY id) as rn
      FROM post
      WHERE user_id IN (...)
    ) WHERE rn > offset AND rn <= offset + limit
    ```

    这种方式在单次查询中同时获取分页数据和总数。

## 回顾

- 列表关系必须有 `order_by`，使用 `"Entity.column"` 字符串格式——声明即开启
- 在 GraphQL 查询中使用 `limit` 或 `fetchAll`（量意图强制，无默认页大小）
- 每个分页关系返回 `{ items, pagination }`，包含 `has_more` 和 `total_count`

## 下一步

- [自动查询](./graphql_auto_query.zh.md) — 跳过 `@query` 自动生成查询
- [Core API 模式](./core_api.zh.md) — REST 端点的 DTO 构建
