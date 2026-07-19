# Phase 0 研究产物：router model_dump bug 修复

**日期**：2026-07-19
**关联 Issue**：KLR-Pattern/nexusx#107
**关联 Spec**：[spec.md](./spec.md)

本文档汇总修复路径上的关键技术决策与权衡。

---

## R1：Bug 根因定位（已确认）

**Decision**：bug 根因在 `src/nexusx/use_case/router.py:170` 与 `router.py:186`——`_make_handler` 在 Case 1（body + ctx）和 Case 2（body only）两个 handler 闭包里调用 `body.model_dump()` 把 request model 整体拍平成 dict。

**Rationale**：

- Pydantic v2 的 `BaseModel.model_dump()` 默认 `mode="python"`，但仍然会**递归**把嵌套 BaseModel 实例转成 dict（这是 Pydantic v2 文档明确的行为，[Pydantic docs: model_dump](https://docs.pydantic.dev/latest/concepts/serialization/#model_dump)）
- FastAPI 在路由分发前会调用 `request_model.model_validate(json_dict)` 完成 JSON → BaseModel 的递归构造（这一步类型是正确的）
- nexusx router 在 FastAPI 与 service 方法之间多加了一道 `model_dump()`，把已经构造好的 BaseModel 实例**重新拍回 dict**，破坏了类型契约

**Alternatives considered**：

1. 以为是 FastAPI 行为问题——**否**。FastAPI 在 request model 阶段类型完全正确，问题在 nexusx 自己的 router
2. 以为是 Pydantic 配置问题——**否**。`model_config` 可以控制序列化行为但无法让 `model_dump()` 保留 BaseModel 实例（这是 API 设计层面的限制）

**Verification**：用 issue #107 的复现代码（`items: List[ItemInput]`）在 `router.py:186` 打断点：

```
body.items[0] → ItemInput 实例（FastAPI 阶段，类型正确）
body.model_dump()["items"][0] → dict（model_dump 阶段，类型破坏）
```

---

## R2：修复路径选型（已确认）

**Decision**：去掉 `body.model_dump()`，改为按字段名做属性访问：

```python
# Case 2 修复后
async def handler(body: request_model) -> Any:
    kwargs = {pname: getattr(body, pname) for pname in body_params}
    return await method(**kwargs)
```

**Rationale**：

- `body` 是 FastAPI 已经 `model_validate` 过的 request model 实例，字段值已经是正确的 Python 类型（嵌套 BaseModel 已构造、标量已 coerce、validators 已执行）
- `getattr(body, pname)` 直接拿到字段值，零转换、零递归、零额外开销
- 比 issue #107 提议的 `inspect.signature` + `ann.model_validate` 方案干净（issue 方案要先 dump 再 validate，等于"拆掉再装回去"）
- 比 `TypeAdapter(ann).validate_python(raw[name])` 方案干净（同理绕弯）

**Alternatives considered**：

| 方案 | 工作量 | 性能 | 类型正确性 | 评价 |
|------|-------|------|-----------|------|
| **A. `getattr` 按字段名取值** | 小 | 最快（O(1) 属性访问） | 完全正确 | ✅ 采用 |
| B. `body.model_dump()` + `TypeAdapter.validate_python` 二次校验 | 中 | 慢（dump + validate 两次） | 完全正确 | ❌ 绕弯，方案 B 是先拆再装 |
| C. `inspect.signature` + 逐字段 `ann.model_validate` | 大 | 慢 | 完全正确 | ❌ 重新实现 Pydantic 已有的能力 |
| D. 文档化 dict 行为（spec option b） | 极小 | N/A | 签名说谎 | ❌ 破坏 nexusx "签名即真相"卖点 |
| E. 引入 `mode="python"` + 自定义 `field_serializer` 保留 BaseModel | 中 | 中 | 部分正确 | ❌ request model 是 `pydantic.create_model` 动态拼出来的，用户无法加 `field_serializer` |

**用户决策记录**：用户在 specify 阶段已显式钉死方案 A（spec FR-002）。

---

## R3：`_make_handler` 签名变化（已确认）

**Decision**：`_make_handler` 是 router.py 内部的私有 helper（前缀 `_`），可以自由修改签名。修改后多接受一个参数 `body_params: list[str]`，用于 handler 闭包按字段名取值。

**修改前**：

```python
def _make_handler(
    method: Any,
    request_model: type[BaseModel] | None,
    context_extractor: Callable[...] | None,
    context_params: dict[str, Any],
) -> Callable[..., Any]:
    ...
```

**修改后**：

```python
def _make_handler(
    method: Any,
    request_model: type[BaseModel] | None,
    body_params: list[str],            # ← 新增
    context_extractor: Callable[...] | None,
    context_params: dict[str, Any],
) -> Callable[..., Any]:
    ...
```

**Rationale**：

- `body_params` 已经在 `create_router()` 的循环里通过 `_classify_params(sig, hints)` 计算出来（`router.py:302`），只需要把它作为参数传给 `_make_handler`
- 不修改 `_classify_params` 或 `_build_request_model`——它们的职责是分类与构造，与 handler 闭包无关
- 私有 helper 签名变化不计入公共 API 变更（spec Assumptions "修复不引入新的依赖，也不修改 nexusx 公共 API"）

**Alternatives considered**：

1. 把 `body_params` 计算挪进 `_make_handler`——**否**，违反职责分离；`_make_handler` 只负责构造 handler，不负责分类
2. 用闭包捕获（在 `create_router` 内部直接定义 handler）——**否**，会让 `create_router` 函数变得很长，破坏现有结构
3. 把 `body_params` 存到 `request_model` 类的属性上——**否**，污染 Pydantic 模型对象

---

## R4：四个 case 的修复差异（已确认）

**Decision**：四个 case 中只有 Case 1（body + ctx）和 Case 2（body only）需要修改；Case 3（ctx only）和 Case 4（no params）天然不受影响。

| Case | 当前代码 | 是否需要改 | 修改后代码 |
|------|---------|-----------|-----------|
| Case 1 (body + ctx) | `kwargs = body.model_dump()` + ctx 覆盖 | ✅ 改 | `kwargs = {p: getattr(body, p) for p in body_params}` + ctx 覆盖 |
| Case 2 (body only) | `return await method(**body.model_dump())` | ✅ 改 | `kwargs = {p: getattr(body, p) for p in body_params}; return await method(**kwargs)` |
| Case 3 (ctx only) | 不涉及 body | ❌ 不变 | 不变 |
| Case 4 (no params) | `return await method()` | ❌ 不变 | 不变 |

**Rationale**：

- Case 3 / Case 4 没有 request model，handler 闭包里根本没有 `body` 变量，`model_dump()` 不存在
- Case 1 比 Case 2 多一步：把 ctx_params 注入到 kwargs 中——这部分逻辑不变，只把"`kwargs` 初始化"那一行从 `body.model_dump()` 换成 getattr 字典推导

**Verification**：修复后必须对四个 case 都跑回归测试（详见 [tasks.md](./tasks.md) 后续生成），其中 Case 3 / Case 4 的现有测试足以覆盖（无需新增）。

---

## R5：现有测试影响面分析（已确认）

**Decision**：现有 `tests/test_use_case_router.py` 中**没有任何测试**会因为本次修复而失败。

**Rationale**：

通读 `tests/test_use_case_router.py`（457 行）：

- 测试中所有 service 方法的参数都是**标量**（`user_id: int` / `name: str` / `email: str`）或 `Annotated[int, FromContext()]`
- 没有任何测试在 service 方法体里访问嵌套 BaseModel 参数（因为根本没声明过）
- `UserDTO` 这个 BaseModel 只作为**返回类型**出现（`list_users` / `get_user` / `create_user`），从未作为参数类型
- 没有任何测试断言 `method(**dict)` 的 dict 形态（都用 `response.json()` 断言最终响应）

**Verification 命令**：

```bash
grep -n 'BaseModel\|model_dump' tests/test_use_case_router.py
# 仅 line 10 import + line 24 UserDTO 定义 + line 38/42/50 返回类型注解
# 没有 service 方法参数使用 BaseModel
```

**Implication**：

- 修复不会让任何现有测试变红
- 但现有测试也**不能验证修复**——必须新增针对嵌套 BaseModel 参数的测试
- 新增测试覆盖矩阵见 [tasks.md](./tasks.md) Phase 2

---

## R6：边角情况覆盖（已确认）

**Decision**：修复后必须覆盖以下边角情况，每种都有对应的回归测试。

| 边角 | 当前行为（bug） | 修复后行为 | 验证手段 |
|------|----------------|-----------|---------|
| `items: List[ItemInput]` | 收到 `List[dict]` | 收到 `List[ItemInput]` | `items[0].text == "a"` |
| `item: ItemInput`（单层） | 收到 `dict` | 收到 `ItemInput` | `item.text == "a"` |
| `item: Optional[ItemInput] = None` | 收到 `dict \| None` | 收到 `ItemInput \| None` | 两种情况都测 |
| `items: Optional[List[ItemInput]]` | 收到 `Optional[List[dict]]` | 收到 `Optional[List[ItemInput]]` | 显式传值 + 省略 |
| `items: List[Optional[ItemInput]]` | 收到 `List[Optional[dict]]` | 收到 `List[Optional[ItemInput]]` | 含 null 元素 |
| `matrix: List[List[ItemInput]]` | 收到 `List[List[dict]]` | 收到 `List[List[ItemInput]]` | 嵌套两层 |
| `owner_id: UUID`（标量） | 收到 `UUID`（已正确） | 收到 `UUID`（保持） | 回归断言 |
| `tags: List[str]`（标量列表） | 收到 `List[str]`（已正确） | 收到 `List[str]`（保持） | 回归断言 |
| `count: int = 10`（默认值） | 省略时收到 `10`（已正确） | 省略时收到 `10`（保持） | 回归断言 |
| `Annotated[T, Field(alias="x")]` | 按 alias 收 JSON、按 pname 输出 dict | 按 alias 收 JSON、按 pname 输出值 | alias 不影响 getattr |
| Case 1: body + FromContext | body 部分被 dump、ctx 注入正确 | body 部分按字段访问、ctx 注入正确 | 混合参数测试 |

**Rationale**：

- 这些边角的修复路径**完全统一**——都是 `getattr(body, pname)` 自然支持的，不需要任何额外代码
- 但回归测试必须显式覆盖，防止后续维护者无意中改回 `model_dump()`

---

## R7：CHANGELOG 与版本号策略（建议）

**Decision**：建议作为 **patch 版本** 发布（如 3.6.2 → 3.6.3），并在 CHANGELOG 中显式声明行为变化。

**Rationale**：

- bug 性质：router 违反了 service 方法签名声明的类型契约，是**实现与文档不一致**——按 semver 严格解读，修复这种"行为偏离文档"的 bug 属于 patch
- 行为变化：用户方法体收到 BaseModel 实例而非 dict。但这个行为变化**完全符合签名声明**——用户方法体如果按签名编写（`it.text`），修复前后都正确；只有违反签名编写的代码（`it["text"]`）会受影响
- 中等风险评估：极少数用户可能依赖了 dict 形态（写过 `it["text"]` 直接访问），需要在 CHANGELOG 中提示
- 版本号归属：本 spec 不强制要求版本号策略，最终由 `/release` skill 决定

**Alternatives considered**：

1. **patch (3.6.3)** ✅ 采用——bug fix，行为符合签名契约
2. minor (3.7.0)——保守，但会过度放大影响（用户看了 minor 会以为有新功能）
3. major (4.0.0)——过度，破坏性变化只是修复契约违反，不是真的破坏 API

**Implication**：

- spec FR-009 要求在 CHANGELOG 中声明行为变化——本 spec 会在 tasks.md 中包含 CHANGELOG entry 任务
- 但 CHANGELOG 文件本身的写入时机由 `/release` skill 掌握——tasks.md 阶段的产物只是**草稿 entry 文本**

---

## R8：未解决项

无。Phase 0 完成后所有技术决策都已确定，可以直接进入 Phase 1 设计与 Phase 2 任务拆解。
