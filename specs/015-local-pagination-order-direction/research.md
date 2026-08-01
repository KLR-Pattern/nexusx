# Research: 本地分页 order/direction

**Feature**: specs/015-local-pagination-order-direction
**Date**: 2026-08-02

## 背景

spec 已定三条架构决策（见 spec.md `## Clarifications / Session 2026-08-01`）：

1. 声明载体：扩展 `Relationship.page_orders`/`default_page_order`
2. profile 与 order_by 共存：profile 优先，order_by 兜底
3. shared core：底层共享（`PageOrder`/`OrderTerm` + 排序/渲染），容器分开（`BatchPageConfig` for federation root，`Relationship.page_orders` for 本地关系）

本 research 解决 spec 标"留 plan"或未明示的 **plan 级实现决策**。

## 决策

### D1: DataLoader per-query 参数注入方式（spec Deferred 项）

**选项**: (a) loader 实例挂当前 selection（复用 federation `_remote_selection` 模式）；(b) order/direction 塞进每个 cmd（同 batch 同值）

**决策**: (b) 塞进 cmd。

**理由**: 本地 page_loader 的 `batch_load_fn` 接收 keys（cmd 列表），cmd 已带 `page_args`（limit/offset）。order/direction 是 per-selection 但同 batch 同值——塞进 cmd（每个 cmd 带 order/direction），`batch_load_fn` 从 `first_cmd` 读 order/direction，与它现在读 `first_cmd.page_args`（`factories.py:355`）完全一致。无需在 loader 实例上挂状态（避免 DataLoader 跨查询复用时的状态污染）。federation 的 `_remote_selection` 注入是为远程 gql 构造（要透传整棵选区），本地不需要选区——排序参数已标量化，塞 cmd 更简洁。

**备选 rejected**: (a) selection 注入 —— 本地 page_loader 不构造 gql，不需要完整选区，只需标量 order/direction；挂 loader 实例引入状态管理复杂度，且本地/federation 两条注入路径分叉。

### D2: shared core 抽取位置

**选项**: (a) 留 `standard_queries.py`（federation 已用，本地 import）；(b) 抽到新模块（如 `loader/pagination_core.py`）

**决策**: (a) 留 `standard_queries.py`，本地 page_loader import 调用。

**理由**: `PageOrder`/`OrderTerm`/`Direction`/`_build_order_expressions`/`_apply_direction` 已在 `standard_queries.py`（federation 在用）。抽新模块会引入 import 重排 + federation 侧改动（直接威胁 SC-005 零回归）。留原处、本地 import，最小改动。若未来出现循环依赖再抽（YAGNI）。

**备选 rejected**: (b) 抽新模块 —— 当前无循环依赖迹象，提前抽增大改动面与回归风险。

### D3: RelationshipInfo 携带 profile 的字段

**选项**: (a) 复用 `page_capability: BatchPageCapability`（federation 已有）；(b) 新字段 `local_orders`

**决策**: (a) 复用 `page_capability: BatchPageCapability | None`。

**理由**: `BatchPageCapability`（`contract.py`）已是 profile 集合的标准载体（`protocol` + `default_order` + `orders`）。本地分页的 profile 集合语义与 federation 相同，复用避免重复结构。`RelationshipInfo` 加 `page_capability: BatchPageCapability | None`（None = 未配 profile，走 `sort_field` 兜底）。语义统一：federation REMOTE_PAGED 与本地 LOCAL 分页都读 `page_capability`。

**备选 rejected**: (b) 新字段 —— 语义重复，渲染/校验要双份逻辑。

### D4: profile 校验复用

**决策**: 复用 `_resolve_page_orders`（`standard_queries.py`，federation 在用）。

**理由**: spec FR-002 要求校验沿 013/014。`_resolve_page_orders` 已校验：enum-safe 大写名、单列（`OrderTerm` 恰好一个）、field 是普通 SQL column（非 JSON/BLOB）、direction ∈ {asc,desc}、nullable 字段显式 `nulls`、未含 PK 追加为 tie-breaker。本地 `page_orders: dict[str, PageOrder]` 直接喂 `_resolve_page_orders`，零重复。

### D5: executor 透传 order/direction 的提取点

**决策**: `query_executor._build_field_jobs` / `_load_field_paginated` 从 `child_sel.arguments`（`FieldSelection.arguments`）提 order/direction，构造本地 page_loader 的 cmd 时塞进。

**理由**: `FieldSelection.arguments` 已被 federation 用（`remote_loader.py:471-472` 读 order/direction）。本地分页走同一 selection 树，executor 在构造 cmd 时读 arguments，复用既有解析。

### D6: 渲染层复用与扩展

**决策**: `pagination_schema.is_active_paginated_relationship` 扩展第四分支（`LOCAL + page_capability != None`），`sdl_generator` 的分页渲染分支 + `introspection` 接入本地分页。

**理由**: spec FR-005 要求复用 federation 渲染。`is_active_paginated_relationship`（`pagination_schema.py:25`）已有三分支：`REMOTE_PAGED` / `REMOTE_COALESCED + pagination` / `LOCAL + page_loader + enable_pagination`。本地分页配 profile 是第四种（`LOCAL + page_capability != None`）——其 schema 形态（`comments(limit, offset, order, direction)`，无 federation 的 batch root 概念）与 federation 分页一致，order enum 从 `page_capability.orders` 生成，复用渲染。

## 不需研究的项（已明确）

- **性能（per-parent batch 不变量）**: order/direction 只改 `ORDER BY`，不改 `PARTITION BY fk` 的 batch 结构，N+1-proof 天然保持。无需专门设计。
- **向后兼容**: 未配 `page_orders` 的 `Relationship` 不带 `page_capability`，page_loader 走 `sort_field`（现状），`comments(limit, offset)` 渲染不变。
- **federation × 本地叠加**: 5.0.1 已让两者物化/反序列化兼容；本特性让内层本地分页也有 order/direction，外层 federation 分页的 order/direction 互不干扰（各自从自己的 selection.arguments 读）。
