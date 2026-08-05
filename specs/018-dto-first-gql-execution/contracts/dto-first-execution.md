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

## 2. Paged field metadata 协议（Step 2）

### Annotated 表达

gql selection 的 `reviews(limit: 5, order: HIGHEST_RATING)` 在 build_response_model 输出 DTO 上表达为：

```python
class ProductResponse:
    reviews: Annotated[
        list[ReviewsItemResponse],
        Paged(limit=5, order="HIGHEST_RATING", direction=None),
    ]
```

约定：
- 字段类型必须是 `list[X]`（or `list[X] | None`），X 是 nested model。
- metadata 必须是单个 `Paged` 实例（不允许 `Annotated[list[X], Paged(...), Other(...)]`）。
- 缺省（无 gql args）→ 字段类型是 `list[X]`（不带 Annotated），Resolver 走 plain loader。

### Resolver 处理 Paged metadata

Resolver 扫描 DTO 字段，遇到 `Annotated[list[X], Paged(...)]`：

```python
hint = typing.get_type_hints(dto_cls, include_extras=True)[field_name]
meta = next(m for m in typing.get_args(hint)[1:] if isinstance(m, Paged))
# meta.limit / meta.offset / meta.order / meta.direction → PageLoadCommand
```

跟 specs/015 + γ Paged default + caller override 链路对齐：gql args 派生的 Paged 跟 field Annotated 的 Paged default 合并（caller override wins）。

## 3. Resolver entity dispatch 契约（Step 3）

### Resolver._bfs_dispatch_entity_fields（新方法）

```python
class Resolver:
    async def _bfs_dispatch_entity_fields(
        self,
        parents: list[SQLModel],
        parent_entity: type[SQLModel],
        field_sel: FieldSelection,
        response_model: type[BaseModel],   # build_response_model 输出
    ) -> None:
        """BFS 遍历 entity relationship，按 response_model 的 Paged metadata 触发 loader。
        逻辑搬迁自 query_executor._bfs_resolve，零行为变化。
        """
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

## 5. feature flag 契约（Step 1 切换）

### GraphQLHandler.__init__ 新增参数

```python
class GraphQLHandler:
    def __init__(
        self,
        ...,
        use_response_builder: bool = False,   # ★ 新增，默认 False（旧路径）
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
