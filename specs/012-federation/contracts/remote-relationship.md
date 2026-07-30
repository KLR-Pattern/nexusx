# 契约:RemoteRelationship 声明 API

**特性**:`specs/012-federation` | 对应 FR-001/FR-002/FR-004

这是联邦特性的**用户面 API**:开发者用它声明跨服务关系。与既有 `Relationship`(本地 custom 关系)并列,且**形状与之对齐**。

## 设计对齐

`RemoteRelationship` 的形状刻意贴近 `Relationship`,共用同一套词汇:

| 槽位 | `Relationship`(本地) | `RemoteRelationship`(远程) |
|---|---|---|
| 源侧 join key | `fk` | `fk`(同名同义) |
| 目标类型 | `target=Tag` 或 `target=list[Tag]` | `target=reviews.Review` 或 `target=list[reviews.Review]` |
| 关系名 | `name` | `name` |
| 加载机制 | `loader=<async 批量函数>`(内联) | `join_remote=<远端字段名>`(框架据此合成 loader) |

唯一**结构性差异**是加载槽:本地关系直接给函数;远程关系给远端字段名,由框架在 `federate()` 组合时生成为 `RemoteLoader`(调用被挂服务的 `by_<join_remote>_in` 批量 root)。多值性两者用同一种约定表达——`target=list[X]`。

## 数据类

```python
@dataclass
class RemoteRelationship:
    fk: str                              # 源实体上用作 join key 的字段(同 Relationship.fk)
    target: RemoteRef | list[RemoteRef]  # RemoteService("srv").TypeName;list[...]=to-many
    name: str                            # 关系名 = 挂载方实体上的字段名
    join_remote: str                     # 被挂类型上的对应字段(须有 by_<join_remote>_in root)
    description: str | None = None
    # is_list 由 target 是否包 list[...] 派生(init=False),不由调用方传入
```

## 声明方式(挂载方实体)

放进实体的 `__relationships__`,与本地 `Relationship` 混列:

```python
from nexusx import Relationship
from nexusx.federation import RemoteRelationship, RemoteService

reviews = RemoteService("reviews")
users = RemoteService("users")

class Product(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str

    __relationships__ = [
        Relationship(fk="id", target=list[Tag], name="tags", loader=tags_loader),  # 本地(不变)
        RemoteRelationship(                                                         # 跨服务(to-many)
            fk="id",
            target=list[reviews.Review],
            name="reviews",
            join_remote="product_id",
        ),
    ]
```

to-one 形态(`target` 不包 `list[...]`):

```python
RemoteRelationship(fk="author_id", target=users.User, name="author", join_remote="id")
```

## 归属规则:跨服务边由源类型的拥有者声明

每条跨服务关系都由**源类型的拥有者**在自己的类上用 `RemoteRelationship`
声明——一个 app 只维护自己拥有的类型上的出边,不越界给别的服务定义关系。
挂载方通过**传递式 ER 拉取**自动继承被挂服务声明的边:catalog 挂 reviews,
而 reviews 在 `Review.__relationships__` 上声明了 `author → users.User`,则
catalog 拉到的 ER 片段就带这条边,自动物化进组合图,挂载方一行都不用写。

因此**不存在**"挂载方在物化的、不属于自己的远程类型上贴边"的机制(早期设计
里的 `RemoteEdge`/`federate(remote_edges=…)` 已移除):那会破坏 app 之间的
封装边界,让挂载方去断言它不拥有的类型的领域关系。若某条跨服务边需要存在,
由源类型的拥有者声明即可。

## 不变量(契约承诺)

- `target` 是 `RemoteRef`(`RemoteService("srv").TypeName`),**不是** Python 类型注解,不参与 Pydantic forward-ref 解析;框架扫描时 parse 为 `("srv","typename")`(FR-002)。
- `target=list[RemoteRef]` 表示 to-many,`target=RemoteRef` 表示 to-one;`is_list` 由此派生,调用方不传。
- **不内联 loader**;loader 由框架在 `federate()` 组合时生成为 `RemoteLoader`(FR-001)。
- `target` 的 RemoteRef 必须 parse 为恰两段;否则 init 校验 fail-fast(FR-013a)。
- 既有 `Relationship`(`target` 为类、`loader` 必填)语义零变化。

## 相关
- [er-introspection.md](./er-introspection.md):`target` 解析依赖的 ER 片段来源。
- [batch-query-root.md](./batch-query-root.md):`join_remote` 必须有对应的 `by_<key>_in` root。
- spec FR-001/FR-002/FR-004;plan Project Structure `federation/relationship.py`。
