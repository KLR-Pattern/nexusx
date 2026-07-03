# 契约：前端 store + UI 集成

**功能**：[spec.md](../spec.md) · **数据模型**：[data-model.md](../data-model.md) · **Payload 契约**：[er-diagram-payload-extension.md](./er-diagram-payload-extension.md)

**位置**：
- `src/nexusx/voyager/web/store.js`（state + toggle 函数）
- `src/nexusx/voyager/web/vue-main.js`（初始化 + fetch 透传）
- `src/nexusx/voyager/web/component/schema-code-display.js`（显示选项面板 checkbox）

---

## store.js 变更

### 新增 state 字段

在 `state.filter` 对象内新增：

```javascript
state.filter = {
  // ... 现有字段保持不变
  hideReverseRelationships: false,   // 新增（本期）
}
```

初始值 `false`，与 spec FR-002"默认未勾选"一致。

### 新增 toggle 函数

紧邻现有 `toggleBetterClusterDisplay`（约第 467-475 行）之后新增：

```javascript
/**
 * Toggle hide reverse relationships mode.
 * When enabled, only MANYTOONE and MANYTOMANY direction relationship edges
 * are rendered (FK-holder side preserved); ONETOMANY reverse mirrors hidden.
 * Persists to localStorage; calls onGenerate to trigger graph re-render.
 * @param {boolean} val - New value
 * @param {Function} onGenerate - Callback to regenerate graph
 */
toggleHideReverseRelationships(val, onGenerate) {
  state.filter.hideReverseRelationships = val
  try {
    localStorage.setItem("hide_reverse_relationships", JSON.stringify(val))
  } catch (e) {
    console.warn("Failed to save hide_reverse_relationships to localStorage", e)
  }
  onGenerate()
},
```

签名、错误降级（`console.warn` 不阻塞）、`onGenerate()` 调用模式与现有 `toggleBetterClusterDisplay` / `toggleBrief` / `togglePydanticResolveMeta` 完全一致。

---

## vue-main.js 变更

### 初始化时读取 localStorage

在现有 `loadToggleState("pydantic_resolve_meta", ...)`（约第 55 行）之后新增：

```javascript
store.state.filter.hideReverseRelationships = loadToggleState(
  "hide_reverse_relationships",
  false,
)
```

`loadToggleState(key, defaultValue)` 是项目内已有的辅助函数（与 `show_module_cluster` / `better_cluster_display` / `brief_mode` / `pydantic_resolve_meta` 复用同一函数），自动处理 JSON 解析失败、隐私模式禁用 localStorage 等降级场景（spec FR-011 / Story 2 验收场景 4-5）。

### fetch `/er-diagram` 时透传字段

约第 189-200 行，现有 `fetch("er-diagram", { body: JSON.stringify({...}) })` 的 body 内新增一行：

```javascript
const res = await fetch("er-diagram", {
  // ... method / headers 不变
  body: JSON.stringify({
    // ... 现有字段保持不变
    schema: store.state.graph.schema,
    show_module: store.state.filter.showModule,
    better_cluster_display: store.state.filter.betterClusterDisplay,
    show_methods: store.state.modeControl.showMethodsEnabled,
    // ... 其他现有字段
    hide_reverse_relationships: store.state.filter.hideReverseRelationships,   // 新增（本期）
  }),
})
```

### fetch `/er-diagram-subgraph` 时透传字段

`/er-diagram-subgraph` 请求体由 `src/nexusx/voyager/web/store.js::buildErDiagramSubgraphPayload(schemaName)` 构造（spec 005 引入，约第 623-632 行）——这是该端点请求体的**唯一构造点**，被 `store.js::fetchRelatedEntities`（约第 638 行）调用、由 `component/related-entities-display.js` 触发。

在本函数返回对象内新增字段：

```javascript
buildErDiagramSubgraphPayload(schemaName) {
  return {
    schema_name: schemaName,
    show_fields: state.filter.showFields,
    show_module: state.filter.showModule,
    better_cluster_display: state.filter.showModule && state.filter.betterClusterDisplay,
    edge_minlen: state.filter.edgeMinlen,
    show_methods: state.filter.showMethods,
    hide_reverse_relationships: state.filter.hideReverseRelationships,   // 新增（本期）
  }
},
```

