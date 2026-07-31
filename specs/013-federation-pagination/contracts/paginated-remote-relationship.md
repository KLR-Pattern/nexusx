# 契约:RemoteRelationship.sort_field 分页声明

**特性**:`specs/013-federation-pagination` | 对应 FR-001/FR-002,研究 [research.md R2](../research.md)

这是**挂载侧声明契约**:在 012 的 `RemoteRelationship` 上新增一个可选字段 `sort_field`,其有无即该跨服务 to-many 关系是否分页。控制模型与本地 `Relationship.order_by` 对称(order_by 存在即分页、per-relationship、缺省则全量)。

## 声明形状

`RemoteRelationship`(012 既有 dataclass)新增可选字段:

```python
@dataclass
class RemoteRelationship:
    fk: str
    target: Any            # list[RemoteRef](to-many) 或 RemoteRef(to-one)
    name: str
    join_remote: str
    description: str | None = None
    # 本期新增:
    sort_field: str | None = None    # 分页开关 + 排序字段;None → 全量(012 行为)
    is_list: bool = field(default=False, init=False)   # 012 既有,派生自 target
```

- 声明 `sort_field` → 该关系分页(按此字段 + 方向排序,返回 `{items, pagination}`)。
- 不声明(`sort_field=None`)→ 全量取(012 既有行为,零变化)。
- **排序方向**:随 `sort_field` 携带,默认 ASC;具体编码(字符串内嵌如 `"created_at desc"`,或独立 `sort_direction` 参数)在实现阶段定,对外语义为"可选方向,默认 ASC"。

## 用法

```python
reviews = RemoteService("reviews", url="http://reviews:8021")

class Product(CatalogBase, table=True):
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[reviews.Review],
            name="reviews", join_remote="product_id",
            sort_field="created_at",        # ← 声明即分页
        ),
    ]
```

## 不变量

- `sort_field` 仅对 to-many(`target=list[...]`)有效;在 to-one 上声明 → 启动期 fail-fast(FR-002),错误指明"分页仅适用于 to-many"。
- `sort_field` 必须是被挂服务该类型的合法标量字段;非法 → 启动期 fail-fast(FR-012b)。
- `default_page_size`/`max_page_size` **不**在 `RemoteRelationship` 上暴露——复用本地固定默认(20/100),对齐本地(R3)。客户端需不同页大小就传 `limit`。
- 未声明 `sort_field` 的远程关系行为与 012 逐字节一致(零回归)。

## 相关

- [paginated-batch-root.md](./paginated-batch-root.md):挂载方声明的 `sort_field` 经 wire 传给 member 的分页 root。
- [paginated-gql-fetch.md](./paginated-gql-fetch.md):分页 RemoteLoader 据此构造分页 gql。
- spec FR-001/FR-002;research.md R2;[data-model.md §1](../data-model.md)。
