# Federation — composing multiple nexusx services

nexusx federation lets one nexusx service **mount** other nexusx services into
a single unified graph. There is no gateway or privileged router — mounting is
a symmetric capability of every nexusx service (relative composition). A query
entering any service is orchestrated by that service; it fans out one nested
GraphQL query per mounted service, and each mounted service resolves its own
subgraph with its own executor.

This is **same-architecture federation**: every member is a nexusx service.
It is not a generic supergraph gateway for third-party GraphQL.

```
catalog (Product)  ──reviews──▶  reviews (Review)  ──author──▶  users (User)
```

## How it works

- **Mount at startup** (async, in a lifespan): `await handler.federate(services={"reviews": "http://...:8021"})`. The mounter pulls each member's **ER graph** (not its SDL) via `GET /nexusx/er-introspection`, materializes the remote types, validates, and freezes — fail-fast if anything is misconfigured.
- **Fetch at query time**: resolving a remote field issues **one** nested GraphQL query to the mounted service (`by_<key>_in` entry root). The mounted service resolves its own composed subgraph and returns shaped data, so cross-service N+1 is structurally impossible.
- **Transitive reach**: mounting one service yields its whole queryable surface, including whatever *it* mounted. `catalog` mounting `reviews` reaches `users` (which `reviews` mounted) without `catalog` declaring `users`.

## Declare a cross-service relationship

`RemoteRelationship` lives in an entity's `__relationships__`, next to local
`Relationship` entries. Its `target` is a `"service.TypeName"` **marker string**,
not a Python type.

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

## Expose a federable member

A member must expose its GraphQL surface **and** its ER introspection, plus a
batch entry root for each join key the mounter will use:

```python
from nexusx.federation.introspect import build_federable_app

handler = GraphQLHandler(
    base=Base, session_factory=session,
    auto_query_config=AutoQueryConfig(batch_keys={"Review": ["product_id"]}),
    service_name="reviews",
)
app = build_federable_app(handler)   # mounts POST /graphql + GET /nexusx/er-introspection
```

`AutoQueryConfig(batch_keys=...)` generates `by_product_id_in(values: list)`
roots (`where field.in_(values)`) — the entry points the mounter's remote
loader drives. This is a generally-useful capability beyond federation.

## Mount + query

```python
# catalog startup (FastAPI lifespan)
await handler.federate(services={"reviews": "http://localhost:8021"})

# a single query traverses catalog → reviews → (transitively) users
await handler.execute("{ Product { by_filter { id reviews { title author { name } } } } }")
```

The client sees a flat, un-prefixed schema (`Review`, `User`, `Product.reviews`,
`Review.author`) — service boundaries are invisible.

## Design principles

| Decision | Why |
|---|---|
| ER graph, not SDL, as composition source | SDL loses FKs/cardinality; ER is the single source of truth (shared with Voyager/executor) |
| `"srv.TypeName"` marker, not a Python type | Dotted names fight Pydantic/mypy; a parsed marker avoids that |
| Bare `__name__` on materialized types | The internal registry is class-keyed; no prefix leaks to the schema |
| One nested gql query per service | Preserves nexusx's "one batched query per service" guarantee across federation |
| Init-time materialization + fail-fast | Misconfiguration surfaces at boot, never at query time |

## Runnable demo

`demo/federation/` runs all three services; `bash start_all.sh` starts them.
Open http://localhost:8022/ for GraphiQL on the catalog service and query
`{ Product { by_filter { id name reviews(limit:5) { items { title rating } pagination { has_more } } } } }`.

## Pagination

Pagination and physical sorting are owned by the member. The member explicitly
publishes named semantic order profiles through `batch_pages`; physical column
names and directions stay private to that service.

```python
from nexusx import BatchPageConfig, OrderTerm, PageOrder

AutoQueryConfig(
    batch_keys={"Review": ["product_id"]},
    batch_pages={
        "Review": {
            "product_id": BatchPageConfig(
                default_order="NEWEST",
                orders={
                    "NEWEST": PageOrder(
                        [OrderTerm("created_at", "desc")]
                    ),
                    "HIGHEST_RATING": PageOrder(
                        [OrderTerm("rating", "desc")]
                    ),
                },
            )
        }
    },
)
```

