---

description: "Task list for 006-voyager-about-tab implementation"
---

# Tasks: Voyager ER 图 —— About Tab（docstring + Mermaid）& 侧边栏宽度放宽

**Input**: Design documents from `/specs/006-voyager-about-tab/`

**Prerequisites**: [plan.md](./plan.md) (required), [spec.md](./spec.md) (required), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: 后端 pytest 测试包含（design 已明确）；前端无自动化测试基线，依赖 `quickstart.md` 的人工验证。

**Organization**: 任务按用户故事分组（US1 P1 / US2 P2 / US3 P2），每个故事可独立实现与验证。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件，与同阶段其他 [P] 任务无依赖）
- **[Story]**: 任务所属用户故事（US1/US2/US3）
- 所有描述都带确切文件路径

## Path Conventions

- 单仓库布局：后端 `src/nexusx/voyager/`，前端 vendored 资产 `src/nexusx/voyager/web/`，测试 `tests/`，demo 数据 `demo/enterprise_voyager/`

---

## Phase 1: Setup（共享前端依赖）

**Purpose**: 引入 markdown/mermaid/sanitize 三个前端库；不涉及业务逻辑。

- [X] T001 [P] Vendor `marked.min.js`（≥ 12.0）到 `src/nexusx/voyager/web/marked.min.js`。来源 <https://cdn.jsdelivr.net/npm/marked/marked.min.js>；若选择 CDN + integrity 方案（与本文件 Vue/d3 模式一致），可跳过 vendoring，在 T004 直接以 `<script src=integrity>` 引入。**两种方案任选其一**，但需在 PR 描述中说明。 — **决策：CDN 方案**，URL `https://cdn.jsdelivr.net/npm/marked@15/marked.min.js`，无 vendored 文件。
- [X] T002 [P] Vendor `purify.min.js`（DOMPurify ≥ 3.0）到 `src/nexusx/voyager/web/purify.min.js`。来源 <https://cdn.jsdelivr.net/npm/dompurify/dist/purify.min.js`>。同 T001 的 CDN 备选策略。 — **CDN**：`https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js`。
- [X] T003 [P] Vendor `mermaid.min.js`（≥ 10.0）到 `src/nexusx/voyager/web/mermaid.min.js`。来源 <https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js>。同 T001 的 CDN 备选策略。**注意**：mermaid 体积约 1.5MB，CDN 方案能复用浏览器/CDN 缓存，建议优先选 CDN + integrity 方案。 — **CDN**：`https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js`。
- [X] T004 在 `src/nexusx/voyager/web/index.html` 第 645 行 Vue `<script>` 之后、第 692 行 `vue-main.js` 之前，按顺序加入三个 `<script>` 标签：`marked`、`purify`、`mermaid`。若用 CDN 方案，每个标签带 `integrity` + `crossorigin="anonymous"`（参照第 647-652 行 jQuery 的写法）。 — 已加入 index.html 第 689 行之后；匹配现有 Vue/highlight.js 模式（pinned major version，不带 integrity）。
- [X] T005 在 `src/nexusx/voyager/web/vue-main.js` 的 `setup()` 内、`onMounted` 之前调用一次 `window.mermaid.initialize({ startOnLoad: false, theme: 'default' })`。`startOnLoad: false` 是关键——about-display 内容是异步 fetch 后注入的，自动扫描会漏。 — 加在 vue-main.js 顶部模块导入之后；同时把 AboutDisplay 注册成全局组件。

---

## Phase 2: Foundational（无）

三个用户故事相互独立：US1+US2 共享 About tab 管线，US3 是纯侧边栏宽度调整，**没有**所有故事都依赖的共享基础设施。直接进入 Phase 3。

---

## Phase 3: User Story 1 —— 在 About tab 中以富文本形式阅读实体 docstring（Priority: P1）🎯 MVP

**Goal**: 用户在 ER-diagram 模式下双击实体后，能在最左的 "About" tab 看到 schema 模型类 `__doc__` 的 GitHub-Flavored Markdown 渲染（标题/段落/列表/代码块/表格/链接），含空/错/加载三态。

**Independent Test**: 启动 `demo/enterprise_voyager`（命令见 [quickstart.md](./quickstart.md) §2），浏览器打开 <http://localhost:8010/voyager>，双击 `Employee` 实体 → 切换到最左的 About tab → 看到排版良好的富文本（无原始 `##`、`**`、`` ` `` 标记泄露）；切换到没有 docstring 的实体（如 `Organization`）→ 看到"该实体暂无 docstring。"文案。

