# MCP and Context Efficiency

When you expose data to an AI agent through MCP, the agent's context window becomes the primary constraint — not the data itself. Context gets consumed in three independent ways, and most setups address only one of them. This guide walks through the three sources of context pressure and how nexusx handles each.

## The three sources of context pressure

### 1. Tool definitions, loaded upfront

The most common pattern is wrapping REST endpoints as MCP tools — `GET /users` → `list_users`, `GET /users/{id}/orders` → `list_user_orders`. A mid-size application easily piles up 50–60 tools.

Every tool's **definition** (schema, parameters, description) is loaded into context in full before the agent does any work. Real-world measurements show a single MCP server's tool definitions can consume **55,000+ tokens** — the first user message hasn't even been processed and context is already half gone.

### 2. Responses that can't be trimmed

An agent that wants one user's name calls `list_users` and receives:

```json
[
  {"id":1,"name":"Alice","email":"…","password_hash":"…","last_login_ip":"…","department_id":7,"meta":{…}},
  … ×50
]
```

One field was needed; 20 fields × 50 rows were not — roughly 10k tokens of noise. After a few turns the agent degrades noticeably, not because the model is weak but because its working memory is full of response data.

### 3. Related data requires N round trips

An agent's real task is rarely "fetch one table" — it is "fetch a tree". "Did product 1 get any bad reviews, and who wrote them?" spans `Product → Reviews → Comments → Author`, four levels.

A REST-wrapped MCP cannot do this in one call. The agent must chain: call `list_reviews(product_id)` → hold review_id → call `list_comments(review_id)` → hold author_id → call `get_user(author_id)`. N levels mean N round trips, each returning another blob, and the agent must hold every intermediate id. One wrong id breaks the whole chain.

---

## How nexusx addresses each

### Progressive disclosure (source 1)

Instead of dumping every tool definition into context upfront, nexusx lets the agent drill down on demand:

1. `list_apps` — which apps/services exist (name + one-line description);
2. `describe_compose_schema` — which methods a service exposes (still compact);
3. `describe_compose_method` — one method's full signature and return type (SDL);
4. `compose_query` — execute.

Each layer returns only the small slice the agent asked for. Most of the time the agent decides by layer 1 or 2 whether to continue; only what it actually uses drills down to signatures and execution. Tool definitions move from "preload everything" to "load on demand".

### Field selection (source 2)

nexusx's MCP runs GraphQL under the hood, so the agent declares which fields it wants at call time instead of receiving a fixed shape. Asking for `name` returns only `name` — the 10k-token blob collapses to a few hundred tokens.

Note that field selection controls **response size**, not the SQL query itself. Which columns are queryable is a separate boundary fixed at definition time (via `DefineSubset`); selection at query time only decides what gets serialized into the response.

### One query for the whole tree + batched loading (source 3)

Field selection extends to the relationship tree: the agent declares not just fields but which relationships to traverse and what to take at each level. One query expresses multi-hop relationships with per-level fields.

Under the hood, a batching loader (DataLoader) merges same-level lookups — "fetch owners for these 50 tasks" — into one query rather than one per row. Query count scales with **depth**, not **row count**: 50 owners is still one query, not 50.

---

## A complete business definition

All three mechanisms grow out of a single business method. A complete nexusx definition has three parts — entities, DTOs, and a service:

```python
# 1. SQLModel entities + relationships
class User(BaseEntity, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    tasks: list["Task"] = Relationship(back_populates="owner")

class Sprint(BaseEntity, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    tasks: list["Task"] = Relationship(back_populates="sprint")

class Task(BaseEntity, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    owner: User | None = Relationship(back_populates="tasks")
    sprint: Sprint | None = Relationship(back_populates="tasks")

# 2. DefineSubset DTOs — field boundary for the outside + nested relationships
class UserSummary(DefineSubset):
    __subset__ = (User, ("id", "name"))         # other entity fields (email, etc.) stay out

class TaskSummary(DefineSubset):
    __subset__ = (Task, ("id", "title"))
    owner: UserSummary | None = None            # relationship field, auto-resolved

class SprintSummary(DefineSubset):
    __subset__ = (Sprint, ("id", "name"))
    tasks: list[TaskSummary] = []               # Sprint → Tasks → Owner, one tree

# 3. UseCaseService — a business method (one capability to the outside)
class SprintService(UseCaseService):
    @query
    async def list_sprints(cls) -> list[SprintSummary]: ...
```

These three parts map onto the three mechanisms:

- **Progressive disclosure = the service (section 3)**. `SprintService` + `@query` methods are exposed over MCP as `list_apps → describe_compose_schema → describe_compose_method → compose_query`. Methods the agent doesn't use never put their signatures into context.
- **Field selection = `__subset__` (section 2)**. `UserSummary.__subset__ = (User, ("id","name"))` pins the exposed fields to id/name; columns like `email` or `password_hash` are not in the boundary at all.
- **Tree + batched loading = nested DTO relationships + entity `Relationship` (sections 1 + 2)**. `SprintSummary.tasks` / `TaskSummary.owner` match the entity's `Relationship(...)`, so nexusx auto-resolves them and batch-loads via DataLoader. Query count scales with depth, not row count.

nexusx consumes the relationship metadata your entities already define — you don't re-describe "a task belongs to a user". One method generates **REST + GraphQL + MCP + CLI**, all sharing the same typed contract and batch-loader.

> This fits best when your project already uses SQLModel.

---

## End-to-end: one MCP interaction

Take the e-commerce example — an agent answering "did product 1 get any bad reviews, and who wrote them?":

**① `list_apps`** → `[{"name": "catalog", "description": "Product catalog and reviews"}]`. One compact description enters context; the agent picks `catalog`.

**② `describe_compose_schema(app: "catalog")`**:
```
→ ProductService { product(id): ProductDetail,  top_rated(): [ProductDetail] }
  ReviewService  { by_product(product_id): [ReviewDetail] }
```
The agent locks onto `ProductService.product(id)`.

**③ `describe_compose_method(app, service, method)`**:
```
→ product(id: Int!): ProductDetail
  ProductDetail { id name reviews: [Review!]! }
  Review        { id rating text comments: [Comment!]! author: UserSummary }
  Comment       { text author: UserSummary }
  UserSummary   { id name }
```
The full type chain is visible — the `product → reviews → comments → author` path, fields at each level, parameter types.

**④ `compose_query`** — one nested selection:
```
{ ProductService { product(id: 1) {
    name
    reviews { rating text
      comments { text author { name } } } } } }
```
Back comes the whole tree, only the selected fields; internal columns like `password_hash` never appear. Under the hood it batch-loads by level — four levels of relationships, a handful of batched queries, not four round trips stitching ids.

All three sources of context pressure are handled in one interaction: steps ①–③ are progressive disclosure, step ④ is one nested selection (smaller response, one tree, batched loading).

---

## Three orthogonal mechanisms

Each capability owns one dimension:

- **Progressive disclosure** (discovery) — tool count
- **Selection** (query) — response size
- **Batched loading / DataLoader** (execution) — query count, N+1
- **DefineSubset** (definition) — field boundary, safety

One business method, four protocols (REST / GraphQL / MCP / CLI) from the same source.

---

## See also

- [MCP Service](./advanced/mcp_service.md) — how to expose SQLModel APIs over MCP
- [MCP API](./api/api_mcp.md) — MCP configuration reference
