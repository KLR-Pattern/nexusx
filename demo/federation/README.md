# Federation demo — nexusx-to-nexusx (relative composition)

Three nexusx services that compose into one unified graph. **No router/gateway**:
every service can mount others. A single query to `catalog` traverses
`catalog → reviews → users` transparently; each mounted service receives
exactly one nested GraphQL query.

```
catalog (Product)  ──reviews──▶  reviews (Review)  ──author──▶  users (User)
   :8022                          :8021                         :8020
```

- `catalog` mounts `reviews` (`Product.reviews → reviews.Review`).
- `reviews` mounts `users` (`Review.author → users.User`) — reviews is itself a
  federating service (relative composition: any nexusx service can mount).
- `catalog` reaches `users` **transitively** through `reviews` — it never
  declares `users` explicitly (FR-005).

## Run

```bash
bash start_all.sh          # starts every demo incl. the 3 federation services
```

Or individually (in this order; later ones retry until dependencies are up):

```bash
uv run uvicorn demo.federation.users_app:app   --port 8020 &
uv run uvicorn demo.federation.reviews_app:app --port 8021 &
uv run uvicorn demo.federation.catalog_app:app --port 8022 &
```

Open **http://localhost:8022/** (GraphiQL on the catalog service) and run:

```graphql
{
  Product {
    by_filter {
      id
      name
      reviews { title rating author { name email } }
    }
  }
}
```

One query → catalog sends **one** nested gql to reviews → reviews resolves
`author` internally (one gql to users) → catalog returns the fully-nested
result. No service prefix leaks to the client; each service is called once.

## What this demonstrates

| Property | Where |
|---|---|
| Relative composition (no router) | every service calls `handler.federate(...)` |
| ER introspection (not SDL) | `GET /nexusx/er-introspection` on each member |
| Transitive discovery | catalog reaches `users` via `reviews`' fragment |
| β nested fetch | one gql per service returns multi-level nested data |
| `by_<key>_in` entry roots | `AutoQueryConfig(batch_keys=...)` on each member |

## UseCase projection over federation data (DefineSubset)

`catalog` also exposes a **UseCaseService** that consumes the federated graph
and projects it via `DefineSubset` — composing the federated GraphQL surface
(`handler.execute`) with the UseCase / Core-API surface (DefineSubset DTOs):

```bash
curl -X POST http://localhost:8022/api/catalog_service/product_summaries \
  -H 'Content-Type: application/json' -d '{}'
# [{"id":1,"name":"Widget","review_count":2,"avg_rating":4.0,"top_reviewer":"Bob"}, ...]
```

`ProductSummary` is a `DefineSubset` sourced from the **local** `Product`
(`__subset__ = (Product, ("id", "name"))`) with computed fields
(`review_count`, `avg_rating`, `top_reviewer`) derived from the **remote**
reviews/users data fetched through the federated query. The remote types are
dynamic (materialized at `federate`-time), so the remote-derived bits live as
computed fields on a DTO subsetted from the local entry entity — the working
pattern for "federation data → DefineSubset shaping".

### DefineSubset a REMOTE type

`review_summaries` subsets a type **owned by another service** — `reviews.Review`
— not a local entity:

```bash
curl -X POST http://localhost:8022/api/catalog_service/review_summaries \
  -H 'Content-Type: application/json' -d '{}'
# [{"title":"Great widget","rating":5},{"title":"Works okay","rating":3}, ...]
```

The materialized remote class only exists after `handler.federate()` runs, so
the DTO cannot be declared at module load. `_review_summary()` builds it lazily
on first use from the `FederatedTypeRegistry`:

```python
fed_review = handler._er_manager._fed_registry.get("reviews.Review")
ReviewSummary = type("ReviewSummary", (DefineSubset,), {
    "__subset__": (fed_review, ("title", "rating")),  # subset of the REMOTE schema
})
```

This is the pattern for "DefineSubset a type from another service's schema":
subset the local entry entity at module load; subset a remote type dynamically
post-federate, then `model_validate` the federated result into it.

### Cross-service data composition

`composed_review_views` joins data from **all three services** into flat rows —
not a single-source projection, but a composition that flattens the federated
nested result (`Product → Review → User`):

```bash
curl -X POST http://localhost:8022/api/catalog_service/composed_review_views \
  -H 'Content-Type: application/json' -d '{}'
# [{"product_name":"Widget","title":"Great widget","rating":5,"author_name":"Alice"},
#  {"product_name":"Widget","title":"Works okay","rating":3,"author_name":"Bob"},
#  {"product_name":"Gadget","title":"Mediocre","rating":2,"author_name":"Alice"}]
```

Each row composes `product_name` (local Product) + `title`/`rating` (reviews
service) + `author_name` (users service). Use `DefineSubset` for single-source
projection; use a plain `BaseModel` like this for cross-source composition that
flattens the nested federated graph.

## Files

- `users_app.py` — leaf service (`User` + `by_id_in`).
- `reviews_app.py` — mounts users; `Review` + `by_product_id_in` / `by_author_id_in`.
- `catalog_app.py` — entry service clients query; mounts reviews.
- `_common.py` — shared FastAPI app builder (`/graphql` + ER introspection +
  GraphiQL) and a `federate`-with-retry helper for boot ordering.
