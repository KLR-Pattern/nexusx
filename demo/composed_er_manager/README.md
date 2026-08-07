# ComposedErManager demo — same-process multi-engine composition

Two SQLite engines (**blog** + **shop**) composed into a single GraphQL schema,
in one process. A single query traverses `blog.CmUser → shop.CmOrder` across
engines via an in-process DataLoader — **no HTTP bridge**. This is the
same-process dual of `demo/federation` (which composes across processes via
GraphQL over HTTP); see specs/019.

```
blog engine (cm_blog.db)              shop engine (cm_shop.db)
CmUser ── posts ── CmPost              CmOrder ── items ── CmOrderItem
   │                                     ▲
   └─ orders ─────────cross-engine──────┘   (CmUser.id → CmOrder.user_id)
```

The cross-engine edge `CmUser.orders → CmOrder` is **not** on the entity — it's
declared on the `ComposedErManager` (`cross_relationships=`), so each member
ErManager stays self-contained (specs/019 DD-02).

## Run

```bash
uv run uvicorn demo.composed_er_manager.app:app --port 8030
```

Open **http://localhost:8030/graphql** (GraphiQL) and query across engines:

```graphql
{
  CmUser {
    get_users {
      name
      posts { title }      # blog engine (same DB)
      orders { total }     # shop engine (cross-engine edge)
    }
  }
}
```

`get_users` fetches from the blog engine; `posts` resolves within blog; `orders`
hops to the shop engine via the composed cross-boundary loader — one query, two
engines, transparent to the client.

## How composition is declared (the developer surface)

```python
# Two self-contained ErManagers — one engine each, loader wired to its session.
blog_er = ErManager(session_factory=blog_async_session, entities=[CmUser, CmPost])
shop_er = ErManager(session_factory=shop_async_session, entities=[CmOrder, CmOrderItem])

# Compose: delegate-by-entity + the cross-engine edge declared here (DD-02).
composed = ComposedErManager(
    members=[blog_er, shop_er],
    cross_relationships=[
        (CmUser, Relationship(
            fk="id", target=list[CmOrder], name="orders", loader=orders_by_user,
        )),
    ],
)

# US3 injection path: skip base discovery, delegate resolution to the registry.
handler = GraphQLHandler(er_manager=composed, entities=[CmUser, CmPost, CmOrder, CmOrderItem])
```

Each `@query` entry fetches its own session (FR-012: multi-engine standard
queries are off — `auto_query_config` is unsupported on the injection path).

## What this demonstrates

| Property | Where |
|---|---|
| Same-process multi-engine composition | `ComposedErManager(members=[blog_er, shop_er])` |
| Cross-engine edge declared at the composition layer | `cross_relationships=` (members are unaware) |
| Single schema over multiple engines | `GraphQLHandler(er_manager=composed)` (US3 injection) |
| Cross-engine resolve, transparent | `CmUser.orders` hops to the shop engine in one query |
| In-process vs. federation's over-HTTP | dual of `demo/federation` (specs/019 vs specs/012) |

## Files

- `models.py` — `CmUser`/`CmPost` (blog) + `CmOrder`/`CmOrderItem` (shop);
  `@query` entries each fetch their own engine's session. Note `CmUser` has **no**
  `orders` field — that edge lives on the ComposedErManager.
- `database.py` — two engines, two session factories, idempotent seed data.
- `app.py` — builds the two ErManagers, composes them, injects into
  `GraphQLHandler`; FastAPI app with `/graphql` (GraphiQL) + `/schema` (SDL).
