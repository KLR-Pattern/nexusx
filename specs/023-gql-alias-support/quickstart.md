# Quickstart: GraphQL Alias 支持（specs/023）

Phase 1 产出。端到端验证场景，每个场景独立可跑，证明 feature 按契约工作。行为预期见 [contracts/graphql-alias-behavior.md](./contracts/graphql-alias-behavior.md)，错误结构见 [data-model.md §2](./data-model.md)。

## 前置

```bash
uv sync --all-extras
uv run pytest tests/ -x -q        # 基线：全量通过（1500+）
```

## 场景 1：Issue #140 原始复现（阶段 B1b 后应通过）

```bash
uv run python - <<'EOF'
from nexusx.query_parser import QueryParser
from graphql import parse

q = """mutation { MyService {
  a1: add_node(content: "one")   { display_id }
  a2: add_node(content: "two")   { display_id }
  a3: add_node(content: "three") { display_id }
} }"""

doc = parse(q)
svc = QueryParser().parse_document(doc)["MyService"]
assert len(svc.sub_fields) == 3, f"期望 3 个响应键，实际 {len(svc.sub_fields)}"
assert list(svc.sub_fields) == ["a1", "a2", "a3"]
print("✓ 解析层保住 3 个别名（6.1.2 此处只剩 1 个）")
EOF
```

端到端（compose MCP 面）：同形状查询经 `compose_query` 执行后，3 个节点全部创建、`data.MyService` 含 `a1/a2/a3` 三个键、`errors == []`。

## 场景 2：query 扇出（阶段 B1a 后应通过）

```bash
uv run python - <<'EOF'
from nexusx.query_parser import QueryParser

q = """query { TaskService {
  high: list_tasks(priority: "high") { id title }
  low:  list_tasks(priority: "low")  { id }
} }"""
svc = QueryParser().parse(q)["TaskService"]
assert svc.sub_fields["high"].name == "list_tasks"   # 查找键是原始名
assert svc.sub_fields["high"].arguments == {"priority": "high"}
assert svc.sub_fields["low"].arguments == {"priority": "low"}
assert set(svc.sub_fields["high"].sub_fields) == {"id", "title"}
assert set(svc.sub_fields["low"].sub_fields) == {"id"}
print("✓ 两个别名各自持参数与投影，互不覆盖")
EOF
```

端到端：两次查询都执行，`data.TaskService.high/low` 各自返回对应参数的结果。

## 场景 3：mutation 部分失败三态（阶段 B1b 后应通过）

发送 3 个别名 mutation，第 2 个制造异常（如违反约束的参数）：

- `data.Svc.a1` = 正常结果（**已成功的结果不丢**——这是对 entity-first 整组作废语义的变更验证点）
- `data.Svc.a2` = `null`，`errors` 含 `path: ["Svc","a2"]`、`extensions.code: "MUTATION_FAILED"`
- `data.Svc.a3` = `null`，`errors` 含 `extensions.code: "SKIPPED_PRIOR_FAILURE"`

## 场景 4：响应键冲突报错（阶段 B1a 后应通过）

- `a: f(x: 1)` 写两遍 → `ALIAS_CONFLICT`，无方法执行
- `f { x }` 与 `f { y }`（无别名同名字段重复）→ `ALIAS_CONFLICT`（不做合并）

## 场景 5：联邦 wire 无别名（阶段 B1a 后应通过）

联邦测试矩阵（β 物化 / γ DTO / 分页）中以方法级别名查询 mounter，在 FakeTransport/HTTP 断言层捕获发往 member 的查询字符串：

```python
assert ":" not in captured_query_fields  # 机造查询字段区无别名标记
```

member 端代码零改动即全部矩阵通过。

## 场景 6：全量回归（每阶段交付前）

```bash
uv run pytest tests/ -q              # 零回归（基线不下降）
ruff check src/                      # CI lint 范围
```

## 验收对照

| 场景 | 对应 SC | 阶段 |
|---|---|---|
| 1 | SC-006（6 个 add_node 全建） | B1b |
| 2 | SC-001（N 执行 N 分组） | B1a |
| 3 | SC-003（已成功保留率 100%） | B1b |
| 4 | SC-002（0 静默丢弃） | B1a |
| 5 | SC-004（wire 别名数 = 0） | B1a |
| 6 | SC-005（零回归） | 每阶段 |
