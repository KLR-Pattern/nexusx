# Tasks: 可组合 ErManager（ComposedErManager）

## Format: `[ID] [P?] [Story] Description`

- **[P]** = 可并行（不同文件 / 无未完成依赖）
- **[USx]** = 归属 User Story（Setup/Foundational/Polish 阶段无此标签）
- 每个 task 带精确文件路径，可直接执行

## Path Conventions

- 核心：`src/nexusx/loader/composed.py`（新文件）
- 导出：`src/nexusx/__init__.py` + `src/nexusx/loader/__init__.py`
- 阶段 2：`src/nexusx/handler.py` + `src/nexusx/mcp/application.py`
- 测试：`tests/test_composed_er_manager.py` + `tests/test_composed_federation.py` + `tests/test_composed_handler.py`
- 参考实现：`spike_composed_er.py`（已验证 resolve + ER 图）

## Phase 1: Setup（共享基础设施）

- [x] T001 创建 `src/nexusx/loader/composed.py` 模块文件 + 中文模块 docstring（说明 ComposedErManager = 同进程 federation 对偶、按 entity 委托 + 跨边界叠加层）

## Phase 2: Foundational（阻塞前置，所有 User Story 依赖）

- [x] T002 定义 `LoaderRegistry` Protocol（`@runtime_checkable`，方法集见 data-model.md §1）in `src/nexusx/loader/composed.py`
- [x] T003 实现 `ComposedErManager.__init__`：参数（`members` + `cross_relationships` + `service_name`）+ 建立 `_route`/`_loader_owner`/`_cross_rels` + 构造期校验（空成员/`full_class_name` 重名/跨边界 target 缺失 → fail-fast `ValueError`）in `src/nexusx/loader/composed.py`
- [x] T004 [P] 实现按 entity 委托的查询方法（`has_entity` / `get_relationships`（含叠加）/ `get_relationship` / `get_loader_for_entity`（含跨边界分支）/ `get_loader_by_name` / `get_loader`（反向路由）/ `get_dto_loader`）in `src/nexusx/loader/composed.py`
- [x] T005 [P] 实现跨边界关系叠加层：`cross_relationships` → `RelationshipInfo`（复用 `_build_custom_relationship_info` 逻辑）+ `get_relationships` 合并本地与跨边界 + `get_all_relationships` 叠加 in `src/nexusx/loader/composed.py`
- [x] T006 [P] 实现 `create_resolver`（照搬 `ErManager.create_resolver` 5 行，注入组合体自身）+ `clear_cache`（聚合所有成员）+ `get_all_entities` in `src/nexusx/loader/composed.py`
- [x] T007 [P] 实现 `_fed_registry` 聚合视图（`_CompositeFedRegistryView`：`qualified_of` / `all_classes` / `service_colors` 遍历成员 `_fed_registry`）in `src/nexusx/loader/composed.py`
- [x] T008 [P] 实现 federation member 暴露聚合（`service_name` + `get_public_dtos` / `get_dto_classes` 聚合所有成员 + `_expose_mounted_endpoints`）in `src/nexusx/loader/composed.py`
- [x] T009 导出 `ComposedErManager` + `LoaderRegistry`：加入 `__all__` in `src/nexusx/__init__.py`，并在 `src/nexusx/loader/__init__.py` 导出

## Phase 3: User Story 1 — 同进程多 engine UseCase 跨库 resolve (Priority: P1) 🎯 MVP

**目标**：ComposedErManager 按 entity 委托 + 总代理 Resolver，跨 engine resolve（含二级钻取）成立。
**独立验收**：`UserDTO.posts`（blog session）+ `UserDTO.orders`（shop session 跨库）+ `orders[*].items`（shop session 二级钻取）全通。

