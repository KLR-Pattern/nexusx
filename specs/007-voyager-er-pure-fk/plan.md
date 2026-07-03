# Implementation Plan：Voyager ER 图 —— Hide Reverse Relationships 连线模式

**Branch**: `007-voyager-er-pure-fk` | **Date**: 2026-07-03 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/007-voyager-er-pure-fk/spec.md`

**Note**: 本计划由 `/speckit-plan` 产出，所有产物使用中文撰写（项目级约定）。功能分支名 `007-voyager-er-pure-fk` 为历史标识（specify 阶段命名），UI 可见 label 已在 clarify 阶段（Q5）改名为 "Hide Reverse Relationships"；分支/目录名保留不变，与 UI label 解耦。

## Summary

为 Voyager ER 图新增 "Hide Reverse Relationships" 显示选项，勾选后只保留 MANYTOONE 方向与 MANYTOMANY 方向的 relationship 连线、隐藏 ONETOMANY 反向镜像，消除 `back_populates` 双向关系产生的视觉重复（每对双向关联实体之间的连线从 2 条降为 1 条）。勾选状态默认关闭、写入 localStorage 持久化、与其他显示选项正交；作用范围包括主画布与 Related Entities 子图（spec 005 已建立"子图跟随主图渲染配置"原则）。

后端实现路径：在 `er_diagram_dot.py::_add_relationship_link` 中按 `RelationshipInfo.direction` 字段（SQLAlchemy `inspect()` 已提供，无需新增反射逻辑）早退过滤 ONETOMANY；`ErDiagramDotBuilder.__init__` 新增 `hide_reverse_relationships: bool = False` 参数；前端通过现有 `/er-diagram`、`/er-diagram-subgraph` 请求体（`ErDiagramPayload`、`ErDiagramSubgraphPayload`）新增同名字段把 UI 状态传到后端。不改造连线锚点或 label 生成方式、不引入新前端依赖、不破坏现有端点契约 shape（新增可选 bool 字段属兼容性变更）。

## Technical Context

- **Language/Version**: Python 3.10+（后端）；Vanilla JS + Vue 3 + Quasar 2（前端，**无构建工具链**，第三方库以 `.min.js` 形式 vendored 在 `src/nexusx/voyager/web/`）
- **Primary Dependencies**: FastAPI 0.135+（后端 HTTP）、Quasar / Vue 3（前端 UI，已 vendored）；本期**不引入新依赖**——`RelationshipInfo.direction` 字段已由 SQLAlchemy `inspect()` 在 `loader/registry.py::_inspect_relationships` 中自动反射
- **Storage**: 浏览器 localStorage（key: `hide_reverse_relationships`，沿用项目内 `better_cluster_display` / `show_module_cluster` / `brief_mode` / `pydantic_resolve_meta` 等偏好持久化模式）；后端无持久化
- **Testing**: `pytest`（后端 `_add_relationship_link` 按 direction 过滤逻辑 + `/er-diagram` / `/er-diagram-subgraph` 端点契约扩展）；前端无自动化测试基线，依赖 `quickstart.md` 的人工验证流程
- **Target Platform**: 开发机（Linux/macOS/Windows）启动 FastAPI 进程，浏览器访问 `http://localhost:<port>`；不做 SSR
- **Project Type**: library（nexusx）+ 内嵌 web 服务子模块（voyager）
- **Performance Goals**: 过滤逻辑（按 direction 早退）开销可忽略——`analysis()` 复杂度从 O(relationships) 不变，只是每次迭代多一次 `if rel_info.direction == 'ONETOMANY'` 比较；前端 toggle 切换触发的 ER 图重新生成与现有 toggle（cluster display / brief mode）一致
- **Constraints**:
  - **不引入前端构建工具链**——所有前端依赖必须能以 `<script src="...">` 直接加载（沿用 `quasar.min.js`、`vue.min.js` 模式）。
  - **不破坏现有端点契约 shape**——`/er-diagram`、`/er-diagram-subgraph` 请求体新增可选 bool 字段（`hide_reverse_relationships: bool = False`）属兼容性变更；响应 shape 不变。
  - 不改变 `Link` / `SchemaNode` 等已序列化的数据结构形状（避免破坏 web/schema 端点缓存与 service worker 缓存）。
  - 不改造 `_add_relationship_link` 现有锚点 / label 生成逻辑——本模式只决定"是否调用 `_add_relationship_link` 完成全部流程"，不改造其内部行为。
  - 不破坏 spec 005 `filter_to_neighborhood` 逻辑——Pure FK 过滤在 `analysis()` 内的 `_add_relationship_link` 早退完成，`filter_to_neighborhood` 在 `analysis()` 之后调用，自然继承已过滤的 `self.links`，子图跟随裁剪无需新增逻辑。
