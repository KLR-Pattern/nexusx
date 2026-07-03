# Phase 1 — 数据模型：Voyager Hide Reverse Relationships 连线模式

**功能**：[spec.md](./spec.md) · **计划**：[plan.md](./plan.md) · **调研**：[research.md](./research.md)

---

## 1. 数据通路总览

```text
┌──────────────────────────────────────────────────────────────────────────┐
│                              前端（浏览器）                                │
│                                                                          │
│  ┌────────────────────┐    ┌──────────────────────────────────────────┐  │
│  │ 显示选项面板        │───▶│ store.js                                │  │
│  │ [✓] Hide Reverse   │    │  state.filter.hideReverseRelationships  │  │
│  │     Relationships  │    │  toggleHideReverseRelationships(val,    │  │
│  └────────────────────┘    │    onGenerate)                          │  │
│                            │    └─▶ 写 localStorage                   │  │
│                            │    └─▶ onGenerate()                      │  │
│                            └──────────────┬───────────────────────────┘  │
│                                           │                              │
│  vue-main.js 初始化时：                    │                              │
│  loadToggleState("hide_reverse_           │                              │
│    relationships", false)                 │                              │
│                                           ▼                              │
│                            ┌──────────────────────────────────────────┐  │
│                            │ fetch POST /er-diagram                   │  │
│                            │   body: {                                │  │
│                            │     ...,                                │  │
│                            │     hide_reverse_relationships: <bool>,  │  │
│                            │   }                                      │  │
│                            └──────────────┬───────────────────────────┘  │
└───────────────────────────────────────────┼──────────────────────────────┘
                                            │ HTTP
                                            ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                              后端（FastAPI）                              │
│                                                                          │
│  create_voyager.py                                                       │
│  @router.post("/er-diagram")                                             │
│    payload: ErDiagramPayload  ◀── 新增 hide_reverse_relationships 字段   │
│                                                                          │
│  voyager_context.py                                                      │
│  get_er_diagram(payload)                                                 │
│    └─▶ ErDiagramDotBuilder(                                              │
│           er_manager,                                                    │
│           show_module=payload["show_module"],                            │
│           better_cluster_display=payload["better_cluster_display"],      │
│           show_methods=payload["show_methods"],                          │
│           hide_reverse_relationships=payload["hide_reverse_              │
│               relationships"],  ◀── 新增透传                              │
│        )                                                                 │
│                                                                          │
│  er_diagram_dot.py                                                       │
│  ErDiagramDotBuilder.__init__  ◀── 新增 hide_reverse_relationships 参数  │
│  ErDiagramDotBuilder.analysis()                                          │
│    └─▶ for entity_kls, rels in all_relationships.items():                │
│            for _rel_name, rel_info in rels.items():                      │
│                self._add_relationship_link(entity_kls, rel_info)         │
│                       │                                                  │
│                       ▼                                                  │
│  ErDiagramDotBuilder._add_relationship_link                              │
│    if not _is_model_like_target(rel_info.target_entity): return          │
│    if self.hide_reverse_relationships and                                │
│       rel_info.direction == 'ONETOMANY': return  ◀── 新增早退            │
│    # 后续逻辑不变（dedup、构造 Link、append）                              │
│                                                                          │
│  最终：self.links 只含 MANYTOONE + MANYTOMANY 方向 Link                  │
│        self.rel_name_set 仍含全部 relationship（供 Fields tab 字段渲染）   │
└──────────────────────────────────────────────────────────────────────────┘
```

**关键不变量**：
- `Link` 数据结构 shape 不变（不新增字段）。
- `SchemaNode.fields` shape 不变（Pure FK 模式只裁剪连线、不裁剪字段展示）。
- `self.rel_name_set` 在 Pure FK 模式下仍记录**全部** relationship（包括被过滤掉的 ONETOMANY），供 `_get_entity_fields` 渲染实体字段表使用——Fields tab 仍展示完整字段列表（含 ONETOMANY 方向 relationship 字段，符合 spec FR-007）。
- `self.link_set`（dedup 集合）只记录实际生成的 Link 对应键，因此 Pure FK 模式下 ONETOMANY 对应的键不入集合（与"该 Link 不存在"一致）。
- `filter_to_neighborhood`（spec 005）在 `analysis()` 之后调用、消费 `self.links`，自动继承过滤结果——子图跟随裁剪无需新增逻辑。

