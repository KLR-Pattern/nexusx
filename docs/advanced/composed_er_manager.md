# ComposedErManager — composing multiple engines in one process

`ComposedErManager` combines several self-contained `ErManager`s — each wired to
its own engine/session — into a single query proxy. A resolver from the composed
manager traverses entities that live in **different databases** within one
process, with no HTTP bridge.

This is the **same-process dual of federation**:

- **federation** (specs/012, [federation.md](federation.md)): compose across
  *processes*; cross-service edges go over HTTP.
- **ComposedErManager** (specs/019): compose within *one process*; cross-engine
  edges go through an in-process DataLoader (a user-supplied closure).

```
blog engine                            shop engine
User ── posts ── Post                   Order ── items ── OrderItem
  │                                       ▲
  └─ orders ──── cross-engine edge ───────┘   (User.id → Order.user_id)
```

## How it works

- **Delegate by entity** — each entity is owned by exactly one member. The
  composed manager routes `has_entity` / `get_relationships` /
  `get_loader_for_entity` to the owning member; member entity sets must be
  mutually exclusive (duplicate registration raises at construction).
- **Cross-engine edges live on the composition layer** — a cross-engine
  relationship (`User → orders → Order`) is declared on the `ComposedErManager`,
  not on either member's entities. Members stay self-contained: used alone, they
  never know about the edge. The edge's loader is a **user-supplied closure**
  that opens the target engine's session.
- **Transparent resolve** — `composed.create_resolver()` yields one resolver;
  `resolve()` fans out across engines through the cross-engine DataLoader. The
  caller sees a single flat tree.

## Compose + declare a cross-engine edge

```python
from sqlmodel import select
from nexusx import ComposedErManager, ErManager, Relationship

blog_er = ErManager(session_factory=blog_sf, entities=[User, Post])
shop_er = ErManager(session_factory=shop_sf, entities=[Order, OrderItem])

async def orders_by_user(user_ids: list[int]) -> list[list[Order]]:
    async with shop_sf() as s:                       # target engine's session
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

The cross-engine edge is declared once, at the composition layer. `User` and
`Order` carry no reference to each other.

## Query across engines

**γ — DTO tree (Resolver)**:

```python
class OrderDTO(DefineSubset):
    __subset__ = (Order, ("id", "total"))

class UserDTO(DefineSubset):
    __subset__ = (User, ("id", "name"))
    orders: list[OrderDTO] = []

Resolver = composed.create_resolver()
resolved = await Resolver().resolve([UserDTO(id=1, name="Alice")])
# Alice.orders resolved against the shop engine, transparently
```

**β — GraphQL handler (inject the composed manager, US3)**:

```python
handler = GraphQLHandler(er_manager=composed, entities=[User, Post, Order, OrderItem])
# @query entries each fetch their own session; one query traverses blog → shop.
```

## vs federation

| | federation (012) | ComposedErManager (019) |
|---|---|---|
| Scope | across processes | within one process |
| Cross-edge transport | HTTP (one nested gql per service) | in-process DataLoader (closure) |
| Member unit | a nexusx service (own app/process) | an ErManager (own engine/session) |
| Setup | mount at startup (`await handler.federate(...)`) | construct (`ComposedErManager(members=...)`) |
| Use when | services deploy independently | one service, several databases |

## Design principles

| Decision | Why |
|---|---|
| Members are self-contained ErManagers | each owns one engine; reusable independently |
| Cross edges on the composition layer | members stay pure; the edge is a property of the composition, not of any member (DD-02) |
| Mutating ops stay on the member | `federate` / `initialize` / `add_virtual_entities` run on members, never on the composed manager (FR-013) — the composed manager only *queries* |
| `LoaderRegistry` Protocol | the composed manager satisfies the same query contract as `ErManager`, so `create_resolver` / `GraphQLHandler` injection needs no special-casing |

## Runnable demo

`demo/composed_er_manager/` runs the blog + shop two-engine example:

```bash
uv run uvicorn demo.composed_er_manager.app:app --port 8030
```

Open http://localhost:8030/graphql and query across engines:

```graphql
{ CmUser { get_users { name posts { title } orders { total } } } }
```

`posts` resolves within the blog engine; `orders` hops to the shop engine in the
same query.

See also: [Federation](federation.md) (the cross-process dual),
[Custom Relationships](../guide/custom_relationship.md).
