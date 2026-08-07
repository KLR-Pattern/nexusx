# Changelog

## [Unreleased] — specs/019 可组合 ErManager（同进程多 engine 组合）

新增 `ComposedErManager`：把多个自洽的 `ErManager`（各自单 engine）组合成一个
「按 entity 委托的查询代理 + 跨边界关系叠加层」，满足 `LoaderRegistry` 协议。
`create_resolver()` 产出单一总代理 Resolver，跨 engine resolve 对用户透明。
本质是「同进程版的 federation」（与 specs/012 跨进程 federation 对偶）。

### Features

- **`ComposedErManager`**（阶段1，`src/nexusx/loader/composed.py`）：按 entity
  委托 + 跨边界关系在组合体层 `cross_relationships` 集中声明（成员无感，单独使用
  纯粹）+ `_fed_registry` 只读聚合视图。
- **`LoaderRegistry` Protocol**：从 `= ErManager` 别名升级为正式
  `@runtime_checkable` Protocol，显式化 Resolver/ER 图 的查询接口契约。
- **`GraphQLHandler` / `Application` 的 `er_manager=` 注入**（阶段2）：新增可选
  `er_manager=` + `entities=`（与 `base=` 互斥），entity-first 路径支持多 engine。
  关系解析走 `er_manager.create_resolver()`，关系解析层 0 改动。

### Notes

- **纯 additive / 非 breaking**：`ErManager` / `Resolver` / `ErDiagram` 0 改动；
  全量 1505 passed 零回归。
- **federation 正交可叠加**（FR-017）：mutating 操作（`federate`/`initialize`）落子
  `ErManager`，组合体只查询委托 + `_fed_registry` 聚合；子 member 各自 federate，
  物化的 remote type 经组合体委托可见。`get_loader` 动态查找 federate 后新增的 loader
  （如 `RemoteLoader`）——US5 测试矩阵兜住的组合性漏洞。

## [Unreleased] — specs/018 DTO-first gql execution

把 entity-first gql 的 serialize 统一到 `response_builder` 心智模型(从 gql
selection 动态构建 DTO schema → Resolver 解析),删除 legacy dict-based
`_serialize` 路径,Resolver 接管 β federation dispatch。

### Breaking Changes

- **`use_response_builder` flag 移除**(Phase 7 T028):entity-first gql 的
  serialize 现在唯一走 `response_builder.build_response_model`。
  `GraphQLHandler(use_response_builder=...)` 参数不再接受——移除该参数即可
  (flag 是 018 新增、从未 release,移除不影响存量用户)。迁移见
  [docs/migration/018-dto-first.md](docs/migration/018-dto-first.md)。

### Features

- **Resolver 接管 β federation dispatch**(US3):`fetch_remote_subtree` 的调用
  从 `QueryExecutor._bfs_resolve` 收敛到 `Resolver._bfs_dispatch_entity_fields`。
  entity-first gql 的关系解析统一走 Resolver,executor 退化成
  "parse gql + dispatch method + build_response_model + Resolver.resolve"。
- **fetch primitive 对称**(US4):新增 `fetch_dto_subtree`(γ DTO federation),
  `fetch_remote_subtree` docstring 改 β-only;两者成为 Resolver 内部对称 primitive。
- **pagination 进 DTO field metadata**(US2 + 019):`reviews(limit: 5)` 在
  `build_response_model` 阶段标 `Annotated[..., PAGED_MARKER]`(占位符);真实
  limit/offset/order/direction 由 executor 注入的 `paged_provider` 闭包在 resolve
  时算(rel default + gql merge),Resolver 不读 gql args(依赖反转)。

### Performance

- **`build_response_model` LRU 缓存**(T026 + 019):按
  `(entity, field_tree, federation_namespace, paged 字段名集合)` 缓存动态 model
  class(LRU 上限 1024)。paged 字段标 `PAGED_MARKER` 占位符(019),cache key
  无视 paged 值——动态 limit 不再碎片化(018 旧 pm repr 方案 100 独特 limit 撑
  100 个 model,019 占位符恒定 1 个)。缓存前 create_model 占 flag-on 73% cumtime
  (慢 10–30×);缓存后典型场景延迟与 legacy 持平。详见
  [specs/018-dto-first-gql-execution/benchmark-baseline.md](specs/018-dto-first-gql-execution/benchmark-baseline.md)。

### Internal

- `QueryExecutor` 删除 `_serialize_relationship_value` / `_bfs_resolve` /
  `_build_field_jobs` / `_load_field*`(搬迁到 Resolver 或被 response_builder 取代)。
- **019 paged provider**:Resolver 删 `_extract_entity_page_args` /
  `_extract_entity_order_direction`;paged 参数经 `paged_provider` 闭包注入
  (executor 构造,per-call 透传 `_bfs_dispatch_entity_fields`,不挂 cached resolver
  实例)。model 用 `PAGED_MARKER` 占位符,cache key 的 paged 维改成
  `frozenset(字段名)`(无视值,零碎片化)。
- **020 删 PAGED_MARKER(纯减法)**:019 的占位符经审查功能性无人读(dispatch 用
  `rel_info.page_loader`,cache key 用 `field_tree` repr 已区分 paged 形状)。删
  `PAGED_MARKER` + `pagination_metadata` 参数链 + `_restrict_metadata` +
  `_field_sel_to_pagination_metadata` + dead plug point(`_extract_paged_metadata` /
  `_resolve_paged_for_dynamic_field`)。model paged 字段回到 plain `result_type`,
  build_response_model / serialize_with_model 删 `pagination_metadata` 参数。
  1444 passed 零回归。
