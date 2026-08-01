# Quickstart: 本地分页 order/direction

> 验证场景，证明本特性端到端 work。实现细节见 `tasks.md`（由 `/speckit-tasks` 生成）。

## 前置

- nexusx 5.0.1+（federation × 本地分页叠加已修）
- member 开了 `enable_pagination=True`（本地分页前提）

## 场景 1: 本地分页 order/direction 端到端（核心）

**配置**（member 侧，参照 [contracts/local-pagination-order.md](./contracts/local-pagination-order.md) 第 1 节）：

```python
class Review(SQLModel, table=True):
    comments: list["Comment"] = Relationship(
        back_populates="review",
        page_orders={
            "NEWEST": PageOrder([OrderTerm("created_at", "desc")]),
            "MOST_LIKED": PageOrder([OrderTerm("likes", "desc", nulls="last")]),
        },
        default_page_order="NEWEST",
    )
```

**查询**（客户端）：

```graphql
{ Review { by_filter {
  comments(limit: 2, order: MOST_LIKED, direction: DESC) {
    items { text likes }
    pagination { has_more total_count }
  }
}}}
```

**期望**：
- items 按 `likes` desc 排序，limit 2
- `pagination.has_more` / `total_count` 正确
- `direction: ASC` 翻转后，顺序与 DESC 严格相反（含 NULL 位置：desc NULL 在末，asc NULL 在首）

## 场景 2: order profile 切换

查 `order: NEWEST` vs `order: MOST_LIKED`，断言结果不同。**种子需让两列反序**（如某条 `likes` 高但 `created_at` 旧），否则两 profile 排序相同看不出差异。

## 场景 3: 向后兼容（未配 profile）

未配 `page_orders` 的本地分页关系（仅 `order_by`），查 `comments(limit, offset)`（**无** order/direction 参数），行为与 5.0.1 完全一致。既有 `test_loader_pagination.py` 全绿。

## 场景 4: federation × 本地 order/direction 叠加

catalog 查外层 federation 分页 + 内层本地 order/direction，各自独立解析：

```graphql
{ Product { by_filter {
  reviews(limit: 5, order: HIGHEST_RATING, direction: DESC) {       # 外层 federation 分页
    items { comments(limit: 2, order: NEWEST, direction: ASC) {      # 内层本地 order/direction
      items { text } pagination { has_more }
    }}
  }
}}}
```

期望：外层按 rating、内层按 created_at，互不干扰；每服务仍一条 gql。

## 验证命令

```bash
# 新增(本特性)
uv run pytest tests/test_local_pagination_order.py tests/test_local_pagination_order_render.py -v

# 回归(向后兼容 + federation 零回归)
uv run pytest tests/test_loader_pagination.py tests/test_pagination_mixed.py \
              tests/test_federation_pagination_e2e.py tests/test_federation_order_direction.py -q
```

## demo 可选

`demo/federation/reviews_app.py` 的 `Review.comments` 目前用 `enable_pagination` + `order_by`（固定）。可顺手加 `page_orders`（如 `NEWEST`/`OLDEST` by `created_at`），让 demo 同时演示本地 order/direction——但这是可选增强，非本特性验收门槛。
