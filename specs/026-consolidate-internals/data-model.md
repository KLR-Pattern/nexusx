# Data Model: 026 内部收敛（M1）

本里程碑不改变 wire 数据；下列为**进程内**类型的变化。

## 1. 新增叶子模块 `nexusx/annotation_utils.py`

| 符号 | 签名 | 说明 |
|---|---|---|
| `is_optional(anno) -> bool` | `Optional[X]` / `X \| None` 判定 | 统一 `typing.Union` 与 `types.UnionType` |
| `unwrap_optional(anno) -> Any` | 去掉 `None` 臂 | 非 Optional 原样返回 |
| `is_list(anno) -> bool` | `list[X]` 判定 | 不解 `Annotated`/`Mapped`，调用方先 `strip_annotated` |
| `list_inner(anno) -> Any` | 取 `list[X]` 的 `X` | 无参返回原值 |
| `strip_annotated(anno) -> Any` | 去 `Annotated[...]` 外壳 | 递归至非 Annotated |
| `is_mapped_wrapper(anno) -> bool` / `unwrap_mapped(anno) -> Any` | SQLAlchemy `Mapped[T]` | 保持现有按 `__name__` 判定的实现 |
| `core_types(anno) -> list[type]` | 解到底层类型列表 | 现有 `utils/schema_helpers.get_core_types` 的实现上移 |
| `is_pydantic(tp) -> bool` | `tp` 为 `BaseModel` 子类 | 替代散落的 `_safe_issubclass(x, BaseModel)` |
| `unwrap_func(obj) -> Callable` | classmethod / bound method → 函数 | 替代 21 处 `x.__func__ if hasattr(x, "__func__") else x` |

`nexusx.utils.type_utils.is_list_annotation` / `map_annotation` 迁入并从原处 re-export一个版本周期（M4 删）。

## 2. 关系变体（`loader/registry.py`）

```python
RelationshipDirection = Literal["MANYTOONE", "ONETOMANY", "ONETOMANY_SCALAR", "MANYTOMANY", "CUSTOM"]

class RelationshipInfo(ABC, dataclass(kw_only=True, frozen=True)):
    direction: RelationshipDirection            # 原 str
    ...                                           # 其余不变
    @abstractmethod can_paginate / is_paginated  # 显式抽象
    def loader_classes(self) -> tuple[type[DataLoader], ...]: ...   # 新增，默认 ()

LocalRelationship.loader: type[DataLoader]       # 原 `| None = None` → 必填
RemotePlainRelationship.loader: type[DataLoader] # 同上
RemotePagedRelationship.loader / page_loader     # 均必填
```

模块级收口函数：`plain_loader_of(rel) -> type[DataLoader] | None`（Coalesced → None）、`page_capability_of(rel) -> BatchPageCapability | None`（Local/RemotePaged 之外的变体 → None）。

## 3. `BatchPageCapability` 位置

`nexusx.loader.pagination.BatchPageCapability`（定义）；`nexusx.federation.contract.BatchPageCapability`（re-export，wire JSON 字段不变：`default_order` / `orders[{name, description}]`）。

## 4. `Decimal` 标量

`SCALAR_TYPE_MAP[decimal.Decimal] = "Decimal"`；introspection 标量列表加 `Decimal`；compose `_SCALAR_NAMES` 同步。wire 值：字符串（与 pydantic `model_dump(mode="json")` 现状一致，不另定序列化）。
