# 数据模型：Router 修复后的请求-响应数据流

**关联 Spec**：[spec.md](./spec.md)
**关联 Plan**：[plan.md](./plan.md)

本特性的"数据模型"不是新增的数据实体（这是 bug fix，不引入新数据），而是**修复后 router 内部的数据流形态**——明确每个阶段变量是什么类型，作为实施时的契约参考。

---

## 核心实体

### 1. Request Model（动态生成）

`create_router()` 为每个 use case 方法用 `pydantic.create_model` 动态构造的 BaseModel 子类。

- **命名规则**：`<ServiceName><MethodNameTitleCase>Request`（如 `MyServiceCreateItemsRequest`）
- **字段**：与 service 方法的 body 参数一一对应（来自 `_classify_params` 的 `body_params` 列表）
- **字段类型**：与 service 方法签名声明完全一致（包括嵌套 BaseModel、List、Optional、Annotated 等）
- **生成位置**：`router.py::_build_request_model`

```python
# 示例：service 方法签名
@mutation
async def create_items(
    cls,
    owner_id: UUID,
    items: List[ItemInput],
) -> List[ItemOutput]: ...

# 动态生成的 request model（等价于）
class MyServiceCreateItemsRequest(BaseModel):
    owner_id: UUID
    items: List[ItemInput]
```

### 2. Body Params（参数名列表）

`create_router()` 在循环中通过 `_classify_params(sig, hints)` 计算出的参数名列表。

- **内容**：所有进入 request model 的参数名（即非 `cls`、非 `FromContext` 的参数）
- **用途**：handler 闭包按此列表从 `body` 上 getattr 取值
- **修复后变化**：从 `create_router()` 的局部变量提升为 `_make_handler()` 的入参（详见 [research.md R3](./research.md)）

### 3. Handler Kwwargs（修复后的核心变化点）

handler 闭包在调用 service 方法前组装的 kwargs 字典。

**修复前（bug 形态）**：

```python
kwargs = body.model_dump()
# kwargs = {
#     "owner_id": UUID(...),       # 标量被保留
#     "items": [dict, dict, ...],  # ← 嵌套 BaseModel 被拍平成 dict
# }
```

**修复后（正确形态）**：

```python
kwargs = {pname: getattr(body, pname) for pname in body_params}
# kwargs = {
#     "owner_id": UUID(...),               # 标量保留
#     "items": [ItemInput(...), ...],      # ← BaseModel 实例原样保留
# }
```

### 4. Context Params（FromContext 注入）

`_classify_params` 分出的另一组参数，值来自 `context_extractor(request)` 返回的 dict。

- **不经过 body**：与 request model 字段无关
- **修复后行为**：完全不变——Case 1 仍然用 `ctx[pname]` 注入 kwargs，Case 3 仍然只走 ctx

---

## 数据流（修复后端到端）

```
┌──────────────────────────────────────────────────────────────────┐
│ 客户端 POST /api/<service>/<method>                              │
│ Body: {"owner_id": "uuid-str", "items": [{"text": "a"}, ...]}   │
└──────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│ FastAPI 路由分发                                                  │
│ - 识别 handler 闭包                                              │
│ - 调用 context_extractor(request) → ctx dict（Case 1 才有）      │
└──────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│ FastAPI request model 校验（Pydantic model_validate）            │
│ - 输入：raw JSON dict                                            │
│ - 输出：body: MyServiceCreateItemsRequest 实例                   │
│   body.owner_id : UUID（标量被 coerce）                          │
│   body.items    : List[ItemInput]（嵌套 BaseModel 已构造）       │
│ - 类型契约：✅ 完全正确                                           │
└──────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│ nexusx router handler 闭包（修复后）                             │
│                                                                  │
│ kwargs = {pname: getattr(body, pname) for pname in body_params}  │
│ # = {"owner_id": UUID(...), "items": [ItemInput(...), ...]}      │
│ # 类型契约：✅ 完全保留（不再 model_dump 拍平）                  │
│                                                                  │
│ if context_params: kwargs.update({p: ctx[p] for p in ...})       │
│ return await method(**kwargs)                                    │
└──────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│ service 方法体                                                   │
│ - 收到 owner_id: UUID（✅）                                      │
│ - 收到 items: List[ItemInput]（✅ 签名不再说谎）                 │
│ - it.text 直接可用                                               │
└──────────────────────────────────────────────────────────────────┘
```

---

## 字段类型保持矩阵

修复后 handler 把 request model 的字段值原样传给 service 方法。Pydantic 在 `model_validate` 阶段已经按字段声明的类型完成构造，所以下表所有"修复后形态"都**等于签名声明**。

| Service 方法参数声明 | Request Model 字段类型 | body 上的属性形态 | 修复后 method 收到的形态 | 修复前 method 收到的形态（bug） |
|---------------------|----------------------|-----------------|------------------------|------------------------------|
| `owner_id: UUID` | `UUID` | `UUID` 实例 | `UUID` | `UUID`（已正确） |
| `name: str` | `str` | `str` | `str` | `str`（已正确） |
| `count: int = 10` | `int` (default 10) | `int` | `int` | `int`（已正确） |
| `tags: List[str]` | `List[str]` | `List[str]` | `List[str]` | `List[str]`（已正确） |
| `items: List[ItemInput]` | `List[ItemInput]` | `List[ItemInput]` | `List[ItemInput]` | **`List[dict]`** ❌ |
| `item: ItemInput` | `ItemInput` | `ItemInput` | `ItemInput` | **`dict`** ❌ |
| `item: Optional[ItemInput] = None` | `Optional[ItemInput]` | `ItemInput \| None` | `ItemInput \| None` | **`dict \| None`** ❌ |
| `items: Optional[List[ItemInput]]` | `Optional[List[ItemInput]]` | `List[ItemInput] \| None` | `List[ItemInput] \| None` | **`List[dict] \| None`** ❌ |
| `items: List[Optional[ItemInput]]` | `List[Optional[ItemInput]]` | `List[ItemInput \| None]` | `List[ItemInput \| None]` | **`List[dict \| None]`** ❌ |
| `matrix: List[List[ItemInput]]` | `List[List[ItemInput]]` | `List[List[ItemInput]]` | `List[List[ItemInput]]` | **`List[List[dict]]`** ❌ |
| `user_id: Annotated[int, FromContext()]` | （不进 body） | （不进 body） | 来自 ctx dict | 来自 ctx dict（已正确） |

**结论**：标量 / 标量列表 / FromContext 三类形态修复前后行为完全一致；所有"嵌套 BaseModel"形态修复后符合签名声明。

---

## 不变式（修复后必须成立）

实施过程与回归测试必须验证以下不变式：

1. **签名契约**：service 方法体收到的每个参数类型，必须严格等于方法签名声明的类型（不含 dict 形态）
2. **零行为变化（标量侧）**：标量参数 / `List[scalar]` 参数 / 默认值参数 / FromContext 参数的运行时行为与修复前完全一致
3. **schema 正交**：`build_compose_schema` / OpenAPI schema 生成输出与修复前二进制一致
4. **公共 API 稳定**：`UseCaseService` / `@query` / `@mutation` / `create_router` / `UseCaseAppConfig` 的签名与行为完全不变
5. **零新依赖**：`pyproject.toml` 的依赖列表完全不变
