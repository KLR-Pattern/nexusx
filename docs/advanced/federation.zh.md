# 联邦(Federation)——组合多个 nexusx 服务

nexusx 联邦让一个 nexusx 服务**挂载**其他 nexusx 服务,组合成一张统一的图。
没有 gateway、没有特权 router——挂载是每个 nexusx 服务对称具备的能力(相对
组合)。一条查询进入哪个服务,就由那个服务编排:对每个被挂服务发**一条**
嵌套 GraphQL 查询,被挂服务用自己的 executor 解析自己的子图。

这是**同构联邦**:每个成员都是 nexusx 服务。它不是面向第三方 GraphQL 的通用
supergraph 网关。

```
catalog (Product)  ──reviews──▶  reviews (Review)  ──author──▶  users (User)
```

## 工作原理

- **启动期挂载**(async,放 lifespan):`await handler.federate(services={"reviews": "http://...:8021"})`。挂载方拉取每个成员的 **ER 图**(不是 SDL),经 `GET /nexusx/er-introspection`,物化远程类型、校验、冻结——错配启动期 fail-fast。
- **查询期取数**:解析远程字段时,对被挂服务发**一条**嵌套 GraphQL 查询(以 `by_<key>_in` 为入口)。被挂服务解析自己的组合子图并返回成型数据,跨服务 N+1 结构性不可能。
- **传递可达**:挂载一个服务 = 挂载它整个查询面,含它自己挂载的下游。`catalog` 挂 `reviews` 就能触达 `users`(`reviews` 自己挂的),无需 `catalog` 声明 `users`。

## 声明跨服务关系

`RemoteRelationship` 放在实体的 `__relationships__` 里,与本地 `Relationship`
并列。它的 `target` 是 `"服务名.类型名"` **标记字符串**,不是 Python 类型。

```python
from nexusx.federation import RemoteRelationship, RemoteService

reviews = RemoteService("reviews")

class Product(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[reviews.Review],
            name="reviews", join_remote="product_id",
        ),
    ]
```

## 暴露一个可被挂载的成员

成员须暴露 GraphQL 面 + ER 内省,以及挂载方要用到的每个 join key 的批量入口
root:

```python
from nexusx.federation.introspect import build_federable_app

# 在 entity 上声明联邦 join key(specs/020)——member 的批量入口根从这里生成,
# 不再来自 AutoQueryConfig。
class Review(Base, table=True):
    __tablename__ = "review"
    __federation_keys__ = ["product_id"]   # → 生成 by_product_id_in(values)

handler = GraphQLHandler(
    base=Base, session_factory=session,
    auto_query_config=AutoQueryConfig(),    # 现在只持开关(default_limit 等)
    service_name="reviews",
)
app = build_federable_app(handler)   # 挂载 POST /graphql + GET /nexusx/er-introspection
```

`__federation_keys__` 为每个声明字段生成 `by_<key>_in(values: list)` root
(`WHERE key IN (values)`)——挂载方远程 loader 驱动的入口。`AutoQueryConfig`
现在只持开关(`default_limit`、`generate_by_id` 等)。

## 挂载 + 查询

```python
# catalog 启动(FastAPI lifespan)
await handler.federate(services={"reviews": "http://localhost:8021"})

# 一条查询贯穿 catalog → reviews →(传递)users
await handler.execute("{ Product { by_filter { id reviews { title author { name } } } } }")
```

客户端看到的是无前缀的扁平 schema(`Review`、`User`、`Product.reviews`、
`Review.author`)——服务边界对客户端不可见。

## 设计原则

| 决定 | 为什么 |
|---|---|
| 组合数据源用 ER 图,不是 SDL | SDL 丢 FK/基数;ER 是单一真相(与 Voyager/executor 同源) |
| `"srv.TypeName"` 标记,不是 Python 类型 | 带点号的名字会与 Pydantic/mypy 打架;parse 的标记避开 |
| 物化类型用裸 `__name__` | 内部注册表按类对象建键;前缀不外泄到 schema |
| 每服务一条嵌套 gql 查询 | 把 nexusx"每服务一次批量"的保证带过联邦边界 |
| init 期物化 + fail-fast | 错配在启动期暴露,绝不留到查询时 |

