# Changelog

## [Unreleased] — issue #160 M1 (suggested minor; spec 026)

### Changed (internal, behaviour-preserving)
- One leaf module `nexusx.annotation_utils` for every `Optional` / `list` / `Annotated` / `Mapped` unwrapping (`is_optional`, `unwrap_optional`, `unwrap_optional_strict`, `is_union`, `is_list`, `is_list_annotation`, `list_inner`, `strip_annotated`, `is_mapped_wrapper`, `unwrap_mapped`, `core_types`, `is_pydantic`, `safe_issubclass`, `unwrap_func`, `map_annotation`); the 20+ private copies are gone. `introspector._collect_core_types` used to keep `NoneType` in its result — the skip-`None` rule is now the only one.
- One `dir(entity)` scan (`scanning.method_scanner.iter_entity_callables` / `iter_operations`) shared by `MethodScanner`, `SDLGenerator`, `EntityDiscovery`, `pagination_schema` and voyager.
- `utils.naming.{pascal_case, snake_case}` and `use_case.context.{is_from_context_annotation, unwrap_from_context}` replace their copies. **Fix on the way:** the CLI used to unwrap *any* subscripted annotation (a `list[int]` parameter became `int` for Typer); only the `Annotated` shell is stripped now.
- `RelationshipInfo` is an `ABC` (instantiating it raises `TypeError`), `direction` is a `Literal` with the same five values, `loader` is **required** on the three loading variants, every variant has `loader_classes()`, and `plain_loader_of()` / `page_capability_of()` replace the 20 `getattr(rel_info, …)` reads. `BatchPageCapability` / `PageOrderDescriptor` are defined in `loader.pagination` (federation wire unchanged; `federation.contract` re-exports). `Relationship` and `RemoteRelationship` share `RelationshipBase`.
- `compose_schema.FieldInfo` → `ComposeField`, `voyager.type.FieldInfo` → `VoyagerField` (old names are aliases until 8.0).
- `response_builder`'s process-level model cache is keyed by the registry; `context` annotation caches are weak; `subset.py` imports `federation.remote_ref` / `loader.pagination` directly.

### Added
- `Decimal` is a named custom scalar on both GraphQL paths (compose used to reject it generically; entity-first silently mapped it to `String`). Wire value unchanged (string).
- `ErManager.session_factory`, `ErManager.dto_batch_roots`, `ErManager.register_dto_batch_roots()`; `nexusx.use_case.create_use_case_router` export.
- `mypy --strict` is enforced in CI (`scripts/check-mypy.sh`) for the cleared modules: `annotation_utils`, `decorator`, `relationship`, `context`, `discovery`, `scanning`, `utils/*`, `loader/*`. Whole-package errors 487 → 132.

### Deprecated (removal in 8.0)
- `QueryParser.parse_document` (merged-operations hazard — use `parse_operations` / `parse`), `QueryParser.validate_no_aliases`, `utils.naming.to_camel_case`, one-argument `ErManager.get_dto_loader(<field_name>)`, the `FieldInfo` aliases above.
- `UseCaseService` now logs a warning (instead of silently skipping) for a sync `@query` / `@mutation` method.

### Removed (dead code)
- `execution.FieldTreeBuilder`, `utils.schema_helpers.collect_enum_types`, `utils.type_utils.get_return_entity_type`, `QueryParser(entity_field_names=)` (never read), two empty `if TYPE_CHECKING: pass` blocks, two wrapper layers around `is_active_paginated_relationship`.

## [Unreleased] — issue #160 M0 (suggested patch)

### Fixed
- `limit: 0` on a local paginated relationship (O2M and M2M) no longer reports `has_more: true` — the peek-by-1 window still fetched one row and `1 > 0` claimed a next page for an empty one. The member-side `page_by_<key>_in` root already had this guard (specs/021 GAP E); the two local loaders now match it.
- `Resolver` caches that read the registry (`should_traverse`, traversable fields) are now scoped per `ErManager` instead of per class. With two ErManagers in one process (ComposedErManager, multi-app, federation tests), the first registry's answer used to freeze in a class-keyed cache and the second registry's relationships were never traversed.
- A paginated field (or `page_by_<key>_in` root) queried without `limit` or `fetchAll` is rejected **before** execution with `extensions.code = "PAGINATION_INTENT_REQUIRED"` and a path pointing at the field — previously the user's method ran and the loader's `ValueError` surfaced as `RESOLVER_ERROR`. The SDL advertises the three args as optional; this check keeps schema and execution honest.
- `GraphQLHandler.execute`'s top-level catch-all now returns `extensions.code = "INTERNAL_ERROR"` like every other error path, so agents never hit a `KeyError` on `extensions`.

### Docs
- `decorator.py` / `how_it_works.md` / `llms-full.txt` / package docstring synced with the 7.0 contract: verbatim method names on `{Entity}Query` group types (no `{entityName}{methodName}`), `sa_relationship_kwargs={"order_by": ...}` as the pagination opt-in (SQLModel's `Relationship` has no `order_by` kwarg), no `enable_pagination`, `limit`-or-`fetchAll` intent rule.

## 7.0.0

### Breaking
- `enable_pagination` removed everywhere — declaring `order_by` IS the pagination opt-in; ordered lists now render `{items, pagination}` + volume args.
- Hidden default page size removed — paginated field queries must declare `limit` or `fetchAll` (no silent 20-item truncation).

### Added
- `fetchAll: Boolean` on paginated fields (local + federation + member roots): overrides `limit`/`offset`, bounded by `max_fetch_all` (default 10000; errors, never truncates).
- Relationship variants: `RelationshipInfo` base + `LocalRelationship` / `RemotePlainRelationship` / `RemotePagedRelationship` / `RemoteCoalescedRelationship`; `RelationshipKind` deleted; polymorphic `can_paginate` / `is_paginated`; illegal states raise `TypeError` at construction. All variants are frozen — mutating one (e.g. smuggling a `page_loader` onto a coalesced rel) raises `FrozenInstanceError`.
- MCP `instructions` auto-append the pagination volume contract when the schema has Result-wrapped fields (single/multi-app factories; γ use-case surface stays pass-through); tool descriptions keep examples + pointer only.


## 6.9.1

### Fixed

- Auto-fit the Related Entities sub-graph in the Voyager sidebar. d3-graphviz only
  honors `fit` when a width/height is set, so the component now mirrors
  `GraphUI.render()` (`.width("100%").height("100%").fit(true)` + `resetZoom()`)
  and re-centers on every tab/entity switch. Previously the sub-graph rendered at
  its natural size and overflowed the sidebar, requiring a manual zoom-out.

## 6.9.0

### Fixed

- Restore `AutoLoad(origin=...)` for DTO fields whose names differ from their
  registered relationships. Type checks and manual resolver priority remain unchanged.
- Preserve required SQL columns when fields use one relationship with different DTO types.
- Apply pagination defaults by DTO field name so aliases retain separate limits and offsets.
- Add regression tests and document relationship overrides in the Core API guide.

### Also in this release

**specs/019 可组合 ErManager（同进程多 engine 组合）**

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

**specs/018 DTO-first gql execution**

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
