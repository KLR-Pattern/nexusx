# Phase 1 — 数据模型：Voyager 节点高亮边框残留修复

**功能**：[spec.md](./spec.md) · **计划**：[plan.md](./plan.md) · **调研**：[research.md](./research.md)

---

## 1. DOM 属性数据流总览

```text
                           节点 SVG <g class="node">
                                    │
                                    ├── <polygon> outerFrame    (节点最外层框)
                                    │       │
                                    │       │  原属性（Graphviz 输出）:
                                    │       │    stroke         = "<原色>"
                                    │       │    stroke-width   = "<原宽>"
                                    │       │    fill           = "<原填充>"
                                    │       │
                                    │       │  graphviz.svg.js 初始化时:
                                    │       │    jQuery .data("graphviz.svg.color")
                                    │       │      = { fill, stroke }   (无 stroke-width)
                                    │       │
                                    │       │  ───  用户双击节点  ───►
                                    │       │
                                    │       │  highlightSchemaBanner():
                                    │       │    setAttribute("stroke", "#FF8C00")
                                    │       │    setAttribute("stroke-width", "3.0")
                                    │       │    setAttribute("data-original-stroke", <原色>)
                                    │       │    setAttribute("data-original-stroke-width", <原宽>)
                                    │       │    setAttribute("data-original-fill", <原填充>)
                                    │       │
                                    │       │  ───  用户切换其他节点  ───►
                                    │       │
                                    │       │  clearSchemaBanners()  ←── 修复后:
                                    │       │    1. gv.highlight()  (无参数)
                                    │       │       └─ graphviz.svg.js restoreElement
                                    │       │            └─ _restoreElementColors:
                                    │       │                 fill ← jQuery .data.fill   ✓ 还原
                                    │       │                 stroke ← jQuery .data.stroke ✓ 还原
                                    │       │                 stroke-width ← 1   ✗ 硬编码（非原值）
                                    │       │
                                    │       │    2.  ◀── 新增 兜底还原 (graph-ui.js):
                                    │       │       for each polygon[data-original-stroke]:
                                    │       │         setAttribute("stroke", <data-original-stroke>)
                                    │       │         setAttribute("stroke-width", <data-original-stroke-width>)
                                    │       │         setAttribute("fill", <data-original-fill>)
                                    │       │
                                    │       │    3.  清除 data-original-* DOM 属性
                                    │       │
                                    └── <polygon> titleBg   (标题栏背景)
                                            │
                                            └─ 同样流程（fill / stroke 被改 / 被还原）
```

**关键不变量**：
- `data-original-*` 属性的写入由 `_saveOriginalAttributes` 在节点首次高亮时完成（不重复写入——`if (!element.hasAttribute("data-original-stroke"))` 保护）。
- 兜底还原必须发生在 `gv.highlight()` 之后、`removeAttribute` 之前——保证 graph-ui.js 的还原是"最后写入者"，且能读到 `data-original-*` 值。
- 还原后 `data-original-*` 属性立即清除——保证下次高亮同一节点时 `_saveOriginalAttributes` 能重新写入"真正的原值"，而不是上一次高亮时已被改过的值（虽然此时已还原，但移除属性让状态干净）。

---

## 2. graph-ui.js 修改前后对照

### 2.1 `clearSchemaBanners` 当前实现（约第 144-156 行）

```javascript
clearSchemaBanners() {
  if (this.gv) {
    this.gv.highlight()
  }
  this._lastHighlight = null

  const allPolygons = document.querySelectorAll("polygon[data-original-stroke]")
  allPolygons.forEach((polygon) => {
    polygon.removeAttribute("data-original-stroke")
    polygon.removeAttribute("data-original-stroke-width")
    polygon.removeAttribute("data-original-fill")
  })
}
```

### 2.2 修复后的 `clearSchemaBanners`

```javascript
clearSchemaBanners() {
  if (this.gv) {
    this.gv.highlight()
  }
  this._lastHighlight = null

  const allPolygons = document.querySelectorAll("polygon[data-original-stroke]")
  allPolygons.forEach((polygon) => {
    // Spec 008 — Restore SVG attributes from data-original-* before clearing.
    // graphviz.svg.js::restoreElement uses jQuery .data("graphviz.svg.color")
    // (init-time snapshot of fill+stroke, missing stroke-width) — independent
    // from graph-ui.js's DOM attribute store. gv.highlight() above may not
    // restore stroke-width (hardcoded to 1) and may skip elements without
    // jQuery data. Writing back from data-original-* is the reliable fallback.
    const origStroke = polygon.getAttribute("data-original-stroke")
    const origStrokeWidth = polygon.getAttribute("data-original-stroke-width")
    const origFill = polygon.getAttribute("data-original-fill")
    if (origStroke !== null) {
      polygon.setAttribute("stroke", origStroke)
    }
    if (origStrokeWidth !== null) {
      polygon.setAttribute("stroke-width", origStrokeWidth)
    }
    if (origFill !== null) {
      polygon.setAttribute("fill", origFill)
    }
    polygon.removeAttribute("data-original-stroke")
    polygon.removeAttribute("data-original-stroke-width")
    polygon.removeAttribute("data-original-fill")
  })
}
```

