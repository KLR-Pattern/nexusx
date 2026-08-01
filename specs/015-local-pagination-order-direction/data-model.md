# Data Model: 本地分页 order/direction

## 实体

### `__pagination_orders__`（类级声明，实体类上）

本地分页关系（SQLModel **ORM** `Relationship`，参数不可扩展）的 order profile，通过实体类级 dict 声明：

- `__pagination_orders__: dict[str, BatchPageConfig]` —— key = ORM relation 名（如 `"comments"`），value = `BatchPageConfig(default_order, orders)`；无此属性 = 未配 profile（走 `order_by` 兜底）

声明在实体类上（不是 `Relationship` 参数——SQLModel ORM `Relationship` 参数固定不可扩展，实测 `TypeError`）。ErManager 启动期 `getattr(entity, "__pagination_orders__", {})` 读取 + 校验。

**校验**（启动期，复用 `_resolve_page_orders`）：
- `page_orders` 非空 → `default_page_order` 必填且 ∈ keys
- 每个 `PageOrder`：单 `OrderTerm`、enum-safe 大写名、field 是普通 SQL column、direction ∈ {asc,desc}、nullable field 显式 `nulls`

**与 order_by 共存**：`page_orders` 优先；`order_by` 仅在未配 `page_orders` 时作为固定排序兜底（FR-003 向后兼容）。

### RelationshipInfo（扩展，`loader/registry.py`）

关系元数据。扩展：

- `page_capability: BatchPageCapability | None = None` —— 本地分页关系的 profile 集合（启动期从 `Relationship.page_orders` 构建）；None = 未配 profile（走 `sort_field`）

现有字段保留：`sort_field`（兜底）、`page_loader`、`kind`（LOCAL/REMOTE_*）、`pagination`（federation 远程分页标记，本地分页不用此字段）。

### BatchPageCapability（复用，`federation/contract.py`）

profile 集合标准载体：`protocol("offset-v1")` + `default_order: str` + `orders: list[PageOrderDescriptor]`。本地分页与 federation 共用同一结构。

### PageOrder / OrderTerm / Direction（复用，`standard_queries.py`）

profile 声明结构（`PageOrder(terms=[OrderTerm(field, direction, nulls)], description)`、`Direction{ASC,DESC}`）。本地分页 import 调用，不重新定义。

### 本地 page_loader（改造，`loader/factories.py`）

`create_page_one_to_many_loader` / `create_page_many_to_many_loader`：

- **现状**: 固定 `ORDER BY sort_field, pk`（`factories.py:377,401`）
- **改后**: 若 `page_capability` 非 None，`ORDER BY _build_order_expressions(_apply_direction(resolved_profile_terms, direction))`（复用 federation 排序构建）；否则维持 `sort_field`

**cmd 扩展**: cmd 携带 `order: str | None`、`direction: Direction | None`（executor 从 `selection.arguments` 注入；同 batch 同值，`batch_load_fn` 从 `first_cmd` 读）。

## 关系图

```
声明期                          启动期                           查询期
──────                          ──────                           ──────
Relationship.page_orders  ──▶  RelationshipInfo.page_capability   ──▶  page_loader 排序
(dict[str, PageOrder])         (BatchPageCapability | None)            (按 profile + direction)
        │                              │                                    ▲
        │                      sdl/introspection 渲染                     │
        │                      order enum + direction              executor 从 selection.arguments
        │                      (复用 federation 渲染分支)           注入 order/direction 到 cmd
        ▼
_resolve_page_orders 校验
(fail-fast)
```

## 状态 / 生命周期

1. **声明期**: `Relationship(page_orders={...}, default_page_order=...)` 在 SQLModel 类定义时声明。
2. **启动期**: `ErManager` 构建关系元数据时，从 `Relationship.page_orders` 调 `_resolve_page_orders` 解析 + 校验 → 构造 `BatchPageCapability` → 挂到 `RelationshipInfo.page_capability`。校验失败 fail-fast。
3. **查询期**: executor 从 `selection.arguments` 读 order/direction → 塞进 cmd → page_loader 的 `batch_load_fn` 从 `first_cmd` 读 order/direction → 按 `page_capability` 的 profile + direction 构建 ORDER BY（`_build_order_expressions` + `_apply_direction`）→ `ROW_NUMBER() OVER (PARTITION BY fk ORDER BY …)` 分页。

## 不变式

- 未配 `page_orders` 的关系：`page_capability=None`，page_loader 走 `sort_field`，行为与现状逐字节一致。
- federation 分页（REMOTE_PAGED）：不受本特性影响，`page_capability` 来源仍是 member 的 ER introspection（`_validate_page_capability`），不与本地 `Relationship.page_orders` 混淆。
