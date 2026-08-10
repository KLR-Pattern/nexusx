# Tasks: 联邦分页自动化（去掉 RemoteRelationship.pagination）

**Input**: Design documents from `/specs/021-federation-pagination-auto/`（spec/plan/research/data-model/contracts/quickstart）

**Tests**: 本 feature 是重构（去掉 pagination + 自动 page_by_），测试跟随迁移 + 新增覆盖。

**Organization**: 按 user story 组织（US1 P1 核心 / US2 P2 schema+测试 / US3 P3 demo/docs/polish）。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无依赖）
- **[Story]**: 所属 user story
- 每个任务含具体文件路径

---

## Phase 1: Setup

**Purpose**: feature 分支（复用既有 src/nexusx，无新基础设施）

- [x] T001 开 feature 分支 `021-federation-pagination-auto`（基于 master be535fe，含 020）

---

## Phase 2: Foundational（阻塞所有 US）

**Purpose**: RemoteRelationship 去 pagination 参数 —— 后续所有改动的基础

**⚠️ CRITICAL**: 本阶段完成前不得开始任何 US

- [x] T002 RemoteRelationship 移除 `pagination` 字段（参数 + 赋值 + docstring）—— `src/nexusx/federation/`（RemoteRelationship 定义处，grep `class RemoteRelationship` 定位）

**Checkpoint**: RemoteRelationship 无 pagination，下游可改读 page_by_ 探测

---

## Phase 3: User Story 1 — federation manager 自动探测 page_by_（Priority: P1）🎯 MVP

**Goal**: 去掉 per-edge pagination 后，federation manager 自动按 member 能力（page_by_ 存在）wire loader。联邦分页 = member 能力 + 查询参数（limit）驱动。

**Independent Test**: 给定 A→B 联邦，B 有 `__pagination_orders__`（暴露 page_by_），A 的 RemoteRelationship 不写 pagination，A 查 `bs(limit:N) { items }` → top-N Result 正常；B 无 `__pagination_orders__` → A 查 `bs { ... }` → list。

- [x] T003 [US1] `_check_target` 改为探测 member fragment 的 `page_by_<join_remote>_in` 存在（取代 `pagination=rrel.pagination`）—— `src/nexusx/federation/manager.py`
- [x] T004 [US1] `_validate_and_wire_remote_relationship` 的 pagination 来源改（从 rrel.pagination → page_by_ 探测）；双 loader（full_br/page_br）跟随 —— `src/nexusx/federation/manager.py`
- [x] T005 [US1] `remote_loader.py` loader wire 跟随（有 page_by_ → paged + full；无 → plain）—— `src/nexusx/federation/remote_loader.py`

**Checkpoint**: US1 完成 —— 去掉 pagination 后，联邦分页自动按 member 能力工作（单层 A→B 可验证）

---

## Phase 4: User Story 2 — schema 同步 + 测试覆盖（Priority: P2）

**Goal**: `is_active_paginated_relationship` 的 REMOTE_PAGED 判定同步（从 rrel.pagination → member 暴露 page_by_）+ SDL/introspection 渲染跟随 + 测试迁移/新增。

**Independent Test**: member 有 page_by_ → SDL 渲染 Result{items, pagination}；无 → list。多层穿透（A→B→C，B/C 不写 pagination）自动分页，不崩。

- [x] T006 [P] [US2] `is_active_paginated_relationship` REMOTE_PAGED 判定改（从 rrel.pagination → member 暴露 page_by_/loader 有 page_by_）—— `src/nexusx/utils/pagination_schema.py`
- [x] T007 [P] [US2] `sdl_generator.py` 跟随 is_active（Result 渲染）—— `src/nexusx/sdl_generator.py`
- [x] T008 [P] [US2] `introspection.py` 跟随 is_active —— `src/nexusx/introspection.py`
- [x] T009 [US2] 测试迁移：所有 `RemoteRelationship(pagination=...)` 删参数（federation 测试 + demo）—— `tests/test_federation_*.py` + `demo/federation/`
- [x] T010 [US2] 测试新增/强化：多层穿透（A→B→C 不写 pagination 自动分页，不崩）+ 无 limit 全量 Result + to-one 不受影响 —— `tests/test_federation_pagination_transitive.py`（迁移 + 新场景）

**Checkpoint**: US2 完成 —— schema 同步 + 测试覆盖（多层穿透自动分页是核心验证点）

---

## Phase 5: User Story 3 — demo/docs/polish（Priority: P3）

**Goal**: demo 迁移 + docs 更新 + changelog breaking + 全量回归。

- [x] T011 [P] [US3] demo 迁移：`demo/federation/{catalog,reviews,users}_app.py` 删 RemoteRelationship pagination= —— `demo/federation/`
- [x] T012 [P] [US3] docs 更新：`docs/advanced/federation.md` + `.zh.md`（去 pagination，联邦分页 = member 能力 + 参数驱动）+ note 16（分页场景全览）—— `docs/advanced/`
- [x] T013 [US3] changelog breaking 标注（移除 RemoteRelationship.pagination）—— `docs/changelog.md`
- [x] T014 [US3] 全量回归 + ruff：`uv run pytest`（基线 1517）零回归 + `uv run ruff check src/` green —— `tests/` + `src/`

**Checkpoint**: US3 完成 —— demo/docs/changelog/回归全 done

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖（分支已开）
- **Foundational (Phase 2, T002)**: 阻塞所有 US —— RemoteRelationship 去 pagination 是基础
- **US1 (Phase 3)**: 依赖 T002；是 MVP（manager 自动探测）
- **US2 (Phase 4)**: 依赖 US1（is_active 跟随 manager 探测结果）+ T002
- **US3 (Phase 5)**: 依赖 US1-US2 完成

### Within US

- T002（去 pagination）→ T003-T005（US1 manager）→ T006-T008（US2 schema）→ T009-T010（US2 测试）→ T011-T014（US3 polish）

### Parallel Opportunities

- T006/T007/T008（is_active + sdl + introspection）可并行（不同文件）
- T011/T012（demo + docs）可并行
- T009（测试迁移）在 T002 后可与 T003-T005 并行

---

## Implementation Strategy

### MVP First（US1 only）

1. T002 去 RemoteRelationship.pagination
2. T003-T005 federation manager 自动探测 page_by_
3. **STOP 验证**：单层 A→B（B 有/无 `__pagination_orders__`）自动分页/全量工作
4. 通过后继续 US2/US3

### Incremental Delivery

- US1（manager 自动探测）→ US2（schema + 测试）→ US3（demo/docs/polish）
- 每个 US 完成后可独立验证

### 回归锚点

- 多层穿透（A→B→C 不写 pagination 自动分页）—— 021 核心验证点
- pytest 基线 1517 + ruff src/ green

---

## Notes

- breaking：直接删 RemoteRelationship.pagination（无 deprecated 期，与 020 一致）
- 020 已 merge（entity dunder 声明），本 feature 是其分页维度收尾
- 动机证据：`tests/test_federation_pagination_transitive.py`（pagination=True 通过 / False 崩溃对比）
- 参考 research.md（5 决策）、contracts/federation-edge.md（联邦边新形态）
