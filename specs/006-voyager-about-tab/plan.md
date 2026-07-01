# Implementation Plan：Voyager ER 图 —— About Tab（docstring + Mermaid）& 侧边栏宽度放宽

**Branch**: `006-voyager-about-tab` | **Date**: 2026-07-01 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-voyager-about-tab/spec.md`

**Note**: 本计划由 `/speckit-plan` 产出，所有产物使用中文撰写（项目级约定）。

## Summary

为 Voyager ER 图侧边栏新增最左的 "About" tab，渲染当前所选 schema 模型类的 Python `__doc__`：先以 GitHub-Flavored Markdown 解析，再就地渲染 ```mermaid 围栏块为图表，并对危险 HTML 做清洗。另把侧边栏拖拽上限从固定 800px 改为视窗宽度 × 2/3，并在视窗缩放时动态 clamp。

## Technical Context

- **Language/Version**: Python 3.10+（后端）；Vanilla JS + Vue 3 + Quasar 2（前端，**无构建工具链**，第三方库以 `.min.js` 形式 vendored 在 `src/nexusx/voyager/web/`）
- **Primary Dependencies**: FastAPI 0.135+（后端 HTTP）、Quasar / Vue 3（前端 UI，已 vendored）；本期新增前端依赖：`marked`、`dompurify`、`mermaid`，均以 vendored `.min.js` 形式引入，**不**通过 npm/构建工具链。
- **Storage**: N/A（运行时反射，无持久化；docstring 取自 Python 类对象 `__doc__` 属性）
- **Testing**: `pytest`（后端端点单测）；前端无自动化测试基线，依赖 `quickstart.md` 的人工验证流程
- **Target Platform**: 开发机（Linux/macOS/Windows）启动 FastAPI 进程，浏览器访问 `http://localhost:<port>`；不做 SSR
- **Project Type**: library（nexusx）+ 内嵌 web 服务子模块（voyager）
- **Performance Goals**: `POST /docstring` 端点 p95 < 50ms（反射读 `__doc__`，无 IO）；前端 Markdown+Mermaid 渲染 < 500ms（典型 docstring < 10KB）
- **Constraints**:
  - **不引入前端构建工具链**——所有前端依赖必须能以 `<script src="...">` 直接加载（与现有 `quasar.min.js`、`vue.min.js` 一致）。
  - 不破坏现有 `/source`、`/vscode-link`、`/er-diagram`、`/er-diagram-subgraph` 端点的契约。
  - 不改变 SchemaNode 等已序列化的数据结构形状（避免破坏 web/schema 端点缓存）。
- **Scale/Scope**: 单 voyager 实例，schema 数量 ~100 量级；docstring 长度 < 10KB（极少数超长文档走滚动条，不做分页）。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` 当前仍是默认模板（项目尚未填入实际原则），无可对照的硬约束。**Gate 结果：通过（trivial）**。

设计阶段产出的关键决策已记录到 `research.md`，并将在 Phase 1 收尾时复检——确认本期设计未引入需要被未来宪法（如"前端不允许引入构建工具链"、"端点必须做输入校验"等潜在原则）追溯约束的考量。

## Project Structure

### Documentation (this feature)

```text
specs/006-voyager-about-tab/
├── plan.md              # 本文件
├── research.md          # Phase 0：技术决策与备选方案
├── data-model.md        # Phase 1：数据通路与状态字段
├── quickstart.md        # Phase 1：end-to-end 验证手册
├── contracts/           # Phase 1：接口契约
│   ├── docstring-endpoint.md
│   ├── about-tab-component.md
│   └── sidebar-width-clamp.md
├── checklists/
│   └── requirements.md  # /speckit-specify 阶段产出
└── tasks.md             # Phase 2（/speckit-tasks 产出，本期不生成）
```

### Source Code (repository root)

```text
src/nexusx/voyager/
├── voyager_context.py            # 修改：新增 get_docstring(schema_name) 方法
├── create_voyager.py             # 修改：新增 POST /docstring 路由
└── web/
    ├── index.html                # 修改：<head> 引入 marked/purify/mermaid；<body> 挂载 about-display
    ├── vue-main.js               # 修改：放宽拖拽 clamp（800 → floor(innerWidth × 2/3)）；加 window resize 监听
    ├── marked.min.js             # 新增（vendored）
    ├── purify.min.js             # 新增（vendored）
    ├── mermaid.min.js            # 新增（vendored）
    └── component/
        ├── schema-code-display.js # 修改：tab 栏最左加 About；只在 ER-diagram 模式显示
        └── about-display.js       # 新增：docstring 加载 + Markdown/Mermaid 渲染组件

tests/
└── test_voyager_docstring.py     # 新增：POST /docstring 端点的 pytest 用例
```

**Structure Decision**：沿用现有的 "single library + vendored web assets" 模式（即 plan-template 的 Option 1）。后端只新增一个端点 + 一个 context 方法（与现有 `/source`、`/vscode-link` 对称），前端只新增一个组件 + 三个 vendored 库；不引入构建工具链，不拆 monorepo，不新增 service 层。

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

无 Constitution 违规，本表留空。

## Phases

### Phase 0 — Outline & Research

详见 [research.md](./research.md)。本期 spec 没有 NEEDS CLARIFICATION 残留（clarify 阶段已全部解决）；Phase 0 主要解决"前端无构建工具链时如何引入 markdown/mermaid"、"docstring 数据通路（新端点 vs SchemaNode 增字段）"、"Mermaid 错误降级 UX"三个实现层面的决策。

### Phase 1 — Design & Contracts

- 数据模型与状态字段：[data-model.md](./data-model.md)
- 接口契约：
  - [contracts/docstring-endpoint.md](./contracts/docstring-endpoint.md) — 后端 `POST /docstring`
  - [contracts/about-tab-component.md](./contracts/about-tab-component.md) — 前端 `<about-display>` 组件
  - [contracts/sidebar-width-clamp.md](./contracts/sidebar-width-clamp.md) — 拖拽 clamp 规则
- 端到端验证：[quickstart.md](./quickstart.md)

Phase 1 收尾复检 Constitution：仍 trivial 通过（见上文）。
