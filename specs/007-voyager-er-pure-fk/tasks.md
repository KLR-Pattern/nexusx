---
description: "Task list for feature implementation: Voyager Hide Reverse Relationships 连线模式"
---

# Tasks: Voyager Hide Reverse Relationships 连线模式

**Input**: Design documents from `/specs/007-voyager-er-pure-fk/`

**Prerequisites**: [plan.md](./plan.md)（必填）、[spec.md](./spec.md)（必填，含 US1/US2 两个 user story）、[research.md](./research.md)、[data-model.md](./data-model.md)、[contracts/](./contracts/)、[quickstart.md](./quickstart.md)

**Tests**: 本期测试在 scope 内——[quickstart.md](./quickstart.md) 列出 10 个后端 pytest 用例 + 10 个浏览器人工验证步骤，对应任务覆盖在后端改动 phase 与各 user story phase 中。

**Organization**: 任务按 user story 分组（US1 = 核心裁剪行为、US2 = 偏好持久化），每个 story 可独立实现与验证。

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: 可并行（不同文件、无依赖）
- **[Story]**: 所属 user story（US1 / US2）
- 所有任务描述含精确文件路径

## Path Conventions

本项目是 "single library + vendored web assets" 结构（见 [plan.md](./plan.md) Project Structure）：

- 后端 Python：`src/nexusx/voyager/`
- 前端 vendored JS：`src/nexusx/voyager/web/`
- 后端测试：`tests/`

---

## Phase 1: Setup（共享基础设施）

**Purpose**: 沿用现有 nexusx 项目结构，本期不引入新依赖、不创建新目录。仅做环境就绪确认。

- [X] T001 确认开发环境就绪：(a) 在仓库根运行 `uv sync` 安装依赖；(b) 运行 `uv run pytest tests/ -k voyager` 并保存输出作为 baseline——预期命中 spec 005 子图相关（`test_voyager_subgraph_*`）、spec 006 docstring 相关（`test_voyager_docstring_*`）等现有测试全部 PASS；本期新增测试文件 `test_voyager_hide_reverse.py` 此时尚不存在、不应被匹配。若 `-k voyager` 无用例匹配，需先确认现有测试命名是否符合 `voyager` 关键字（否则改用更宽关键字或直接 `uv run pytest tests/`）

---

## Phase 2: Foundational（阻塞性前置——后端 Hide Reverse Relationships 过滤管线）

**Purpose**: 后端 `ErDiagramDotBuilder` 与 Payload model 的字段扩展，是 US1 前端 toggle 与 US2 持久化共同的前置依赖。**前端任何工作开始前，本阶段必须完成。**

**⚠️ CRITICAL**: US1 / US2 都依赖本阶段产出的"后端能按 direction 过滤 ONETOMANY"能力。

- [X] T002 [P] 修改 `ErDiagramDotBuilder`：在 `src/nexusx/voyager/er_diagram_dot.py::__init__`（约第 87-110 行）构造函数 keyword-only 参数区新增 `hide_reverse_relationships: bool = False`，函数体内新增 `self.hide_reverse_relationships = hide_reverse_relationships`
- [X] T003 [P] 在 `src/nexusx/voyager/create_voyager.py` 的 `ErDiagramPayload`（约第 64 行）与 `ErDiagramSubgraphPayload`（约第 72 行）两个 Pydantic model 内分别新增字段 `hide_reverse_relationships: bool = False`（紧邻现有 `show_methods: bool = True` 之后，保持与现有 toggle 字段对齐）
- [X] T004 在 `src/nexusx/voyager/er_diagram_dot.py::_add_relationship_link`（约第 199-237 行）函数体内、`if not _is_model_like_target(rel_info.target_entity): return` 之后、`source_name = full_class_name(entity_kls)` 之前，新增早退判定 `if self.hide_reverse_relationships and rel_info.direction == 'ONETOMANY': return`（依赖 T002）
- [X] T005 在 `src/nexusx/voyager/voyager_context.py` 的 4 处 `ErDiagramDotBuilder(...)` 构造调用点（约第 108、128、171-175、229-233 行）各新增一行透传：`hide_reverse_relationships=payload.get("hide_reverse_relationships", False),`（依赖 T002、T003）

**Checkpoint**: 后端 Hide Reverse Relationships 过滤管线就绪——`POST /er-diagram` 与 `POST /er-diagram-subgraph` 接受 `hide_reverse_relationships` 字段、True 时 ONETOMANY 反向镜像被裁剪、False / 不传时行为与现状完全一致。可通过 curl 或后端单测验证。

