# Federation demo — nexusx-to-nexusx (relative composition)

Three nexusx services that compose into one unified graph. **No router/gateway**:
every service can mount others. A single query to `catalog` traverses
`catalog → reviews → users` transparently; each mounted service receives
exactly one nested GraphQL query and resolves its own subgraph.

Each service hosts **≥2 levels** of relationships, so one query walks the full
multi-branch chain `Product → Review → Comment → User → UserConfig`:

```
catalog :8022                     reviews :8021                    users :8020
Product                           Review ── comments ── Comment     User ── config ── UserConfig
   │                                  │                    │        │
   └─ reviews ─────────▶ reviews.Review              author ─▶ users.User
```

- `catalog` mounts `reviews` (`Product.reviews → reviews.Review`).
- `reviews` mounts `users` (`Comment.author → users.User`) — reviews is itself a
  federating service (relative composition: any nexusx service can mount).
- `reviews` and `users` each host a **local** second level (`Review→Comment`,
  `User→UserConfig`) resolved within their own gql response.
- `catalog` reaches `users` **transitively** through `reviews` — it never
  declares `users` explicitly (FR-005).

## Run

Start the three services in order (later ones retry until their dependencies are up):

```bash
uv run uvicorn demo.federation.users_app:app   --port 8020 &
uv run uvicorn demo.federation.reviews_app:app --port 8021 &
uv run uvicorn demo.federation.catalog_app:app --port 8022 &
```

Open **http://localhost:8022/** (GraphiQL on the catalog service) and run the
deep chain:

> **Voyager (composed-graph ER diagram):** open **http://localhost:8022/voyager**
> on the catalog service and switch to the **ER diagram** tab. Because catalog is
> the composition entry, the diagram shows the full federated graph — local
> `Product` plus materialized `reviews.Review` / `reviews.Comment` /
> `users.User` / `users.UserConfig`, each tagged with its owning service (FR-016).
> (Edges currently render uniformly; cross-service edge styling is a planned
> enhancement.)

```graphql
{
  Product {
    by_filter {
      id
      name
      reviews(limit: 5) {
        items {
          title
          rating
          comments { text author { name config { theme } } }
        }
        pagination { has_more total_count }
      }
    }
  }
}
```

One query → catalog sends **one** nested gql to reviews → reviews resolves
`Review → Comment` locally and `Comment.author` against users (one gql to users,
which resolves `User → UserConfig` locally) → catalog returns the fully-nested
result. No service prefix leaks to the client; each service is called once.

## How federation is declared (the developer surface)

```python
# reviews_app.py — declare the remote type + its url once
users = RemoteService("users", url="http://localhost:8020")

class Comment(ReviewsBase, table=True):
    author_id: int
    __relationships__ = [RemoteRelationship(
        fk="author_id", target=users.User,                # RemoteRef, not a string
        name="author", join_remote="id",
    )]

# at startup — services are derived from the declarations, no services= arg
await handler.er.initialize()
```

## What this demonstrates

| Property | Where |
|---|---|
| Relative composition (no router) | every service calls `handler.er.initialize()` |
| ER introspection (not SDL) | `GET /nexusx/er-introspection` on each member |
| Transitive discovery | catalog reaches `users` via `reviews`' fragment |
| β nested fetch | one gql per service returns the multi-level nested chain |
| Multi-level members | `Review→Comment` and `User→UserConfig` resolved locally per service |
| `by_<key>_in` entry roots | `AutoQueryConfig(batch_keys=...)` on each member |
| Member-owned pagination order | `AutoQueryConfig(batch_pages=...)` on reviews |
| Voyager on the composed graph | `http://localhost:8022/voyager` (ER tab) — catalog only |

## UseCase composition over federated data (DefineSubset + Resolver)

`catalog` also exposes a **UseCaseService** (`composed_tree`) that composes the
cross-service graph into a DTO tree via **DefineSubset + Resolver** — declaratively,
no manual per-row assembly, no gql string.

```bash
curl -X POST http://localhost:8022/api/catalog_service/composed_tree \
  -H 'Content-Type: application/json' -d '{}'
# [{"id":1,"name":"Widget","reviews":[
#    {"title":"Great widget","rating":5},
#    {"title":"Works okay","rating":3}]}, ...]
```

**β vs γ, in one place:**
- The **gql (β) path** (the query above) traverses the *full* chain, including
  edges local to a member (`Review→Comment`, `User→UserConfig`) — those are
  resolved inside the member's own gql response.
- The **Resolver (γ) path** (`composed_tree`) traverses **cross-service** edges
  (`Product → Review`). Edges local to a member are β's job, so the Resolver tree
  is the cross-service projection. (Hence the DTOs below stop at `Review`.)

```python
# reviews service: member PUBLIC DTO (016 γ) — exposed via dto_classes=[ReviewDTO]
class ReviewDTO(DefineSubset):
    __subset__ = SubsetConfig(
        kls=reviews.Review, fields=("title", "rating", "product_id"),
        federation_public=True, federation_join_key="product_id",
    )
    __pagination_orders__ = BatchPageConfig(
        default_order="HIGHEST_RATING",
        orders={"HIGHEST_RATING": PageOrder([OrderTerm("rating", "desc")])},
    )

# catalog service: DTO references the member public DTO + Paged default (top-N)
class ProductDTO(DefineSubset):
    __subset__ = (Product, ("id", "name"))
    reviews: Annotated[list[rev_svc.ReviewDTO], Paged(limit=2)] = Field(
        default_factory=list
    )
```

The Resolver auto-loads `Product → Review` over federation, slicing per-parent
via the member batch root's SQL-level top-N (order omitted → member's
`default_order`); `model_dump` serializes the tree.

## Files

- `users_app.py` — leaf; `User ── UserConfig` (local one-to-one) + `by_id_in`.
- `reviews_app.py` — mounts users; `Review ── Comment` (local one-to-many),
  `Comment.author → users.User`, + full and paginated product batch roots.
- `catalog_app.py` — entry service clients query; mounts reviews; DefineSubset DTOs;
  mounts Voyager at `/voyager` over the composed federated graph.
- `_common.py` — shared FastAPI app builder (`/graphql` + ER introspection +
  GraphiQL) and an `initialize`-with-retry helper for boot ordering.
