# 契约：`<about-display>` 前端组件

**功能**：[spec.md](../spec.md) · **数据模型**：[data-model.md](../data-model.md) · **Mermaid 管线**：[research.md](../research.md) 决策 3

**位置**：`src/nexusx/voyager/web/component/about-display.js`（新增）

---

## 角色

Voyager ER 图侧边栏新增 "About" tab 的内容组件。当用户在 ER-diagram 模式下双击实体打开侧边栏、并切换到 About tab 时，本组件加载该 schema 模型类的 docstring，以 Markdown 渲染（含 Mermaid 块的就地图表渲染）。

模式与现有 `<related-entities-display>` 完全对称——独立组件、自管 state、只在被激活时发请求、提供 loading/error/empty 三态。

---

## Props

| 名称 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `schemaName` | `String` | required | 当前所选实体的全限定名（`module.Class`），与 `<schema-code-display>` 的同 名 prop 一致 |
| `visible` | `Boolean` | `false` | 当前 About tab 是否处于激活可见状态。仅当从 `false` 切到 `true` 时才发起 fetch；切到 `false` 时**不**清空已渲染内容（切回时无需重发请求） |

**不用** vuex/quasar store；不接收 `schemas` 列表 prop——docstring 不在 schema_map 里（见 [data-model.md](../data-model.md) §2.3）。

---

## 内部 ref（不暴露）

| ref | 类型 | 说明 |
|-----|------|------|
| `docstring` | `string` | 原始 docstring 文本 |
| `loading` | `boolean` | 是否正在请求 `/docstring` |
| `error` | `string \| null` | 错误文案；`null` 表示无错误 |
| `mermaidErrors` | `Array<{index: number, message: string, source: string}>` | 各 mermaid 块的渲染失败诊断（按块序号）；成功的块不进此数组 |

---

## 行为契约

### 1. 数据加载

- 当 `visible` 由 `false` → `true` 且 `schemaName` 非空 且 `docstring.value === "" && !error.value`（即尚未加载过）→ 触发 `fetchDocstring()`
- 当 `schemaName` 变化（侧边栏切到另一个实体）→ **重置** `docstring/loading/error/mermaidErrors` 后重新 `fetchDocstring()`
- `fetchDocstring()` 内部：
  - `loading = true`、`error = null`
  - `fetch('docstring', { method: 'POST', headers: {...}, body: JSON.stringify({schema_name: props.schemaName}) })`
  - 成功（200）：`docstring = data.docstring ?? ""`、`loading = false`
  - 失败（4xx/5xx 或网络错）：`error = data.error || "Failed to load docstring"`、`loading = false`
- 切回非激活 tab 再切回：**不**重新 fetch，保留已渲染 DOM（spec 边界情况约定）

### 2. 渲染管线（每次 `docstring` 变化后触发）

```
raw docstring
    │
    ▼ marked.parse(docstring, { gfm: true, breaks: false })
htmlString
    │
    ▼ DOMPurify.sanitize(htmlString, {
        ADD_ATTR: ['class','target','rel','href'],
        ADD_TAGS: ['pre','code','details','summary'],
      })
cleanHtml
    │
    ▼ container.innerHTML = cleanHtml
DOM
    │
    ▼ 对每个 code.language-mermaid 单独处理：
      - 取出 sourceText
      - try mermaid.parse(sourceText) 校验
        - ok → 替换为 <div class="mermaid">sourceText</div>
        - fail → mermaidErrors.push({index, message, source})，替换为
                <div class="mermaid-error">
                  <p>该 Mermaid 图渲染失败：{message}</p>
                  <details><summary>查看源码</summary><pre>{sourceText}</pre></details>
                </div>
      - 失败的块由 mermaid.run 跳过
    │
    ▼ mermaid.run({ nodes: container.querySelectorAll('div.mermaid') })
最终 DOM
```

**对每个 `<a>` 强制注入** `target="_blank" rel="noopener noreferrer"`（在 `cleanHtml` 注入后用一次 `container.querySelectorAll('a').forEach(...)` 完成）——实现 FR-017 + FR-009 的链接安全契约。

### 3. 三态 UI

| 状态 | 条件 | 渲染 |
|------|------|------|
| Loading | `loading === true` | `<q-linear-progress indeterminate color="primary" size="2px" />`（与 `<schema-code-display>` 风格一致） |
| Error | `error !== null` | `<div style="color:#c10015">{{ error }}</div>`（与 `<schema-code-display>` 的错误样式一致） |
| Empty | `!loading && !error && docstring.trim() === ''` | `<div class="text-grey-7">该实体暂无 docstring。</div>`（spec FR-005） |
| Content | `!loading && !error && docstring.trim() !== ''` | 上述渲染管线产出的 DOM |

### 4. Mermaid 初始化（全局一次，不在本组件）

`vue-main.js` 或 `index.html` 引入 `mermaid.min.js` 后立即：

```js
window.mermaid.initialize({ startOnLoad: false, theme: 'default' })
```

本组件**不**重复 initialize；多次 initialize 会让 mermaid 抱怨。

---

## 模板结构（伪代码）

```html
<div class="about-display" style="height:100%; overflow:auto;">
  <q-linear-progress v-if="loading" indeterminate color="primary" size="2px" />
  <div v-else-if="error" style="color:#c10015; font-family:Menlo,monospace; font-size:12px;">
    {{ error }}
  </div>
  <div v-else-if="emptyDocstring" class="text-grey-7" style="padding:12px;">
    该实体暂无 docstring。
  </div>
  <div v-else ref="contentRef" class="markdown-body" style="padding:8px 16px;"></div>
</div>
```

`contentRef` 在内容注入后用于 querySelector；mermaid 失败诊断用 `mermaidErrors` 数组在 dev 模式下做排错展示（生产环境靠 DOM 内的 `.mermaid-error` 节点即可）。

---

## 集成到 `<schema-code-display>`

修改 `schema-code-display.js`：

1. **tab 栏**：把 `<q-tab name="about" label="About" />` 加在最前（在 Fields 之前），并用 `v-if="showAbout"` 控制（与 `showRelatedEntities` 对称，仅 ER-diagram 模式显示）。
2. **content 区**：新增 `<div v-show="tab === 'about'">` 分支，挂载 `<about-display :schema-name="schemaName" :visible="tab === 'about' && modelValue" />`。
3. **props**：新增 `showAbout: { type: Boolean, default: false }`，由外层 `index.html` 传 `store.state.mode === 'er-diagram'`（与现有 `showRelatedEntities` 一致）。
4. **默认激活 tab 不变**：`tab = ref("fields")` 保持原状（spec 假设 + Session Q1 决议）。