---

## Phase 3: User Story 1 —— 核心裁剪行为（Priority: P1） 🎯 MVP

**Goal**: 用户在 ER-diagram 显示选项面板勾选 "Hide Reverse Relationships"，画布立即重新渲染、只保留 MANYTOONE 方向与 MANYTOMANY 方向 relationship 连线、隐藏 ONETOMANY 反向镜像。完成本期 P1 核心价值（详见 [spec.md](./spec.md) Story 1）。

**Independent Test**: 在 `demo/enterprise_voyager` 上启动 voyager，找到双向 `back_populates` 关系（如 `Post.author ↔ User.posts`），勾选前 `Post` 与 `User` 之间 2 条连线，勾选后 1 条 MANYTOONE 连线，ONETOMANY 反向被隐藏（详见 [quickstart.md](./quickstart.md) 步骤 2.2）。

### Tests for User Story 1

> **NOTE**: 先写测试、确认 FAIL、再做实现（TDD）。测试用例对应 [quickstart.md](./quickstart.md) 第 1.2 节。

- [X] T006 [P] [US1] 在 `tests/test_voyager_hide_reverse.py` 编写 `test_filter_off_keeps_all_directions`：构造含双向 `back_populates` 的 SQLModel 实体对（如 `Post.author ↔ User.posts`），`hide_reverse_relationships=False` 下调用 `ErDiagramDotBuilder.analysis()`，断言 `len(builder.links) == 2`
- [X] T007 [P] [US1] 在 `tests/test_voyager_hide_reverse.py` 编写 `test_filter_on_hides_onetomany`：同样实体对，`hide_reverse_relationships=True` 下断言 `len(builder.links) == 1` 且保留的是 MANYTOONE 方向（可通过 link.source 含 MANYTOONE 字段名验证）
- [X] T008 [P] [US1] 在 `tests/test_voyager_hide_reverse.py` 编写 `test_m2m_preserved_when_filter_on`：构造含 `secondary="..."` 的 M2M 关系，`hide_reverse_relationships=True` 下断言两端实体双方向 M2M 连线都保留（`len == 2`）
- [X] T009 [P] [US1] 在 `tests/test_voyager_hide_reverse.py` 编写 `test_manytoone_unirectional_preserved` 与 `test_onetomany_unirectional_hidden`：构造无 `back_populates` 的单向 relationship，断言 MANYTOONE 单向保留、ONETOMANY 单向隐藏
- [X] T010 [P] [US1] 在 `tests/test_voyager_hide_reverse.py` 编写 `test_fields_table_unchanged`：断言 Hide Reverse Relationships 开关下 `SchemaNode.fields` 列表完全一致（含 ONETOMANY 方向 relationship 字段，验证 spec FR-007 不变量 1）
- [X] T011a [P] [US1] 在 `tests/test_voyager_hide_reverse.py` 编写 `test_endpoint_with_filter_on`：通过 FastAPI TestClient 验证 `POST /er-diagram` 带 `hide_reverse_relationships: true` 时响应 dot 中 ONETOMANY 边缺失（对应 spec FR-005、SC-001）
- [X] T011b [P] [US1] 在 `tests/test_voyager_hide_reverse.py` 编写 `test_endpoint_default_omits_field`：通过 FastAPI TestClient 验证 `POST /er-diagram` 不带该字段时响应与本期改动前完全一致（对应 spec FR-002 默认未勾选、向后兼容）
- [X] T011c [P] [US1] 在 `tests/test_voyager_hide_reverse.py` 编写 `test_subgraph_follows_filter`：通过 FastAPI TestClient 验证 `POST /er-diagram-subgraph` 带 `hide_reverse_relationships: true` 时子图按 Pure FK 模式裁剪（对应 spec FR-007、Story 1 验收场景 9）
- [X] T011d [P] [US1] 在 `tests/test_voyager_hide_reverse.py` 编写 `test_self_referential_back_populates`：构造自引用双向关系（`Tree.parent` ↔ `Tree.children`），断言 Pure FK 模式下保留 `parent`（MANYTOONE）、隐藏 `children`（ONETOMANY），自环呈现为单条 MANYTOONE 自连线

### Implementation for User Story 1