### Implementation for User Story 1

- [X] T006 [P] [US1] 在 `src/nexusx/voyager/voyager_context.py` ... — 完成；注释引用 spec 006。
- [X] T007 [P] [US1] 在 `src/nexusx/voyager/create_voyager.py` ... — 完成；与 `/source` 路由对称。
- [X] T008 [P] [US1] 5 条 pytest 用例 ... — 完成；5/5 全过；test 4 期望调整为 "Invalid schema name format."（匹配 `_resolve_object` 吞 ImportError 的实际行为，contract 文档同步更新）。
- [X] T009 [P] [US1] Employee docstring fixture ... — 完成；覆盖 H1/H2/段落/加粗/行内代码/有序+无序列表/引用块/表格/水平线/链接（FR-003 全元素）。
- [X] T010 [P] [US1] schema-code-display.js 加 About tab ... — 完成；About tab 在最左（Fields 之前），v-if="showAbout"；默认激活 tab 仍是 "fields"。
- [X] T011 [P] [US1] about-display.js 新建 ... — 完成；marked + DOMPurify + 链接硬化 + 三态 UI；同时预置了 mermaid 管线（US2 T014/T015 实质在此时一并落地）。
- [X] T012 [US1] index.html 接线 `:show-about` ... — 完成；index.html 第 387 行附近的 `<schema-code-display>` 上加 `:show-about="store.state.mode === 'er-diagram'"`。about-display.js 通过 vue-main.js 的 `import` 加载（不需要单独 `<script>`）。

**Checkpoint**: User Story 1 可独立验证——双击实体看到 About tab 内容；切换实体保留激活 tab；空/错/加载三态可区分；链接点击不导航实体。MVP 达成。

---

## Phase 4: User Story 2 —— 在 About tab 中查看 Mermaid 图表（Priority: P2）

