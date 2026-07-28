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

## UseCase composition over federated data (DefineSubset)

`catalog` also exposes a **UseCaseService** that composes the cross-service
graph into a nested DTO tree — declaratively, **no manual per-row assembly**.

The split: **federation fetches** (one nested gql per service — β), and
**DefineSubset shapes** (`model_validate` recurses the nested result).

```bash
curl -X POST http://localhost:8022/api/catalog_service/composed_tree \
  -H 'Content-Type: application/json' -d '{}'
# [{"id":1,"name":"Widget","reviews":[
#    {"title":"Great widget","rating":5,"author":{"name":"Alice"}},
#    {"title":"Works okay","rating":3,"author":{"name":"Bob"}}]},
#  {"id":2,"name":"Gadget","reviews":[
#    {"title":"Mediocre","rating":2,"author":{"name":"Alice"}}]}]
```

The DTO tree mirrors the graph — `ProductDTO` (DefineSubset of the local
`Product`) → `reviews: list[ReviewDTO]` → `author: UserDTO`:

```python
class UserDTO(BaseModel):
    name: str

class ReviewDTO(BaseModel):
    title: str
    rating: int
    author: UserDTO | None = None

class ProductDTO(DefineSubset):
    __subset__ = (Product, ("id", "name"))
    reviews: list[ReviewDTO] = Field(default_factory=list)


res = await handler.execute(
    "{ Product { by_filter { id name reviews { title rating author { name } } } } }"
)
tree = [ProductDTO.model_validate(p) for p in res["data"]["Product"]["by_filter"]]
```

`model_validate` recurses through the nested `BaseModel` fields, so the whole
`Product → Review → User` tree is built with **one root-level comprehension** —
no for-loop over children. The remote levels are plain `BaseModel` (the
materialized remote types are dynamic, so they're shaped by field selection,
not `DefineSubset` over a source class). For `post_*`-style transforms, run
`Resolver().resolve(tree)` afterwards — relationships are already filled, so the
Resolver only runs the hooks (it is not the fetcher here — federation is).

## Files

- `users_app.py` — leaf service (`User` + `by_id_in`).
- `reviews_app.py` — mounts users; `Review` + `by_product_id_in` / `by_author_id_in`.
- `catalog_app.py` — entry service clients query; mounts reviews.
- `_common.py` — shared FastAPI app builder (`/graphql` + ER introspection +
  GraphiQL) and a `federate`-with-retry helper for boot ordering.
