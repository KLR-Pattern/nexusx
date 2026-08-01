# Contract: 本地分页 order/direction 公开 API

**Feature**: specs/015-local-pagination-order-direction

本契约定义本特性对外暴露的 4 个 API 面：member 声明、客户端 GraphQL 字段、page_loader 内部接口、启动期校验。

## 1. `__pagination_orders__` 声明（member 开发者 API）

本地分页关系（SQLModel **ORM** `Relationship`，参数不可扩展）的 order profile，通过**实体类级** `__pagination_orders__` dict 声明。ErManager 启动期读取、按 key 关联 ORM relation 名。

```python
from sqlmodel import Relationship, Field
from nexusx import BatchPageConfig, PageOrder, OrderTerm

class Review(SQLModel, table=True):
    id: int = Field(primary_key=True)
    comments: list["Comment"] = Relationship(
        back_populates="review",
        sa_relationship_kwargs={"order_by": "Comment.id"},   # 兜底(未配 profile 时)
    )
    # ★ 类级声明: key = ORM relation 名, value = BatchPageConfig
    __pagination_orders__ = {
        "comments": BatchPageConfig(
            default_order="NEWEST",
            orders={
                "NEWEST": PageOrder([OrderTerm("created_at", "desc")]),
                "MOST_LIKED": PageOrder([OrderTerm("likes", "desc", nulls="last")]),
            },
        ),
    }
```

| 声明 | 说明 |
|------|------|
| `__pagination_orders__` | `dict[str, BatchPageConfig]`，key = ORM relation 名（如 `"comments"`），value = profile 集合 + default；缺省/无此属性 = 不开启 order/direction（走 `order_by`） |

与 `enable_pagination=True` 配合（page_loader 存在的前提）。`BatchPageConfig`/`PageOrder`/`OrderTerm` 复用 federation 分页的同名类（`standard_queries.py`），不重新定义。

## 2. GraphQL 字段签名（客户端 API）

配了 `page_orders` 的本地分页关系字段渲染为：

```graphql
comments(
  limit: Int,
  offset: Int = 0,
  order: CommentCommentsOrder,     # enum, 值 = page_orders 的 key 集合
  direction: Direction             # enum {ASC, DESC}
): CommentCommentsResult!
```

- `order` enum 值 = `page_orders.keys()`（如 `NEWEST` / `MOST_LIKED`），默认 = `default_page_order`
- `direction` enum = `{ASC, DESC}`（全局 `Direction`，与 federation 共用），默认 = profile 的 direction
- 返回包类型 `{ items: [Target]!, pagination: { has_more, total_count } }`，与 federation 分页同构

**未配 `page_orders` 的本地分页关系**：维持既有形态 `comments(limit: Int, offset: Int = 0)`（无 order/direction）—— 向后兼容。

## 3. page_loader 内部接口（实现契约）

`create_page_one_to_many_loader` / `create_page_many_to_many_loader`（`loader/factories.py`）签名扩展，接受 `page_capability: BatchPageCapability | None`：

- `page_capability=None` → 固定 `sort_field` 排序（现状，逐字节不变）
- `page_capability` 非 None → 按 cmd 携带的 `order`/`direction` + profile 构建 ORDER BY（`_build_order_expressions(_apply_direction(resolved_terms, direction))`）

**cmd 扩展**：cmd 携带 `order: str | None`、`direction: Direction | None`（executor 从 `selection.arguments` 注入；同 batch 同值，`batch_load_fn` 从 `first_cmd` 读，与 `first_cmd.page_args` 同模式，见 `factories.py:355`）。

## 4. 校验契约（启动期 fail-fast）

`page_orders` 非空时，`ErManager` 启动期校验（复用 `_resolve_page_orders`，与 federation `batch_pages` 同一校验函数）：

- `default_page_order` ∈ `page_orders.keys()`
- 每个 profile 名 enum-safe 大写（GraphQL enum 合法标识符）
- 每个 `PageOrder` 恰好一个 `OrderTerm`（单列，沿用 014）
- `OrderTerm.field` 是实体上的普通 SQL column（非 JSON / BLOB）
- `OrderTerm.direction` ∈ {asc, desc}
- nullable 字段必须显式 `nulls`（first/last）
- 未含的主键列自动追加为稳定 tie-breaker

任一失败 → 启动 fail-fast，不进入运行时。
