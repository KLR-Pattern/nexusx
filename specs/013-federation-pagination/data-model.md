# Data Model

## Member Configuration

```python
@dataclass(frozen=True)
class OrderTerm:
    field: str | InstrumentedAttribute
    direction: Literal["asc", "desc"] = "asc"
    nulls: Literal["first", "last"] | None = None

@dataclass(frozen=True)
class PageOrder:
    terms: list[OrderTerm]
    description: str | None = None

@dataclass(frozen=True)
class BatchPageConfig:
    default_order: str
    orders: dict[str, PageOrder]
```

`AutoQueryConfig.batch_pages` 类型：

```python
dict[str, dict[str, BatchPageConfig]]
```

## Federation Declaration

```python
@dataclass
class RemoteRelationship:
    ...
    pagination: bool = False
    order: str | None = None
```

`order` 不能在 `pagination=False` 时设置。

## ER Wire Types

```python
class PageOrderDescriptor(BaseModel):
    name: str
    description: str | None = None

class BatchPageCapability(BaseModel):
    protocol: Literal["offset-v1"] = "offset-v1"
    default_order: str
    orders: list[PageOrderDescriptor]

class BatchRoot(BaseModel):
    name: str
    arg_name: str
    arg_type: str
    page: BatchPageCapability | None = None
```

## Runtime Metadata

分页 root 的 `_pagination_root` metadata 包含：

```python
{
    "entity": Entity,
    "fk_field": "product_id",
    "fk_type": int,
    "package_name": "ReviewProductIdPagePackage",
    "order_enum": ReviewProductIdPageOrder,
    "page_capability": BatchPageCapability(...),
}
```

`RelationshipInfo.sort_field` 保留给本地 relationship pagination。远程分页通过 `page_loader + target_service` 路由，不复用物理 sort field。