- [X] T012 [P] [US1] 在 `src/nexusx/voyager/web/store.js` 的 `state.filter` 对象内新增字段 `hideReverseRelationships: false`（紧邻现有 `betterClusterDisplay` / `brief` 等字段）
- [X] T013 [P] [US1] 在 `src/nexusx/voyager/web/store.js` 紧邻 `toggleBetterClusterDisplay`（约第 467-475 行）之后新增 `toggleHideReverseRelationships(val, onGenerate)` 函数：写 `state.filter.hideReverseRelationships = val`、`localStorage.setItem("hide_reverse_relationships", JSON.stringify(val))`（含 try/catch + `console.warn` 降级）、调 `onGenerate()`（依赖 T012）
- [X] T014 [P] [US1] **两处透传**（依赖 T012）：(a) 在 `src/nexusx/voyager/web/vue-main.js` 现有 `fetch("er-diagram", { body: JSON.stringify({...}) })`（约第 189-200 行）请求体内新增透传字段 `hide_reverse_relationships: store.state.filter.hideReverseRelationships`；(b) 在 `src/nexusx/voyager/web/store.js::buildErDiagramSubgraphPayload`（约第 623-632 行，spec 005 引入）返回对象内新增 `hide_reverse_relationships: state.filter.hideReverseRelationships`——该函数是 `/er-diagram-subgraph` 请求体的唯一构造点（被 `fetchRelatedEntities` 调用），子图跟随裁剪（spec FR-007、Story 1 验收场景 9）依赖此处透传
- [X] T015 [P] [US1] 在 `src/nexusx/voyager/web/component/schema-code-display.js`（或显示选项面板所在组件）的模板内、紧邻现有 `better cluster display` / `brief mode` toggle 之后，新增 Quasar `<q-checkbox>` 元素：`label="Hide Reverse Relationships"`、`:model-value="store.state.filter.hideReverseRelationships"`、`@update:model-value="(val) => store.toggleHideReverseRelationships(val, onGenerate)"`（依赖 T012、T013；具体位置 spec FR-001 仅要求"与现有显示选项同侧"，可参考 [contracts/frontend-toggle.md](./contracts/frontend-toggle.md)）。Quasar `<q-checkbox>` 默认满足 spec FR-004 键盘可达（Tab 聚焦、Space 切换）与可见聚焦框，无需额外 a11y 配置——但 T016 浏览器验证必须显式确认
- [ ] T016 [US1] 在 `demo/enterprise_voyager` 启动 voyager、按 [quickstart.md](./quickstart.md) 步骤 2.2-2.7 完成浏览器人工验证：勾选裁剪 / 取消恢复 / 切换 schema 不重置 / M2M 双向保留 / Fields 不受影响 / 子图跟随裁剪；**额外**验证 spec FR-004 键盘可达：Tab 键能把焦点移到 "Hide Reverse Relationships" checkbox、Space 键能切换勾选状态、聚焦时可见聚焦框（依赖 T002-T015 全部完成）

**Checkpoint**: User Story 1 完成——用户可勾选 "Hide Reverse Relationships"，ER 图立即按 direction 过滤 ONETOMANY 反向镜像、保留 MANYTOONE + MANYTOMANY 连线，与其他显示选项正交、不影响 Fields/Source/About 各 tab、Related Entities 子图跟随裁剪。

---

## Phase 4: User Story 2 —— 偏好持久化（Priority: P2）

**Goal**: 用户勾选 "Hide Reverse Relationships" 后，刷新浏览器或重新进入 ER 图 tab 时偏好被自动保留；localStorage 不可用时优雅降级。详见 [spec.md](./spec.md) Story 2。

**Independent Test**: 勾选 Hide Reverse Relationships 后刷新浏览器，复选框仍为勾选状态、ER 图按 Hide Reverse Relationships 渲染；取消勾选后再刷新，状态恢复为未勾选（详见 [quickstart.md](./quickstart.md) 步骤 2.8）。

**依赖**：US1 必须先完成（需要 T012 定义的 `hideReverseRelationships` state 字段、T013 toggle 函数写入的 localStorage key `hide_reverse_relationships`）。

### Tests for User Story 2

- [ ] T017 [US2] [必做] 在 `tests/test_voyager_hide_reverse.py` 编写 `test_loadToggleState_handles_invalid_json`：单元测试 `loadToggleState("hide_reverse_relationships", false)` 在 localStorage 返回非 JSON 字符串、`null`、配额满等场景下安全降级到默认 false。**不允许跳过**——这是 spec FR-011（localStorage 异常降级）读取侧的唯一自动化测试覆盖；即使 `loadToggleState` 已有项目级测试，本期新增的 key 必须有针对性用例防止后续重构回归