**改动范围**：在原有 `removeAttribute` 调用前，新增 ~12 行兜底还原（含注释）。

### 2.3 `_saveOriginalAttributes` 不变

```javascript
_saveOriginalAttributes(element) {
  if (!element.hasAttribute("data-original-stroke")) {
    element.setAttribute("data-original-stroke", element.getAttribute("stroke") || "")
    element.setAttribute(
      "data-original-stroke-width",
      element.getAttribute("stroke-width") || "1"
    )
    element.setAttribute("data-original-fill", element.getAttribute("fill") || "")
  }
}
```

**注**：`_saveOriginalAttributes` 的"原 stroke-width 默认 1"是个潜在隐患——如果原 stroke-width 不存在，会写入默认 "1"；而 Graphviz 输出的 polygon 通常有 stroke-width，所以这个 default 几乎不触发。本期不修这个 helper（不是 bug 源头）。

### 2.4 `highlightSchemaBanner` 不变

`highlightSchemaBanner` 仍按现状写入 stroke / stroke-width / fill 与 `data-original-*`。本特性只修清除路径，不改写入路径。

---

## 3. 调用 clearSchemaBanners 的所有路径

`clearSchemaBanners` 是 GraphUI 类的公共方法，被以下路径调用（grep 结果）：

| 调用点 | 触发场景 | 修复后行为 |
|--------|---------|-----------|
| `_applyNodeHighlight(node)` (graph-ui.js) | 单击节点切换选中（shallow 高亮）| ✓ 旧节点 outerFrame / titleBg 完全还原 |
| `clearHighlight()` (graph-ui.js) | 用户主动清除高亮 | ✓ 还原 |
| `onSchemaClick(id)` (vue-main.js / graph-ui.js click handler) | 单击节点触发 | ✓ 还原 |
| `onReset` (vue-main.js:401) | 用户点 "Reset" 按钮 | ✓ 还原 |
| `renderErDiagram` 完成后（spec 007 后） | 主图重新渲染 | ✓ 还原（数据属性已存在的旧元素） |

修复后所有调用路径都受益——一处改动、所有清除场景生效。

---

## 4. 边界情况数据行为

| 边界情况 | 数据行为 |
|---------|---------|
| 节点 SVG 元素被 Graphviz 重新生成（如切换 schema / 显示选项触发重渲染） | 旧 SVG 元素被整体替换，新 SVG 上无 `data-original-*` 属性、无 jQuery data——`clearSchemaBanners` 的 `querySelectorAll("polygon[data-original-stroke]")` 返回空集，兜底还原循环不执行。新画布默认状态干净。 |
| 极快速连续点击（A → B 在 1 帧内） | 每次 `_applyNodeHighlight` 都先调 `clearSchemaBanners`，多次连续调用幂等——第二次调用时 `data-original-*` 已被清除、`querySelectorAll` 返回空集，无副作用。 |
| 自引用关系节点（如 `Tree`） | 自环节点的 outerFrame / titleBg 与普通节点结构一致，兜底还原路径相同。 |
| `data-original-stroke` 等属性值是空字符串（原 stroke 不存在） | `_saveOriginalAttributes` 第 161 行用 `|| ""` 兜底，写入空字符串；兜底还原时 `setAttribute("stroke", "")`——SVG 视为不设该属性、回退到默认值，与原状态一致。 |
| 浏览器刷新页面 | 整个 SVG 重新生成（Graphviz 重新渲染），新 SVG 上无 `data-original-*` 属性——画布默认状态干净。 |
| 主题色变更（假设未来引入） | 兜底还原基于"原值"，不依赖任何主题色常量——主题切换后还原回该主题下的原 stroke / fill，正确。 |
| `data-graphviz-hitbox="true"` 元素（边的高亮 hit area） | `_saveOriginalAttributes` 不在 hitbox 元素上写入 `data-original-*`（hitbox 由 graphviz.svg.js 管理、`highlightSchemaBanner` 只动 outerFrame / titleBg），兜底还原循环不影响 hitbox。 |
| 节点被 dim（`gv.highlight($set)` 时未在 $set 内的节点） | dim 走 graphviz.svg.js 的 `colorElement` 路径（jQuery data 管理），不受本特性影响。本特性只兜底 `highlightSchemaBanner` 直接 setAttribute 改过的元素。 |
