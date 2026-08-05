# Changelog

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
- **pagination 进 DTO field metadata**(US2):`reviews(limit: 5)` 在
  `build_response_model` 阶段变成 `Annotated[list[X], Paged(limit=5)]`。

### Performance

- **`build_response_model` LRU 缓存**(T026):按
  `(entity, field_tree, federation_namespace, paged metadata)` 缓存动态 model
  class(LRU 上限 1024),消除 per-entity `create_model` 开销——缓存前它占
  flag-on serialize 73% cumtime(flag-on 比 legacy 慢 10–30×)。缓存后典型场景
  延迟与 legacy 持平。详见
  [specs/018-dto-first-gql-execution/benchmark-baseline.md](specs/018-dto-first-gql-execution/benchmark-baseline.md)。

### Internal

- `QueryExecutor` 删除 `_serialize_relationship_value` / `_bfs_resolve` /
  `_build_field_jobs` / `_load_field*`(搬迁到 Resolver 或被 response_builder 取代)。
