# 内部契约：`_make_handler` 修复后形态

**关联 Plan**：[plan.md](../plan.md)
**关联 Research**：[research.md R3 / R4](../research.md)

本文档定义 router.py 内部 helper `_make_handler` 修复后的契约。这是**内部实现契约**（私有函数），不是公共 API——但实施时必须按此契约编码，回归测试也据此断言。

---

## 函数签名（修复后）

```python
def _make_handler(
    method: Any,
    request_model: type[BaseModel] | None,
    body_params: list[str],                              # ← 新增参数
    context_extractor: Callable[[Any], dict[str, Any] | Awaitable[dict[str, Any]]] | None,
    context_params: dict[str, Any],
) -> Callable[..., Any]:
    ...
```

**与修复前的差异**：仅新增第三个位置参数 `body_params: list[str]`。其余参数顺序、类型、含义完全不变。

**调用方变更**：`create_router()` 中调用 `_make_handler` 的位置（`router.py:314-319`）必须把 `body_params` 传进去。

---

## 四个 Case 的 handler 行为契约

### Case 1：`request_model is not None and ctx_dep is not None`（body + FromContext）

**handler 签名**：

```python
async def handler(
    body: request_model,
    ctx: dict[str, Any] = ctx_dep,
) -> Any:
    ...
```

**handler 行为**：

1. 用 `getattr` 从 body 上按 `body_params` 取值，组装 kwargs dict
2. 对每个 `context_params` 中的参数名 `pname`：
   - 如果 `pname in ctx`：`kwargs[pname] = ctx[pname]`
   - 否则如果 `pname not in kwargs`：抛 `HTTPException(400, f"Required context parameter '{pname}' not provided")`
3. 调用 `await method(**kwargs)`

**关键不变式**：
- kwargs 中来自 body 的参数值类型 = service 方法签名声明（嵌套 BaseModel 实例化保留）
- kwargs 中来自 ctx 的参数值类型 = context_extractor 返回的类型（不经过 body）

### Case 2：`request_model is not None and ctx_dep is None`（body only）

**handler 签名**：

```python
async def handler(body: request_model) -> Any:
    ...
```

**handler 行为**：

1. 用 `getattr` 从 body 上按 `body_params` 取值，组装 kwargs dict
2. 调用 `await method(**kwargs)`

**关键不变式**：
- kwargs 中每个值类型 = service 方法签名声明

### Case 3：`request_model is None and ctx_dep is not None`（FromContext only）

**handler 签名**：

```python
async def handler(ctx: dict[str, Any] = ctx_dep) -> Any:
    ...
```

**handler 行为**：与修复前**完全一致**——不涉及 body，无 `body_params` 使用。

### Case 4：`request_model is None and ctx_dep is None`（无参数）

**handler 签名**：

```python
async def handler() -> Any:
    ...
```

**handler 行为**：与修复前**完全一致**——直接 `await method()`。

---

## Body → Kwargs 转换的等价语义

修复后 handler 中 body 到 kwargs 的转换：

```python
kwargs = {pname: getattr(body, pname) for pname in body_params}
```

**等价语义**（用于回归测试断言）：

- 对每个 `pname in body_params`：`kwargs[pname] is getattr(body, pname)`（identity 相等）
- kwargs 的 key 集合 = `set(body_params)`（不包含 `cls`、不包含 context_params）
- kwargs 中每个值的运行时类型 = service 方法签名声明中对应参数的类型（嵌套 BaseModel 已实例化）

**反例（修复前 bug 形态）**：

```python
kwargs = body.model_dump()
# 嵌套 BaseModel 字段被拍平成 dict，违反类型契约
```

---

## 测试断言模板

回归测试应包含以下断言（以 Case 2 + `List[ItemInput]` 为例）：

```python
@mutation
async def create_items(cls, owner_id: UUID, items: List[ItemInput]) -> List[ItemOutput]:
    # 断言 1：items 是 list（不是 dict）
    assert isinstance(items, list)
    # 断言 2：每个元素是 ItemInput 实例（不是 dict）
    assert all(isinstance(it, ItemInput) for it in items)
    # 断言 3：可以直接访问属性（不再 AttributeError）
    return [ItemOutput(text=it.text, checked=it.checked) for it in items]
```

测试不应通过 mock 来断言 dict / BaseModel 形态（那是实现细节），而应在 service 方法体内用 `isinstance` 断言类型，并通过 HTTP 端到端验证属性访问正常。

---

## 不属于本契约的内容

- **不**规定 `_classify_params` / `_build_request_model` 的行为（它们不变）
- **不**规定 `create_router()` 的对外签名（它不变）
- **不**规定 service 方法体的写法（用户自由编写，依赖类型契约即可）
- **不**规定回归测试的代码组织（test class 名、test method 名由 tasks.md 阶段决定）