### Implementation for User Story 2

- [X] T018 [US2] 在 `src/nexusx/voyager/web/vue-main.js` 现有 `loadToggleState("pydantic_resolve_meta", false)`（约第 55 行）之后新增 `store.state.filter.hideReverseRelationships = loadToggleState("hide_reverse_relationships", false)`（依赖 T012、T013 已定义 state 字段与 localStorage key 命名）
- [ ] T019 [US2] 在 `demo/enterprise_voyager` 按 [quickstart.md](./quickstart.md) 步骤 2.8-2.9 完成浏览器人工验证：勾选后刷新保留 / 取消后刷新恢复 / 首次默认未勾选 / **DevTools → Application → Storage 禁用 localStorage（或隐私模式）时优雅降级**——后者对应 spec FR-011 与 Story 2 验收场景 4，具体操作详见 quickstart 步骤 2.9（依赖 T018）

**Checkpoint**: User Story 2 完成——偏好持久化生效，刷新/重新进入 ER 图 tab 时 Hide Reverse Relationships 状态被自动恢复；localStorage 不可用时不阻塞 UI、不抛错。

---

## Phase 5: Polish & Cross-cutting Concerns

**Purpose**: 跨 story 的整合验证、回归测试、文档同步。

- [X] T020 [P] 运行后端全套相关测试：`uv run pytest tests/test_voyager_hide_reverse.py -v`，确认 10 个用例全部通过
- [X] T021 运行后端回归测试：`uv run pytest tests/ -k voyager`，确认现有 voyager 相关测试无回归（特别是 spec 005 子图相关测试 `test_voyager_subgraph_*`、spec 006 docstring 相关测试 `test_voyager_docstring_*`）
- [ ] T022 [P] 浏览器跨 toggle 正交性验证：按 [quickstart.md](./quickstart.md) 步骤 2.10 同时勾选 Hide Reverse Relationships + Better Cluster Display + Brief Mode，确认各选项效果独立叠加、无相互干扰
- [ ] T023 在 `demo/enterprise_voyager` 跑完 [quickstart.md](./quickstart.md) 第 4 节"失败排查"清单，确认无勾选后连线不变、画布空白、刷新状态丢失、子图未跟随、Fields 字段缺失、与其他 toggle 冲突等问题
- [ ] T024 [P] 同步 CHANGELOG / 版本号（如项目有此惯例）：把本期变更（新增 Hide Reverse Relationships 显示选项）记入 release notes；同时记录 spec FR-012（状态不进入 URL）由实现默认满足——前端 toggle 函数不修改 URL 参数、不进入 schema 元数据，无需额外代码或测试，作为零工作项约束由 code review 把关

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖——立即开始
- **Foundational (Phase 2)**: 依赖 Setup 完成——**阻塞所有 user story**
- **User Story 1 (Phase 3)**: 依赖 Foundational 完成（前端 toggle 需要后端支持）
- **User Story 2 (Phase 4)**: 依赖 User Story 1 完成（持久化读取的 localStorage key 由 US1 toggle 函数定义）
- **Polish (Phase 5)**: 依赖 US1 与 US2 都完成

### Within Foundational (Phase 2)

- T002 (er_diagram_dot.py 构造函数) 与 T003 (create_voyager.py Payload) 可并行——不同文件
- T004 (er_diagram_dot.py 早退过滤) 依赖 T002（同一文件，需先有构造函数参数）
- T005 (voyager_context.py 透传) 依赖 T002 + T003（构造函数参数 + Payload 字段都已就位）

### Within User Story 1 (Phase 3)

- T006-T011d 测试任务（含 T011 拆出的 a/b/c/d 4 个子任务）可全部并行（同一测试文件，但用例之间无依赖；建议按 TDD 先写测试再做实现）
- T012 (store.js state 字段) 是 T013、T014 的前置
- T013 (store.js toggle 函数) 依赖 T012
- T014 (vue-main.js fetch 透传) 依赖 T012（读取 state 字段）
- T015 (schema-code-display.js checkbox) 依赖 T012 + T013
- T016 (浏览器验证) 依赖 T002-T015 全部完成

### Cross-story Dependencies

- US1 与 US2 不可并行——US2 依赖 US1 已定义的 state 字段、toggle 函数、localStorage key
- 若有多个开发者：Foundational 完成后，US1 由一个开发者承担；US1 完成后 US2 由同一或另一开发者承担

