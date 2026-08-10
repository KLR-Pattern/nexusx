# Research: 联邦分页自动化

## 决策 1：去掉 RemoteRelationship.pagination，联邦分页 = member 能力 + 查询参数驱动

- **选择**：去掉 per-edge `RemoteRelationship(pagination=True/False)`。联邦分页 = member 有 `page_by_`（`__pagination_orders__`）→ mounter 自动 wire `page_by_` → 关系 `Result{items, pagination}`（`limit` 可选）；member 无 → `by_` → list。查询带 limit → top-N；不带 → 全量。
- **理由**：020 后 `pagination` 冗余（member `__pagination_orders__` 已声明能力）+ 不传递（漏一跳崩，对比实验 `test_federation_pagination_transitive.py` 为证）。member 能力 + 参数驱动最简 + 自动传递（member 能力自动被消费，无需逐边声明）。
- **替代（否决）**：mounter `enable_pagination` 接管联邦 —— 多一个静态开关，且 member 能力已够；per-edge 保留 —— 不传递问题仍在。

## 决策 2：mounter enable_pagination 不控联邦

- **选择**：`enable_pagination`（handler 级）只管该服务自己的本地关系分页（member/mounter 对称，各管各的本地）。联邦分页完全由 member 能力 + 查询参数。
- **理由**：正交（enable 本地、联邦参数驱动）。避免 enable 耦合联邦。member 本地分页（comments）vs 联邦分页（被拉）是两件事。

## 决策 3：_check_target 探测 page_by_ 存在

- **选择**：`_check_target`（manager.py）改为探测 member fragment 的 `page_by_<join_remote>_in` 是否存在。存在 → wire paged loader（page_by_）；不存在 → wire plain loader（by_）。
- **理由**：取代 `rrel.pagination` 静态标志。member 能力（introspection fragment 的 batch_roots）是真相来源。

## 决策 4：is_active_paginated_relationship 的 REMOTE_PAGED 判定

- **选择**：`REMOTE_PAGED`（关系活跃分页）判定从「rrel.pagination」改为「该联邦边 wire 了 page_by_ loader」（即 member 暴露 page_by_）。
- **理由**：跟随决策 3。SDL/introspection 的 Result 渲染跟随（member 有 page_by_ → Result）。

## 决策 5：limit 可选（Result 结构统一）

- **选择**：member 有 page_by_ → 联邦关系 schema 统一 `Result{items, pagination}`，`limit` 可选（带 → top-N，不带 → 全量 Result{items:全部}）。
- **理由**：GraphQL schema 静态（一字段一类型）。"不做分页"= 不做 top-N 切片（全量），结构仍 Result（wire 的是 page_by_）。不引入"无 limit 走 by_ list"（破坏 schema 静态）。

## 风险与回滚

- **breaking**：删 `RemoteRelationship.pagination`。federation 用户少，直接删（无 deprecated 期，与 020 一致）。
- **federation manager 核心路径**（loader wire）。需充分测试（β/γ/多层/to-one/无 limit）。
- **迁移**：现有 `RemoteRelationship(pagination=True/False)` 删参数。
- **回滚**：单分支，不合 master 前可整体回滚。