### Tests for User Story 1
- [x] T010 [P] [US1] 集成测试：两 engine（blog SQLite + shop SQLite）+ 跨库 resolve + 二级钻取（对应 spike 4 断言）in `tests/test_composed_er_manager.py`
- [x] T011 [US1] 测试已知坑：root DTO 只填 subset 标量字段（勿 `model_validate(orm)`，验证 DetachedInstanceError 不发生）+ 跨边界 loader 闭包使用目标 session in `tests/test_composed_er_manager.py`

### Implementation for User Story 1
- [x] T012 [US1] 从 `spike_composed_er.py` 产品化 ComposedErManager 用法到测试（声明跨边界 `Relationship` 用组合体层 `cross_relationships=`，非源实体 `__relationships__`）in `tests/test_composed_er_manager.py`

## Phase 4: User Story 2 — 跨 engine ER 图合并 (Priority: P1)

**目标**：`ErDiagram.from_er_manager(composed)` / `ErDiagramDotBuilder(composed)` 零改动产出跨 engine 图。
**独立验收**：图含全部实体 + 跨库边 + federation styling 不被 `_fed_registry` 聚合破坏。

### Tests for User Story 2
- [x] T013 [P] [US2] 测试：`ErDiagram.from_er_manager(composed).to_mermaid()` 含 4 实体 + 跨库边 `User ||--o{ Order : orders` in `tests/test_composed_er_manager.py`
- [x] T014 [P] [US2] 测试：`ErDiagramDotBuilder(composed)` DOT 渲染跨 engine（验证 `_fed_registry` 聚合视图下 styling 不缺失）in `tests/test_composed_er_manager.py`

## Phase 5: User Story 5 — federation × ComposedErManager 叠加测试矩阵 (Priority: P1)

**目标**：组合 × 组合的组合性边界完整覆盖（用户明确要求）。FR-017 正交规则成立。
**独立验收**：A–E 矩阵全绿 + 现有 federation 测试零回归。

### Tests for User Story 5
- [x] T015 [P] [US5] 测试 A（member 端组合）：A1 mounter 拉取子树含 member 跨 engine 数据 + A2 member ER/DTO introspection 反映全部子 member + 统一 service_name in `tests/test_composed_federation.py`
- [x] T016 [P] [US5] 测试 B（mounter 端组合）：B1 一子 member federate → 物化 type 经组合体委托可见 + resolve 通；B2 多子 member 各自 federate 不同远程；B3 resolve 同时跨 engine + 跨 service 混合路径 in `tests/test_composed_federation.py`
- [x] T017 [P] [US5] 测试 C（状态聚合）：`_fed_registry` 聚合视图正确（remote type 判断 + ER 图 styling）in `tests/test_composed_federation.py`
- [x] T018 [P] [US5] 测试 D（约束）：`ComposedErManager.initialize` / `federate` 明确报错（FR-013）+ 子 member `initialize` 成功、组合体委托看到物化结果 in `tests/test_composed_federation.py`
- [x] T019 [US5] 测试 E（回归）：现有 federation 测试（012/013/014/016）零回归 — 跑 `uv run pytest tests/test_federation*.py`

## Phase 6: User Story 4 — 跨边界关系声明 (Priority: P2)

**目标**：跨边界关系声明在组合体层（DD-02），同时进 resolve 链路 + ER 图 + 构造期校验。
**独立验收**：`cross_relationships` 声明 → resolve + ER 图边；非法声明 fail-fast。

### Tests for User Story 4
- [x] T020 [P] [US4] 测试：`cross_relationships` 声明跨边界关系 → resolver 跨库 resolve + ER 图画出边 in `tests/test_composed_er_manager.py`
- [x] T021 [US4] 测试：构造期校验 fail-fast（重名实体 / 空 members / 跨边界 source-target 缺失 / `Relationship` 非法）in `tests/test_composed_er_manager.py`

## Phase 7: User Story 3 — entity-first GraphQLHandler 注入 (Priority: P2，阶段 2)

**目标**：GraphQLHandler / Application 接受 ComposedErManager，一个 schema 暴露多 engine @query，关系解析跨 engine（非 breaking）。
**独立验收**：SDL 合并 + execute 跨 engine + 现有 `base=` 路径零变化。

