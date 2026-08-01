# Tasks: 本地分页 order/direction

**Input**: Design documents from `/specs/015-local-pagination-order-direction/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/local-pagination-order.md

**Organization**: 按 user story 组织（spec.md: US1 P1 / US2 P1 / US3 P2），每个 story 可独立实现与测试。nexusx 是既有 library，无 Setup 初始化，从 Foundational 起。

**Tests**: 本特性含测试任务（端到端 + 渲染 + 回归），因 spec 的 Success Criteria 要求零回归 + 行为可验证。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件，无未完成依赖）
- **[Story]**: 归属 user story（US1/US2/US3）；Foundational/Polish 无 story 标签
- 描述含精确文件路径

---

## Phase 1: Foundational（声明 + 元数据 + 校验）

**Purpose**: 所有 user story 的基础——声明 API、元数据携带 profile、启动期校验。**⚠️ 阻塞所有 story。**

- [x] T001 约定类级 `__pagination_orders__: dict[str, BatchPageConfig]`（key=ORM relation 名）声明本地分页 order profile；ErManager 启动期读取 `getattr(entity, "__pagination_orders__", {})`、按 key 关联 ORM relationship name in `src/nexusx/loader/registry.py`
- [x] T002 [P] `RelationshipInfo.page_capability` 字段已存在（`registry.py:77`，014 为 federation 加）；本地分页在 `_inspect_relationships` 构造时传入 in `src/nexusx/loader/registry.py`
- [x] T003 启动期从 `__pagination_orders__` 构建 `page_capability`：`_resolve_local_page_capability` 复用 federation 的 `_resolve_page_orders` 校验（enum 名/单列/SQL column/direction/nulls/default∈keys）→ `BatchPageCapability`；无声明时 None（向后兼容） in `src/nexusx/loader/registry.py`
- [x] T004 [P] shared core（`_resolve_page_orders`/`_build_order_expressions`/`_apply_direction`）已在 `standard_queries.py`，helper 局部 import 调用，无循环依赖 in `src/nexusx/standard_queries.py`

**Checkpoint**: 声明 API 就位、启动期 fail-fast 校验、关系元数据携带 profile 集合。未配 `page_orders` 的关系 `page_capability=None`，行为不变。

---

## Phase 2: User Story 2 — member 声明 → schema 渲染 order enum + direction (Priority: P1)

**Goal**: member 配 `page_orders` 后，schema 自动把本地分页关系渲染成 `comments(limit, offset, order: <Enum>, direction: Direction)`，查询者能从 schema 发现选项。

**Independent Test**: `Review.comments` 配 `{NEWEST, MOST_LIKED}` 后取 SDL + `__schema` 内省，断言字段签名含 `order` enum（两值，默认=`default_page_order`）+ `direction` enum（ASC/DESC）。

- [ ] T005 [P] [US2] `is_active_paginated_relationship` 加第四分支（`kind==LOCAL and page_capability is not None` → 判定为分页字段），让本地分页 profile 关系走分页渲染 in `src/nexusx/utils/pagination_schema.py`
- [ ] T006 [US2] `sdl_generator` 为本地分页关系渲染 `order` enum（值=`page_capability.orders` 名集合，默认=`default_order`）+ `direction` 参数，复用 federation 分页的 order enum 渲染分支 in `src/nexusx/sdl_generator.py`
- [ ] T007 [P] [US2] `introspection` 的 `__schema` 同步渲染 order/direction（SDL 与内省同源，SC-003） in `src/nexusx/introspection.py`
- [ ] T008 [US2] 测试：SDL + `__schema` 渲染 order enum + direction（配 `{NEWEST, MOST_LIKED}` → 字段签名含两参数 + 默认值正确；未配 `page_orders` 的关系无 order/direction 参数——向后兼容） in `tests/test_local_pagination_order_render.py`

**Checkpoint**: schema 暴露 order/direction，查询者能发现选项（spec US2 达成）。

---

## Phase 3: User Story 1 — 查询者挑 order/direction + page_loader 执行 (Priority: P1) 🎯 MVP

**Goal**: 查询者传 `comments(order: X, direction: DESC)` → 本地 page_loader 按 profile + direction 排序，返回正确分页结果。

**Independent Test**: 起 member（`Review.comments` 配 `NEWEST`/`MOST_LIKED`），查 `comments(order: MOST_LIKED, direction: DESC)` 与 `comments(order: NEWEST, direction: ASC)`，断言两次排序不同且各自正确。

- [ ] T009 [US1] `create_page_one_to_many_loader` 改造：接受 `page_capability: BatchPageCapability | None`；非 None 时按 `cmd.order`/`cmd.direction` + 选定 profile 构建 ORDER BY（复用 `_build_order_expressions(_apply_direction(resolved_terms, direction))`），替代固定 `sort_field`；None 时维持现状（逐字节不变） in `src/nexusx/loader/factories.py`
- [ ] T010 [P] [US1] `create_page_many_to_many_loader` 同改造（many-to-many 本地分页关系） in `src/nexusx/loader/factories.py`
- [ ] T011 [US1] cmd 扩展携带 `order: str | None` + `direction: Direction | None`；`batch_load_fn` 从 `first_cmd` 读（同 `first_cmd.page_args` 模式，`factories.py:355`；同 batch 同值，research D1） in `src/nexusx/loader/factories.py`
- [ ] T012 [US1] `query_executor` 从 `child_sel.arguments`（`FieldSelection.arguments`）提 `order`/`direction`，构造本地 page_loader 的 cmd 时注入（research D5） in `src/nexusx/execution/query_executor.py`
- [ ] T013 [US1] 端到端测试：`comments(order, direction)` 排序正确 + `limit/offset/has_more/total_count` + 不同 profile 结果不同 + 稳定 tie-breaker（PK） in `tests/test_local_pagination_order.py`

**Checkpoint**: 查询者能挑 order/direction 并拿到正确排序（spec US1 达成，MVP 完成）。

---

## Phase 4: User Story 3 — direction 翻转时 nulls 跟随 (Priority: P2)

**Goal**: `direction` DESC↔ASC 翻转时，NULL 位置正确跟随（desc NULL 在末、asc NULL 在首），沿用 014 语义。

**Independent Test**: nullable 列的 profile（desc + nulls_last），查 desc 与 asc，断言 NULL 位置翻转。

- [ ] T014 [US3] 测试：nullable order 字段 direction 翻转，nulls 跟随（`nulls_last`→`nulls_first`）；验证 `_apply_direction` 复用对本地 page_loader 生效（窗口内层与外层 order 表达式一致） in `tests/test_local_pagination_order.py`

**Checkpoint**: nulls 翻转语义正确（spec US3 达成，复用 014 的 `_apply_direction`）。

---

## Phase 5: Polish & Cross-Cutting

- [ ] T015 [P] 回归测试：未配 `page_orders` 的本地分页行为不变（`test_loader_pagination`/`test_pagination_mixed` 全绿，SC-004）+ federation 分页不受影响（`test_federation_pagination_e2e`/`test_federation_order_direction` 全绿，SC-005） in `tests/`
- [ ] T016 [P] demo 可选：`demo/federation/reviews_app.py` 的 `Review.comments` 加 `page_orders`（如 `NEWEST`/`OLDEST` by `created_at`），演示本地 order/direction in `demo/federation/reviews_app.py`
- [ ] T017 [P] 文档：本地分页 order/direction 用法补进 `docs/advanced/federation.md`（或本地分页文档），含声明示例 + 查询形态 in `docs/`

---

## Dependencies & Execution Order

### Phase 依赖

- **Foundational (T001-T004)**：无前置，**阻塞所有 story**
- **US2 渲染 (T005-T008)**：依赖 Foundational
- **US1 执行 (T009-T013)**：依赖 Foundational；端到端测试（T013）依赖 US2 渲染（schema 要有 order enum 才能查）
- **US3 nulls (T014)**：依赖 US1 执行（page_loader 要先支持 direction）
- **Polish (T015-T017)**：依赖所有 story

### 并行机会

- Foundational 内：T002（RelationshipInfo）与 T004（shared core 确认）不同文件 [P]
- US2 渲染内：T005（pagination_schema）与 T007（introspection）不同文件 [P]
- T010（many-to-many）仿 T009（one-to-many）模式，T009 完成后 [P]
- Polish：T015/T016/T017 互不冲突 [P]

---

## Implementation Strategy

### MVP First（Foundational + US2 + US1）

1. Phase 1 Foundational → 声明/元数据/校验就位
2. Phase 2 US2 渲染 → schema 暴露 order/direction
3. Phase 3 US1 执行 → page_loader 按 profile+direction 排序
4. **STOP 验证**：查 `comments(order, direction)` 返回正确排序（spec US1+US2 联合 = MVP）
5. US3 / Polish 增量

### 增量交付

- Foundational → US2（渲染可独立验证：SDL 有 enum）→ US1（执行可独立验证：查询排序正确）→ US3（nulls）→ Polish（回归 + demo + 文档）
- 每步不破坏前步（向后兼容 + federation 零回归是不变式）

---

## Notes

- 复用优先：`_resolve_page_orders` / `_build_order_expressions` / `_apply_direction` / federation 渲染分支均直接调用，不重复实现（research D2/D4/D6）
- 向后兼容：未配 `page_orders` 的关系 `page_capability=None`，page_loader 走 `sort_field`，逐字节不变
- federation × 本地叠加（5.0.1）不受本特性影响；外层 federation order/direction 与内层本地 order/direction 各自从自己的 `selection.arguments` 读，互不干扰
- Commit 习惯：每个 task 或逻辑组后提交；Checkpoint 处验证 story 独立可测
