# 契约：`clearSchemaBanners` 兜底还原逻辑

**功能**：[spec.md](../spec.md) · **数据模型**：[data-model.md](../data-model.md)

**位置**：`src/nexusx/voyager/web/graph-ui.js::GraphUI.clearSchemaBanners`（约第 144-156 行）

---

## 现状（修改前）

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

**问题**：清除 `data-original-*` 之前未把它们保存的原值写回 SVG attribute。`gv.highlight()` 走 graphviz.svg.js 的 `restoreElement` 路径，但后者：(a) 用 jQuery `.data("graphviz.svg.color")` 而非 DOM attribute，数据源不互通；(b) 硬编码 `stroke-width=1`；(c) 对未被 `setupNodesEdges` 处理的元素跳过还原。结果：被 `highlightSchemaBanner` 直接改过的 outerFrame 与 titleBg 的 stroke / stroke-width / fill 没有被可靠还原，留下橙色描边残留。

---

## 修改后

```javascript
clearSchemaBanners() {
  if (this.gv) {
    this.gv.highlight()
  }
  this._lastHighlight = null

  const allPolygons = document.querySelectorAll("polygon[data-original-stroke]")
  allPolygons.forEach((polygon) => {
    // Spec 008 — Restore SVG attributes from data-original-* before clearing.
    // gv.highlight() above goes through graphviz.svg.js::restoreElement which
    // uses jQuery .data("graphviz.svg.color") (init-time snapshot of
    // fill+stroke, missing stroke-width, hardcoded to 1 on restore). That
    // data source is independent from graph-ui.js's DOM attribute store
    // (data-original-*). Writing back from data-original-* is the reliable
    // fallback that guarantees pixel-perfect restoration for elements
    // highlightSchemaBanner directly modified.
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

---

## 不变量

1. **写入与清除路径对称**：`highlightSchemaBanner` 写入 stroke / stroke-width / fill 与 `data-original-*`；`clearSchemaBanners` 先读 `data-original-*` 写回 SVG attribute，再清除 `data-original-*`。两者读写完全对称。
2. **顺序保证**：兜底还原必须发生在 `gv.highlight()` 之后（让 graphviz.svg.js 先做它的清理）、`removeAttribute` 之前（保证能读到原值）。修改后的代码遵守此顺序。
3. **幂等性**：多次连续调用 `clearSchemaBanners` 安全——第二次调用时 `querySelectorAll("polygon[data-original-stroke]")` 返回空集（属性已被第一次调用清除），兜底循环与 removeAttribute 都不执行。
4. **不破坏 graphviz.svg.js 既有体系**：本特性不动 graphviz.svg.js 任何代码；`gv.highlight()` 调用保留，graphviz.svg.js 继续负责邻居节点、边的 dim/highlight 管理。
5. **不影响 hitbox 元素**：`_saveOriginalAttributes` 不在 hitbox 元素上写入 `data-original-*`，兜底还原的 `querySelectorAll` 不命中 hitbox。
6. **不引入新 API**：`clearSchemaBanners` 签名不变、返回值不变、副作用只增加"写回 SVG attribute"——对外部调用方透明。

---

## 关键场景行为表

| 场景 | `gv.highlight()` 行为 | graph-ui.js 兜底行为 | 最终结果 |
|------|----------------------|---------------------|---------|
| 双击节点 A → 单击 B | 还原所有节点的 jQuery-managed fill/stroke；A 的 outerFrame.stroke-width 被硬编码为 1 | 把 A 的 outerFrame.stroke/stroke-width/fill 写回原值（基于 `data-original-*`） | A 完全还原回未高亮状态 |
| 双击节点 A → 双击 B | 同上 | 同上 | A 完全还原 |
| 单击 A → 单击 B（shallow 高亮） | 同上 | 同上 | A 完全还原 |
| 切换 schema | 旧 SVG 被整体替换、新 SVG 上无 `data-original-*` | `querySelectorAll` 返回空集、循环不执行 | 新画布默认状态干净 |
| 切换 ER-diagram ↔ voyager 模式 | 同上 | 同上 | 新画布默认状态干净 |
| 浏览器刷新 | 整个 SVG 重新生成 | 同上 | 默认状态干净 |
| 自引用节点（`Tree`）双击 | 与普通节点一致 | 与普通节点一致 | 完全还原 |
| 快速连续点击 A → B（1 帧内） | 多次调用、第二次起 jQuery data 已稳定 | 多次调用、第二次起 `querySelectorAll` 空集 | 最终态：B 高亮、A 完全还原 |

---

## 与其他模块的契约

| 模块 | 契约 | 修复后是否变更 |
|------|------|---------------|
| `graphviz.svg.js::highlight()` | 调用方负责传 `$nodesEdges` 参数或不传（全清）；返回值无 | 不变 |
| `graphviz.svg.js::restoreElement` | 内部细节，不被外部直接调用 | 不变 |
| `graph-ui.js::highlightSchemaBanner` | 写入 stroke / stroke-width / fill 与 `data-original-*` | 不变 |
| `graph-ui.js::_saveOriginalAttributes` | 在元素首次高亮时写入 `data-original-*`（幂等保护） | 不变 |
| `vue-main.js` 调用 `clearSchemaBanners` 的所有路径 | 公共方法、无参数、无返回值 | 不变 |
| Graphviz 后端 dot 输出 | 输出 polygon stroke / stroke-width / fill 属性 | 不变 |

---

## 不在 scope 内的修改

明确**不**做的修改（避免 scope 蔓延）：

- ❌ 改 `_saveOriginalAttributes` 的"原 stroke-width 默认 1"逻辑（不是 bug 源头）
- ❌ 改 `highlightSchemaBanner` 的写入逻辑（写入正确，问题在清除）
- ❌ 改 `graphviz.svg.js` 任何代码（vendored 库，影响面大）
- ❌ 改 `GraphUI.HIGHLIGHT_COLOR` 或 `GraphUI.HIGHLIGHT_STROKE_WIDTH` 常量（不改色值）
- ❌ 引入 CSS class 替代 inline 属性（项目模式不一致）
- ❌ 重构整个高亮管理体系（spec FR-009 / FR-010 约束）
- ❌ 引入前端测试基础设施（spec 假设区块约束）