### Implementation for User Story 3
- [x] T022 [US3] `GraphQLHandler.__init__` 增加可选 `er_manager=` + `entities=` 注入分支（与 `base=` 互斥；注入时跳过 `EntityDiscovery` + 自造 ErManager，`QueryExecutor(loader_registry=composed)`）；`er` property 注解放宽 `-> LoaderRegistry` in `src/nexusx/handler.py`
- [x] T023 [P] [US3] 测试：`GraphQLHandler(er_manager=composed)` SDL 含 UserQuery + OrderQuery + `execute` 跨 engine + `base=` 单 base 路径回归 + `handler.er` 管理接口报错 in `tests/test_composed_handler.py`
- [x] T024 [US3] `Application.__init__` 增加可选 `er_manager=` + `entities=` 注入（透传 GraphQLHandler，与 `base=`/`url`/`engine`/`session_factory` 互斥）in `src/nexusx/mcp/application.py`
- [x] T025 [P] [US3] 测试：`Application(er_manager=composed)` 构造 + 现有 `base=` 路径回归 in `tests/test_composed_handler.py`

## Phase 8: Polish & Cross-Cutting Concerns

- [x] T026 [P] 多 engine 组合可运行 demo（spike_composed_er.py：两 engine + 跨库 resolve + ER 图，`uv run python specs/019-composable-er-manager/spike_composed_er.py` 即跑）
- [x] T027 跑全量测试套件零回归：`uv run pytest`
- [x] T028 [P] 跑 benchmark 确认组合体委托开销可忽略：`uv run python benchmarks/bench_resolver.py`
- [x] T029 更新 `CHANGELOG.md`（英文，pydantic-resolve 风格）+ 相关 `docs/`

---

## Dependencies（User Story 完成顺序）

```
Phase 2 Foundational (T002–T009)
        │
        ├──▶ Phase 3 US1 (T010–T012)  🎯 MVP
        │       │
        │       └──▶ Phase 5 US5 (T015–T019)  [依赖 US1/US2 能力 + federation]
        │
        ├──▶ Phase 4 US2 (T013–T014)  [与 US1 并行]
        │
        ├──▶ Phase 6 US4 (T020–T021)  [与 US1/US2 并行，依赖 Foundational]
        │
        └──▶ Phase 7 US3 (T022–T025)  [阶段 2，独立于 US1/US2/US5]

Phase 8 Polish (T026–T029)  [依赖前面全部]
```

- **US1 / US2 / US4**：彼此独立，依赖 Foundational 即可并行
- **US5**：依赖 US1 + US2（组合 + ER 图能力就绪）+ 现有 federation 基建
- **US3**：阶段 2，独立于 US1/US2/US5，可后置

## Parallel Execution Examples

- Foundational 内 T004/T005/T006/T007/T008 方法独立，可并行实现（同文件不同方法）
- US1（T010）/US2（T013）/US4（T020）测试可并行（同 `test_composed_er_manager.py` 不同测试函数）
- US5 矩阵 A/B/C/D（T015–T018）分组独立，可并行
- US3 handler（T022/T023）与 Application（T024/T025）可并行

## Implementation Strategy（MVP first，增量交付）

1. **MVP = Phase 2 Foundational + Phase 3 US1**：ComposedErManager 核心 + 跨库 resolve 跑通 → 证明「同进程多 engine 组合」成立（spike 已验证，产品化收口）
2. **增量 1**：US2（ER 图）+ US4（声明/校验）—— 补全阶段 1 全部 P1/P2
3. **增量 2**：US5（federation 叠加矩阵）—— 组合 × 组合的测试兜底
4. **阶段 2**：US3（GraphQLHandler/Application 注入）
5. **收尾**：demo + 零回归 + changelog

每步可独立验证（见 quickstart.md 场景 1–4），全程纯 additive / 非 breaking（见 contracts §6）。
