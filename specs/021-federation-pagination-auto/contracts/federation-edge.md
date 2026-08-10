# Contract: 联邦边（RemoteRelationship，021 后）

开发者声明跨服务联邦边。021 后**无 `pagination` 参数** —— 联邦分页由 member 能力（`__pagination_orders__` → `page_by_`）+ 查询参数（limit）自动决定。

## 声明形态

```python
reviews = RemoteService("reviews", url=...)

class Product(CatalogBase, table=True):
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[reviews.Review],
            name="reviews", join_remote="product_id",
            # 无 pagination 参数 —— 联邦分页由 reviews.Review 的 __pagination_orders__ 决定
        ),
    ]
```

## 联邦分页行为（自动，无需 mounter 声明）

| member 侧 | mounter schema | 查询 |
|---|---|---|
| Review 有 `__pagination_orders__`（暴露 `page_by_product_id_in`） | `reviews: Result{items, pagination}`（limit 可选） | `reviews(limit:5) { items {...} pagination {...} }` 或 `reviews { items {...} }`（全量） |
| Review 无（只 `by_product_id_in`） | `reviews: list` | `reviews { ... }` |
| to-one（如 `author: User`） | 单对象（不分页） | `author { name }` |

## 迁移（旧 → 新）

| 旧 | 新 |
|---|---|
| `RemoteRelationship(..., pagination=True)` | 删 `pagination=True`（member 有 `__pagination_orders__` → 自动分页 Result） |
| `RemoteRelationship(..., pagination=False)` | 删 `pagination=False`（member 无 → 自动 by_ list） |

## 不变项

- `fk` / `target` / `name` / `join_remote`（联邦边核心声明）
- to-one 关系（从不分页）
- member 的 `__federation_keys__` / `__pagination_orders__`（020）