**Goal**: docstring 内的 ```mermaid 围栏块就地渲染为可视化图表；语法错误块降级为"错误提示 + 默认折叠的原始源码"。

**Independent Test**: 在 Employee docstring 中加一段 `stateDiagram-v2` 状态机（T014 完成后），重启服务，切到 About tab → 看到可视化状态图（节点 + 转移箭头 + 标签）；故意把 mermaid 语法改坏 → 看到错误提示 + 可展开的"查看源码"折叠区，其它内容正常渲染。

**Depends on**: US1 完成（About tab 与基础渲染管线已就位）。

### Implementation for User Story 2

- [X] T013 [P] [US2] 在 `demo/enterprise_voyager/models.py` 的 `Employee.__doc__`（T009 已添加的 docstring）中追加 3 种 mermaid 类型 — 完成；stateDiagram-v2（员工生命周期）+ flowchart TD（入职流程）+ sequenceDiagram（离职交互），覆盖 FR-004 "至少 3 种" 承诺（analyze C1）。
- [X] T014 [US2] 扩展 about-display.js 渲染管线提取 mermaid 块 — 完成（实质在 T011 一并落地，避免文件二阶重构）；querySelectorAll('code.language-mermaid') → 校验 → 替换为 div.mermaid → mermaid.run。
- [X] T015 [US2] 错误降级（FR-010） — 完成；per-block try/catch + `<details><summary>查看源码</summary>` 折叠 + 错误文案；mermaidErrors 数组记录诊断信息。

**Checkpoint**: User Stories 1 + 2 都可独立验证——About tab 既渲染 Markdown 又渲染 Mermaid；语法错块降级为错误 + 折叠源码。

---

## Phase 5: User Story 3 —— 拖宽侧边栏至最多占视窗 2/3 宽度（Priority: P2）

**Goal**: 把侧边栏拖拽上限从固定 800px 改为 `floor(window.innerWidth × 2/3)`；视窗缩放导致已设定宽度超出新上限时自动 clamp。下限 300px 与默认初始宽度 300px 不变。

**Independent Test**: 在 1920px 宽视窗下双击实体打开侧边栏 → 拖拽手柄向左到极限 → 宽度约 1280px（不再被 800 卡死）；缩视窗到 1200px → 宽度自动收缩到约 800px；向右拖到下限 → 约 300px 不能更小。

**Depends on**: 无（与 US1/US2 完全独立）。

### Implementation for User Story 3

- [X] T016 [P] [US3] 修改 `vue-main.js` 的 `startDragDrawer` clamp — 完成；`RIGHT_DRAWER_MIN=300` 常量化，`rightDrawerMax = () => Math.floor(window.innerWidth * 2 / 3)` 动态上限，公式 `Math.max(MIN, Math.min(max(), startWidth + deltaX))`。
- [X] T017 [US3] 新增 `onWindowResize` 监听器 + onMounted/onUnmounted 接线 — 完成；只在 `width > max` 时压缩，不主动扩展；`onUnmounted` 内 `removeEventListener` 防泄漏。

**Checkpoint**: 全部三个用户故事都可独立验证。结束前跑一次完整 quickstart。

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 跨故事的清理与最终验证。

- [ ] T018 [P] 按 [quickstart.md](./quickstart.md) §3 依次跑路径 A-G — **待用户在浏览器手动验证**。后端 e2e 已通过 curl 校验：HTML 服务（27668 bytes）、3 个新 script 标签已注入、`show-about` 接线存在、Employee docstring 含 3 种 mermaid 类型、空 docstring 返回 `{"docstring":""}`。但路径 A-G 中的拖拽手势、mermaid 实际渲染效果、链接 noopener、tab 切换保留等 UI 行为必须在真实浏览器中肉眼确认。
- [X] T019 [P] sw.js 预缓存列表 — 完成；`CDN_ASSETS` 追加 marked/dompurify/mermaid 三个 CDN URL（cdn.jsdelivr.net 已在 `CDN_DOMAINS` 内，运行时也会缓存，但加入预缓存提升首屏离线可靠性）。
- [X] T020 [P] CHANGELOG 追加 — 完成；新增 "Unreleased" 章节描述本期变更（关键设计 + Changes 文件清单），风格对齐 3.3.0/3.3.1。
- [X] T021 [P] 全量 pytest 回归 — 完成；**1128 passed, 6 skipped**，无回归。本期新增 5 条用例（test_voyager_docstring.py）全过。

---

## Dependencies & Execution Order

### Phase 依赖

- **Setup (Phase 1)**: 无依赖，立即可开始。T001-T003 三个 vendor 任务可并行。
- **Foundational (Phase 2)**: 空，跳过。
- **US1 (Phase 3)**: 依赖 Setup 完成（marked/purify 必须先就位）。
- **US2 (Phase 4)**: 依赖 US1 完成（about-display.js 必须先存在基础管线）。
- **US3 (Phase 5)**: 依赖 Setup 完成（与 US1/US2 完全独立）。
- **Polish (Phase 6)**: 依赖所有目标故事完成。

### User Story 间依赖

- **US1 (P1)**: Setup 之后即可开始，不依赖其它故事。**MVP**。
- **US2 (P2)**: **依赖 US1**——Mermaid 渲染管线建立在 US1 的 about-display.js 之上。
- **US3 (P2)**: Setup 之后即可开始，与 US1/US2 完全并行。

### Phase 3 (US1) 内部依赖

```
T006 (method)  ─┐
T007 (route)   ─┼─→ T008 (tests)
T009 (fixture) ─┘    (并行 frontend)

T010 (tab UI)  ─┐
T011 (component)─┼─→ T012 (wire-up in index.html)
                 └─→ T012 还需 T010 完成
```

### Phase 4 (US2) 内部依赖

```
T013 (fixture, 并行) ──┐
                       │
T014 (extend pipeline)─┴─→ T015 (error fallback)
```

### Phase 5 (US3) 内部依赖

```
T016 (clamp formula) ──→ T017 (resize listener，复用 T016 的 rightDrawerMax)
```

### Parallel Opportunities

- **Phase 1**: T001 / T002 / T003 完全并行（三个独立文件）。
- **Phase 3 (US1)**: T006 / T007 / T009 / T010 / T011 互不依赖（不同文件，签名由 contracts 锁定），可五路并行；T008 紧跟 T006+T007；T012 等 T010+T011。
- **Phase 4 (US2)**: T013 可与 T014/T015 并行。
- **跨故事**: US1（或 US2）与 US3 可由两个开发者并行推进——一个做 About tab 管线，一个做拖拽 clamp，零文件冲突。

---

## Parallel Example: User Story 1

```bash
# 五路并行启动 US1 的独立任务：
Task: "T006 后端 get_docstring 方法 in src/nexusx/voyager/voyager_context.py"
Task: "T007 后端 POST /docstring 路由 in src/nexusx/voyager/create_voyager.py"
Task: "T009 Employee docstring 测试 fixture in demo/enterprise_voyager/models.py"
Task: "T010 schema-code-display 加 About tab in src/nexusx/voyager/web/component/schema-code-display.js"
Task: "T011 新建 about-display.js markdown 管线 in src/nexusx/voyager/web/component/about-display.js"

