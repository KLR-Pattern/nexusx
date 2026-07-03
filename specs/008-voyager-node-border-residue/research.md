# Phase 0 — 研究与决策：Voyager 节点高亮边框残留修复

**功能**：[spec.md](./spec.md) · **计划**：[plan.md](./plan.md)

**调研范围**：spec 中无 NEEDS CLARIFICATION 残留（已在 `/speckit-clarify` 阶段确认无关键歧义）；本文件聚焦三个**实现层面**的决策——修复位置、还原语义、与 graphviz.svg.js 既有体系的协作。同时完整记录代码现状与根因分析，作为 plan 阶段的事实基础。

---

## 现状核对（基于代码 grep 结果）

在确定决策前，先核实 spec 描述与代码现实一致：

### 高亮写入路径

`graph-ui.js::highlightSchemaBanner(node)`（约第 126-142 行）做了两件事：

1. 找到节点的两个 polygon：
   - `outerFrame = polygons[0]`（节点最外层框）
   - `titleBg = polygons[1]`（标题栏背景）
2. 对两个 polygon 直接用 `setAttribute` 改 SVG 属性：
   - `outerFrame.stroke = HIGHLIGHT_COLOR`（#FF8C00）
   - `outerFrame.stroke-width = HIGHLIGHT_STROKE_WIDTH`（"3.0"）
   - `titleBg.fill = HIGHLIGHT_COLOR`
   - `titleBg.stroke = HIGHLIGHT_COLOR`
3. 通过 `_saveOriginalAttributes(element)` 把原值存到 DOM attribute：
   - `data-original-stroke`（来自 `getAttribute("stroke")`）
   - `data-original-stroke-width`（来自 `getAttribute("stroke-width")` 或默认 "1"）
   - `data-original-fill`（来自 `getAttribute("fill")`）

### 高亮清除路径

`graph-ui.js::clearSchemaBanners()`（约第 144-156 行）：

