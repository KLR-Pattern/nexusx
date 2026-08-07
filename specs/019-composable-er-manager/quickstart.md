# Quickstart: 可组合 ErManager（specs/019）

> Phase 1 产出。端到端验证场景，证明特性 works。基于 spike（`spike_composed_er.py`）已验证的场景产品化。本文是验证/运行指南，实现细节在 `tasks.md`。

## 前置

- Python ≥3.10，已 `uv sync`
- 分支 `feat/composable-er-manager`
- 本特性 0 改动既有组件（Resolver/ErManager/ErDiagram），验证时这些路径行为应与主线一致

## 场景 1：阶段 1 核心 —— 两 engine 跨库 resolve + ER 图（US1/US2/US4，P1）

**验证目标**：ComposedErManager 按 entity 委托 + 跨边界关系叠加层 + 总代理 Resolver + ER 图合并，全部成立。

**setup**：两个 SQLite engine（blog/shop），各自自洽 ErManager，一条跨库 `Relationship`（blog.User → shop.Order）。结构见 [data-model.md §3](./data-model.md)，契约见 [contracts §1](./contracts/composable-er-manager.md)。

```bash
# 产品化后（阶段 1 完成）：
uv run pytest tests/test_composed_er_manager.py -v
```

**期望**：
- `UserDTO.posts` 来自 blog session（同库 ORM 关系）
- `UserDTO.orders` 来自 shop session（跨 engine 桥，loader 闭包）
- `UserDTO.orders[*].items` 来自 shop session（跨库二级钻取，委托 shop_er）
- `ErDiagram.from_er_manager(composed)` 含 4 实体 + 跨库边 `User ||--o{ Order : orders`
- 组合体构造期重名/空成员/跨边界 target 缺失 → fail-fast 报错

> spike（`spike_composed_er.py`）已用源实体级声明验证上述；产品化改组合体层 `cross_relationships=` 注入，断言不变。

**已知坑验证**（须在测试覆盖，见 [research.md「spike 已知坑」](./research.md)）：
- root DTO 只填 subset 标量字段（勿 `model_validate(orm)`）
- `loader/composed.py` + demo models.py 不用 `from __future__ import annotations`

## 场景 2：federation × ComposedErManager 叠加（US5 矩阵，P1）

**验证目标**：组合 × 组合的组合性边界，完整测试覆盖（用户明确要求）。

```bash
uv run pytest tests/test_composed_federation.py -v
```

**期望矩阵**（每条独立测试）：

| 分组 | 场景 | 期望 |
|---|---|---|
| A. member 端组合 | A1 mounter 拉取的子树含 member 跨 engine 数据 | ✅ |
| | A2 member ER/DTO introspection 反映全部子 member + 统一 service_name | ✅ |
| B. mounter 端组合 | B1 一子 member federate → 物化 type 经组合体委托可见 + resolve 通 | ✅ |
| | B2 多子 member 各自 federate 不同远程 → 组合体聚合 | ✅ |
| | B3 resolve 同时跨 engine + 跨 service 混合路径 | ✅ |
| C. 状态聚合 | `_fed_registry` 聚合视图正确（remote type 判断、ER 图 styling） | ✅ |
| D. 约束 | ComposedErManager.initialize/federate 报错；子 member initialize 成功 | ✅ |
| E. 回归 | 现有 federation 测试（012/013/014/016）零回归 | ✅ |

## 场景 3：阶段 2 —— entity-first GraphQLHandler 注入（US3，P2）

**验证目标**：GraphQLHandler 接受 ComposedErManager，一个 schema 暴露多 engine @query，关系解析跨 engine。

```bash
uv run pytest tests/test_composed_handler.py -v   # 阶段 2
```

**期望**：
- `GraphQLHandler(er_manager=composed, entities=[合并集])` 构造成功
- `handler.get_sdl()` 同时含 UserQuery 和 OrderQuery
- `handler.execute("{ User { ... } Order { ... } }")` 跨 engine 执行，关系解析正确（走 `composed.create_resolver()`）
- 现有 `GraphQLHandler(base=...)` 单 base 路径行为零变化（回归断言）
- `handler.er` 返回组合体时，管理接口调用明确报错（语义边界）

## 场景 4：零回归（全量）

```bash
# 全量测试套件（确认 0 改动既有组件、纯 additive）
uv run pytest

# benchmark（确认组合体委托开销可忽略）
uv run python benchmarks/bench_resolver.py
```

**期望**：全量 pass；benchmark 无回退（组合体委托 = O(1) dict 查找）。

## 验证命令速查

```bash
uv run pytest tests/test_composed_er_manager.py tests/test_composed_federation.py -v  # 阶段 1
uv run pytest                                                                          # 全量零回归
uv run python spike_composed_er.py                                                     # spike 独立验证（分支上）
```
