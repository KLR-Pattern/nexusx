# Implementation Plan: DTO-first gql execution（统一两条 gql 路径）

**Branch**: `018-dto-first-gql-execution` | **Date**: 2026-08-05 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/018-dto-first-gql-execution/spec.md`

## Summary

把 entity-first gql（`GraphQLHandler.execute` / `QueryExecutor`）改造成跟 UseCase 模式一致的心智模型：从 gql selection 动态构建 DTO schema → Resolver 解析。激活当前未启用的 `response_builder.build_response_model`，扩展支持 pagination + federation remote type，让 Resolver 接管 β federation dispatch，最终 `fetch_remote_subtree` 退化成 Resolver 内部实现细节。

分 4 步走，每步可独立验证：
- **Step 1（P0）**：`_serialize` 替换为 `build_response_model` + model_validate，零回归（feature flag 控制）。
- **Step 2（P1）**：扩展 `build_response_model` 支持 `Paged[X]`，pagination 进 DTO field。
- **Step 3（P1）**：Resolver 接管 β federation dispatch，`fetch_remote_subtree` 从 `query_executor` 迁出。
- **Step 4（P2）**：抽 `fetch_dto_subtree`，对称 β / γ primitive，docstring 改诚实。

## Technical Context

**Language/Version**: Python ≥3.10（既有栈）
**Primary Dependencies**: SQLModel, SQLAlchemy(async), Pydantic v2, aiodataloader, httpx, graphql-core（nexusx 既有栈，无新增）
**Testing**: pytest（既有 federation e2e + entity-first gql 测试集 1429 个）
**Project Type**: library
**Constraints**:
- 4 步必须可独立验证；Step 1 零回归（feature flag 控制）
- β federation 协议不变（member 端 gql batch root + by_X_in / page_by_X_in）
- γ federation 协议不变（member 端 /nexusx/dto-batch）
- entity-first 开发体验不变（用户仍写 `@query -> list[Entity]`）
- 跟 [feedback_framework_boundary] 不冲突（schema 层字段过滤，不吸收业务逻辑）

**Scale/Scope**:
- Step 1：~2 源文件（query_executor.py + response_builder.py）+ 全量回归
- Step 2：~3 源文件（response_builder.py + pagination.py + resolver.py）
- Step 3：~2 源文件（query_executor.py + resolver.py）
- Step 4：~1 源文件（federation/remote_loader.py）
- 总计 ~5 源文件改动 + 新测试。中等规模。

**Performance Goals**: Step 1 / Step 3 完成后跑全量 benchmark，单 entity 序列化开销可量化（pydantic model_validate vs dict 过滤），整体 gql 响应延迟回退应 < 10%（如果超过，benchmark 分析瓶颈）。

## Constitution Check

`.specify/memory/constitution.md` 为占位模板（无实际原则）。遵循 nexusx 通用纪律：

| 纪律 | 本特性如何遵守 |
|---|---|
| 复用优先 | 激活已存在的 `response_builder.build_response_model`，不新建 |
| β 不动协议 | β gql batch root + selection-driven 语义不变，只换 caller（从 query_executor 迁到 resolver） |
| 向后兼容 | Step 1 用 feature flag（`use_response_builder=True`），测试通过后切默认 |
| fail-fast | response_builder 现有 `SelectionError` 保留；新加的 pagination metadata 缺失要 raise |
| N+1-proof | Resolver 仍是 N+1 核心；build_response_model 不引入 N+1（仅 schema 层） |
| Entity 只承载 resource（[project_entity_resource_no_computation]） | DTO schema 由 gql selection 派生，不写 resolve_* 到动态 model 上 |

**Gate: PASS**。所有纪律符合，无 Constitution violation。

## Project Structure

```text
src/nexusx/
├── execution/
│   └── query_executor.py        # ★ Step 1: _serialize → build_response_model
│                                 # ★ Step 3: 去掉 fetch_remote_subtree 直接调用
├── response_builder.py          # ★ Step 1: 激活 + 补 paginated package / forward-ref 边缘 case
│                                 # ★ Step 2: 加 Paged[X] 字段类型识别 + gql args → metadata
├── resolver.py                  # ★ Step 3: 接管 entity-first 的 BFS 字段 dispatch
├── loader/
│   └── pagination.py            #   create_result_type 复用（无改动）
└── federation/
    └── remote_loader.py         # ★ Step 4: fetch_remote_subtree docstring 改 β-only
                                 # ★ Step 4: 抽 fetch_dto_subtree（对称 γ primitive）