## 可运行 demo

`demo/federation/` 跑全部三个服务;`bash start_all.sh` 启动。打开
http://localhost:8022/(catalog 服务的 GraphiQL),查
`{ Product { by_filter { id name reviews(limit:5) { items { title rating } pagination { has_more } } } } }`。

## 分页

分页和物理排序归数据所在的 member。声明了 `__pagination_orders__`(单一排序
profile)的 entity,其**每个** federation key 都会额外生成 `page_by_<key>_in`
分页根(与 `by_<key>_in` 共存);实际列名和方向不跨服务暴露。排序是 entity 自己
的属性 —— 与用哪个 federation key 作入口正交。

```python
from nexusx import BatchPageConfig, OrderTerm, PageOrder

class Review(Base, table=True):
    __tablename__ = "review"
    __federation_keys__ = ["product_id"]          # 入口字段
    __pagination_orders__ = BatchPageConfig(      # entity 自己的排序(单一)
        default_order="NEWEST",
        orders={
            "NEWEST": PageOrder([OrderTerm("created_at", "desc")]),
            "HIGHEST_RATING": PageOrder([OrderTerm("rating", "desc")]),
        },
    )
    # federation_keys 决定入口字段;__pagination_orders__ 决定排序 —— 正交。
    # 一个 profile 服务所有 federation key。
```

查询者在查询期挑选其中一个 profile，并指定方向（`ASC`/`DESC`）。挂载方把
profile 名渲染成 schema 的 enum，并在关系字段上加 `order`/`direction`
参数 —— `RemoteRelationship` 不声明 pagination（specs/021：联邦分页自动，
member 有 `__pagination_orders__` → mounter 自动走 `page_by_`，查询参数
`limit`/`order` 运行时驱动 top-N）：

```python
RemoteRelationship(
    fk="id", target=list[reviews.Review],
    name="reviews", join_remote="product_id",
    # 无 pagination 参数 —— member 有 __pagination_orders__ 时自动分页
)
```

省略 `order` 使用 member 的 `default_order`；省略 `direction` 使用 profile 的
默认方向。`total_count` 可选（仅在选择时计算）：

```graphql
{ Product { by_filter {
  reviews(limit: 5, offset: 0, order: HIGHEST_RATING, direction: DESC) {
    items { title rating }
    pagination { has_more total_count }
  }
} } }
```

`direction` 覆盖 profile 的默认方向，**nulls 跟随翻转**（`desc + nulls_last`
⇄ `asc + nulls_first`），因此翻转得到的是严格相反的顺序（含 NULL 位置）。
每个 profile 只能单列（多列 profile 在 member 启动期被拒绝）——这让翻转无歧
义。排序 *字段* 仍封闭：查询者只能在 member 发布的名字集合里选名 + 翻方向，
索引控制权始终在 member（查询者无法 `order by` 无索引列）。

分页发生在数据所在的 member(按 join key 的窗口函数);挂载方每次遍历对每个被挂服务发一条 gql,并按 join key 对齐 per-key 分页包。`items` 子树(嵌套关系,含更深的跨服务跳转)由 member 在这一条 gql 内解析。
内部调用为 `page_by_<key>_in(keys, order, direction, limit, offset)`；ER contract
只暴露 profile 名和描述，不暴露物理排序字段。

相关:[自定义关系](../guide/custom_relationship.zh.md)、
[ER 图可视化](voyager.zh.md)。

## DTO 联邦(γ)——在 DTO 层组合

