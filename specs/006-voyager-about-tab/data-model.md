# Phase 1 — 数据模型：Voyager About Tab & 侧边栏宽度放宽

**功能**：[spec.md](./spec.md) · **计划**：[plan.md](./plan.md) · **调研**：[research.md](./research.md)

---

## 1. 数据通路总览

```text
Python 类对象 ──.__doc__─> VoyagerContext.get_docstring(schema_name)
                              │
                              ▼
                        POST /docstring  (HTTP)
                              │
                              ▼
                <about-display> 组件 fetch
                              │
                              ▼
        marked.parse → DOMPurify.sanitize → mermaid.run
                              │
                              ▼
                   About tab 内容 DOM
```

不修改 `SchemaNode` 等已序列化的 dataclass；不修改 `/er-diagram`、`/er-diagram-subgraph`、`/source`、`/vscode-link` 任何现有响应 shape。

---

## 2. 后端数据契约

### 2.1 新增方法：`VoyagerContext.get_docstring(schema_name: str) -> dict`

| 字段 | 类型 | 说明 |
|------|------|------|
| `docstring` | `str` | 类 `__doc__` 属性的原始字符串；若为 `None` 返回空串 `""`。仅在成功路径下出现。 |
| `error` | `str` | 失败时出现，与现有 `get_source_code` 的错误信息格式一致（`"Invalid schema name format."` / `"Module not found: ..."` / `"Class not found: ..."` / `"Internal error: ..."`）。 |

**实现要点**：复用 `self._resolve_object(schema_name)` 拿到类对象；`obj.__doc__ or ""` 即返回值。错误处理与 `get_source_code` 对称（4 个 except 分支）。

### 2.2 新增端点：`POST /docstring`

请求体：`{"schema_name": "<module.Class>"}`（与 `/source` 完全一致）

响应：
- 成功：`200 OK` · `{"docstring": "..."}`
- schema 名格式非法：`400 Bad Request` · `{"error": "Invalid schema name format."}`
- module/class 未找到：`404 Not Found` · `{"error": "..."}`
- 其他异常：`400 Bad Request` · `{"error": "Internal error: ..."}`

状态码映射规则与现有 `/source` 端点（`create_voyager.py:184-189`）**逐字对齐**——便于前端复用同一份错误处理代码。

### 2.3 不修改的现有 dataclass

| 类 | 文件 | 是否改动 | 理由 |
|----|------|---------|------|
| `SchemaNode` | `src/nexusx/voyager/type.py:57` | 否 | 决策 2（research.md）——避免 er-diagram 初始 payload 膨胀 |
| `FieldInfo` | `src/nexusx/voyager/type.py:14` | 否 | 字段级 `desc` 仍走 Fields tab 路径，与 docstring 解耦 |
| `Link` | `src/nexusx/voyager/type.py:82` | 否 | 边数据与本期无关 |

---

## 3. 前端 store 状态变更

### 3.1 `store.js` 现有相关字段（**不改**）

```js
state.schemaDetail = {
  schemaCodeName: "",     // 当前侧边栏指向的实体全限定名
}
state.rightDrawer = {
  drawer: false,
  width: 300,             // 当前拖拽设定的像素宽度
  previousWidth: ...
}
```

这些字段本期**完全不动**——`schemaDetail.schemaCodeName` 已足以驱动 `<about-display>` 内部 fetch；`rightDrawer.width` 仅是用户设定的目标值，clamp 由 vue-main.js 在事件回调中处理（见 §4）。

### 3.2 `<about-display>` 组件内部状态（**新增**，不进全局 store）

| ref | 类型 | 初始值 | 含义 |
|-----|------|--------|------|
| `docstring` | `string` | `""` | 从 `/docstring` 拿到的原始 docstring |
| `loading` | `boolean` | `false` | 是否正在请求 |
| `error` | `string \| null` | `null` | 失败时的错误文案；`null` 表示无错误 |
| `mermaidErrors` | `Array<{index, message, source}>` | `[]` | 单块 mermaid 渲染失败的诊断信息（用于在 UI 中按块展示错误+折叠源码） |

**为何不进全局 store**：这些是 `<about-display>` 私有的瞬时态，与 spec 005 的 `<related-entities-display>` 模式一致（后者也是组件内自管 state），保持对称。

### 3.3 拖拽 clamp 派生量（**新增**，不持久化）

`vue-main.js` 的 `startDragDrawer` 与新增的 `window.resize` 监听器内部使用：

```js
const MIN_WIDTH = 300                                  // 沿用现有常量
const maxWidth  = () => Math.floor(window.innerWidth * 2 / 3)
```

`maxWidth` 是函数（实时计算），**不**写入 store、**不**持久化到 localStorage；每次拖拽/resize 调用时现取。

---

## 4. 实体验证规则

### 4.1 docstring 字符串

- **来源**：Python 类 `__doc__` 属性的原始字符串（含前导/尾随空白、含可能的 ```mermaid 围栏块）。
- **不修剪**：后端返回原始 docstring，**不**做 `inspect.cleandoc` 或 lstrip；前端在渲染前可统一做一次 `cleandoc`-风格的缩进规整（用 `marked` 默认处理即可，无需自定义）。
- **长度无上限**：极长 docstring（数千行）依赖外层容器 `overflow: auto` 滚动（spec 边界情况已约定）。

### 4.2 schema_name 输入

- 格式：必须是 `<module.path>.<ClassName>`，至少包含一个 `.`；与现有 `/source`、`/vscode-link` 的输入约束完全一致。
- 不合法时返回 `400` + `Invalid schema name format.`，与现有端点行为对齐。

### 4.3 拖拽宽度

- 数值范围：`[300, floor(window.innerWidth × 2/3)]` 像素，闭区间。
- 取整：必须为整数像素（避免亚像素渲染抖动）。
- 持久化策略：本期**不**显式持久化（store 内存中即可）；若现有 `rightDrawer.width` 已有 localStorage 持久化机制则保留，但每次 hydrate 时必须 clamp 到当前 `floor(innerWidth × 2/3)`。

---

## 5. 状态机（无）

本期无显式状态机。docstring 渲染是"取数据 → 单向渲染"的纯函数式管线；侧边栏宽度是用户拖拽驱动的连续数值。Mermaid **图内容**中可能包含状态机（如 `stateDiagram-v2`），但那是图本身的内容，不是本功能的状态机。