tests/
├── test_response_builder.py             # ★ Step 1: 补 paginated package / forward-ref case
├── test_query_executor_dto_first.py     # 新: Step 1 feature flag 切换的等价性测试
├── test_response_builder_pagination.py  # 新: Step 2 Paged[X] 字段构建
├── test_resolver_beta_dispatch.py       # 新: Step 3 Resolver 接管 β
└── test_federation_*.py                 # 既有: β/γ federation 全量回归

specs/018-dto-first-gql-execution/
├── spec.md                # ✓ 已写
├── plan.md                # ✓ 本文件
├── research.md            # Phase 0 输出
├── data-model.md          # Phase 1 输出
├── quickstart.md          # Phase 1 输出
├── contracts/             # Phase 1 输出
│   ├── response_builder_api.md   # build_response_model 接口契约
│   ├── paged_field_metadata.md   # Step 2 Paged[X] metadata 协议
│   └── resolver_dispatch.md      # Step 3 Resolver dispatch 契约
└── tasks.md               # Phase 2 输出（/speckit-tasks 后续）
```

**Structure Decision**:
- **核心改动集中在 execution / response_builder / resolver 三层**——不动 federation / loader / sdl_generator 的协议层。
- **feature flag 入口**：`GraphQLHandler.__init__` 加 `use_response_builder: bool = False` 参数，控制 `QueryExecutor` 走新路径还是旧路径。Step 1 全量测试通过后切默认 `True`，Step 4 完成后删除旧路径。
- **新文件**：`test_query_executor_dto_first.py` / `test_response_builder_pagination.py` / `test_resolver_beta_dispatch.py` 跟现有测试集隔离，便于逐步迁移。

## Complexity Tracking

无 Constitution violation，本节不填。

## Plan Workflow 输出

### Phase 0: research.md（待生成）

需要研究的关键 unknowns（来自 Technical Context 与 spec.md）：

1. **`_serialize` 边缘 case 盘点**：paginated package / materialized remote type forward-ref / UUID / date / coalesced remote 字段——这些 case 在 response_builder 里要全部覆盖。需要逐 case 比 dict-based vs model-based 行为差异。
2. **DTO schema 缓存策略**：`build_response_model` 每次 query 调用 `create_model` 的开销有多大？是否需要按 `(entity, field_tree_canonical_hash)` 缓存？参考 `use_case/selection.build_subset_model` 是否有类似缓存。
3. **Resolver 接管 β 的语义对齐**：当前 `query_executor._bfs_resolve` BFS 跟 Resolver 内部 collect 的语义差异（如 coalesced 字段、page_loader 调用时机）。
4. **feature flag 切换的渐进步骤**：Step 1 全量通过后切默认前，是否需要发 deprecation notice？保留旧路径多久？

### Phase 1: data-model.md / contracts/ / quickstart.md（待生成）

- **data-model.md**：动态构建的 DTO schema 形状（每个 entity 的 subset model 树）+ Paged[X] metadata 结构。
- **contracts/**：3 份契约（response_builder API、Paged metadata 协议、Resolver dispatch 契约）。
- **quickstart.md**：4 个 Step 的独立验证脚本（feature flag 切换、Paged 字段构建、Resolver dispatch、docstring 校验）。
