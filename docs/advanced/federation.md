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
`{ Product { by_filter { id name reviews { title rating author { name } } } } }`.

See also: [Custom Relationships](../guide/custom_relationship.md),
[ER Diagram Visualization](voyager.md).
