---
description: "Task list for feature implementation: Voyager 节点高亮边框残留修复"
---

# Tasks: Voyager 节点高亮边框残留修复

**Input**: Design documents from `/specs/008-voyager-node-border-residue/`

**Prerequisites**: [plan.md](./plan.md)（必填）、[spec.md](./spec.md)（必填，含 US1/US2 两个 user story）、[research.md](./research.md)、[data-model.md](./data-model.md)、[contracts/clear-banners-restore.md](./contracts/clear-banners-restore.md)、[quickstart.md](./quickstart.md)

**Tests**: 项目无前端自动化测试基线（与 spec 005/006/007 一致），本期验证方式为 quickstart 步骤化人工验证。

**Organization**: 任务按 user story 分组（US1 = 单次切换无残留、US2 = 长会话不累积）。本期改动面极小（单文件、~12 行新增），US1 与 US2 共享同一处代码修改，US2 仅多一道验证步骤。

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: 可并行（不同文件、无依赖）
- **[Story]**: 所属 user story（US1 / US2）
- 所有任务描述含精确文件路径

## Path Conventions

本项目是 "single library + vendored web assets" 结构（见 [plan.md](./plan.md) Project Structure）：

- 前端 vendored JS：`src/nexusx/voyager/web/`
- 后端测试（用于回归检查）：`tests/`

本期无后端改动、无新依赖、无新文件。

---

## Phase 1: Setup（环境基线确认）

**Purpose**: 确认开发环境就绪、现有测试基线无回归风险。

- [X] T001 确认开发环境就绪：在仓库根运行 `uv sync` 安装依赖；运行 `uv run pytest tests/ -k voyager --no-cov -q` 确认现有 voyager 相关测试全部 PASS（baseline，本期无后端改动，测试基线应保持 PASS）

---

## Phase 2: User Story 1 —— 单次切换无残留（Priority: P1） 🎯 MVP

**Goal**: 用户双击节点 A、切换到节点 B（单击或双击）后，A 的标题背景与外框都完全恢复到未高亮状态——stroke / stroke-width / fill 与从未被点击过的同类节点像素级一致。完成本期 P1 核心价值（详见 [spec.md](./spec.md) Story 1）。

**Independent Test**: 在 `demo/enterprise_voyager` 上启动 voyager，双击 `Employee`、单击 `Department`，DevTools 检查 `Employee` 节点 outerFrame `<polygon>` 的 stroke / stroke-width / fill 属性与从未高亮过的 `Role` 节点完全一致（详见 [quickstart.md](./quickstart.md) §2.2）。

**修复路径**：在 `src/nexusx/voyager/web/graph-ui.js::GraphUI.clearSchemaBanners` 内、`gv.highlight()` 调用之后、`removeAttribute` 之前，新增一段"先把 `data-original-stroke` / `data-original-stroke-width` / `data-original-fill` 写回对应 SVG attribute、再删除这些数据属性"的兜底还原逻辑。完整修改前/后对照、不变量、边界情况见 [contracts/clear-banners-restore.md](./contracts/clear-banners-restore.md)。

### Implementation for User Story 1

- [X] T002 [US1] 在 `src/nexusx/voyager/web/graph-ui.js::GraphUI.clearSchemaBanners`（约第 144-156 行）现有 `gv.highlight()` 调用之后、`querySelectorAll("polygon[data-original-stroke]")` 的 `forEach` 循环内、`removeAttribute` 调用之前，新增兜底还原逻辑——对每个匹配的 polygon，先用 `getAttribute` 读 `data-original-stroke` / `data-original-stroke-width` / `data-original-fill`，再用 `setAttribute` 把它们的值写回对应的 SVG attribute（`stroke` / `stroke-width` / `fill`），然后再执行原有的三个 `removeAttribute`。完整代码与注释模板见 [contracts/clear-banners-restore.md](./contracts/clear-banners-restore.md) §2.2
- [ ] T003 [US1] 在 `demo/enterprise_voyager` 启动 voyager、按 [quickstart.md](./quickstart.md) §2.2-2.7 完成浏览器人工验证：双击→单击切换无残留（含 DevTools 属性对比）/ 双击→双击切换 / 单击→单击切换 / 切换 schema / 切换 ER-diagram ↔ voyager 模式 / 自引用节点高亮-清除（依赖 T002 完成）

**Checkpoint**: User Story 1 完成——任何节点切换路径（双击/单击组合）后，旧节点视觉状态完全恢复，无橙色描边残留；DevTools 检查 SVG attribute 与从未高亮过的同类节点一致。

---

## Phase 3: User Story 2 —— 长会话不累积 + 回归（Priority: P2）

**Goal**: 用户在长会话内连续切换 20+ 次节点（混合双击/单击）后，画布视觉状态与刚加载时一致，无累积、无半褪色。同时验证修复未引入回归（其他 toggle / 现有交互行为不变）。

**Independent Test**: 在 ER 图中连续切换 20 次以上节点，截屏对比"刚加载完的画布"与"切换 20 次后的画布"（除当前选中节点外），无累积性视觉差异（详见 [quickstart.md](./quickstart.md) §2.8）。

