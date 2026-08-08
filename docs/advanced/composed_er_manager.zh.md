# ComposedErManager —— 同进程多 engine 组合

`ComposedErManager` 把多个自洽的 `ErManager`（各自焊死自己的 engine/session）
组合成一个查询代理。组合体产出的 resolver 能在一次 resolve 里跨过**不同数据库**
的实体，全程在单进程内，无 HTTP 桥。

它是 **federation 的同进程对偶**：

- **federation**（specs/012，见 [federation.zh.md](federation.zh.md)）：跨**进程**组合，
  跨服务关系走 HTTP。
- **ComposedErManager**（specs/019）：在**单一进程**内组合，跨 engine 关系走进程内
  DataLoader（用户提供的闭包）。

```
blog engine                            shop engine
User ── posts ── Post                   Order ── items ── OrderItem
  │                                       ▲
  └─ orders ──── 跨 engine 边 ────────────┘   (User.id → Order.user_id)
```

## 工作原理

- **按 entity 委托** —— 每个实体只属于一个 member。组合体把 `has_entity` /
  `get_relationships` / `get_loader_for_entity` 路由到所属 member；成员实体集必须
  互斥（重复注册在构造时报错）。
- **跨 engine 关系在组合体层声明** —— 跨 engine 关系（`User → orders → Order`）声明在
  `ComposedErManager` 上，不在任一 member 的实体上。成员保持自洽：单独使用时对这条边
  无感。这条边的 loader 是**用户提供的闭包**，内部打开目标 engine 的 session。
- **resolve 透明** —— `composed.create_resolver()` 产出单一 resolver；`resolve()` 经
  跨 engine DataLoader 扇出。调用方看到一棵扁平的树。

## 组合 + 声明跨 engine 边

```python
from sqlmodel import select
from nexusx import ComposedErManager, ErManager, Relationship

blog_er = ErManager(session_factory=blog_sf, entities=[User, Post])
shop_er = ErManager(session_factory=shop_sf, entities=[Order, OrderItem])

async def orders_by_user(user_ids: list[int]) -> list[list[Order]]:
    async with shop_sf() as s:                       # 用目标 engine 的 session
        result = await s.exec(select(Order).where(Order.user_id.in_(user_ids)))
    by: dict[int, list[Order]] = {}
    for o in result.all():
        by.setdefault(o.user_id, []).append(o)
    return [by.get(uid, []) for uid in user_ids]

composed = ComposedErManager(
    members=[blog_er, shop_er],
    cross_relationships=[
        (User, Relationship(
            fk="id", target=list[Order], name="orders", loader=orders_by_user,
        )),
    ],
)
```

跨 engine 边在组合体层声明一次。`User` 与 `Order` 互不引用。

## 跨 engine 查询

**γ —— DTO 树（Resolver）**：

```python
class OrderDTO(DefineSubset):
    __subset__ = (Order, ("id", "total"))

class UserDTO(DefineSubset):
    __subset__ = (User, ("id", "name"))
    orders: list[OrderDTO] = []

Resolver = composed.create_resolver()
resolved = await Resolver().resolve([UserDTO(id=1, name="Alice")])
# Alice.orders 透明地在 shop engine 上 resolve
```

**β —— GraphQL handler（注入组合体，US3）**：

```python
handler = GraphQLHandler(er_manager=composed, entities=[User, Post, Order, OrderItem])
# @query 入口各自取自己的 session；一次查询跨 blog → shop。
```

## 与 federation 对比

| | federation（012） | ComposedErManager（019） |
|---|---|---|
| 范围 | 跨进程 | 单进程内 |
| 跨边传输 | HTTP（每个服务一条嵌套 gql） | 进程内 DataLoader（闭包） |
| 成员单位 | 一个 nexusx service（独立 app/进程） | 一个 ErManager（独立 engine/session） |
| 装配 | 启动时 mount（`await handler.federate(...)`） | 构造（`ComposedErManager(members=...)`） |
| 适用场景 | 服务独立部署 | 单服务、多数据库 |

## 设计原则

| 决策 | 原因 |
|---|---|
| member 是自洽的 ErManager | 各自独占一个 engine；可独立复用 |
| 跨边在组合体层声明 | member 保持纯粹；跨边是组合的属性，不属于任一 member（DD-02） |
| mutating 操作留在 member | `federate` / `initialize` / `add_virtual_entities` 在 member 上做，从不在组合体上（FR-013）—— 组合体只查询 |
| `LoaderRegistry` Protocol | 组合体满足与 `ErManager` 相同的查询契约，故 `create_resolver` / `GraphQLHandler` 注入无需特殊处理 |

## 可运行 demo

`demo/composed_er_manager/` 跑 blog + shop 双 engine 示例：

```bash
uv run uvicorn demo.composed_er_manager.app:app --port 8030
```

打开 http://localhost:8030/graphql，跨 engine 查询：

```graphql
{ CmUser { get_users { name posts { title } orders { total } } } }
```

`posts` 在 blog engine 内 resolve；`orders` 在同一查询里跳到 shop engine。

参见：[Federation](federation.zh.md)（跨进程对偶）、[自定义关系](../guide/custom_relationship.md)。
