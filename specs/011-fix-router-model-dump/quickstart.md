# 验证指南：Router 修复端到端确认

**关联 Spec**：[spec.md](./spec.md)
**关联 Plan**：[plan.md](./plan.md)

本文档列出可在本地执行的验证场景，证明修复有效且未引入回归。每个场景都给出**前置条件**、**执行命令**与**预期结果**，可直接作为手动冒烟测试或回归脚本。

---

## 前置：环境准备

```bash
# 在仓库根目录
UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple uv sync --all-extras
# 或（不走镜像，走代理）：
# https_proxy=http://192.168.71.149:16780 uv sync --all-extras

# 确认 Python / Pydantic 版本与 issue 报告环境一致
uv run python -c "import sys, pydantic; print(sys.version_info[:2], pydantic.VERSION)"
# 期望输出：(3, 13) 2.13.x（或更高）
```

---

## 场景 1：修复前 bug 复现（基线对照）

**目的**：确认 bug 真实存在，作为修复前的对照基线。

**步骤**：

1. **不要**应用本 spec 的修复（保持在 master 或修复前的 commit）
2. 创建临时验证脚本 `repro_bug.py`：

```python
from typing import List, UUID
from pydantic import BaseModel
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nexusx import UseCaseService, mutation
from nexusx.use_case.router import create_router
from nexusx.use_case.types import UseCaseAppConfig

class ItemInput(BaseModel):
    text: str
    checked: bool = False

class ItemOutput(BaseModel):
    text: str
    checked: bool

class MyService(UseCaseService):
    @mutation
    async def create_items(cls, owner_id: UUID, items: List[ItemInput]) -> List[ItemOutput]:
        return [ItemOutput(text=it.text, checked=it.checked) for it in items]

app = FastAPI()
app.include_router(create_router(UseCaseAppConfig(name="demo", services=[MyService])))
client = TestClient(app)

resp = client.post("/api/my_service/create_items", json={
    "owner_id": "11111111-1111-1111-1111-111111111111",
    "items": [{"text": "a", "checked": True}, {"text": "b"}],
})
print("status:", resp.status_code)
print("body:", resp.text)
```

3. 运行：`uv run python repro_bug.py`

**预期结果**（修复前）：HTTP 500，错误信息包含 `AttributeError: 'dict' object has no attribute 'text'`。

---

## 场景 2：修复后端到端验证

**目的**：验证修复使 issue #107 复现脚本正常工作。

**步骤**：

1. 应用本 spec 的修复（按 [tasks.md](./tasks.md) 实施）
2. 重跑场景 1 的 `repro_bug.py`

**预期结果**（修复后）：

- HTTP 200
- 响应 body：

```json
[
  {"text": "a", "checked": true},
  {"text": "b", "checked": false}
]
```

- 无 `AttributeError`，无 500 错误

---

## 场景 3：参数形态全覆盖（回归测试套件）

**目的**：验证修复覆盖所有嵌套 BaseModel 形态，且不破坏标量 / FromContext / 默认值行为。

**步骤**：

```bash
uv run pytest tests/test_use_case_router.py::TestNestedBaseModelParams -v
```

**预期结果**：新增的 `TestNestedBaseModelParams` test class 全部通过，覆盖：

| Test Case | 参数形态 | 关键断言 |
|-----------|---------|---------|
| `test_list_of_basemodel` | `items: List[ItemInput]` | `items[0].text == "a"` |
| `test_single_nested_basemodel` | `item: ItemInput` | `item.text == "a"` |
| `test_optional_basemodel_with_value` | `item: Optional[ItemInput] = None`（传值） | `item.text == "a"` |
| `test_optional_basemodel_with_none` | 同上（传 null） | `item is None` |
| `test_optional_list_of_basemodel` | `items: Optional[List[ItemInput]]` | 嵌套保留 |
| `test_list_of_optional_basemodel` | `items: List[Optional[ItemInput]]` | 含 null 元素时正确处理 |
| `test_nested_two_levels` | `matrix: List[List[ItemInput]]` | 两层嵌套都保留 |
| `test_scalar_unchanged` | `owner_id: UUID` | 标量行为不变（回归） |
| `test_scalar_list_unchanged` | `tags: List[str]` | 标量列表行为不变（回归） |
| `test_default_value_unchanged` | `count: int = 10` | 默认值生效（回归） |
| `test_basemodel_with_from_context` | body 中的 BaseModel + FromContext 标量 | Case 1 混合参数正确 |

---

## 场景 4：现有 router 测试零回归

**目的**：确认修复未破坏任何现有功能。

**步骤**：

```bash
uv run pytest tests/test_use_case_router.py -v
```

**预期结果**：

- 现有 30+ 个 test method 全部通过（修复前通过集合 = 修复后通过集合）
- 新增的 `TestNestedBaseModelParams` 全部通过
- 总通过数 = 现有数 + 新增数

---

## 场景 5：Schema 路径正交性验证

**目的**：确认修复未影响 OpenAPI / compose schema 生成（spec FR-007、SC-004）。

**步骤 1：OpenAPI schema diff**

```bash
# 在修复前（master）
uv run python -c "
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nexusx.use_case.router import create_router
from nexusx.use_case.types import UseCaseAppConfig
# 用一个固定的 service 集合
app = FastAPI()
app.include_router(create_router(UseCaseAppConfig(name='demo', services=[...])))
print(TestClient(app).get('/openapi.json').json())" > /tmp/openapi_before.json

# 切换到修复后分支，重跑同样的命令，输出到 /tmp/openapi_after.json

diff /tmp/openapi_before.json /tmp/openapi_after.json
```

**预期结果**：`diff` 输出为空（两份 OpenAPI schema 二进制一致）。

**步骤 2：Compose schema diff**

```bash
uv run python -c "
from nexusx.use_case.compose_schema import build_compose_schema
from nexusx.use_case.types import UseCaseAppConfig
# 同样的 service 集合
schema = build_compose_schema(UseCaseAppConfig(name='demo', services=[...]))
print(schema.to_sdl())" > /tmp/sdl_before.sdl
# 修复前后对比
diff /tmp/sdl_before.sdl /tmp/sdl_after.sdl
```

**预期结果**：`diff` 输出为空。

---

## 场景 6：静态检查通过

**目的**：确认代码风格与类型检查通过。

**步骤**：

```bash
uv run ruff check src/nexusx/use_case/router.py tests/test_use_case_router.py
uv run mypy --strict src/nexusx/use_case/router.py
```

**预期结果**：两条命令都退出码 0，无任何输出。

---

## 完成判定

当且仅当以下条件**全部**成立时，本 spec 的实施完成：

- [x] 场景 1 在修复前可复现 bug
- [x] 场景 2 修复后端到端跑通（HTTP 200 + 正确响应）
- [x] 场景 3 `TestNestedBaseModelParams` 全部通过
- [x] 场景 4 现有测试零回归
- [x] 场景 5 OpenAPI / compose schema diff 为空
- [x] 场景 6 ruff + mypy 通过
- [ ] CHANGELOG 草稿 entry 已写入（spec FR-009，详见 tasks.md）

最后一项由 `/release` skill 在版本发布阶段最终落地。
