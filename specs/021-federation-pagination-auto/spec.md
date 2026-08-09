# Spec 议题：联邦分页自动化（去掉 RemoteRelationship.pagination，回归全局分页）

> 状态：议题存档（待 spec-kit 流程细化）。020 merge 后启动。

## 一句话

去掉 `RemoteRelationship(pagination=True/False)` 这个 per-edge 参数；mounter 自动按 member 已声明的分页能力（`__pagination_orders__` → `page_by_<key>_in`）选择走分页根还是批量根。分页在 ER diagram 级别回归「全局开启/关闭」语义，不再逐边声明。

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

### 去掉 `RemoteRelationship.pagination`

mounter 改为**自动选择**（`_check_target` 内部）：

```python
br = _find_batch_root(frag, join_remote, pagination=True)    # 先找 page_by_<key>_in
if br is None:
    br = _find_batch_root(frag, join_remote, pagination=False)  # 回退 by_<key>_in
```

- member 有 `__pagination_orders__`（暴露 `page_by_`）→ mounter 自动走分页根 → 关系渲染 `Result{items, pagination}`
- member 无（只 `by_`）→ 自动回退批量根 → 关系渲染普通 list
- **mounter 不再声明 pagination**；中间层（B→C）无需任何配置，A 的查询穿透到 C 自然分页（自动消费 member 能力 = 自动传递）

### 分页控制回归 member 侧（ER diagram 级全局）

去掉 per-edge 后，分页的全部控制权在 member：

| 控制点 | 作用 | 层级 |
|---|---|---|
| `__pagination_orders__`（entity） | member 暴不暴露 `page_by_`（联邦分页能力）+ 排序 profile | entity 级 |
| `enable_pagination`（handler） | member 自己本地关系（comments）分页的总开关 | handler 级（全局） |

mounter 侧零分页配置 —— 只读 member 的能力。

## 影响分析

### breaking

- `RemoteRelationship(pagination=...)` 参数移除。federation 用户少，直接删（无 deprecated 期，与 020 一致）。

### federation manager 核心改动

- `_validate_and_wire_remote_relationship`（manager.py:333）：`_check_target` 的 `pagination=` 参数来源从 `rrel.pagination` 改为「探测 page_by_ 是否存在」。
- 双 loader 逻辑（full_br `by_` + page_br `page_by_`）：改为「有 page_by_ → wire paged（+ full）；无 → 只 plain」。
- `is_active_paginated_relationship`：`REMOTE_PAGED` 的判定从「rrel.pagination」改为「member 暴露了 page_by_」。

### schema 形态统一

- to-many 联邦关系：只要 member 支持分页（有 `__pagination_orders__`），mounter schema 一律 `Result{items, pagination}`。不再有「普通 list」选项（当前 `pagination=False` 的形态消失）。
- 客户端查询统一：`rel(limit, order) { items { ... } pagination { has_more } }`。
- to-one 不受影响（从不分页，照旧 by_id_in）。

## 开放问题（待 spec-kit clarify）

1. **`enable_pagination` 的角色是否扩展**：当前只管本地关系分页。用户愿景是「ER diagram 级全局开关」—— 是否让 `enable_pagination` 也控制联邦 `page_by_` 的生成（即 member 关掉它就既不分页本地、也不暴露联邦 page_by_）？还是保持两者独立（`__pagination_orders__` 管联邦、`enable_pagination` 管本地）？
   - 倾向：保持独立（两者正交，020 已确立）。但「全局开关」的语义可能需要一个新的统一概念。
2. **mounter 能否强制不分页**：去掉后，member 支持分页时 mounter 总是走 page_by_。是否有场景 mounter 想要全量 list（不要 Result）？`page_by_(limit=None)` 可返全部，但结构仍是 Result。若确有需求，保留一个 opt-out（如 `RemoteRelationship(no_pagination=True)`，反向语义，默认 False）。
3. **introspection/SDL 渲染**：`page_by_` 存在性 → 关系类型（Result vs list），需同步 sdl_generator / introspection。

## 关联

- specs/020（federation 配置正交化 —— 本议题是其分页维度的收尾）
- note 15（federation 准备清单）、note 16（分页场景全览）
- 实证测试：`tests/test_federation_pagination_transitive.py`（A→B→C 穿透分页；`pagination=True` 通过 / `False` 崩溃的对比）
