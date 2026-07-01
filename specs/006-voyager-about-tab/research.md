# Phase 0 — 研究与决策：Voyager About Tab & 侧边栏宽度放宽

**功能**：[spec.md](./spec.md) · **计划**：[plan.md](./plan.md)

**调研范围**：spec 中无 NEEDS CLARIFICATION 残留（已在 `/speckit-clarify` 阶段全部解决）；本文件聚焦三个**实现层面**的决策——前端依赖引入方式、docstring 数据通路、Mermaid 错误降级 UX；外加拖拽 clamp 的具体公式。

---

## 决策 1：前端依赖（marked / DOMPurify / mermaid）的引入方式

**Decision**：以 vendored `.min.js` 文件直接 `<script>` 引入到 `src/nexusx/voyager/web/index.html`，与现有 `quasar.min.js`、`vue.min.js` 模式一致。**不**引入 npm / 打包器 / ES 模块构建工具链。

**Rationale**：
- 现有 voyager 前端就是 vanilla JS + vendored 库 + 全局变量（`window.Vue`、`window.Quasar`）模式，没有任何构建步骤；贸然引入构建工具链会破坏现有开发体验与发布流程（CLAUDE.md 内项目约束："不引入前端构建工具链"是潜在原则）。
- 三个库都官方提供 UMD/IIFE standalone 版本（marked、DOMPurify、mermaid 均有 `dist/*.min.js`），可直接 `<script src>` 加载并暴露全局（`window.marked`、`window.DOMPurify`、`window.mermaid`）。
- 体积可接受：marked ~40KB、DOMPurify ~20KB、mermaid ~1.5MB（含所有图表类型）。voyager 是开发者工具，首屏体积不是核心约束；若担心，可后续切到 mermaid 的按需子集构建，但本期不做。

**Alternatives considered**：
- **引入 Vite/esbuild + npm**：被否——破坏现有无构建模式，且要求所有 nexusx 使用者装 Node 工具链。
- **后端渲染 Markdown/Mermaid 为 HTML/SVG 再发到前端**：被否——Mermaid 渲染需要浏览器字体度量，服务端渲染需引入 puppeteer，过重；Markdown 服务端渲染虽可行（`markdown-it` 也有 Python 实现 `markdown` 包），但失去客户端切换实体时的即时渲染优势。
- **CDN 引入**：被否——离线场景（开发机无外网）会断；nexusx 已 vendored 其它库，保持一致。

---

## 决策 2：docstring 数据通路（新端点 vs SchemaNode 增字段 vs 复用 /source）

**Decision**：**新增独立端点** `POST /docstring`，请求体 `{schema_name: str}`、响应 `{docstring: str}`（或 `{error: str}`）。后端在 `VoyagerContext` 上新增方法 `get_docstring(schema_name)`，复用现有 `_resolve_object(schema_name)` 拿到类对象，返回 `obj.__doc__ or ""`。**不**修改 SchemaNode / 不改 `/source` 响应。

**Rationale**：
- 与现有 `/source`、`/vscode-link` 三个对称端点的模式完全一致：on-demand 拉取，按 schema_name 解析类对象，反射读属性。代码量最小、最易测、最不破坏现有契约。
- 把 docstring 塞进 SchemaNode（决策 A）会**全量预取**所有 schema 的 docstring 到 er-diagram 初始 payload 里；对一个含 ~100 实体的 schema，docstring 总量可达几十 KB 到上百 KB，绝大多数用户从不打开 About tab，浪费明显。
- 复用 `/source` 端点（决策 C）让该端点的响应多一个字段，违反单一职责；且 `/source` 已经被 service worker 缓存（`web/sw.js:132`），改动响应 shape 需要同步改 sw 缓存键，得不偿失。
- 前端组件 `about-display.js` 已经独立成单组件，自己发 fetch、自己管 loading/error 状态，与 `related-entities-display.js` 的模式一致；新端点正好对上这个组件的生命周期。

**Alternatives considered**：
- **A. SchemaNode 新增 `docstring: str = ''` 字段**：见上，被否（payload 膨胀、破坏现有序列化 shape）。
- **C. 扩展 `/source` 响应为 `{source_code, docstring}`**：见上，被否（破坏 sw 缓存契约 + 单一职责）。

---

## 决策 3：Mermaid 渲染管线与错误降级

**Decision**：渲染管线采用 "marked 解析 → DOMPurify 清洗 → mermaid.run() 后处理"，对每段 mermaid 块**单独 try/catch**，失败时把该块替换为 "错误提示 + 默认折叠的原始源码" 的 DOM 节点。

具体步骤：
1. 用 `marked.parse(docstring)` 解析整段 docstring 为 HTML 字符串。mermaid 围栏块此时被解析为 `<pre><code class="language-mermaid">...源码...</code></pre>`。
2. 在 marked 输出后、注入 DOM 前，用 DOMPurify 清洗整段 HTML，配置 `ADD_TAGS: ['pre','code']`、`ADD_ATTR: ['class']`，允许 mermaid 后续需要的 class 属性通过。
3. 把清洗后的 HTML 注入容器，然后用 `container.querySelectorAll('code.language-mermaid')` 找到所有 mermaid 源码块，**逐个**：
   - 取出源码文本，包成 `<div class="mermaid">源码</div>`，替换原 `<pre><code>`。
   - 调用 `mermaid.parse(sourceText)` 做语法校验：
     - 通过 → 让 `mermaid.run({ nodes: [那个 div] })` 渲染为 SVG。
     - 失败 → 把该 div 替换为 `<div class="mermaid-error">错误提示 + <details><summary>查看源码</summary><pre>源码</pre></details></div>`。
