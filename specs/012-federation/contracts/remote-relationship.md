# 契约:RemoteRelationship 声明 API

**特性**:`specs/012-federation` | 对应 FR-001/FR-002/FR-004

这是联邦特性的**用户面 API**:开发者用它声明跨服务关系。与既有 `Relationship`(本地 custom 关系)并列。

## 数据类

```python
@dataclass
class RemoteRelationship:
    name: str                     # 关系名 = 挂载方实体上的字段名
    target: str                   # "<srv>.<typename>" 标记字符串(非 Python 类型)
    join_local: str               # 挂载方实体上的 join key 字段
    join_remote: str              # 被挂类型上的对应字段(须有 by_<join_remote>_in root)
    is_list: bool = False         # True=to-many, False=to-one
    description: str | None = None
```

## 声明方式(挂载方实体)

放进实体的 `__relationships__`,与本地 `Relationship` 混列:

```python
from nexusx import Relationship
from nexusx.federation import RemoteRelationship

class Product(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str

    __relationships__ = [
        Relationship(fk="id", target=list[Tag], name="tags", loader=tags_loader),  # 本地 custom(不变)
        RemoteRelationship(                                                         # 跨服务
            name="reviews",
            target="reviews.Review",        # 标记字符串
            join_local="id",
            join_remote="product_id",
            is_list=True,
        ),
    ]
```

## 远程→远程边(挂在物化的远程类型上)

因挂载方不拥有远程类,这类边在 `federate()` 配置里声明(不能 co-location 到远程类体):

```python
await er.federate(
    services={"reviews": "http://reviews:8000", "users": "http://users:8000"},
    remote_edges=[
        # source 形如 "<srv>.<typename>.<field>"
        RemoteEdge(source="reviews.Review.author", target="users.User",
                   join_local="author_id", join_remote="id", is_list=False),
    ],
)
```

## 不变量(契约承诺)

- `target` **不是** Python 类型注解,不参与 Pydantic forward-ref 解析;框架扫描时 parse 为 `("srv","typename")`(FR-002)。
- **不内联 loader**;loader 由框架在 `federate()` 组合时生成为 `RemoteLoader`(FR-001)。
- `target` 必须 parse 为恰两段;否则 init 校验 fail-fast(FR-013a)。
- 既有 `Relationship`(`target` 为类、`loader` 必填)语义零变化。

## 相关
- [er-introspection.md](./er-introspection.md):`target` 解析依赖的 ER 片段来源。
- [batch-query-root.md](./batch-query-root.md):`join_remote` 必须有对应的 `by_<key>_in` root。
- spec FR-001/FR-002/FR-004;plan Project Structure `federation/relationship.py`。
