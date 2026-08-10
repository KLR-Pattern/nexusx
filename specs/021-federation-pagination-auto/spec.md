# Spec 议题：联邦分页自动化（去掉 RemoteRelationship.pagination，回归全局分页）

> 状态：议题存档（待 spec-kit 流程细化）。020 merge 后启动。

## 一句话

去掉 `RemoteRelationship(pagination=True/False)` 这个 per-edge 参数。联邦分页完全由 **member 能力（`__pagination_orders__` → `page_by_<key>_in` 自动暴露）+ 查询参数（limit/order 运行时驱动）** 决定，mounter 零联邦分页配置。member 自己的本地关系分页仍由 `enable_pagination` 控制（member/mounter 对称，各管各的本地）。

## Clarifications

### Session 2026-08-10

- Q: 去掉 `RemoteRelationship.pagination` 后 `enable_pagination` 的角色？ → A: **保持独立**（Option A）。`__pagination_orders__` 控联邦 `page_by_` 生成，`enable_pagination` 控本地关系分页。两者正交（延续 020）。"全局"语义已满足 —— 控制都在 member 级（entity dunder + handler 开关），非 mounter per-edge。
- Q: member 支持分页时 mounter 能否 opt-out / 谁控联邦分页？ → A: **mounter 的 `enable_pagination` 不接管联邦关系**（修正早前"接管"设想）。联邦分页完全由 **member 能力 + 查询参数**驱动：member 有 `page_by_`（`__pagination_orders__`）→ mounter 自动 wire → 关系 `Result{items, pagination}`，`limit` 可选（带 → top-N，不带 → 全量）；member 无 → `by_` → list。mounter 查询带 limit → top-N；不带 → 全量（不切片）。mounter 的 `enable_pagination` 只管 mounter 自己的本地关系（与 member enable 对称）。

## 动机

### 1. `pagination` 参数是 020 后的冗余残留

020 后，member 是否暴露 `page_by_<key>_in` 已由 member entity 的 `__pagination_orders__` 决定（entity 级声明）：

```
member 有 __pagination_orders__ → 每个 federation key 生成 by_X_in + page_by_X_in
member 无                       → 只生成 by_X_in
```

即 **member 已经声明了"我能不能被分页拉取"**。mounter 再用 `RemoteRelationship(pagination=True)` 声明"我要分页拉你"，是同一信息的重复声明 —— 两边必须对齐，漏一边就崩。

### 2. 实证：漏一条边就崩（不传递）

对比实验（`tests/test_federation_pagination_transitive.py`，A→B→C 三层）：

| B→C 边的 `pagination` | A 查 `cs(limit:1) { items }` | 结果 |
|---|---|---|
| `pagination=True` | 走 `page_by_b_id_in`，返 `Result{items:[C1]}` | ✅ 正常 |
| 不写（默认 `False`） | 走 `by_b_id_in`，返普通 list `[C1,C2]`，客户端期望 `items` → 结构不匹配 | ❌ `ValidationError: cs.items Field required` |

A 配了 A→B 的 `pagination=True`，**不会**让 B→C 自动开。B→C 要 B 自己声明，漏了就崩。这就是用户提的「应该带传递性质」的真实缺口。

### 3. 设计愿景（用户）

> 「在 ER diagram 级别，分页应该就是一个全局开启或者关闭的逻辑。」

分页是 member ER diagram（schema）级别的属性，应由 member 自己的全局开关控制，不该是 mounter 逐边的声明。这与 020 精神一致：**声明在 member，消费方读它**（join key、order 都是这样，pagination 应跟进）。

## 设计方向

### 去掉 `RemoteRelationship.pagination`，联邦分页 = member 能力 + 查询参数驱动

per-edge `RemoteRelationship(pagination=True/False)` 移除。联邦分页不再由 mounter 任何静态开关控制，而是：

- **member 能力**（`__pagination_orders__` → 自动暴露 `page_by_<key>_in`）决定 mounter 能不能分页拉
- **查询参数**（mounter 查询时传的 `limit`/`order`）决定这次拉不拉 top-N