4. 其余代码块（`language-python` 等）保持 `<pre><code>` 不动。

**Rationale**：
- "整段清洗再后处理 mermaid" 比 "用 marked extension 拦截 mermaid 块" 更简单直接——extension API 需要熟悉 marked 内部，而 querySelector 方案 5 行代码搞定。
- 单块 try/catch 是 FR-010"不影响 docstring 其他部分"的字面实现；只要每个 mermaid 块独立处理，一个失败不影响其它。
- "默认折叠" 用原生 `<details><summary>` 元素，零 JS、键盘可访问、不引入额外 UI 库。
- 用 `mermaid.parse(sourceText)` **预先**校验语法（而不是直接 `mermaid.run()` 让它内部抛错），可以拿到结构化的错误信息（行号、期望 token），便于在错误提示里展示。

**Alternatives considered**：
- **marked extension 在解析阶段拦截 mermaid**：更"优雅"但实现复杂度高、对 marked 版本敏感；本期采用更朴素的 querySelector 方案。
- **失败时静默回退为原始代码块**：违反 FR-010"明确的错误提示"。
- **失败时全屏 alert/console.error**：过于打扰；用就地 `<details>` 折叠更合适。

---

## 决策 4：Markdown 链接点击行为（不导航实体）

**Decision**：DOMPurify 配置 `ADD_ATTR: ['target','rel','href']`，并对所有 `<a>` 注入 `target="_blank" rel="noopener noreferrer"`。不在前端做任何"识别实体引用并触发 store action 跳转"的逻辑——FR-017 明文规定不导航。

**Rationale**：
- 行为与 spec 决议一致；实现最简。
- 强制所有链接新 tab 打开 + `rel="noopener"` 防止 reverse tabnabbing，与 FR-009（XSS 清洗）的安全基调一致。

**Alternatives considered**：
- **识别 `entity:module.Class` 形态的链接并触发跳转**：被否——FR-017 已明确不在本期范围。

---

## 决策 5：侧边栏拖拽 clamp 公式

**Decision**：把 `vue-main.js:269` 的 `Math.max(300, Math.min(800, startWidth + deltaX))` 改为：

```js
const min = 300
const max = Math.floor(window.innerWidth * 2 / 3)
const newWidth = Math.max(min, Math.min(max, startWidth + deltaX))
```

并新增 `window.addEventListener('resize', ...)` 监听器：触发时若 `store.state.rightDrawer.width > floor(innerWidth × 2/3)`，把 store 中的 width clamp 到新上限。

**Rationale**：
- 下限 300px 保持现状（与 spec 假设一致：不引入新的更小下限）。
- 上限 `floor(W × 2/3)` 是 spec 验收场景 1 的字面实现；`floor` 取整避免亚像素抖动。
- resize 监听是 FR-015 的字面实现——已设定的宽度超过新上限时主动 clamp，避免"侧边栏比画布还宽"的破损布局。
- 不持久化"上限值"——上限始终从 `window.innerWidth` 实时计算，刷新页面/重启浏览器后自动跟随当前视窗。

**Alternatives considered**：
- **使用 CSS `max-width: 66.67vw`** 而非 JS clamp：被否——Quasar `q-drawer` 的 `:width` prop 是 JS 控制的像素值，CSS max-width 会与 Quasar 内联 style 冲突；且 FR-015 要求"store 中的 width 值也 clamp"，必须在 JS 层处理。
- **使用 ResizeObserver 监听 drawer 本身**：被否——drawer 大小是被 width prop 控制的因变量，监听它会循环；监听 `window.resize` 才是正确的"自变量"。

---

## 决策 6：Mermaid 主题与初始化时机

**Decision**：在 `index.html` 引入 `mermaid.min.js` 后，在 `vue-main.js` 顶部（或 `app.js` 等全局初始化位置）调用一次 `mermaid.initialize({ startOnLoad: false, theme: 'default' })`。`startOnLoad: false` 关掉自动扫描，改由 `about-display.js` 在内容注入后显式 `mermaid.run({ nodes })`。主题用 `default`（light）与应用整体基调一致。

**Rationale**：
- `startOnLoad: true` 会在 DOMContentLoaded 时全文档扫描 `.mermaid` 节点，但 about-display 的内容是异步 fetch 后才注入的，自动扫描会漏；必须 `false` + 手动 `run()`。
- 主题不暴露成可配置项（spec 假设：跟随应用主题，不引入新主题切换）；如未来引入暗色主题再扩展。

---

## 待 Phase 2（/speckit-tasks）处理的实现细节

以下不在本期 plan 范围，留给 tasks 阶段拆分：

- vendored 库的具体版本号（marked ≥ 12、DOMPurify ≥ 3、mermaid ≥ 10 即可，三者互相兼容）。
- `<about-display>` 组件具体的 props 名称（倾向：`schemaName: String`、`visible: Boolean`，与 `related-entities-display` 对齐）。
- pytest 用例的精确覆盖矩阵（happy path / 空 docstring / schema 不存在 / module import 失败 4 条够用）。
- whether to add a `<about-display>` service-worker prefetch entry（倾向：不加，docstring 端点是 on-demand，不该预缓存）。