β 通过 gql 组合**实体**图;**γ 在 DTO 层组合**:member 把部分 `DefineSubset` DTO
声明为 **public**,mounter 自己的 DTO 字段直接引用它们——Resolver 自动跨服务加载
这棵树,无 gql 字符串、无手写组装。

### Member 侧:发布 public DTO

```python
class ReviewDTO(DefineSubset):
    __subset__ = SubsetConfig(
        kls=Review, fields=("title", "rating", "product_id"),
        federation_public=True,              # 通过 dto-introspection / dto-batch 暴露
        # join key + order profile 现在都从源 entity 读:
        #   join key  ← Review.__federation_keys__(单 key 自动)
        #   order     ← Review.__pagination_orders__ (entity 单一排序)
        # 多 federation key 时用 federation_key="product_id" 选择。
    )

handler = GraphQLHandler(base=Base, ..., service_name="reviews")
# ReviewDTO federation_public=True → 自动发现（022），不需 dto_classes
```

Member 额外暴露两个端点:`GET /nexusx/dto-introspection`(public DTO 片段)和
`POST /nexusx/dto-batch`(按 join key 批量取数,跑 member 自己的 Resolver——`resolve_*`
方法和嵌套出边都生效)。

### Mounter 侧:引用 member DTO

```python
class ProductDTO(DefineSubset):
    __subset__ = (Product, ("id", "name"))
    reviews: Annotated[list[rev_svc.ReviewDTO], Paged(limit=2)] = Field(
        default_factory=list
    )
```

`Paged(...)` 默认值驱动 member 侧 SQL 层 top-N(经其 `__pagination_orders__`
profile);它在字段上固化——运行时入参应在 UseCase 方法签名上,不在 Resolver context。member 值是只读的——mounter 用自己 DTO 上的 `resolve_*` / `post_*` 加字段,不修改 member 值。

### β vs γ 一览

| | β (gql) | γ (UseCase/Resolver) |
|---|---|---|
| 组合单元 | 实体关系(`RemoteRelationship`) | public DTO 引用(`DefineSubset` 字段) |
| 遍历方式 | 每层每挂载服务一次嵌套 gql | Resolver `_batch_auto_load` 走 `dto-batch` |
| 分页 | 关系字段上的 gql 参数 | `Paged(...)` 字段默认(固化) |
| 入口 | `GraphQLHandler` schema | `UseCaseService` + `create_resolver()` |
| member 值 | 实例 | DTO(只读;mounter 自己计算) |

## 从 pre-020 迁移(`batch_keys` / `batch_pages` / `federation_join_key`)

联邦 member 配置现在声明在 entity 上;`AutoQueryConfig` 和 `SubsetConfig` 不再承载它。迁移:

| 旧(020 移除) | 新 |
|---|---|
| `AutoQueryConfig(batch_keys={"Review": ["product_id"]})` | `Review.__federation_keys__ = ["product_id"]` |
| `AutoQueryConfig(batch_pages={"Review": {"product_id": ...}})` | `Review.__pagination_orders__ = BatchPageConfig(...)` (entity 单一排序) |
| `SubsetConfig(federation_join_key="product_id")` | 从 `Review.__federation_keys__` 推导(单 key 自动;多 key 用 `federation_key=` 选) |
| `DefineSubset` 上的 DTO 级 `__pagination_orders__` | 从源 entity 的单一 `__pagination_orders__` 读 |

一个 federation key 总会生成 `by_<key>_in` 根;若 entity 声明了
`__pagination_orders__`,每个 federation key 都额外生成 `page_by_<key>_in`
(两者共存——分页联邦关系同时 wire full 和 paged 两个 loader)。本地关系分页
读 **target** entity 的 `__pagination_orders__`(如 `Review.comments` 分页时读
`Comment` 的排序)——在被排序对象上声明一次,每个 owner 复用。

可运行示例见 `demo/federation/`(reviews 发布 `ReviewDTO`;catalog 的
`ProductDTO` 引用它)。