---

## 2. 后端数据契约扩展

### 2.1 `ErDiagramDotBuilder.__init__` 新增参数

`src/nexusx/voyager/er_diagram_dot.py` 第 87-110 行：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `hide_reverse_relationships` | `bool` | `False` | True 时 `analysis()` 内 `_add_relationship_link` 跳过 `direction == 'ONETOMANY'` 的 relationship；False 时行为与现状完全一致 |

构造函数体内新增 `self.hide_reverse_relationships = hide_reverse_relationships`。

### 2.2 `_add_relationship_link` 新增早退判定

`src/nexusx/voyager/er_diagram_dot.py` 第 199-237 行函数体，在现有 `if not _is_model_like_target(rel_info.target_entity): return` 之后、`source_name = full_class_name(entity_kls)` 之前，新增：

```python
if self.hide_reverse_relationships and rel_info.direction == 'ONETOMANY':
    return
```

**为什么用字符串字面量 `'ONETOMANY'`**：`RelationshipInfo.direction` 字段类型为 `str`（非 Enum），取值字符串由 SQLAlchemy `inspect()` 在 `loader/registry.py::_inspect_relationships` 中赋值（如 `direction="MANYTOONE"` 等，第 90 行附近的 import）。直接比较字符串与现有代码风格一致；若未来引入 Enum 可同步迁移。

### 2.3 `ErDiagramPayload`、`ErDiagramSubgraphPayload` 字段扩展

`src/nexusx/voyager/create_voyager.py`：

**`ErDiagramPayload`（第 64 行）新增字段**：

```python
class ErDiagramPayload(PydanticModel):
    # ... 现有字段
    show_module: bool = True
    better_cluster_display: bool = False
    # ... 其他
    show_methods: bool = True
    hide_reverse_relationships: bool = False   # 新增
```

**`ErDiagramSubgraphPayload`（第 72 行）新增同名字段**：

```python
class ErDiagramSubgraphPayload(PydanticModel):
    # ... 现有字段（与 ErDiagramPayload 对齐）
    show_methods: bool = True
    hide_reverse_relationships: bool = False   # 新增
```

### 2.4 `voyager_context.py` 4 处构造点透传

在 `voyager_context.py` 第 108、128、171-175、229-233 行附近的 4 处 `ErDiagramDotBuilder(...)` 构造调用，每处新增一行：

```python
hide_reverse_relationships=payload.get("hide_reverse_relationships", False),
```

**为什么用 `payload.get(...)` 而非 `payload.hide_reverse_relationships`**：与现有 `better_cluster_display=payload.get("better_cluster_display", False)` 模式一致（第 171-175 行）；同时提供默认值，对老客户端（不传该字段）向后兼容。

---

## 3. 前端状态字段扩展

### 3.1 `store.js` 新增 state 字段

`src/nexusx/voyager/web/store.js` 中 `state.filter` 对象新增字段：

```javascript
state.filter = {
  // ... 现有字段
  betterClusterDisplay: false,
  showModule: false,
  brief: false,
  // ... 其他
  hideReverseRelationships: false,   // 新增
}
```

### 3.2 `store.js` 新增 toggle 函数

紧邻现有 `toggleBetterClusterDisplay`（第 467-475 行附近）之后新增：

