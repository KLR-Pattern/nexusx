# Quickstart: UseCase Service → GraphQL → MCP

**Feature**: `001-usecase-graphql-mcp` | **Date**: 2026-06-20

本文档给出可运行的端到端验证步骤。完成这些步骤 = 特性交付完成。

---

## Q1. 前置条件

```bash
# 1. 在特性分支
git checkout 001-usecase-graphql-mcp

# 2. 依赖已同步（graphql-core / fastmcp 已是核心依赖）
uv sync --all-extras

# 3. CI 检查通过
./scripts/check-ci.sh
```

---

## Q2. 启动 demo（手工验证）

### 启动 UseCase GraphQL MCP demo

```bash
uv run --with fastmcp python -m demo.use_case.mcp_server_graphql
```

**期望**：MCP server 在 stdio 上启动，无错误。控制台输出类似：
```
[nexusx] UseCase GraphQL MCP server 'Core API UseCase GraphQL Demo' ready.
[nexusx] Apps: project (3 services)
```

### 通过 MCP inspector 探索

打开 MCP Inspector（或任何 MCP 客户端），连接到上述 server。应能看到 4 个工具：
- `list_apps`
- `describe_compose_schema`
- `describe_compose_method`
- `compose_query`

按层调用：

1. `list_apps` → 应返回 1 个 app（"project"）
2. `describe_compose_schema(app_name="project")` → 应返回 3 个 service 与各自方法列表
3. `describe_compose_method(app_name="project", service_name="TaskService", method_name="list_tasks")` → 应返回参数表、返回类型、SDL 片段
4. `compose_query(app_name="project", query="{ TaskService { list_tasks { id title owner { id name } } } }")` → 应返回 `{data: {TaskService: {list_tasks: [...]}}}`，每个 task 含 id/title/owner

### GraphiQL 兼容性（如适用）

```python
from nexusx import build_compose_schema, UseCaseAppConfig
from graphql import build_schema, print_schema

app = UseCaseAppConfig(name="project", services=[...])
schema = build_compose_schema(app)
introspection = schema.render_introspection()

# 验证 graphql-core 能消费
gql_schema = build_schema(introspection)  # 不抛异常即通过
print(print_schema(gql_schema))
```

---

## Q3. 单元/集成测试（自动化验证）

```bash
# 全部新增测试
uv run pytest tests/use_case/test_compose_schema.py \
               tests/use_case/test_compose_executor.py \
               tests/use_case/test_compose_mcp_server.py \
               tests/use_case/test_introspection_rejected.py \
               tests/use_case/test_old_api_removed.py -v
```

### 期望通过的代表性测试

参考 [research.md R10](./research.md#r10-测试套件覆盖与-sc-002-对齐) 的完整清单。

特别关注：

- `test_compose_schema.py::test_introspection_round_trips_through_graphql_core`
  - 断言：`build_schema(schema.render_introspection())` 不抛异常
- `test_compose_schema.py::test_deduplicates_dto_referenced_from_multiple_services`
  - 断言：同一 DTO 类被两个 service 引用时，registry 中只出现一次
- `test_compose_executor.py::test_projects_only_requested_fields`
  - 断言：查询 `{ TaskService { list_tasks { id } } }` 返回值中**只有** `id` 字段
- `test_compose_executor.py::test_does_not_wrap_service_method_result_in_resolver`
  - 断言：service 方法返回的 DTO 上的 `resolve_*` 字段若未在 service 方法内显式 `Resolver().resolve()`，则不会被自动填充（验证 FR-004a）
- `test_compose_mcp_server.py::test_layer_3_returns_graphql_standard_envelope`
  - 断言：`compose_query` 返回 `{data, errors}`，不是 `{success, ...}`
- `test_compose_mcp_server.py::test_layers_0_to_2_return_success_envelope`
  - 断言：`list_apps` / `describe_compose_schema` / `describe_compose_method` 返回 `{success, data}`
- `test_introspection_rejected.py::test_rejects_schema_query_with_hint`
  - 断言：`compose_query` 收到 `{ __schema { types { name } } }` 时返回 `{data: null, errors: [...]}`
- `test_old_api_removed.py::test_old_mcp_imports_fail`
  - 断言：`from nexusx import create_use_case_mcp_server` 抛 `ImportError`

---

## Q4. 老 demo 迁移验证

```bash
# 老 demo 路径
uv run python demo/use_case/mcp_server.py
```

**期望**：执行失败，错误消息包含指向 `create_use_case_graphql_mcp_server` 的迁移提示（FR-010）。

按 `docs/migrations/2.0-use-case-graphql.md` 把 demo 内容改写为新入口，重新运行应通过 Q2。

---

## Q5. 正交出口未被破坏

```bash
# FastAPI REST demo（应继续工作）
uv run uvicorn demo.use_case.fastapi:app --port 8007

# Voyager 可视化 demo（应继续工作）
uv run python -m demo.use_case.voyager_demo
```

**期望**：两者行为与 1.x 一致；无 warning、无 deprecation 提示、无签名变化。

---

## Q6. 完整 CI 通过

```bash
./scripts/check-ci.sh
```

**期望**：
- `ruff check src/ tests/` 全过
- `mypy src/` 全过
- `pytest` 全过（含新增 5 个测试文件 + 既有测试无回归）

---

## Q7. 验证矩阵

| 场景 | 期望 | 验证手段 |
|------|------|---------|
| 启动新 MCP server | 成功，无报错 | Q2 |
| 4 层工具 happy path | 返回符合 contracts/mcp-tools.md 的 shape | Q2、Q3 |
| 字段选择投影生效 | 只返回请求字段 | test_compose_executor.py |
| introspection 被拒 | `{data: null, errors: [...]}` + hint | test_introspection_rejected.py |
| 同 DTO 多 service 引用 | registry 中只注册一次 | test_compose_schema.py |
| 同名 service 冲突 | 启动期 ComposeSchemaError | test_compose_schema.py |
| DTO 字段引用 SQLModel | 启动期 SQLModelInDtoFieldError | test_compose_schema.py |
| service 方法抛异常 | `{data: null, errors: [...]}` + 含方法名 | test_compose_executor.py |
| 老 MCP 入口导入 | ImportError + 提示新入口 | test_old_api_removed.py |
| FastAPI/Voyager demo | 行为不变 | Q5 |
| GraphiQL 消费 schema | 渲染成功 | test_compose_schema.py + Q2 |
| 既有测试无回归 | 全部通过 | Q6 |

---

## Q8. 完成 Definition of Done

本特性 Done 当且仅当：

- [ ] 上述 Q1–Q7 全部通过
- [ ] `src/nexusx/__init__.py` 与 `src/nexusx/use_case/__init__.py` 仅导出 [contracts/public-api.md](./contracts/public-api.md) C1 与 C2 列出的条目；C3 列出的条目均不可导入
- [ ] `pyproject.toml` version = `2.0.0`
- [ ] `CHANGELOG.md` 含 2.0.0 段落（BREAKING + Added）
- [ ] `docs/migrations/2.0-use-case-graphql.md` 存在，含两个老入口的迁移示例
- [ ] `demo/use_case/mcp_server_graphql.py` 可运行
- [ ] `./scripts/check-ci.sh` 绿