- **Scale/Scope**: 单 voyager 实例，schema 数量 ~100 量级；ONETOMANY 反向关系通常占 relationship 总数 1/3–1/2（双向关系定义下），过滤后画布连线密度显著下降。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` 当前仍是默认模板（项目尚未填入实际原则），无可对照的硬约束。**Gate 结果：通过（trivial）**。

设计阶段产出的关键决策已记录到 `research.md`，并将在 Phase 1 收尾时复检——确认本期设计未引入需要被未来宪法（如"前端不允许引入构建工具链"、"端点必须做输入校验"、"显示偏好状态不进入 URL"、"ORM relationship 元数据必须可在前端消费"等潜在原则）追溯约束的考量。

## Project Structure

### Documentation (this feature)

```text
specs/007-voyager-er-pure-fk/
├── plan.md              # 本文件
├── spec.md              # /speckit-specify 阶段产出
├── research.md          # Phase 0：技术决策与备选方案
├── data-model.md        # Phase 1：数据通路与状态字段
├── quickstart.md        # Phase 1：end-to-end 验证手册
├── contracts/           # Phase 1：接口契约
│   ├── er-diagram-payload-extension.md
│   ├── hide-reverse-filter.md
│   └── frontend-toggle.md
├── checklists/
│   └── requirements.md  # /speckit-specify 阶段产出
└── tasks.md             # Phase 2（/speckit-tasks 产出，本期不生成）
```

### Source Code (repository root)

```text
src/nexusx/voyager/
├── er_diagram_dot.py             # 修改：构造函数加 hide_reverse_relationships 参数；
│                                 #       _add_relationship_link 内按 direction 早退过滤 ONETOMANY
├── voyager_context.py            # 修改：4 处 ErDiagramDotBuilder 构造点透传新参数
└── create_voyager.py             # 修改：ErDiagramPayload、ErDiagramSubgraphPayload 加可选字段；
                                 #       /er-diagram、/er-diagram-subgraph 路由无需改逻辑

src/nexusx/voyager/web/
├── store.js                      # 修改：state.filter 新增 hideReverseRelationships 字段；
│                                 #       新增 toggleHideReverseRelationships(val, onGenerate) 函数；
│                                 #       buildErDiagramSubgraphPayload 返回对象内透传 hide_reverse_relationships
│                                 #       （/er-diagram-subgraph 请求体的唯一构造点，spec 005 引入）
├── vue-main.js                   # 修改：初始化时从 localStorage 读取 hide_reverse_relationships；
                                 #       fetch /er-diagram 请求体内透传 hide_reverse_relationships
└── component/
    └── schema-code-display.js    # 修改：显示选项面板新增 Hide Reverse Relationships toggle
                                  #       （与 cluster display / brief mode 同侧；具体位置 plan 不固化）

tests/
└── test_voyager_hide_reverse.py  # 新增：后端过滤逻辑 + 端点契约的 pytest 用例
```

**Structure Decision**：沿用现有的 "single library + vendored web assets" 模式（即 plan-template 的 Option 1）。后端只新增一个构造函数参数 + 一处早退过滤 + 两个 Payload model 各加一个可选字段 + 4 处构造点透传；前端只新增一个 store 字段 + 一个 toggle 函数 + 显示选项面板加一个 checkbox + 初始化时读 localStorage；不引入构建工具链，不拆 monorepo，不新增 service 层，不新增前端依赖。

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

无 Constitution 违规，本表留空。

## Phases

### Phase 0 — Outline & Research

详见 [research.md](./research.md)。本期 spec 没有 NEEDS CLARIFICATION 残留（clarify 阶段 Q1-Q5 全部解决）；Phase 0 主要解决四个**实现层面**的决策：

1. 过滤发生位置（前端 SVG 隐藏 vs 后端 dot 裁剪）
2. UI 状态传输路径（请求体扩展字段 vs 新增端点 vs URL 参数）
3. 命名约定（localStorage key / store 字段 / toggle 函数 / Payload 字段的对齐策略）
4. 过滤逻辑在 `_add_relationship_link` 内的具体位置（早退 vs 末尾过滤 vs 渲染时过滤）

### Phase 1 — Design & Contracts

- 数据模型与状态字段：[data-model.md](./data-model.md)
- 接口契约：
  - [contracts/er-diagram-payload-extension.md](./contracts/er-diagram-payload-extension.md) — 后端 `ErDiagramPayload`、`ErDiagramSubgraphPayload` 字段扩展
  - [contracts/hide-reverse-filter.md](./contracts/hide-reverse-filter.md) — `_add_relationship_link` 早退过滤逻辑
  - [contracts/frontend-toggle.md](./contracts/frontend-toggle.md) — 前端 store + UI 集成
- 端到端验证：[quickstart.md](./quickstart.md)

Phase 1 收尾复检 Constitution：仍 trivial 通过（见上文）。
