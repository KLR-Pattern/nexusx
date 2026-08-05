# Migration: DTO-first gql execution(specs/018)

## 概述

specs/018 把 entity-first gql 的 serialize 统一到 `response_builder` 心智模型
(从 gql selection 动态构建 DTO schema → Resolver 解析),删除 legacy dict-based
`_serialize` 路径与 `use_response_builder` flag。entity-first 开发体验不变
(用户仍写 `@query -> list[Entity]`),改动是 executor 内部实现。

## Breaking:`use_response_builder` flag 移除

**之前**(018 早期 opt-in 阶段):

```python
GraphQLHandler(base=..., use_response_builder=True)   # opt-in 新路径
GraphQLHandler(base=..., use_response_builder=False)  # legacy dict-based(默认)
```

**现在**(Phase 7 T028 后,唯一路径):

```python
GraphQLHandler(base=...)   # response_builder 是唯一路径,无 flag
```

如果代码里传了 `use_response_builder=...`,**移除该参数**即可。

> flag 是 specs/018 引入的 opt-in 开关,**从未进入正式 release**(从 master 看是新
> 增代码),所以移除不影响任何已发布版本的用户。018 早期 flag 默认 `False`(legacy),
> 移除后默认 response_builder,等价于之前的 `use_response_builder=True`——行为已经
> 过 1451 个测试零回归验证(含 24 个 federation e2e)。

## 性能

`build_response_model` 加了 **LRU 缓存**(上限 1024),动态 model class 按 gql
selection 复用——消除 per-entity `pydantic.create_model` 开销(缓存前占 flag-on
serialize 73% cumtime,导致 flag-on 比 legacy 慢 10–30×)。

**缓存 key**:`(entity, model_name, field_tree, federation_namespace type ids, paged metadata repr)`。

- gql selection 是离散的(用户固定几个 query 模式),正常命中率很高。
- `limit`/`offset`/`order`/`direction` 等 gql args 进 key(因 US2 把 `Paged` 值注入
  model 的 `Annotated[..., Paged(...)]` metadata,不同值必须区分),LRU 上限兜底
  防止循环/恶意调用膨胀。
- benchmark 见 `specs/018-dto-first-gql-execution/benchmark-baseline.md`。

## 内部架构变化(贡献者参考)

- **β federation dispatch**:从 `QueryExecutor._bfs_resolve` 搬到
  `Resolver._bfs_dispatch_entity_fields`(US3 / T016-T018)。`fetch_remote_subtree`
  的调用方收敛到只在 Resolver 内部(`grep -rn fetch_remote_subtree src/`)。
- **fetch primitive 对称**(US4):`fetch_remote_subtree`(β)+ `fetch_dto_subtree`
  (γ)对称,`set_dto_page_params` 的唯一调用方收敛到 `fetch_dto_subtree`。
- **pagination dispatch 的实际数据源**:entity-first 路径的 page_loader dispatch
  仍从 `field_sel.arguments` 读 limit/offset(`Resolver._extract_entity_page_args`),
  **不是**从 model 的 `Annotated[..., Paged]` metadata 读——US2 注入的 metadata 是
  为未来 metadata-driven dispatch 预留的 plug point(`_resolve_paged_for_dynamic_field`,
  当前未接入)。所以缓存 model 时 Paged 值进 key 是为了 US2 注入的正确性,不是为了
  dispatch 行为(后者由 field_sel 决定)。

## 复现 / 验证

```bash
uv run pytest -q                                         # 全量 1451 测试
uv run python benchmarks/gql_benchmark.py                # response_builder 延迟
uv run python benchmarks/gql_benchmark.py --profile      # + cProfile
```
