# Contract: Entity 联邦声明（开发者面向）

开发者通过 entity 上的两个 dunder 声明 federation member 的联邦能力。这是新模型的**唯一**声明入口（member 侧）。

## 声明形态

```python
class Comment(BaseEntity, table=True):
    # Comment 自己的排序 —— 被 Review.comments（或任何 owner）分页时读它
    __pagination_orders__ = BatchPageConfig(default_order="NEWEST",
                                            orders={"NEWEST": PageOrder([...])})
    ...


class Review(BaseEntity, table=True):
    product_id: int
    rating: int
    comments: list[Comment] = Relationship(...)

    # ① 联邦外键标记 —— 哪些字段是联邦批量入口（纯标记，不带 order）
    __federation_keys__ = ["product_id"]

    # ② Review 自己的排序 —— 被联邦批量分页（page_by_product_id_in）时读它
    __pagination_orders__ = BatchPageConfig(default_order="HIGHEST_RATING",
                                            orders={"HIGHEST_RATING": PageOrder([...])})
    # 注：comments 的排序在 Comment 上，不在 Review —— 排序归被排序对象
```

## 规则

1. `__federation_keys__` 的字段**必须是 entity 的实际字段**（生成 `by_<key>_in` 要 `WHERE key IN (values)`）。
2. `__pagination_orders__` 是 entity 的**单一** BatchPageConfig（该 entity 自己的排序），不按维度分。
3. 联邦批量分页读 **owner 自己**的 `__pagination_orders__`；本地关系分页读 **target** 的（如 Review.comments 读 Comment 的）。两者读不同 entity。
4. 联邦字段的根生成（FR-002 + FR-003 **叠加**）：
   - **每个** `__federation_keys__` 字段都生成 `by_<key>_in`（批量根，`WHERE key IN`）
   - entity 声明了 `__pagination_orders__` → 每个 federation key **额外**生成 `page_by_<key>_in`（共用这一个 profile）
   - 分页联邦关系同时 wire 两个根（mounter full loader 用 by_、paged loader 用 page_by_）

## γ DTO（federation_public）

```python
class ReviewDTO(DefineSubset):
    __subset__ = SubsetConfig(kls=Review, fields=("title", "rating", "product_id"),
                              federation_public=True)
    # join key 自动从 Review.__federation_keys__ 推导（单 key 时）
    # 多 key 时：federation_key="product_id"  ← 选择器，引用 entity 已声明的 key 名
```

## 退场项（breaking，直接删）

| 旧用法 | 新模型 |
|---|---|
| `AutoQueryConfig(batch_keys={"Review":["product_id"]})` | 删 → entity `__federation_keys__` |
| `AutoQueryConfig(batch_pages={"Review":{"product_id": BatchPageConfig(...)}})` | 删 → entity `__pagination_orders__ = BatchPageConfig(...)`（单一） |
| `SubsetConfig(federation_join_key="product_id")` | 退化为 `federation_key`（选择器，单 key 时省略） |
| `DTO.__pagination_orders__`（γ 单独的） | 统一到源 entity `__pagination_orders__` |

## 不变项

- `RemoteService` / `RemoteRef` / `RemoteRelationship`（mounter 侧声明模型）—— 保持不变（正交性分析已确认这部分设计良好）。
- mounter 侧 `RemoteRelationship(join_remote=...)` —— 保留（跨服务契约，不在此去重范围，见 spec Clarifications Q1）。
