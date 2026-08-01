# Tasks: Federation 分页 order/direction 开放给查询者

**Input**: Design documents from `/specs/014-federation-order-direction/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/order-direction.md, quickstart.md

**Organization**: 任务按 User Story 组织。本特性的 US1（查询者挑 order+direction）/ US2（mounter 渲染 enum）/ US3（direction 翻转 nulls）是同一条端到端链路的不同验证面——member 侧改动（direction 翻转 + 单列）是它们共同的 Foundational 基础，US1 是端到端 MVP，US2/US3 是 US1 之上的独立验证维度。

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: 可并行（不同文件，无依赖）
- **[Story]**: 所属 User Story（US1/US2/US3）
- 描述含精确文件路径

---

## Phase 1: Setup

**Purpose**: 确认环境（已有 library，无新项目结构）

- [X] T001 确认当前在 `feat/federation` 分支（或切到 `feat/federation-order-direction`）；`specs/014-federation-order-direction/` 文档齐全；`nexusx[federation]` extra（httpx）可用

---

## Phase 2: Foundational — member 侧 direction 支持

**Purpose**: member 的 `page_by_<key>_in` 接受 direction 并按它翻转。这是 US1/US3 的共同基础，MUST 先完成。

**⚠️ CRITICAL**: US1/US3 都依赖此 phase。

- [X] T002 member: `page_by_field_in` 新增 `direction` 参数（annotations + `__signature__` 加 Direction 参数，与 order/limit/offset 并列）in `src/nexusx/standard_queries.py`
- [X] T003 member: 在 `_build_order_expressions` **之前**按 direction 翻转 terms —— `direction` 覆盖 term 默认方向、`nulls` 跟随翻转（`desc+nulls_last` ↔ `asc+nulls_first`），翻转后 terms 同时用于 window 内层与 outer（含 PK tie-breaker 方向）in `src/nexusx/standard_queries.py`
- [X] T004 member: `_resolve_page_orders` 收紧单列 —— `PageOrder` 必须恰好一个 `OrderTerm`（多列启动期拒绝，错误指明 profile 名）in `src/nexusx/standard_queries.py`
- [X] T005 [P] member 单元测试: direction 翻转（ASC/DESC）+ nulls 跟随 + 单列拒绝多列 in `tests/test_federation_order_direction.py`（新建）

**Checkpoint**: member 端独立可测 —— `page_by_<key>_in(keys, order, direction=DESC/ASC)` 返回正确翻转排序。

---

## Phase 3: User Story 1 — 查询者挑 order + direction（Priority: P1）🎯 MVP

**Goal**: 查询者经 GraphQL `reviews(order, direction)` 挑排序，mounter 透传给 member，member 按选择排序返回——完整端到端。

**Independent Test**: 起 catalog（挂 reviews，reviews 暴露 HIGHEST_RATING/NEWEST）+ reviews + users，查 `reviews(order: HIGHEST_RATING, direction: DESC)` 与 `reviews(order: NEWEST, direction: ASC)`，断言排序不同且各自正确。

### Implementation for User Story 1

- [X] T006 [P] [US1] `RelationshipInfo` 加 `page_capability: BatchPageCapability | None = None` 字段 in `src/nexusx/loader/registry.py`
- [X] T007 [US1] `manager._validate_and_wire` 从 `BatchRoot.page` 取 capability 存进 `rel_info.page_capability`；校验放宽（`pagination=True` 不再强制 `RemoteRelationship.order`；改为校验 `page_capability.orders` 非空，否则 fail-fast）in `src/nexusx/federation/manager.py`
- [X] T008 [US1] RemoteLoader: `create_paginated_remote_loader` 去掉 `order` 参数（不再 bake order）in `src/nexusx/federation/remote_loader.py`
- [X] T009 [US1] RemoteLoader: `build_paginated_gql_query` 加 `direction`；`batch_load_fn` 从 `selection.arguments` 读 order/direction（缺省传 member default_order / profile 默认方向）in `src/nexusx/federation/remote_loader.py`
- [X] T010 [P] [US1] SDL: federation 分页关系字段渲染 `reviews(limit: Int, offset: Int = 0, order: <XxxOrder>, direction: Direction): <Target>Result!` —— order enum 值 = `rel_info.page_capability.orders` 名集合，默认 = `default_order`；`Direction`(ASC|DESC) mounter 自有全局 enum in `src/nexusx/sdl_generator.py`
- [X] T011 [P] [US1] Introspection 镜像: `__schema` 暴露同样的 order/direction 参数（复用 `utils/pagination_schema` 共享判定，保证与 SDL 一致）in `src/nexusx/introspection.py`
- [X] T012 [P] [US1] `RemoteRelationship.order` 字段废弃: 删除 `order` 字段 + `__post_init__` 相关分支 + `order requires pagination=True` 校验 in `src/nexusx/federation/relationship.py`
- [X] T013 [US1] e2e 测试: 查询者传 `order`+`direction` → mounter 透传 → member 收到正确 order+direction、按翻转排序；断言同一关系不同 order/direction 结果不同且正确 in `tests/test_federation_order_direction.py`

**Checkpoint**: US1 端到端跑通 —— 查询者能挑 order+direction 拿到正确排序结果。

---

## Phase 4: User Story 2 — mounter schema 暴露 order/direction（Priority: P1）

**Goal**: 查询者从 mounter 的 SDL / `__schema` 能发现 `order` enum（值=member profile 集合）+ `direction`，无需手写 enum。

**Independent Test**: 挂载 reviews（暴露两 profile）后取 SDL + `__schema`，断言 `reviews` 字段有 order 参数（enum 含两 profile 名，默认=default_order）+ direction 参数。

**Note**: 本 story 的**实现**已在 US1 的 T010/T011 完成（SDL/introspection 渲染 enum）；本 phase 是**独立的 schema 发现验证**。

- [X] T014 [US2] schema 发现测试: 取 mounter SDL + `__schema` 内省，断言 federation 分页字段含 `order` enum（值 = member profile 名集合，默认 = `default_order`）+ `direction`(ASC|DESC)；SDL 与 `__schema` 暴露一致 in `tests/test_federation_order_direction.py`

**Checkpoint**: US2 验证 —— 客户端能从 schema 发现 order/direction 选项。

---

## Phase 5: User Story 3 — direction 翻转 nulls 正确（Priority: P2）

**Goal**: direction 翻转时 NULL 位置语义正确（desc NULL 末尾 ↔ asc NULL 开头）。

**Independent Test**: member 定义 nullable 列 profile（desc + nulls_last），查 DESC 与 ASC，断言 NULL 位置翻转。

**Note**: 本 story 的**实现**已在 Foundational T003（翻转含 nulls flip）；本 phase 是**聚焦 nullable 场景的正确性验证**。

- [X] T015 [US3] nulls 翻转测试: nullable 列 profile，direction DESC vs ASC，断言 NULL 位置翻转（`nulls_last` ↔ `nulls_first`），含 window/outer 一致 in `tests/test_federation_order_direction.py`

**Checkpoint**: US3 验证 —— NULL 排序跨 direction 正确。

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: demo / 文档 / 迁移 / 全量验证

- [X] T016 [P] demo: `reviews_app` 暴露 `HIGHEST_RATING` + `NEWEST` 两个单列 profile；`catalog_app` 用 `RemoteRelationship(pagination=True)`（不写 order）+ 查询示例带 order/direction in `demo/federation/reviews_app.py` + `demo/federation/catalog_app.py`
- [X] T017 [P] 文档: `docs/advanced/federation.md` + `docs/advanced/federation.zh.md` 加 order/direction 开放段（查询形态 + 翻转语义 + 索引控制权边界）in `docs/advanced/`
- [X] T018 迁移既有用法: 移除 `RemoteRelationship(order=...)` 的旧声明（demo + tests）+ 移除断言 "order 静态 bake" 的旧测试（如 `test_federation_pagination_decl.py` 里 order 相关、`test_federation_pagination_e2e.py` 的 order 断言）—— 改为查询参数驱动 in `tests/` + `demo/`
- [X] T019 全量 `uv run pytest tests/ -q` + `uv run ruff check src/ tests/` 全绿
- [X] T020 按 `specs/014-federation-order-direction/quickstart.md` 跑 6 个验证场景

---

## Dependencies & Execution Order

### Phase 依赖

- **Phase 1 Setup**: 无依赖
- **Phase 2 Foundational（member）**: 依赖 Setup —— **阻塞** US1/US3
- **Phase 3 US1（端到端 MVP）**: 依赖 Phase 2 —— US1 内部顺序：T006→T007（registry→manager）、T008→T009（remote_loader）、T010/T011/T012 可并行、T013 依赖 T006-T012
- **Phase 4 US2（schema 验证）**: 依赖 US1（T010/T011 实现）
- **Phase 5 US3（nulls 验证）**: 依赖 Phase 2（T003 翻转）
- **Phase 6 Polish**: 依赖 US1 完成

### User Story 独立性

- **US1（P1，MVP）**: 依赖 Foundational。独立可测 = 端到端查询挑 order/direction。
- **US2（P1）**: 实现⊆US1；独立验证 = schema 发现。
- **US3（P2）**: 实现⊆Foundational；独立验证 = nulls 翻转正确性。

### 并行机会

- Phase 2: T005（测试）可与 T002-T004 并行（不同文件）
- Phase 3: T006 / T010 / T011 / T012 不同文件可并行（均依赖 Foundational）；T008→T009 同文件顺序；T007 依赖 T006
- Phase 6: T016 / T017 不同文件可并行

---

## Implementation Strategy

### MVP First（Foundational + US1）

1. Phase 1 Setup（确认环境）
2. Phase 2 Foundational（member direction 翻转 + 单列）—— **STOP 验证**: member 单元测试 direction 翻转正确
3. Phase 3 US1（mounter 端到端）—— **STOP 验证**: e2e 查询者挑 order/direction 拿到正确结果
4. 此时 MVP 成立：查询者能挑 order+direction

### Incremental Delivery

5. Phase 4 US2（schema 发现验证）—— 客户端可从 schema 发现选项
6. Phase 5 US3（nulls 翻转验证）—— NULL 排序正确
7. Phase 6 Polish（demo/文档/迁移/全量）

### 关键风险点（实现时留意）

- **T003 翻转一致性**: 翻转在 `_build_order_expressions` 之前对 terms 一次性完成，window 内层与 outer 复用同一翻转后 terms（沿用 013 稳定排序约束）
- **T009/T010 order 缺省链**: 查询者不传 order → mounter 用 default_order；不传 direction → member 用 profile 默认方向
- **T018 迁移波及面**: `RemoteRelationship.order` 删除影响所有用 `order=` 的 demo/test（grep `RemoteRelationship(order=` 或 `order=` in RemoteRelationship 构造）

---

## Notes

- [P] 任务 = 不同文件、无依赖
- [Story] label 映射到 spec.md 的 User Story
- US1 是 MVP（端到端）；US2/US3 实现分别在 US1/Foundational，本 tasks 把它们的**独立验证**单列 phase
- 每个 checkpoint 可停下来独立验证
- 提交粒度：按 task 或逻辑组提交
