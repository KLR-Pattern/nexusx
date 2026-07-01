# 契约：POST /docstring（Voyager 后端端点）

**功能**：[spec.md](../spec.md) · **数据模型**：[data-model.md](../data-model.md)

**位置**：`src/nexusx/voyager/create_voyager.py`（与现有 `/source`、`/vscode-link` 路由并列）+ `src/nexusx/voyager/voyager_context.py`（新增 `get_docstring` 方法）

---

## 路由

```python
@router.post("/docstring")
def get_docstring_endpoint(payload: SourcePayload) -> JSONResponse:
    result = ctx.get_docstring(payload.schema_name)
    status_code = 200 if "error" not in result else 400
    if "error" in result and "not found" in result["error"]:
        status_code = 404
    return JSONResponse(content=result, status_code=status_code)
```

复用现有的 `SourcePayload`（`{schema_name: str}`）请求模型——与 `/source`、`/vscode-link` 一致，无需新建 Pydantic model。

---

## 请求

- **Method / Path**：`POST /docstring`
- **Content-Type**：`application/json`
- **Body**：

  ```json
  { "schema_name": "demo.enterprise_voyager.models.User" }
  ```

- **校验**（与 `/source` 对齐）：
  - `schema_name` 必填，必须是字符串。
  - 必须包含至少一个 `.`（用于区分 module 与 class）；否则后端返回 `400` + `Invalid schema name format.`。

---

## 响应

### 成功（200）

```json
{
  "docstring": "用户实体。\n\n表示系统中的一个用户。\n\n## 状态机\n\n```mermaid\nstateDiagram-v2\n    [*] --> Active\n    Active --> Disabled: 禁用\n    Disabled --> Active: 恢复\n    Active --> [*]: 注销\n```"
}
```

- `docstring`：类 `__doc__` 的原始字符串。若 `__doc__` 为 `None`，返回空串 `""`（不返回 null，便于前端 `v-if` 判空）。
- 不做 `inspect.cleandoc`——前端的 Markdown 解析器（marked）默认能处理缩进；后端保持原始字节，便于排错。

### 业务错误

| HTTP | body | 触发条件 |
|------|------|---------|
| `400 Bad Request` | `{"error": "Invalid schema name format."}` | `schema_name` 格式不合法（无 `.`、或 module 无法导入——`_resolve_object` 把 ImportError 吞为 None） |
| `404 Not Found` | `{"error": "Class not found: <detail>"}` | module 已加载但 class 不存在（`getattr` 抛 AttributeError） |
| `400 Bad Request` | `{"error": "Internal error: <detail>"}` | 其它未预期异常（兜底） |

状态码与错误文案格式与现有 `/source`、`/vscode-link` **完全一致**，便于前端复用同一份 fetch+错误处理代码。

> **行为细节**：`_resolve_object`（`voyager_context.py:288`）对 `ImportError` 是吞掉返回 None 的（与 `/source` 完全一致），因此"module 不存在"在 API 表面看与"格式不合法"无法区分——都返回 400 + `"Invalid schema name format."`。这是既有行为，本期不改变。

---

## Service Worker 缓存

**不**加入 `web/sw.js` 的预缓存列表（行 132-133 的 `/source`、`/vscode-link` 是因为前端组件首屏即调用，docstring 仅在用户主动切换 About tab 时才发）。Service Worker 对 `/docstring` 走默认的网络优先策略即可。

---

## 测试覆盖（pytest）

| 用例 | 输入 | 期望 |
|------|------|------|
| happy path | 已存在 schema_name | 200，`docstring` 非空且等于类 `__doc__` |
| 空 docstring | `__doc__` 为 None 的类 | 200，`docstring === ""` |
| 非法 schema_name（无 `.`） | `"no_dot_string"` | 400，`error === "Invalid schema name format."` |
| Module 不存在（但格式合法） | `"nonexistent_module.Foo"` | 400，`error === "Invalid schema name format."`（`_resolve_object` 吞 ImportError 返回 None） |
| Class 不存在（module 已加载） | `"tests.test_voyager_docstring.NoSuchClass"` | 400，`error` 含 `Class not found` |

测试文件：`tests/test_voyager_docstring.py`，与现有 `tests/test_er_diagram.py` 风格一致。