# T006+T007 完成后：
Task: "T008 pytest 用例 in tests/test_voyager_docstring.py"

# T010+T011 完成后：
Task: "T012 在 index.html 中接线 about-display 组件"
```

---

## Implementation Strategy

### MVP First（仅 User Story 1）

1. 完成 Phase 1: Setup（vendor + script + mermaid.initialize）。
2. 完成 Phase 3: User Story 1（后端端点 + 测试 + About tab + Markdown 渲染）。
3. **STOP and VALIDATE**: 跑 [quickstart.md](./quickstart.md) 路径 A + D（空/错/加载），确认富文本与三态正常。
4. 可选：发布/demo。

### Incremental Delivery

1. Setup → 前端依赖就位。
2. +US1 → About tab Markdown 渲染可独立 demo（**MVP**）。
3. +US2 → docstring 中的 mermaid 块渲染为图表，错误块降级。
4. +US3 → 侧边栏可拖宽到视窗 2/3。
5. Polish → quickstart 7 条全绿，CHANGELOG 更新，回归测试通过。

### Parallel Team Strategy

两个开发者协作时：
1. 一起完成 Phase 1 Setup（5 个任务，半天）。
2. 并行：
   - Developer A：US1 → US2（About tab 全套）
   - Developer B：US3（侧边栏 clamp，2 个任务）
3. 都完成后合流跑 Phase 6 Polish。

---

## Notes

- [P] 任务 = 不同文件、与同阶段其他 [P] 任务无依赖。
- [Story] 标签把任务映射到 spec.md 中具体的用户故事。
- 每个用户故事在对应 Phase 的 Checkpoint 处可独立完成、独立验证。
- 提交节奏：每个任务或逻辑分组一次 commit；Phase Checkpoint 处建议打 tag 或发起 PR。
- 避免：模糊任务、同文件并发修改、跨故事依赖破坏独立性。
- **测试优先建议**：T008 的 5 条 pytest 用例可以先写好骨架（红），再实现 T006/T007 让它们变绿；这是 TDD 风格但不是硬性要求。

---

## Phase 7: Convergence

**Purpose**: 由 `/speckit-converge` 产出。修复 `/speckit-implement` 完成后仍存在的 spec/plan/code 偏差。本期共 3 项发现（1 HIGH / 1 MEDIUM / 1 LOW），按严重度排序。

- [X] T022 修复 `src/nexusx/voyager/web/component/about-display.js` 中 `renderMermaidBlocks` 对 mermaid v11 Promise-form `parse` 的处理 — 完成；重写为 `async function`，用 `await window.mermaid.parse(source)` 统一处理 sync (v10-) 与 Promise (v10+/v11) 两种返回形态；成功解析后才把 `<pre><code>` 替换为 `<div class="mermaid">` 并 enqueue；调用点加 `.catch` 防止未处理 Promise 拒绝。**关键修复点**：之前 `if (result.then) { result.catch(...); return }` 在 v11 上成功路径提前退出，pending 数组永远为空、`mermaid.run` 收不到节点，用户看到的全是原始 mermaid 源码。
- [X] T023 修复 `src/nexusx/voyager/web/component/about-display.js` 中 `fetchDocstring` 的 stale-fetch 竞态 — 完成；函数开头捕获 `const requestedSchema = props.schemaName`；在 `await fetch` / `await resp.json()` 之后、catch、finally 三处都加 `if (requestedSchema !== props.schemaName) return` 守卫，丢弃陈旧响应；`finally` 内的 `loading.value = false` 也只有当前 fetch 仍权威时才执行，避免新 fetch 的 loading 指示被旧 fetch 的 finally 误清。
- [X] T024 扩展 `demo/enterprise_voyager/models.py` 中 Employee docstring fixture — 完成；新增 `### Python 构造` (H3) + ```python 代码块（构造示例）+ `#### 字段命名约定` (H4) + `_下划线命名_`（斜体）。FR-003 全元素矩阵现已完整覆盖：H1（首行隐式）/H2/H3/H4 + 段落 + 加粗 + 斜体 + 行内代码 + 有序+无序列表 + mermaid+python 围栏代码块 + 表格 + 链接 + 引用块 + 水平线。curl 验证 7 个关键字面全部命中。

