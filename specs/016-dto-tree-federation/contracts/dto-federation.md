# Contract: DTO federation 公开 API

**Feature**: specs/016-dto-tree-federation

## 1. SubsetConfig federation 参数（member 开发者 API）

DefineSubset 的 `SubsetConfig` 扩展两个参数：

```python
from nexusx import DefineSubset, SubsetConfig, Loader

class ReviewDTO(DefineSubset):
    __subset__ = SubsetConfig(
        source=Review,
        fields=("title", "rating", "product_id"),
        federation_public=True,            # ★ 暴露为 federation public DTO
        federation_join_key="product_id",  # ★ federation join key(public=True 时必填)
    )
    total_after_discount: float | None = None
    def resolve_total_after_discount(self, loader=Loader("discount")):
        return loader.load(self.product_id)
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `federation_public` | `bool = False` | 是否暴露 federation；False（默认）= member 内部用 |
| `federation_join_key` | `str \| None = None` | federation join key；public=True 时必填（DTO 字段名，派生自 base_entity FK） |

校验（启动期 fail-fast）: public=True → join_key 必填且 ∈ model_fields。

## 2. 独立 DTO introspection 端点（member → mounter）

member 暴露独立端点（β ER introspection 不动），序列化 public DTO 列表：

```
GET /dto-introspection → [DTOFragment(...), ...]
```

DTOFragment（对称 EntityFragment）:

| 字段 | 来源 | 说明 |
|------|------|------|
| `name` | `DTO.__name__` | DTO 类名 |
| `base_entity` | `_subset_registry[DTO].__name__` | subset of 的实体名 |
| `fields` | `model_fields` | 全部字段 + 类型（骨架 + PK + 计算） |
| `join_key` | `SubsetConfig.federation_join_key` | federation join key |
| `batch_root` | 生成的 DTO batch root 名 | mounter RemoteLoader 发它取数 |
| `remote_refs` | `__relationships__` | DTO 的跨 service 出边 |

## 3. DTO batch root（member 取数入口）

member 生成的 DTO batch root（按 join_key），内部跑 Resolver：

```
DTO batch root(join_key values):
  ① SQL 按 join_key 取实体(batch)
  ② 造 DTO 实例(from 实体, subset)
  ③ er.create_resolver().resolve(dto_instances)  ← Resolver 加工(含 resolve_* + 跨 service)
  ④ 返 DTO 树(按 join_key 对齐)
```

mounter 的 RemoteLoader 发 DTO batch root（跟发实体 by_<key>_in 对称），member 返 DTO 树。

## 4. mounter γ 引用 member public DTO（mounter 开发者 API）

mounter UseCaseService 的 DTO 引用 member public DTO（同 namespace，跟引用实体一样）：

```python
reviews = RemoteService("reviews", url="http://reviews:8021")

class ProductDTO(DefineSubset):
    __subset__ = (Product, ("id", "name"))
    reviews: list[reviews.ReviewDTO] = Field(default_factory=list)  # ★ member public DTO
    def resolve_reviews(self, loader=Loader("reviews")):
        return loader.load(self.id)  # RemoteLoader 取 reviews.ReviewDTO 树
```

`reviews.ReviewDTO` = RemoteRef（跟 `reviews.Review` 实体同 namespace）。mounter γ 物化 ReviewDTO（from DTOFragment）+ RemoteLoader 取（DTO batch root）。

## 5. member 值只读契约（边界）

mounter 拿 member DTO 后可二次 resolve（DefineSubset 选 / resolve_* 加 / 重组），**但不改 member 业务字段值**。现有 Resolver/DefineSubset 纪律保证（resolve_* 加字段不覆盖、DefineSubset 选字段不改值）。