```javascript
/**
 * Toggle hide reverse relationships (Hide Reverse Relationships mode).
 * When enabled, only MANYTOONE and MANYTOMANY direction relationship
 * edges are rendered; ONETOMANY reverse mirrors are hidden.
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

签名、错误降级（`console.warn` 不阻塞）、`onGenerate()` 调用模式均与现有 toggle 函数逐字对齐。

### 3.3 `vue-main.js` 初始化时读取 localStorage

`src/nexusx/voyager/web/vue-main.js` 第 55-65 行附近（现有 `loadToggleState("pydantic_resolve_meta", ...)` 之后）新增：

```javascript
store.state.filter.hideReverseRelationships = loadToggleState("hide_reverse_relationships", false)
```

### 3.4 `vue-main.js` 调用 `fetch /er-diagram` 时透传字段

在 `vue-main.js` 第 189 行附近（现有 `fetch("er-diagram", { body: JSON.stringify({...}) })`），请求体新增字段：

```javascript
const res = await fetch("er-diagram", {
  // ...
  body: JSON.stringify({
    // ... 现有字段
    show_methods: store.state.modeControl.showMethodsEnabled,
    hide_reverse_relationships: store.state.filter.hideReverseRelationships,   // 新增
  }),
})
```

`/er-diagram-subgraph` 请求体同理（如果 vue-main.js 直接构造；若由 `related-entities-display.js` 构造则在该组件内透传）。

### 3.5 显示选项面板新增 checkbox

`src/nexusx/voyager/web/component/schema-code-display.js`（或对应显示选项面板所在组件）的模板，紧邻现有 `better cluster display` / `brief mode` toggle 之后新增 Quasar `q-checkbox`：

```html
<q-checkbox
  :model-value="store.state.filter.hideReverseRelationships"
  @update:model-value="(val) => store.toggleHideReverseRelationships(val, onGenerate)"
  label="Hide Reverse Relationships"
/>
```

具体位置（顺序、分组）属于 UI 实现细节，本数据模型不固化；只需满足 spec FR-001"与现有显示选项位于同一交互区域"。

---

## 4. 不受 Pure FK 模式影响的数据通路

以下数据通路在 Pure FK 模式开启/关闭时**完全不变**：

- **`/source`（源码）、`/vscode-link`（IDE 跳转）、`/docstring`（spec 006）**：与 ER 图渲染独立，不受 Pure FK 影响。
- **`SchemaNode.fields`（字段表）**：`_get_entity_fields` 仍消费 `self.rel_name_set`（记录全部 relationship 名），Fields tab 仍展示完整字段列表。
- **`Web/schema`（schema 元数据）端点**：不经 `ErDiagramDotBuilder` 流程，不受影响。
- **`/use-case-diagram` 等其他模式端点**：Pure FK 仅作用于 ER-diagram 模式（spec 假设区块固化），其他模式不传 `hide_reverse_relationships` 字段。

---

## 5. 边界情况数据契约

| 边界情况 | 数据行为 |
|---------|---------|
| 老客户端不传 `hide_reverse_relationships` 字段 | Pydantic 默认 `False`，行为与现状一致 |
| 字段值为非 bool（如 `"true"` 字符串） | Pydantic 自动转换（与现有 bool 字段一致）；转换失败返回 422 |
| `rel_info.direction` 为非常规值（如 None） | 不匹配 `'ONETOMANY'`，按"MANYTOONE/MANYTOMANY 同等保留"处理（不会被过滤） |
| `localStorage.hide_reverse_relationships` 为非 JSON 字符串 | `loadToggleState` 已有 try/catch 降级（spec 边界情况已覆盖），默认 false |
| 自引用双向关系（`Tree.parent` ↔ `Tree.children`） | `parent` MANYTOONE 保留、`children` ONETOMANY 隐藏；自环呈现为单条 MANYTOONE 自连线 |
| M2M 关系（`secondary="..."`） | SQLAlchemy `direction` 为 `MANYTOMANY`，不匹配 `'ONETOMANY'`，双方向都保留 |
| 单向 ONETOMANY（无 `back_populates`） | 仍按 `direction == 'ONETOMANY'` 隐藏，符合 spec 验收场景 5 |
