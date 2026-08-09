# Tasks: Federation 配置正交化

## ⚠️ 实现进度（2026-08-09，第一轮对话 — 工作进行中，未完成）

**分支**：`020-federation-config-orthogonal`（基于 `fix/paged-core-api-no-context-override`，含 P6 修复）

**已完成**：
- T001 ✅ 分支
- T003/T005 核心逻辑 ✅ `add_standard_queries`（`standard_queries.py`）改读 `entity.__federation_keys__` + `__pagination_orders__`，import OK；`AutoQueryConfig.batch_keys/batch_pages` 标 removed 注释（**未真删**）

**⚠️ 当前分支状态：测试会红**（工作进行中，不可 merge/发版）
- `add_standard_queries` 改了读 dunder，但 7 个 federation 测试 + demo 的 entity 没有 `__federation_keys__` → by_/page_ 根不生成 → 测试失败

**新对话接手待做（按 tasks.md 顺序）**：
1. **US1 收尾**：真删 `AutoQueryConfig.batch_keys/batch_pages`（参数+docstring+赋值）+ 迁 7 测试（`tests/test_federation_*.py`，batch_* → entity dunder）+ 迁 demo（reviews/catalog/users_app）+ T006（`_resolve_local_page_capability` 防 federation key 重名）
2. **US2**（T007-T008）+ **US3**（T009-T011）+ **Polish**（T012-T017）
3. 全量回归（基线 1517 passed）

**接法**：新对话读本 tasks.md + `specs/020/` + `git diff src/nexusx/standard_queries.py`，继续 `/speckit-implement`。

---

**Input**: Design documents from `/specs/020-federation-config-orthogonal/`（spec.md / plan.md / research.md / data-model.md / contracts/）

**Tests**: 含迁移 + 新声明模型测试（本 feature 是重构，测试跟随迁移）。

**Organization**: 按 user story 组织（US1 P1 / US2 P2 / US3 P3），US1 为 MVP，US2/US3 依赖 US1。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无依赖）
- **[Story]**: 所属 user story
- 每个任务含具体文件路径

---

## Phase 1: Setup

**Purpose**: feature 分支（复用既有 src/nexusx，无新基础设施）

- [x] T001 开 feature 分支 `020-federation-config-orthogonal`（基于 master，或基于当前 fix/paged-core-api-no-context-override 分支叠加以包含 P6 修复）

---

## Phase 2: Foundational（阻塞所有 US）

**Purpose**: `__federation_keys__` 的扫描识别底座 —— US1/US2/US3 都依赖

**⚠️ CRITICAL**: 本阶段完成前不得开始任何 US

- [ ] T002 在 entity 初始化扫描里识别 `__federation_keys__`：GraphQLHandler / ErManager 初始化时收集各 entity 的 `__federation_keys__`（复用 `__pagination_orders__` 已有的扫描机制，`registry.py:145`），存入 registry 供下游生成/路由读 —— `src/nexusx/loader/registry.py` + `src/nexusx/handler.py`

**Checkpoint**: 框架能从 entity 收集到 `__federation_keys__`，US 实现可开始

---

## Phase 3: User Story 1 — entity 集中声明 + AutoQueryConfig 退化（Priority: P1）🎯 MVP

**Goal**: member 在 entity 上一处声明联邦能力（`__federation_keys__` + `__pagination_orders__`），AutoQueryConfig 退化为读 entity 生成 by_/page_by 根（删 batch_keys/batch_pages）。

**Independent Test**: 给定 Review entity 带 `__federation_keys__=["product_id"]` + `__pagination_orders__["product_id"]`，框架生成 `Review.by_product_id_in` / `page_by_product_id_in` 根，mounter 能联邦它，全程不读 AutoQueryConfig.batch_keys/batch_pages。

- [ ] T003 [US1] AutoQueryConfig 删除 `batch_keys` / `batch_pages` 字段（`__init__` 签名 + docstring + 赋值）—— `src/nexusx/standard_queries.py`
- [ ] T004 [US1] 根生成函数 `_create_by_keys_in_query` / `_create_page_by_keys_in_query` 改为接收「从 entity 扫描来的 federation key + 对应 order profile（取自该 entity 的 `__pagination_orders__`）」而非 AutoQueryConfig 的 batch_* —— `src/nexusx/standard_queries.py`
- [ ] T005 [US1] `add_standard_queries` / handler 初始化遍历 entity 的 `__federation_keys__`，对每个 key 按「有无 order profile」调 `_create_by_*` 生成 `by_<key>_in`（无 profile）/ `page_by_<key>_in`（有 profile）根 —— `src/nexusx/standard_queries.py` + `src/nexusx/handler.py`
- [ ] T006 [P] [US1] `__pagination_orders__` 统一路由：维度在 `__federation_keys__` → 联邦批量根；不在 → 本地关系 loader（`registry.py` 读 `__pagination_orders__` 时按 `__federation_keys__` 判断维度归属）—— `src/nexusx/loader/registry.py`

**Checkpoint**: US1 完成 —— entity 声明 → 生成根 → 路由，端到端可用（demo 单 member 可验证）

---

## Phase 4: User Story 2 — order profile 统一，不区分对内对外（Priority: P2）

**Goal**: 本地关系分页 + 联邦批量分页共用同一 `__pagination_orders__` 载体，框架靠 `__federation_keys__` 自动路由，移除 γ DTO 单独的 `__pagination_orders__` 路径。

**Independent Test**: Review 同时有本地关系分页（comments）和联邦批量分页（product_id），两者 order profile 都在同一个 entity `__pagination_orders__`，框架分别正确路由。

