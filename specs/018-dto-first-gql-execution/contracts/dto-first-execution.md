# Contract: DTO-first gql execution 公开 API

**Feature**: specs/018-dto-first-gql-execution

## 1. response_builder API（Step 1 + Step 2）

### build_response_model（扩展）

```python
from nexusx.response_builder import build_response_model

model_cls = build_response_model(
    entity=Product,                                  # SQLModel 实体
    field_tree={                                     # gql FieldSelection 派生的 dict
        "id": None,
        "name": None,
        "reviews": {"items": {"title": None}, "pagination": {"has_more": None}},
    },
    federation_namespace=fed_registry._namespace,    # 新增 optional，federation remote type 解析
)
# model_cls 是动态 pydantic model，含 scalar / nested / paginated 字段
```

| 参数 | 类型 | Step 1 | Step 2 |
|------|------|--------|--------|
| `entity` | `type[SQLModel]` | ✓ | ✓ |
| `field_tree` | `dict[str, Any] \| None` | ✓ | ✓ |
| `federation_namespace` | `dict[str, type] \| None = None` | ✓ 新增 | ✓ |
| `pagination_metadata` | `dict[str, Paged] \| None = None` | — | ✓ 新增（gql args 派生的 Paged） |

返回：动态 pydantic model class（白名单字段 + nested + paginated）。

### serialize_with_model（扩展）

```python
serialized = serialize_with_model(
    value=product_instance,        # SQLModel 实例 / list / dict（paginated package）
    entity=Product,
    field_tree=...,
    federation_namespace=...,      # 新增 optional
)
# serialized 是 dict / list[dict]
```

行为：`build_response_model` + `model_validate(value)` + `model_dump(mode="json")`。paginated package 走专门分支（拼 items + pagination）。

## 2. Paged field（020：model 纯形状，无 marker）

### Annotated 表达（020 后：plain result_type，无 marker）

gql selection 的 `reviews(limit: 5, order: HIGHEST_RATING)` 在 build_response_model
输出 DTO 上是 **plain `result_type`**（{items, pagination} shape），**不标任何 paged
marker**——paged 信息完全不进 model：

```python
class ProductResponse:
    reviews: ResultType    # {items, pagination} shape,plain(无 Annotated marker)
```

约定：
- paged 字段 = plain `result_type`（020 删 `PAGED_MARKER`：它功能性无人读）。
- 判 paged 在 dispatch 用 `rel_info.page_loader`（`_build_entity_field_jobs`），不读 model。
- 真实 `limit/offset/order/direction` 由 executor 注入的 `paged_provider` 闭包在 resolve
  时算（rel default + gql args merge）。
- cache key 用 `field_tree` repr（已区分 paged 形状——含 items/pagination 子键），无 paged 维。

### Resolver 处理（019 provider，不读 model）

Resolver 不扫 model 取 paged；effective Paged 在 BFS job 构建时由 `paged_provider` 算好，
塞进 `_EntityFieldJob.paged`：

```python
# executor 构造 provider 闭包（gql 知识只在此）
def provider(rel_info, field_sel, field_name):
    return Resolver._merge_paged(
        _rel_default_paged(rel_info),              # RelationshipInfo default
        _gql_args_to_paged(field_sel, field_name), # gql args（含 enum 解包）
    )

# _build_entity_field_jobs 用 rel_info.page_loader 判 paged,调 provider 塞 job.paged
# _load_entity_field_paginated 读 job.paged → PageArgs + PageLoadCommand
```

跟 specs/015 + γ `_merge_paged` 链路对齐（同一 helper）。

## 3. Resolver entity dispatch 契约（Step 3）

### Resolver._bfs_dispatch_entity_fields（新方法）

```python
class Resolver:
    async def _bfs_dispatch_entity_fields(
        self,
        parents: list[SQLModel],
        parent_entity: type[SQLModel],
        field_sel: FieldSelection,
        response_model: type[BaseModel] | None,   # 占位，当前不读（019 metadata-driven 未启用）
        *,
        store: Callable[[Any, str, Any], None],
        enable_pagination: bool = False,
        paged_provider: Callable | None = None,    # 019：executor 注入的闭包（per-call）
    ) -> None:
        """BFS 遍历 entity relationship。paged 参数从 paged_provider 拿（019），不读
        field_sel.arguments。逻辑搬迁自 query_executor._bfs_resolve。"""
```

