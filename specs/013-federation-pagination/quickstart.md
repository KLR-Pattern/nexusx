# Quickstart

```python
from nexusx import (
    AutoQueryConfig,
    BatchPageConfig,
    OrderTerm,
    PageOrder,
    RemoteRelationship,
)

member_config = AutoQueryConfig(
    batch_keys={"Review": ["product_id"]},
    batch_pages={
        "Review": {
            "product_id": BatchPageConfig(
                default_order="NEWEST",
                orders={
                    "NEWEST": PageOrder(
                        terms=[OrderTerm("created_at", "desc")]
                    ),
                    "HIGHEST_RATING": PageOrder(
                        terms=[OrderTerm("rating", "desc")]
                    ),
                },
            )
        }
    },
)

RemoteRelationship(
    fk="id",
    target=list[reviews.Review],
    name="reviews",
    join_remote="product_id",
    pagination=True,
    order="HIGHEST_RATING",
)
```

```graphql
query {
  Product {
    by_id(id: 1) {
      reviews(limit: 5, offset: 0) {
        items { title rating }
        pagination { has_more total_count }
      }
    }
  }
}
```

验证重点：

- ER 中存在 `page_by_product_id_in`，page protocol 为 `offset-v1`。
- mounter 发送显式 `order: HIGHEST_RATING`。
- 业务 schema 不含 `order` 参数。
- 未配置 `batch_pages` 时不生成分页 root。
