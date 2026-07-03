# Implementation Plan：Voyager ER 图 —— 节点高亮边框残留修复

**Branch**: `008-voyager-node-border-residue` | **Date**: 2026-07-03 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/008-voyager-node-border-residue/spec.md`

**Note**: 本计划由 `/speckit-plan` 产出，所有产物使用中文撰写（项目级约定）。本特性是纯前端 UI bug 修复，无后端改动、无契约变更、无新依赖。

## Summary

修复 Voyager ER 图节点切换后旧节点外框残留橙色描边的视觉瑕疵。根因是 `graph-ui.js::highlightSchemaBanner` 直接用 `setAttribute` 改了节点 SVG 的 stroke / stroke-width / fill，并把原值存到 DOM attribute `data-original-*`；但 `clearSchemaBanners` 只清除了 `data-original-*` 数据属性、未真正把原值写回 SVG attribute，依赖 `graphviz.svg.js::restoreElement` 还原又不可靠——后者硬编码 `setStrokeWidth=1` 且只在 jQuery `.data("graphviz.svg.color")` 上有快照的元素上生效，与 `graph-ui.js` 的两套数据源不互通。

修复路径：让 `clearSchemaBanners` 在清除前先把 `data-original-stroke` / `data-original-stroke-width` / `data-original-fill` 写回对应的 SVG attribute（兜底还原），再删除数据属性。修复不影响 graphviz.svg.js 既有管理体系、不破坏现有 API、不动 Graphviz SVG 输出格式。

## Technical Context

- **Language/Version**: Vanilla JS + Vue 3 + Quasar 2（前端，**无构建工具链**，第三方库以 `.min.js` 形式 vendored 在 `src/nexusx/voyager/web/`）；本期无后端改动
- **Primary Dependencies**: jQuery（graphviz.svg.js 依赖）；Quasar / Vue 3（已 vendored）；本期**不引入新依赖**
- **Storage**: 浏览器 DOM attribute（`data-original-stroke` / `data-original-stroke-width` / `data-original-fill`，由 `graph-ui.js::_saveOriginalAttributes` 写入）；无 localStorage / 后端持久化
- **Testing**: 项目无前端自动化测试基线（与 spec 005/006/007 一致），依赖 `quickstart.md` 的人工验证流程
- **Target Platform**: 开发机（Linux/macOS/Windows）启动 FastAPI 进程，浏览器访问 `http://localhost:<port>`；现代 Chromium 系或 Firefox
- **Project Type**: library（nexusx）+ 内嵌 web 服务子模块（voyager）
- **Performance Goals**: SVG 属性还原（每次清除遍历少量 polygon）开销可忽略——典型 schema ~100 节点 × 2 polygon/节点 = ~200 DOM 操作，毫秒级；用户感知"立即清干净"
- **Constraints**:
  - **不引入前端构建工具链**——所有前端依赖必须能以 `<script src="...">` 直接加载。
  - **不改 graphviz.svg.js 的公共 API**——`highlight()` / `colorElement()` / `restoreElement()` 等签名与行为不变，避免破坏 voyager 之外的可能调用方。
  - **不改 Graphviz SVG 输出格式契约**——后端 dot 生成与前端 SVG 解析路径不变。
  - **不改变"哪个节点该被高亮"的语义**——只修复"清除不彻底"的视觉瑕疵，不引入新触发条件、不调整橙色色值（沿用 `GraphUI.HIGHLIGHT_COLOR = "#FF8C00"`）。
  - **不动 spec 007 刚修过的 `renderErDiagram` 末尾子图 refetch 逻辑**——本特性是独立的视觉修复。
- **Scale/Scope**: 单 voyager 实例，schema 数量 ~100 量级；典型节点切换触发 2-4 个 polygon 的属性还原。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` 当前仍是默认模板（项目尚未填入实际原则），无可对照的硬约束。**Gate 结果：通过（trivial）**。

设计阶段产出的关键决策已记录到 `research.md`，并将在 Phase 1 收尾时复检——确认本期设计未引入需要被未来宪法（如"前端不允许引入构建工具链"、"DOM 直接操作必须可被 React/Vue 追踪"等潜在原则）追溯约束的考量。

## Project Structure

### Documentation (this feature)

```text
specs/008-voyager-node-border-residue/
├── plan.md              # 本文件
├── spec.md              # /speckit-specify 阶段产出
├── research.md          # Phase 0：技术决策与备选方案
├── data-model.md        # Phase 1：DOM 属性数据流
├── quickstart.md        # Phase 1：end-to-end 验证手册
├── contracts/           # Phase 1：接口契约
│   └── clear-banners-restore.md
├── checklists/
│   └── requirements.md  # /speckit-specify 阶段产出
└── tasks.md             # Phase 2（/speckit-tasks 产出，本期不生成）
```

### Source Code (repository root)

```text
src/nexusx/voyager/web/
└── graph-ui.js                   # 修改：clearSchemaBanners 在清除 data-original-* 前
                                  #       先把原值写回 SVG attribute（兜底还原）

无新增文件、无后端改动、无新依赖。
```

**Structure Decision**：沿用现有的 "single library + vendored web assets" 模式（即 plan-template 的 Option 1）。本期是单文件、~10 行级别的最小修复——在 `clearSchemaBanners` 内追加"还原 data-original-* 到 SVG attribute"的兜底逻辑；不引入新模块、不拆分函数、不改公共 API。

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

无 Constitution 违规，本表留空。

## Phases

### Phase 0 — Outline & Research

详见 [research.md](./research.md)。本期 spec 没有 NEEDS CLARIFICATION 残留（clarify 阶段已确认无关键歧义）；Phase 0 主要解决三个**实现层面**的决策——修复发生位置（graph-ui.js vs graphviz.svg.js）、还原语义（基于原值 vs 涂改回固定颜色）、与 graphviz.svg.js 既有管理体系的协作模式。

### Phase 1 — Design & Contracts

- 数据模型与状态字段：[data-model.md](./data-model.md)
- 接口契约：[contracts/clear-banners-restore.md](./contracts/clear-banners-restore.md) — `clearSchemaBanners` 兜底还原逻辑
- 端到端验证：[quickstart.md](./quickstart.md)

Phase 1 收尾复检 Constitution：仍 trivial 通过（见上文）。