### QueryExecutor 调用方（Step 3 后）

```python
# query_executor._resolve_result 改成
async def _resolve_result(
    self, result, entity, field_sel, *, is_pagination_root=False,
) -> None:
    if result is None:
        return
    response_model = build_response_model(entity, field_sel_to_tree(field_sel), ...)
    resolver = self._registry.create_resolver()
    if is_pagination_root:
        # paginated root 特殊处理（如现状）
        ...
    else:
        await resolver._bfs_dispatch_entity_fields(
            parents=result if isinstance(result, list) else [result],
            parent_entity=entity,
            field_sel=field_sel,
            response_model=response_model,
        )
```

### Federation dispatch 内部收敛

`fetch_remote_subtree`（β）+ `fetch_dto_subtree`（γ）只在 Resolver 内部调用：

```bash
# Step 3 完成后 grep
grep -rn "fetch_remote_subtree\|fetch_dto_subtree" src/nexusx/
# 期望：只在 resolver.py 内部，query_executor.py 不再出现
```

## 4. fetch primitive 对称（Step 4）

### fetch_remote_subtree（β-only，docstring 改）

```python
def fetch_remote_subtree(
    *, registry, rel_info, parents, selection, paged: bool = False,
) -> list[Any]:
    """Fetch a β entity federation sub-tree (entity-first gql mode only).

    One nested gql to ``rel_info``'s owning service, returning target instances
    with the whole sub-tree populated by the member. Used exclusively by
    Resolver's entity-field dispatch (Step 3 onwards).
    """
```

### fetch_dto_subtree（γ-only，新增）

```python
def fetch_dto_subtree(
    *, registry, dto_loader_cls, parents, field_name, page_params: Paged | None = None,
) -> list[Any]:
    """Fetch a γ DTO federation sub-tree (Core API / UseCase mode only).

    POST /nexusx/dto-batch to the member; member runs Resolver on its DTO
    batch root and returns a resolved DTO tree. Used exclusively by Resolver's
    DTO-field dispatch.
    """
```

## 5. feature flag 契约（Step 1 切换 → Phase 7 T028 删除）

> **当前状态（Phase 7 T028 后）**：`use_response_builder` flag 已删除。response_builder
> 现在是 entity-first gql serialize 的唯一路径。下面是 018 Step 1 的切换历史（保留作
> 设计记录）。

### GraphQLHandler.__init__ 新增参数（018 Step 1；Phase 7 T028 已删）

```python
class GraphQLHandler:
    def __init__(
        self,
        ...,
        use_response_builder: bool = False,   # 018 新增；Phase 7 T028 删除
    ):
```

| 值 | 行为 |
|----|------|
| `False`（默认） | 走旧路径（`_serialize` dict-based） |
| `True` | 走新路径（`build_response_model` + model-based） |

### QueryExecutor 接 flag

```python
class QueryExecutor:
    def __init__(self, ..., use_response_builder: bool = False):
        self._use_response_builder = use_response_builder

    def _serialize(self, result, entity, field_sel):
        if self._use_response_builder:
            return self._serialize_via_response_builder(result, entity, field_sel)
        return self._serialize_legacy(result, entity, field_sel)  # 现状
```

### 切换阶段

| 阶段 | flag 默认 | 行为 |
|------|----------|------|
| Step 1.a | `False` | 新代码就位，flag on 跑测试集 |
| Step 1.b | `False` | flag-on / flag-off 输出 diff 为空（CI matrix） |
| Step 1.c | `True` | flag 默认开，旧路径 deprecated |
| Step 1.d（Step 4 后）| （删除 flag）| 旧路径删除 |

## 不变式

- **UseCase 模式 build_subset_model** 不变（独立机制）。
- **β/γ federation 传输协议** 不变（member 端不改）。
- **entity-first 开发者 API**（`@query`、`GraphQLHandler.execute`）签名不变（只加 optional flag）。
- **零回归 gate**：每个 Step 完成必须跑 1429 全量测试 + 新加的等价性 / 边缘 case 测试。
