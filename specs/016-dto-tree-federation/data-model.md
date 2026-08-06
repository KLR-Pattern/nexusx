# Data Model: DTO federation

## 实体

### SubsetConfig（扩展，`subset.py`）

DefineSubset 的配置类。扩展 federation 参数：

- `federation_public: bool = False` —— 是否暴露为 federation public DTO（默认 False，member 内部用）
- `federation_join_key: str | None = None` —— federation join key（public=True 时必填，派生自 base_entity 的 FK 字段名）

**校验**（启动期）: `federation_public=True` → `federation_join_key` 必填且 ∈ DTO model_fields。

```python
class ReviewDTO(DefineSubset):
    __subset__ = SubsetConfig(
        source=Review,
        fields=("title", "rating", "product_id"),
        federation_public=True,
        federation_join_key="product_id",
    )
    total_after_discount: float | None = None  # 计算字段
    def resolve_total_after_discount(self, loader=Loader("discount")):
        return loader.load(self.product_id)
```

### DTOFragment（新，`federation/contract.py`）

DTO 的 introspection 序列化（对称 `EntityFragment`）。

- `name: str` —— DTO 类名（`__name__`）
- `base_entity: str` —— subset of 的实体名（`_subset_registry[DTO].__name__`）
- `fields: list[FieldDescriptor]` —— 全部字段 + 类型（`model_fields`，含骨架 + PK + 计算字段）
- `join_key: str` —— federation join key（SubsetConfig `federation_join_key`）
- `batch_root: str` —— DTO batch root 名（生成的 `by_<key>_in` DTO 版）
- `remote_refs: list[RelDescriptor]` —— DTO 的跨 service 出边（`__relationships__`）

### DTO batch root（新，`standard_queries.py`）

member 按 join_key 返 DTO 树的 federation 入口。内部：

1. SQL 按 join_key 取实体（batch，复用 by_<key>_in 的 SQL 框架）
2. 造 DTO 实例（from 实体，subset）
3. `er.create_resolver().resolve(dto_instances)` —— Resolver 加工（含 resolve_* 计算字段 + 跨 service 出边解析）
4. 返 DTO 树（按 join_key 对齐）

### DTO introspection 端点（新，`federation/introspect.py`）

独立端点（β ER introspection 不动）。序列化 member 的 public DTO 列表 → `DTOFragment` 列表。

- 扫描 member 的 federation public DTO（SubsetConfig `federation_public=True`）
- 每个 public DTO → DTOFragment（收集 name/base_entity/fields/join_key/batch_root/remote_refs）
- mounter GET 这个端点 → 收 DTOFragment 列表

## 关系图

```
声明期                        启动期                         查询期
──────                        ──────                         ──────
SubsetConfig              ErManager 扫描 public DTO         mounter γ 查 ProductDTO
(federation_public,       → 注册 DTO batch root              → RemoteLoader 取 reviews
 federation_join_key)     → DTO introspection 端点               的 DTO batch root
       │                        │                              │
       ▼                        ▼                              ▼
DefineSubset DTO         DTOFragment(序列化)              member batch root:
                       ← mounter GET(独立端点)            SQL 取实体 → 造 DTO →
                                                          er.create_resolver().resolve()
                                                          → 返自包含 DTO 树
```

## 不变式

- 非 public DTO（`federation_public=False` 或缺省）: 不暴露 federation，member 内部用。
- β 路径（ER federation）: 不动——ER introspection 不含 DTOFragment，SQLModel GraphQL 不改。
- member 值只读: mounter 二次 resolve 不改 member 业务字段值（Resolver/DefineSubset 纪律）。
