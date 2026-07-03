# 契约：ErDiagramPayload / ErDiagramSubgraphPayload 字段扩展

**功能**：[spec.md](../spec.md) · **数据模型**：[data-model.md](../data-model.md) · **过滤契约**：[hide-reverse-filter.md](./hide-reverse-filter.md)

**位置**：`src/nexusx/voyager/create_voyager.py`（`ErDiagramPayload` 第 64 行、`ErDiagramSubgraphPayload` 第 72 行）

---

## 字段定义

### `ErDiagramPayload`（`POST /er-diagram` 请求体）

新增字段：

```python
class ErDiagramPayload(PydanticModel):
    # ... 现有字段保持不变
    show_module: bool = True
    better_cluster_display: bool = False
    show_methods: bool = True
    hide_reverse_relationships: bool = False   # 新增（本期）
```

### `ErDiagramSubgraphPayload`（`POST /er-diagram-subgraph` 请求体，spec 005）

新增同名字段：

```python
class ErDiagramSubgraphPayload(PydanticModel):
    """Spec 005 — request body for POST /er-diagram-subgraph.

    Same rendering fields as :class:`ErDiagramPayload`, plus the required
    schema_name.
    """
    schema_name: str
    # ... 现有渲染字段保持不变（与 ErDiagramPayload 对齐）
    show_module: bool = True
    better_cluster_display: bool = False
    show_methods: bool = True
    hide_reverse_relationships: bool = False   # 新增（本期）
```

---

## 请求示例

### 主图请求

```http
POST /er-diagram HTTP/1.1
Content-Type: application/json

{
  "schema": "demo.enterprise_voyager",
  "show_module": true,
  "better_cluster_display": false,
  "show_methods": true,
  "hide_reverse_relationships": true
}
```

### 子图请求（spec 005）

```http
POST /er-diagram-subgraph HTTP/1.1
Content-Type: application/json

{
  "schema": "demo.enterprise_voyager",
  "schema_name": "demo.enterprise_voyager.models.Post",
  "show_module": true,
  "better_cluster_display": false,
  "show_methods": true,
  "hide_reverse_relationships": true
}
```

---

## 校验规则

- **类型**：`bool`，Pydantic 自动校验。非 bool 值（如 `"true"` 字符串、`1` 整数）按 Pydantic 默认行为转换；转换失败返回 `422 Unprocessable Entity`，与现有 bool 字段（`show_module` 等）一致。
- **必填性**：可选（默认 `False`）。老客户端不传该字段时行为与现状完全一致（向后兼容）。
- **取值语义**：
  - `false`（默认）：行为与现状完全一致——所有方向（MANYTOONE / ONETOMANY / MANYTOMANY）的 relationship 连线都生成。
  - `true`：进入 Pure FK 模式——`_add_relationship_link` 跳过 `direction == 'ONETOMANY'` 的 relationship，详见 [hide-reverse-filter.md](./hide-reverse-filter.md)。

---

## 响应 shape

**完全不变**——`/er-diagram` 仍返回 `{dot: str, links: [...], schemas: {...}}`，`/er-diagram-subgraph` 仍返回 spec 005 定义的子图响应 shape。`hide_reverse_relationships: true` 时唯一可观察的差异是 `dot` 字符串和 `links` 数组中 ONETOMANY 方向的边缺失。

---

## 向后兼容性

- **老客户端**（包括已发布的 voyager 前端缓存版本、第三方调用者）不传该字段时，Pydantic 默认 `False`，行为完全一致。
- **service worker 缓存**（`web/sw.js`）：本期不修改缓存键策略；如果 sw 把请求体作为缓存键的一部分（需在实现时确认），新增字段会导致老缓存失效、新缓存重新填充——属于一次性开销，无需特殊处理。
- **路由处理函数**：`@router.post("/er-diagram")` 与 `@router.post("/er-diagram-subgraph")` 的处理逻辑**无需修改**——FastAPI 自动把请求体映射到 `voyager_context.get_er_diagram(payload)` 等方法，新增字段通过 `payload.get("hide_reverse_relationships", False)` 在 `voyager_context.py` 内透传到 `ErDiagramDotBuilder` 构造函数。

---

## 与现有 toggle 字段的对齐表

| 字段 | localStorage key | 默认值 | 作用 |
|------|-----------------|--------|------|
| `show_module` | `show_module_cluster` | `True` | 按模块聚类显示 |
| `better_cluster_display` | `better_cluster_display` | `False` | 改进的聚类显示 |
| `show_methods` | （仅会话内） | `True` | 显示实体方法 |
| `brief` | `brief_mode` | `False` | 简短模式（仅 tag → schema） |
| `pydantic_resolve_meta` | `pydantic_resolve_meta` | `False` | 显示 Pydantic resolve 元数据 |
| **`hide_reverse_relationships`**（本期新增） | **`hide_reverse_relationships`** | **`False`** | **隐藏 ONETOMANY 反向镜像** |

新增字段在命名、默认值、localStorage 持久化模式上与现有字段完全对齐。