**为什么直接透传而不做条件包装**：与 `better_cluster_display` 不同（其在 subgraph 中受 `state.filter.showModule && ...` 条件包装，因为 cluster display 依赖 module 聚类），`hide_reverse_relationships` 是独立的渲染配置、无前置依赖，直接透传即可——与 spec FR-007"子图跟随主图渲染配置"原则一致。

---

## 显示选项面板变更（component/schema-code-display.js 或同等位置）

### 新增 Quasar checkbox

紧邻现有 `better cluster display` / `brief mode` / `pydantic resolve meta` toggle 之后新增：

```html
<q-checkbox
  :model-value="store.state.filter.hideReverseRelationships"
  @update:model-value="(val) => store.toggleHideReverseRelationships(val, onGenerate)"
  label="Hide Reverse Relationships"
/>
```

### 仅在 ER-diagram 模式下可见

`schema-code-display.js` 已有按 `store.state.mode === 'er-diagram'` 条件渲染面板的逻辑（spec FR-001）——新增 checkbox 沿用同一条件，无需新增判断。

### 键盘可达性（spec FR-004）

Quasar `q-checkbox` 默认键盘可达（Tab 聚焦、Space 切换），与现有 `q-checkbox` 一致，无需额外配置。

### 选项位置（plan 阶段不固化）

spec FR-001 仅要求"与现有显示选项位于同一交互区域"，具体顺序（出现在 brief mode 之前还是之后）、分组（独立还是合并到"relationship display"子组）属于 UI 实现细节，由 tasks 阶段决定。建议放在 `better cluster display` 之后、`brief mode` 之前（语义上"裁剪连线"接近"聚类显示"）。

---

## 与项目内现有 toggle 的对齐表

| Toggle | state.filter 字段 | localStorage key | toggle 函数 | Payload 字段 |
|--------|------------------|------------------|-------------|--------------|
| Show Module Cluster | `showModule` | `show_module_cluster` | `toggleShowModule` | `show_module` |
| Better Cluster Display | `betterClusterDisplay` | `better_cluster_display` | `toggleBetterClusterDisplay` | `better_cluster_display` |
| Brief Mode | `brief` | `brief_mode` | `toggleBrief` | `brief` |
| Pydantic Resolve Meta | `pydanticResolveMetaEnabled`* | `pydantic_resolve_meta` | `togglePydanticResolveMeta` | `show_pydantic_resolve_meta` |
| **Hide Reverse Relationships**（本期） | **`hideReverseRelationships`** | **`hide_reverse_relationships`** | **`toggleHideReverseRelationships`** | **`hide_reverse_relationships`** |

*`pydanticResolveMetaEnabled` 在 `state.modeControl` 而非 `state.filter`，因为它影响"是否生成 Pydantic resolve 元数据"而非"如何渲染图"。本期 Pure FK 模式属于"如何渲染图"范畴，归 `state.filter`，与 cluster display / brief mode 同侧。

---

## 不变量

1. **URL 不含状态**：toggle 函数不修改 URL 参数（spec FR-012）；分享 URL 时接收方按自己 localStorage 偏好渲染。
2. **不破坏现有 toggle**：Pure FK 与 cluster display / brief mode / show fields / pydantic resolve meta 等正交（spec FR-013）——各 toggle 独立写入 localStorage、独立透传到请求体、后端独立处理。
3. **localStorage 不可用降级**：`loadToggleState` 与 `localStorage.setItem` 的 try/catch 已覆盖隐私模式、配额满、JSON 解析失败等场景（spec FR-011 / Story 2 验收场景 4-5）。
4. **勾选即生效**：`toggleHideReverseRelationships` 调用 `onGenerate()` 触发 ER 图重新生成（spec FR-003），与现有 toggle 一致——不需要用户额外点击"应用"或"刷新"。