---

## Parallel Example: User Story 1

```bash
# Launch all tests for User Story 1 together (TDD step 1, expect failures):
Task: "T006 test_filter_off_keeps_all_directions in tests/test_voyager_hide_reverse.py"
Task: "T007 test_filter_on_hides_onetomany in tests/test_voyager_hide_reverse.py"
Task: "T008 test_m2m_preserved_when_filter_on in tests/test_voyager_hide_reverse.py"
Task: "T009 test_manytoone_unirectional_preserved + test_onetomany_unirectional_hidden in tests/test_voyager_hide_reverse.py"
Task: "T010 test_fields_table_unchanged in tests/test_voyager_hide_reverse.py"
Task: "T011a test_endpoint_with_filter_on in tests/test_voyager_hide_reverse.py"
Task: "T011b test_endpoint_default_omits_field in tests/test_voyager_hide_reverse.py"
Task: "T011c test_subgraph_follows_filter in tests/test_voyager_hide_reverse.py"
Task: "T011d test_self_referential_back_populates in tests/test_voyager_hide_reverse.py"

# After tests FAIL, implement in this order:
# 1. Foundational (T002-T005) — backend pipeline
# 2. US1 frontend (T012 → T013 → T014, T015 in parallel after T012)
# 3. Verify tests PASS (T006-T011 now pass)
# 4. Browser verify (T016)
```

```bash
# Once T012 (store.js state field) lands, parallelize frontend implementation:
Task: "T013 toggleHideReverseRelationships in src/nexusx/voyager/web/store.js"
Task: "T014 fetch hide_reverse_relationships in src/nexusx/voyager/web/vue-main.js"
Task: "T015 q-checkbox in src/nexusx/voyager/web/component/schema-code-display.js"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. 完成 Phase 1 Setup（确认环境基线）
2. 完成 Phase 2 Foundational（后端 Hide Reverse Relationships 过滤管线）—— **CRITICAL，阻塞前端**
3. 完成 Phase 3 User Story 1（前端 toggle + UI + 测试 + 浏览器验证）
4. **STOP and VALIDATE**: 按 [quickstart.md](./quickstart.md) 步骤 2.2-2.7 完成 US1 独立验证
5. 此时已可发布/演示——用户能勾选 Hide Reverse Relationships、画布立即裁剪 ONETOMANY 反向镜像（MVP 价值已交付）

### Incremental Delivery

1. Setup + Foundational → 后端管线就绪（可 curl 测试）
2. 加 US1 → 浏览器独立验证 → 发布/Demo（**MVP!**）
3. 加 US2 → 浏览器独立验证刷新恢复 → 发布/Demo
4. Polish 阶段跑完跨 toggle 正交性、回归测试、CHANGELOG → 正式版本

### Single Developer Strategy（推荐）

本特性总工作量较小（约 4 个后端文件改动 + 3 个前端文件改动 + 1 个测试文件），适合单开发者按顺序执行：

1. T001（5 分钟）
2. T002 → T004 → T005（同文件串行，30 分钟）
3. T003 并行（独立文件，10 分钟）
4. T006-T011（TDD 起草测试，30 分钟）
5. T012 → T013（同文件串行）→ T014 → T015（前端，30 分钟）
6. T016 浏览器验证（20 分钟）
7. T018-T019（US2，15 分钟）
8. T020-T024（Polish，30 分钟）

预计总工时 ~3 小时。

---

## Notes

- [P] 任务 = 不同文件、无依赖
- [Story] 标签把任务映射到 user story（US1 / US2），便于追溯
- 每个 user story 可独立完成与验证
- TDD 流程：先写测试 → 确认 FAIL → 实现 → 测试 PASS
- 每个 task 或逻辑组完成后 commit
- 在任何 checkpoint 可停下来独立验证 story
- 避免：模糊任务、同文件冲突、跨 story 破坏独立性的依赖
- 后端早退过滤逻辑严格按 [contracts/hide-reverse-filter.md](./contracts/hide-reverse-filter.md) 实现，**不要改造 `_add_relationship_link` 现有锚点 / label 生成逻辑**（spec 不变量）
- 前端 toggle 函数严格按 [contracts/frontend-toggle.md](./contracts/frontend-toggle.md) 模式（沿用 `toggleBetterClusterDisplay` 等现有模式），**不要新增错误处理或回调签名**