**依赖**：US1 必须先完成（修复代码在 US1 实现，US2 只是验证它在长会话下稳定）。

### Implementation for User Story 2

- [ ] T004 [US2] 在 `demo/enterprise_voyager` 按 [quickstart.md](./quickstart.md) §2.8-2.10 + §3 完成浏览器人工验证：长会话 20+ 次切换无累积 / 刷新页面画布干净 / 切换显示选项 toggle 无残留 / 现有交互行为不变（双击打开侧边栏、单击切换、邻居高亮 dim 效果、边的高亮、Related Entities 子图、About/Fields/Source Code 各 tab）/ 其他 toggle 不受影响（Show Module Cluster / Better Cluster Display / Brief Mode / Show Methods / Hide Reverse Relationships / Pydantic Resolve Meta / Edge Minlen）（依赖 T003 完成）

**Checkpoint**: User Story 2 完成——长会话多次切换稳定、无回归。

---

## Phase 4: Polish & Cross-cutting Concerns

**Purpose**: 跨 story 的整合验证、CHANGELOG 同步。

- [X] T005 运行后端回归测试：`uv run pytest tests/ -k voyager --no-cov -q`，确认现有 voyager 相关测试无回归（本期无后端改动，结果应与 T001 baseline 一致——41 个 voyager 测试全部 PASS）
- [ ] T006 [P] 同步 CHANGELOG / 版本号（如项目有此惯例）：把本期变更（修复节点高亮边框残留）记入 release notes；可在下次 `/release patch` 时一并处理

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖——立即开始
- **User Story 1 (Phase 2)**: 依赖 T001 完成（确认环境基线）
- **User Story 2 (Phase 3)**: 依赖 User Story 1 完成（US2 仅验证 US1 修复在长会话下稳定）
- **Polish (Phase 4)**: 依赖 US1 与 US2 都完成

### Within User Story 1

- T002（修改 clearSchemaBanners）是 T003（浏览器验证）的前置
- T003 内 6 个验证步骤（§2.2-2.7）建议按顺序执行——前面的步骤失败时，后面的步骤无意义

### Cross-story Dependencies

- US1 与 US2 不可并行——US2 是 US1 修复的长会话稳定性验证
- 单开发者按 T001 → T002 → T003 → T004 → T005 顺序执行即可

---

## Parallel Example

本期改动面极小（单文件、~12 行），无可并行的任务——所有任务串行执行。

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. 完成 Phase 1 Setup（T001，~1 分钟）
2. 完成 Phase 2 User Story 1：
   - T002 修改代码（~5 分钟）
   - T003 浏览器验证（~15 分钟，含 6 个步骤）
3. **STOP and VALIDATE**: 按 [quickstart.md](./quickstart.md) §2.2 的 DevTools 属性对比确认 Employee / Role 节点 outerFrame 的 stroke / stroke-width / fill 完全一致
4. 此时已可发布/演示——双击→单击切换后旧节点视觉完全干净（MVP 价值已交付）

### Incremental Delivery

1. Setup → User Story 1 修复 → 浏览器验证 → 发布/Demo（**MVP!**）
2. 加 User Story 2 长会话验证 → 发布/Demo
3. Polish 跑回归测试 + CHANGELOG → 正式版本

### Single Developer Strategy（推荐）

本期总工作量极小（单文件修改 + 浏览器人工验证），适合单开发者一次完成：

1. T001（1 分钟）
2. T002 修改代码（5 分钟）
3. T003 浏览器验证 6 步骤（15 分钟）
4. T004 长会话验证 + 回归（10 分钟）
5. T005 后端回归测试（1 分钟）
6. T006 CHANGELOG（项目惯例，可选）

预计总工时 ~30 分钟。

---

## Notes

- [P] 任务 = 不同文件、无依赖；本期无 [P] 标记任务（改动面太小，全部串行）
- [Story] 标签把任务映射到 user story（US1 / US2），便于追溯
- 本期无自动化测试任务——项目无前端测试基线（与 spec 005/006/007 一致），依赖 quickstart 人工验证
- 修改严格按 [contracts/clear-banners-restore.md](./contracts/clear-banners-restore.md) §2.2 的代码模板，**不要改造 `highlightSchemaBanner` 或 `_saveOriginalAttributes`**（写入路径与原值保存路径都正确，问题在清除路径）
- **不动 `graphviz.svg.js`**（vendored 第三方库，影响面大；本期修复责任在 graph-ui.js 这一侧）
- **不改 `GraphUI.HIGHLIGHT_COLOR` / `GraphUI.HIGHLIGHT_STROKE_WIDTH` 常量**（spec FR-009：不改变现有高亮规则、不调整色值）
- **不动 spec 007 刚修过的 `renderErDiagram` 末尾子图 refetch 逻辑**（独立的视觉修复，避免冲突）
- 每个 task 或逻辑组完成后 commit；在任何 checkpoint 可停下来独立验证 story