The caller chooses one of those profiles at query time, plus a direction
(`ASC`/`DESC`). The mounter renders the profile names as a schema enum and an
`order`/`direction` argument on the relationship field — no static binding is
declared on `RemoteRelationship`:

```python
RemoteRelationship(
    fk="id", target=list[reviews.Review],
    name="reviews", join_remote="product_id",
    pagination=True,
)
```

Omitting `order` uses the member's `default_order`; omitting `direction` uses
the profile's default direction. `total_count` is optional (computed only when
selected):

```graphql
{ Product { by_filter {
  reviews(limit: 5, offset: 0, order: HIGHEST_RATING, direction: DESC) {
    items { title rating }
    pagination { has_more total_count }
  }
} } }
```

`direction` overrides the profile's default direction; **nulls follow the flip**
(`desc + nulls_last` ⇄ `asc + nulls_first`), so flipping yields the strict
reverse order including NULL placement. Each profile is single-column (multi-
column profiles are rejected at member startup) — that keeps the flip
unambiguous. The sort *field* stays closed: callers may only pick a name the
member published and flip its direction, so index control never leaves the
member (a caller cannot `order by` an un-indexed column).

Pagination happens at the owning member (a window function partitions by join
key); the mounter sends one gql per mounted service per traversal and aligns
the per-key packages by join key. `items` subtrees (nested relationships, incl.
further cross-service hops) are resolved by the member inside that one gql.
Internally, the mounter calls
`page_by_<key>_in(keys, order, direction, limit, offset)`; the ER contract
exposes only profile names and descriptions, never physical sort fields.

See also: [Custom Relationships](../guide/custom_relationship.md),
[ER Diagram Visualization](voyager.md).

## DTO federation (γ) — composing at the DTO layer

β composes the *entity* graph over gql. **γ composes at the DTO layer**: a
member publishes some of its `DefineSubset` DTOs as **public**, and a mounter's
own DTO fields reference them directly — the Resolver auto-loads the tree over
federation, no gql string, no manual assembly.

### Member side: publish a public DTO

```python
class ReviewDTO(DefineSubset):
    __subset__ = SubsetConfig(
        kls=Review, fields=("title", "rating", "product_id"),
        federation_public=True,          # expose via dto-introspection / dto-batch
        federation_join_key="product_id",  # auto-derivable when the subset has exactly one FK
    )
    __pagination_orders__ = BatchPageConfig(
        default_order="HIGHEST_RATING",
        orders={"HIGHEST_RATING": PageOrder([OrderTerm("rating", "desc")])},
    )

handler = GraphQLHandler(base=Base, ..., dto_classes=[ReviewDTO])
```

The member exposes two extra endpoints: `GET /nexusx/dto-introspection` (the
public DTO fragments) and `POST /nexusx/dto-batch` (batch-fetch by join key,
running the member's Resolver so `resolve_*` methods and nested edges work).

### Mounter side: reference the member DTO

```python
class ProductDTO(DefineSubset):
    __subset__ = (Product, ("id", "name"))
    reviews: Annotated[list[rev_svc.ReviewDTO], Paged(limit=2)] = Field(
        default_factory=list
    )
```

The `Paged(...)` default drives a SQL-level top-N on the member (via its
`__pagination_orders__` profile); a caller can override per-field through
`Resolver(context={...})`. Member values are read-only — a mounter adds fields
with its own `resolve_*` methods / `post_*` hooks, never by mutating member
values.

### β vs γ at a glance

| | β (gql) | γ (UseCase/Resolver) |
|---|---|---|
| Composition unit | entity relationships (`RemoteRelationship`) | public DTO references (`DefineSubset` fields) |
| Traversal | one nested gql per mounted service per level | Resolver `_batch_auto_load` via `dto-batch` |
| Pagination | gql args on the relationship field | `Paged(...)` field default + caller context |
| Entry | `GraphQLHandler` schema | `UseCaseService` + `create_resolver()` |
| Member values | instances | DTOs (read-only; mounter computes its own) |

See `demo/federation/` (reviews publishes `ReviewDTO`; catalog's `ProductDTO`
references it) for a runnable example.
