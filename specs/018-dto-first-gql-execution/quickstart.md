# Quickstart: DTO-first gql execution

> 验证场景，证明 4 个 Step 各自达成目标。实现细节见 `tasks.md`（由 `/speckit-tasks` 生成）。

## 前置

- nexusx 5.1.0+（015 本地分页 order/direction）+ specs/016（γ DTO federation）已合并
- entity-first gql 测试集（1429 个）全绿
- `response_builder.py` 当前未启用（[memory: project-response-builder-dormant]）

## 场景 1: Step 1 — `use_response_builder=True` 零回归（核心 P0）

把 `QueryExecutor._serialize` 替换为 `build_response_model` + model_validate，flag-on / flag-off 输出 diff 必须为空。

```python
# 两种构造方式
handler_old = GraphQLHandler(base=Base, session_factory=..., enable_pagination=True)
handler_new = GraphQLHandler(
    base=Base, session_factory=..., enable_pagination=True,
    use_response_builder=True,   # ★ 新 flag
)
```

**等价性 fixture 验证**：

```python
@pytest.mark.parametrize("query", GQL_FIXTURES)
async def test_response_builder_equivalent(query, handler_old, handler_new):
    """flag on / flag off 输出 diff 必须为空。"""
    expected = await handler_old.execute(query)
    actual = await handler_new.execute(query)
    assert actual == expected  # 零差异
```

**验证命令**：

```bash
# Step 1 完成后跑全量
uv run pytest tests/ -q

# 重点：等价性 fixture（新加）
uv run pytest tests/test_query_executor_dto_first.py -v
```

**期望**：1429 passed / 6 skipped / 0 failed；等价性 fixture 全绿。

## 场景 2: Step 2 — pagination 进 DTO field（P0）

`reviews(limit: 5, order: HIGHEST_RATING)` 在 build_response_model 阶段变成 DTO field `reviews: Annotated[list[X], Paged(limit=5, order="HIGHEST_RATING")]`。

```python
from nexusx.response_builder import build_response_model

# gql selection 派生
field_tree = {
    "reviews": {"items": {"title": None}, "pagination": {"has_more": None}},
}
gql_args = {"reviews": {"limit": 5, "order": "HIGHEST_RATING"}}

model_cls = build_response_model(
    entity=Product,
    field_tree=field_tree,
    pagination_metadata=gql_args,   # ★ Step 2 新参数
)

# 检查 reviews 字段类型
hint = typing.get_type_hints(model_cls, include_extras=True)["reviews"]
assert typing.get_origin(hint) is list
paged_meta = next(m for m in typing.get_args(hint)[1:] if isinstance(m, Paged))
assert paged_meta.limit == 5
assert paged_meta.order == "HIGHEST_RATING"
```

**验证命令**：

```bash
uv run pytest tests/test_response_builder_pagination.py -v
```

**期望**：单测验证 Paged metadata 正确注入到字段；不带 args 的 `reviews` 字段类型是 `list[X]`（无 Annotated）。

## 场景 3: Step 3 — Resolver 接管 β federation dispatch（P1）

`fetch_remote_subtree` 不再被 `QueryExecutor._load_field_batch` 直接调用。

**Grep 验证**：

```bash
# Step 3 完成后跑
grep -rn "fetch_remote_subtree" src/nexusx/
# 期望: 只在 resolver.py 内部（之前还在 query_executor.py:456/469）
```

**等价性回归测试**：

```bash
# 全量 federation 测试（β 路径行为不变）
uv run pytest tests/test_federation_e2e.py tests/test_federation_pagination_e2e.py \
    tests/test_federation_nested_local_pagination.py tests/test_federation_resolver_deep_chain.py \
    -q
```

**期望**：grep 命中收敛；federation 测试全部通过（β 路径零回归）。

## 场景 4: Step 4 — fetch primitive 对称化（P2）

`fetch_remote_subtree` docstring 改诚实（β-only）；新增 `fetch_dto_subtree`（γ-only）。

**Docstring 校验**：

```python
from nexusx.federation.remote_loader import fetch_remote_subtree, fetch_dto_subtree

assert "β entity federation" in fetch_remote_subtree.__doc__
assert "γ DTO federation" in fetch_dto_subtree.__doc__
```

**调用方 grep**：

```bash
# β / γ primitive 各自只在自己的 dispatch 路径
grep -rn "fetch_remote_subtree\|fetch_dto_subtree" src/nexusx/
# 期望: fetch_remote_subtree 只在 resolver entity dispatch
#       fetch_dto_subtree 只在 resolver DTO dispatch
```

**验证命令**：

```bash
uv run pytest tests/test_federation_resolver_deep_chain.py \
    tests/test_dto_federation_e2e.py -v
```

**期望**：β / γ 测试都绿；docstring 校验通过。

## 综合：场景 5 — 端到端 DTO-first gql 行为不变（P0）

entity-first gql query 选 entity field，行为跟改造前完全一致：

```bash
# 跑同一组 gql query fixture
curl -X POST http://localhost:8022/graphql -d '{
    Product {
        by_filter {
            id
            name
            reviews(limit: 3) {
                items { title rating }
                pagination { has_more total_count }
            }
        }
    }
}'

# 期望响应结构（旧路径 = 新路径）
{
    "data": {
        "Product": {
            "by_filter": [
                {
                    "id": 1,
                    "name": "Widget",
                    "reviews": {
                        "items": [{"title": "...", "rating": 5}, ...],
                        "pagination": {"has_more": true, "total_count": 42}
                    }
                }
            ]
        }
    }
}
```

**期望**：响应 dict 跟旧路径逐字段相等（场景 1 的 fixture 集覆盖此场景）。

## 不在 quickstart 范围

- 实际 benchmark（DTO schema 构建开销 / Resolver 接管 β 后的延迟对比）—— 单独 benchmark 脚本，不在 quickstart 范围。
- 性能 < 10% 回退的验收门槛 —— 在 plan.md "Performance Goals" 列出，benchmark 脚本另起。
- 向后兼容 deprecation notice —— Step 1.c 起加 changelog，不在 quickstart 范围。
