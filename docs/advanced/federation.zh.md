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

handler = GraphQLHandler(
    base=Base, session_factory=session,
    auto_query_config=AutoQueryConfig(batch_keys={"Review": ["product_id"]}),
    service_name="reviews",
)
app = build_federable_app(handler)   # 挂载 POST /graphql + GET /nexusx/er-introspection
```

`AutoQueryConfig(batch_keys=...)` 生成 `by_product_id_in(values: list)` root
(`where field.in_(values)`)——挂载方远程 loader 驱动的入口。这是单体 nexusx 也
受益的通用能力,非联邦专属。

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
`{ Product { by_filter { id name reviews { title rating author { name } } } } }`。

## 分页

跨服务 to-many 关系可通过在 `RemoteRelationship` 上声明 `sort_field` 开启分页——它的存在即分页开关(对称本地 `Relationship.order_by`)。member 默认生成分页批量 root `by_<key>_in_page`(零配置);挂载方在声明了 `sort_field` 时路由到它,否则走普通 `by_<key>_in`。

```python
RemoteRelationship(
    fk="id", target=list[reviews.Review],
    name="reviews", join_remote="product_id",
    sort_field="rating",           # ← 声明即开启分页
    sort_direction="desc",         # 可选,默认 "asc"
)
```

查询时带 `limit`/`offset`;`total_count` 可选(仅在选择时计算):

```graphql
{ Product { by_filter {
  reviews(limit: 5, offset: 0) {
    items { title rating }
    pagination { has_more total_count }
  }
} } }
```

分页发生在数据所在的 member(按 join key 的窗口函数);挂载方每次遍历对每个被挂服务发一条 gql,并按 join key 对齐 per-key 分页包。`items` 子树(嵌套关系,含更深的跨服务跳转)由 member 在这一条 gql 内解析。

相关:[自定义关系](../guide/custom_relationship.zh.md)、
[ER 图可视化](voyager.zh.md)。