```javascript
clearSchemaBanners() {
  if (this.gv) {
    this.gv.highlight()           // 无参数 → 进入 graphviz.svg.js restoreElement 路径
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

只清除了 `data-original-*` DOM 属性，**没有把保存的原值写回 SVG attribute**。

### graphviz.svg.js 的颜色管理体系

`graphviz.svg.js::setupNodesEdges`（约第 143-185 行）在初始化时对每个形状 polygon 保存原色到 **jQuery `.data("graphviz.svg.color")`**：

```javascript
$this.data("graphviz.svg.color", {
  fill: $this.attr("fill"),
  stroke: $this.attr("stroke"),
})
```

注意：**只保存了 fill 与 stroke，没保存 stroke-width**。

`graphviz.svg.js::restoreElement($el)`（第 477-480 行）：

```javascript
GraphvizSvg.prototype.restoreElement = function ($el) {
  this._restoreElementColors($el.find(GraphvizSvg.ALL_COLOR_ELEMENTS), 1)
}
```

第二个参数 `setStrokeWidth = 1` 硬编码 stroke-width 为 1。

`graphviz.svg.js::_restoreElementColors`（第 415-435 行）：

```javascript
var color = $this.data("graphviz.svg.color")
if (color) {
  if (color.fill && color.fill != "none") {
    $this.attr("fill", color.fill)
  }
  if (color.stroke && color.stroke != "none") {
    $this.attr("stroke", color.stroke)
  }
  if (setStrokeWidth !== undefined) {
    $this.attr("stroke-width", setStrokeWidth)   // 硬编码 1
  }
}
```

### 两套数据源不互通

`graph-ui.js` 用 DOM attribute（`data-original-*`）存原值；`graphviz.svg.js` 用 jQuery `.data("graphviz.svg.color")` 存原值。**两套数据源完全独立**，互相不知道对方的存在。

### 残留根源

当用户切换节点触发 `clearSchemaBanners`：

1. `gv.highlight()` 无参数 → 所有元素走 `restoreElement` 路径
2. 对 outerFrame polygon：
   - graphviz.svg.js 从 jQuery data 读出初始化时的原 fill / stroke，写回 SVG attribute（**stroke 颜色应该被还原回原值**）
   - 但 stroke-width 被硬编码为 1（**即使原 stroke-width 不是 1，也被强制改成 1**）
3. graph-ui.js 然后清除 `data-original-*` 属性，**不还原 stroke / stroke-width / fill**

理论上 stroke 颜色应该被还原回原色（graphviz.svg.js 的 restoreElement 处理了）；但用户报告有"淡淡橙色"残留——可能的具体表现：

- **表现 A（stroke-width 错配）**：原 stroke-width 不是 1（可能是 0 或 0.5），高亮时被改成 3.0，清除时被硬编码回 1——比原值粗，原本几乎不可见的描边变得可见，残留视觉感
- **表现 B（stroke 未还原）**：某些 polygon 在 graphviz.svg.js 初始化时未被 `setupNodesEdges` 处理（如 cluster 内部 polygon、动态插入的元素），jQuery data 上没有快照，`_restoreElementColors` 第 423 行 `if (color)` 跳过——stroke 留着 #FF8C00
- **表现 C（hitbox 干扰）**：`_restoreElementColors` 第 419 行跳过 `data-graphviz-hitbox="true"` 元素——若 hitbox polygon 与 outerFrame 视觉重叠，可能误判为残留

不论哪种具体表现，**核心问题是 graph-ui.js 自己保存了原值但没用来还原**，依赖 graphviz.svg.js 的还原路径又不可靠（数据源不互通、stroke-width 硬编码）。

**结论**：spec 的根因判断准确，决策方向明确——让 graph-ui.js 兜底用自己的 `data-original-*` 还原。

---

## 决策 1：修复位置——graph-ui.js vs graphviz.svg.js

**Decision**：**在 `graph-ui.js::clearSchemaBanners` 内追加兜底还原逻辑**。不改 `graphviz.svg.js`。

**Rationale**：
- **`graph-ui.js` 是问题源头**——`highlightSchemaBanner` 用 `setAttribute` 改了 SVG 属性、用 `_saveOriginalAttributes` 把原值存到了 DOM attribute，自然应该由它在清除时还原。修复责任落在写入侧。
- **`graphviz.svg.js` 是 vendored 第三方库**（虽然名字像项目内文件，但它是基于 jquery.graphviz.svg 的修改版本），改它需要更谨慎地评估对其他调用方的影响。本期修复不应扩大改动面。
- **数据源归属**：`data-original-*` 是 graph-ui.js 自己的私有数据，graphviz.svg.js 不消费它——清除时由 graph-ui.js 兜底消费，是最自然的归属。
- **修复面最小**：单文件、单函数追加 ~10 行，无 API 变更、无回归风险。

**Alternatives considered**：
- **A. 改 graphviz.svg.js 的 `_restoreElementColors`，让它也保存并还原 stroke-width**：被否——(a) 改 vendored 库的代价高；(b) graphviz.svg.js 的初始化时已丢失原 stroke-width 信息（只存了 fill / stroke），需要改 `setupNodesEdges` 同时改 `_restoreElementColors`，两处协调；(c) 不解决"graph-ui.js 改的值 graphviz.svg.js 不知道"的根本问题。
- **B. 让 graph-ui.js 调 graphviz.svg.js 的 `colorElement` / `restoreElement`，统一用 jQuery data 管理**：被否——(a) graphviz.svg.js 的 colorTransformer API 是为 dim/highlight 视觉效果设计的，不适合"还原到完全原值"；(b) 改用 graphviz.svg.js 的管理体系要重写 `highlightSchemaBanner`，改动面比"加兜底"大得多。
- **C. 用 CSS class 替代 inline setAttribute**：被否——(a) SVG 元素的 stroke / stroke-width 用 CSS class 控制需要 `class` 选择器与 `!important` 配合，与项目现有 inline 属性模式不一致；(b) CSS class 切换的优先级与 Graphviz 内联样式有冲突风险。

---

## 决策 2：还原语义——基于原值 vs 涂改回固定颜色

**Decision**：**基于 `data-original-*` 保存的原值还原**（spec FR-002 已固化此语义）。绝不涂改回某个固定颜色。

**Rationale**：
- **正确性**：原值是节点未被高亮时的真实属性，写回它 = 像素级一致。涂改回固定颜色（如 "transparent" 或某个猜测的浅灰）只在不同 schema 主题色下都会失败。
- **主题色兼容**：spec 假设区块提"主题色变更"边界——如果未来引入深色模式或主题切换，基于原值还原天然兼容；涂改回固定颜色需要为每个主题维护映射。
- **未来扩展**：spec FR-009 已固化"不改变现有高亮规则"——基于原值还原保证不会引入任何新的视觉副作用。

**实现要点**：
- `_saveOriginalAttributes` 已经把原值存到 DOM attribute（`data-original-stroke` / `data-original-stroke-width` / `data-original-fill`），数据已就绪
- `clearSchemaBanners` 在清除 `data-original-*` 属性前，先把它们的值写回对应的 SVG attribute
- 写回顺序与删除顺序：先写回，后删除（避免读不到值）
- 使用 `getAttribute` / `setAttribute`，与 `highlightSchemaBanner` 的写入路径对称

**Alternatives considered**：
- **A. 涂改回 "transparent" 或固定浅灰**：被否——见 Rationale。
- **B. 用 CSS class + class 切换**：被否——见决策 1 Alternative C。
- **C. 重做整套高亮管理（jQuery data + 事件总线）**：被否——spec FR-009 / FR-010 明确"不改变现有高亮规则、不影响其他渲染管线"，本期是 bug 修复，不是重构。

---

## 决策 3：与 graphviz.svg.js 既有体系的协作模式

**Decision**：**双层兜底**——`clearSchemaBanners` 先调 `gv.highlight()`（保留现有 graphviz.svg.js 的 restoreElement 路径，处理邻居节点、边的 dim 还原），**之后**再追加自己的 `data-original-*` 还原（兜底 outerFrame / titleBg 这两个 graph-ui.js 直接改过的元素）。两层独立、互不依赖。

**Rationale**：
- **保留现有路径**：`gv.highlight()` 还负责"清除选中态、把 dim 过的元素还原"等更广泛的高亮管理功能，不能因为修 outerFrame 残留就跳过它。
- **顺序重要**：先调 `gv.highlight()` 让 graphviz.svg.js 先做它的清理，然后 graph-ui.js 兜底——保证 graph-ui.js 的还原是"最后写入者"，覆盖任何 graphviz.svg.js 留下的不一致。
- **幂等性**：即使 graphviz.svg.js 已经把 stroke 还原回原值，graph-ui.js 再写一次同样的原值也无副作用（幂等）；如果 graphviz.svg.js 漏还原（如 stroke-width 硬编码为 1），graph-ui.js 的兜底覆盖正确值。
- **不互相调用**：graph-ui.js 不调 graphviz.svg.js 的私有方法（如 `_restoreElementColors`），graphviz.svg.js 也不知道 graph-ui.js 的存在——保持模块边界清晰。

**Alternatives considered**：
- **A. 移除 `gv.highlight()` 调用，完全用 graph-ui.js 自己还原**：被否——`gv.highlight()` 还原的不只是 outerFrame / titleBg，还有邻居节点、边的 dim 效果；移除会破坏现有的"切换节点时邻居高亮清除"语义。
- **B. 让 graphviz.svg.js 知道 graph-ui.js 的 `data-original-*`，统一管理**：被否——见决策 1，需要改 vendored 库、影响面大。
- **C. 在 highlightSchemaBanner 写入时同步通知 graphviz.svg.js**：被否——增加耦合，且 graphviz.svg.js 没有"接受外部原值"的 API。

---

## 决策 4：测试覆盖方式

**Decision**：沿用项目惯例（无前端自动化测试基线），通过 `quickstart.md` 步骤化人工验证。

**Rationale**：
- **项目惯例**：spec 005 / 006 / 007 都是前端 UI 修改、无前端自动化测试，本期保持一致。
- **不引入测试基础设施**：避免破坏 Constitution 潜在的"不引入前端构建/测试工具链"约束。
- **人工验证足够**：本特性是视觉修复，肉眼可观察、易判断（残留消失/未消失），无需复杂断言。

**quickstart 覆盖矩阵**：

| 验收场景 | quickstart 步骤 | 验证方式 |
|---------|----------------|---------|
| 双击→单击切换无残留 | §2.2 | 截屏对比 A 与第三方 C 的外框 |
| 双击→双击切换无残留 | §2.3 | 截屏对比 |
| 单击→单击切换无残留 | §2.4 | 截屏对比 |
| 切换 schema 无残留 | §2.5 | 视觉检查 |
| 切换 ER-diagram ↔ voyager 模式 | §2.6 | 视觉检查 |
| 自引用节点高亮/清除 | §2.7 | 视觉检查 |
| 长会话 20+ 次切换无累积 | §2.8 | 截屏对比 |
| 刷新页面后画布干净 | §2.9 | 视觉检查 |
| 切换显示选项 toggle 无残留 | §2.10 | 视觉检查 |

**Alternatives considered**：
- **A. 引入 Playwright/Cypress 做前端 e2e 测试**：被否——见 Rationale。
- **B. 写 jest 单元测试 `_saveOriginalAttributes` / `clearSchemaBanners` 函数**：被否——这两个函数是 GraphUI 类的方法、依赖 jQuery 与 DOM 环境，单独抽出来测试需要 mock 整套 graphviz.svg.js 环境，性价比低。