- [ ] T007 [US2] 移除 γ DTO 单独的 `__pagination_orders__` 读取路径（`introspect.py:317` / `standard_queries.py:1019`），统一到源 entity 的 `__pagination_orders__` —— `src/nexusx/federation/introspect.py` + `src/nexusx/standard_queries.py`
- [ ] T008 [US2] 验证 by vs page 根的区分完全由 `__pagination_orders__` 有无 order profile 决定（替代旧 batch_keys→by / batch_pages→page 二分），补测试覆盖 —— `src/nexusx/standard_queries.py` + `tests/`

**Checkpoint**: US2 完成 —— order 单一载体、不区分对内对外，γ DTO 不再单独声明 order

---

## Phase 5: User Story 3 — γ DTO join key 归并到 entity（Priority: P3）

**Goal**: γ DTO 的 join key 从源 entity 的 `__federation_keys__` 推导，`SubsetConfig.federation_join_key` 退化为选择器（多 key 时选；单 key 自动）。

**Independent Test**: ReviewDTO（federation_public=True）的 join key 由源 Review 的 `__federation_keys__` 决定，DTO 上不再声明 join key 值。

- [ ] T009 [US3] γ DTO `federation_public=True` 时，join key 从源 entity（`__subset__.kls`）的 `__federation_keys__` 推导：单 key 自动取；多 key 用 `SubsetConfig.federation_key` 选择 —— `src/nexusx/subset.py` + `src/nexusx/federation/introspect.py`
- [ ] T010 [US3] `SubsetConfig.federation_join_key` 重命名/退化为 `federation_key`（选择器，引用 entity 已声明的 key 名，默认 None=自动单 key）—— `src/nexusx/subset.py`
- [ ] T011 [US3] γ 内省（`introspect.py`）读 join key 从源 entity `__federation_keys__`（不再读 DTO `__federation_join_key__`）—— `src/nexusx/federation/introspect.py`

**Checkpoint**: US3 完成 —— join key 单一来源（entity），DTO 不再声明 join key 值

---

## Phase 6: Polish & Cross-Cutting

**Purpose**: demo 迁移 + 文档 + 测试 + 回归 + breaking 标注

- [ ] T012 [P] 迁移 `demo/federation/reviews_app.py`：Review 加 `__federation_keys__` + `__pagination_orders__`；删 `AutoQueryConfig(batch_keys/batch_pages)` + ReviewDTO `federation_join_key` —— `demo/federation/reviews_app.py`
- [ ] T013 [P] 迁移 `demo/federation/catalog_app.py`：ReviewDTO 删 `federation_join_key`（自动推导）—— `demo/federation/catalog_app.py`
- [ ] T014 [P] 迁移 `demo/federation/users_app.py`：若有 batch 配置，同 reviews 迁移 —— `demo/federation/users_app.py`
- [ ] T015 文档更新：`docs/advanced/federation.md` + `.zh.md` 改为新声明模型（entity 两 dunder）+ 迁移说明（旧 batch_keys/batch_pages/federation_join_key → 新）—— `docs/advanced/federation.md` + `docs/advanced/federation.zh.md`
- [ ] T016 测试迁移 + 新增：federation 相关测试改用新声明；新增「entity __federation_keys__ 生成 by_/page_ 根」「γ join key 自动推导」测试 —— `tests/`
- [ ] T017 全量回归 + breaking 标注：三层联邦 demo（catalog→reviews→users）跑通（SC-004）；`uv run pytest` 零回归（基线 1517 passed）；changelog 标 breaking（移除 batch_keys/batch_pages/federation_join_key）—— `docs/changelog.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖，立即开始
- **Foundational (Phase 2, T002)**: 依赖 Setup；**阻塞所有 US**
- **US1 (Phase 3)**: 依赖 T002；是 MVP
- **US2 (Phase 4)**: 依赖 US1（路由底座）；与 US3 可并行（order vs join key，不同维度）
- **US3 (Phase 5)**: 依赖 US1（`__federation_keys__`）；与 US2 可并行
- **Polish (Phase 6)**: 依赖 US1-US3 完成

### Within US
- T002（扫描）→ T003-T006（US1 生成+路由）→ US2/US3 → Polish

### Parallel Opportunities
- T006（registry 路由）可与 T003-T005（standard_queries 生成）并行（不同文件）
- T012/T013/T014（三个 demo）互不相关，可并行
- US2（T007-T008）与 US3（T009-T011）可并行（order vs join key）

---

## Implementation Strategy

### MVP First（US1 only）
1. T001 开分支 → T002 扫描底座 → T003-T006 US1（entity 声明 → 生成根 → 路由）
2. **STOP 验证**：单 member（reviews）用新声明能生成 by_/page_ 根、被 mounter 联邦
3. 通过后继续 US2/US3/Polish

### Incremental Delivery
- US1（MVP：声明 + 生成 + 路由）→ US2（order 统一）→ US3（γ join key 归并）→ Polish（demo/文档/测试/回归）
- 每个 US 完成后可独立验证

### 回归锚点
- 三层联邦 demo（SC-004）+ pytest 基线 1517

---

## Notes

- breaking：直接删 batch_keys/batch_pages/federation_join_key，无 deprecated 期（spec Clarifications Q2）
- mounter 侧 join_remote 不动（spec Clarifications Q1）
- RemoteService/RemoteRef/RemoteRelationship 声明模型不变
- 参考 research.md（5 个实现决策）、contracts/federation-entity-declaration.md（开发者声明契约）
