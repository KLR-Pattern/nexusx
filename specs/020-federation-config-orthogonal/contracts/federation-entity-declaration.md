# Contract: Entity 联邦声明（开发者面向）

开发者通过 entity 上的两个 dunder 声明 federation member 的联邦能力。这是新模型的**唯一**声明入口（member 侧）。

## 声明形态

```python
class Review(BaseEntity, table=True):
    product_id: int
    rating: int
    comments: list[Comment] = Relationship(...)

    # ① 联邦外键标记 —— 哪些字段是联邦批量入口（纯标记，不带 order）
    __federation_keys__ = ["product_id"]

    # ② order profile —— 统一一份，不区分对内（本地关系）对外（联邦批量）
    __pagination_orders__ = {
        "comments": BatchPageConfig(default_order="NEWEST",        # 本地关系维度
                                    orders={"NEWEST": PageOrder([...])}),
        "product_id": BatchPageConfig(default_order="HIGHEST_RATING",  # 联邦字段维度
                                      orders={"HIGHEST_RATING": PageOrder([...])}),
    }
```

## 规则

1. `__federation_keys__` 的字段**必须是 entity 的实际字段**（生成 `by_<key>_in` 要 `WHERE key IN (values)`）。
2. `__pagination_orders__` 的维度名路由：
   - 在 `__federation_keys__` → 联邦批量 order（生成 `page_by_<key>_in`）
   - 不在 → 本地关系 order（走 loader 本地分页）
3. 联邦字段的根生成（FR-002 + FR-003 **叠加**，非互斥）：
   - **每个** `__federation_keys__` 字段都生成 `by_<key>_in`（批量根，`WHERE key IN`）
   - 有 order profile 的**额外**生成 `page_by_<key>_in`（分页根）
   - 分页联邦关系同时 wire 两个根（mounter full loader 用 by_、paged loader 用 page_by_）
4. 维度名冲突（关系名 == 字段名）：`__federation_keys__` 优先识别为联邦维度。

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
| `AutoQueryConfig(batch_pages={"Review":{"product_id": BatchPageConfig(...)}})` | 删 → entity `__pagination_orders__["product_id"]` |
| `SubsetConfig(federation_join_key="product_id")` | 退化为 `federation_key`（选择器，单 key 时省略） |
| `DTO.__pagination_orders__`（γ 单独的） | 统一到源 entity `__pagination_orders__` |

## 不变项

- `RemoteService` / `RemoteRef` / `RemoteRelationship`（mounter 侧声明模型）—— 保持不变（正交性分析已确认这部分设计良好）。
- mounter 侧 `RemoteRelationship(join_remote=...)` —— 保留（跨服务契约，不在此去重范围，见 spec Clarifications Q1）。