具体：
- member 有 `__pagination_orders__`（暴露 `page_by_`）→ mounter 自动 wire `page_by_` → 关系渲染 `Result{items, pagination}`，`limit` **可选**：带 limit → top-N 切片；不带 → 全量（不做分页）
- member 无 `__pagination_orders__`（只 `by_`）→ mounter wire `by_` → 关系渲染 list（全量）
- to-one 关系不受影响（从不分页）

member 的 `page_by_` 能力独立 —— mounter 不能删，只按查询参数决定调 `page_by_`（带 limit）还是 `by_`（不带）。

### 分页控制：member 声明能力 + 本地开关；联邦由参数驱动

| 控制点 | 作用 | 归属 |
|---|---|---|
| `__pagination_orders__`（entity dunder） | member 暴不暴露 `page_by_`（联邦分页能力）+ 排序 profile | member |
| `enable_pagination`（handler） | 该服务**自己本地关系**（comments）分页的总开关 | member 或 mounter（各管各的本地） |
| 查询参数 `limit`/`order`（mounter → member） | 联邦拉取时这次要不要 top-N | 运行时（查询驱动） |

mounter 侧**零联邦分页配置**：无 `RemoteRelationship.pagination`，`enable_pagination` 也只管 mounter 本地关系（不控联邦）。联邦分页 = member 能力（`__pagination_orders__`）+ 查询参数（limit）。`enable_pagination` 在 member/mounter 对称：各管各的本地关系分页。

## 影响分析

### breaking

- `RemoteRelationship(pagination=...)` 参数移除。federation 用户少，直接删（无 deprecated 期，与 020 一致）。

### federation manager 核心改动

- `_validate_and_wire_remote_relationship`（manager.py:333）：`_check_target` 的 `pagination=` 参数来源从 `rrel.pagination` 改为「探测 page_by_ 是否存在」。
- 双 loader 逻辑（full_br `by_` + page_br `page_by_`）：改为「有 page_by_ → wire paged（+ full）；无 → 只 plain」。
- `is_active_paginated_relationship`：`REMOTE_PAGED` 的判定从「rrel.pagination」改为「member 暴露了 page_by_」。

### schema 形态统一

- to-many 联邦关系：member 有 `__pagination_orders__` → mounter schema 一律 `Result{items, pagination}`（`limit` 可选：带 → top-N，不带 → 全量）；member 无 → list。
- 客户端查询：`rel(limit, order) { items { ... } pagination { has_more } }`（带 limit）或 `rel { items { ... } }`（不带，全量，仍 Result 结构）。
- to-one 不受影响（从不分页，照旧 by_id_in）。

## 开放问题（待 spec-kit clarify）

1. ~~`enable_pagination` 的角色是否扩展~~（✅ 已决策 Session 2026-08-10）：**保持独立**。`__pagination_orders__` 控联邦 `page_by_`，`enable_pagination` 控本地关系。两者正交。"全局"= 控制都在 member 级（非 mounter per-edge），已满足。
2. ~~mounter 能否强制不分页 / 谁控联邦分页~~（✅ 已决策 Session 2026-08-10，后修正）：**mounter `enable_pagination` 不控联邦**。联邦分页 = member 能力（`page_by_` 自动暴露）+ 查询参数（`limit` 运行时驱动）。member 有 `page_by_` → Result（limit 可选）；无 → list。mounter 零联邦分页配置。
3. **introspection/SDL 渲染**：`page_by_` 存在性 → 关系类型（Result vs list），需同步 sdl_generator / introspection。

## 关联

- specs/020（federation 配置正交化 —— 本议题是其分页维度的收尾）
- note 15（federation 准备清单）、note 16（分页场景全览）
- 实证测试：`tests/test_federation_pagination_transitive.py`（A→B→C 穿透分页；`pagination=True` 通过 / `False` 崩溃的对比）
