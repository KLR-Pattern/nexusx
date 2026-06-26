# Virtual Entities (Non-SQLModel Roots)

Most NexusX response roots map to a database table — a SQLModel entity like `User` or `Order`. But some roots are assembled from request context, third-party SDKs, or external services, with no underlying table:

- **`CurrentUser`** assembled from OIDC / JWT claims
- **Page wrappers** that aggregate multiple services
- **Third-party SDK classes** (Stripe customer, OAuth profile) that you don't own
- **Cross-service DTOs** populated by an HTTP call rather than a query

For these, NexusX lets you declare a **virtual entity**: a plain `pydantic.BaseModel` registered via `ErManager.add_virtual_entities()`. Once registered, the class participates in resolution, custom relationships, cross-layer flows (ExposeAs / SendTo / Collector), and ER/Voyager visualization — *without* requiring a SQLModel subclass, a `__table__`, or any persistence concern.

## When to use virtual entities

| Situation | Use virtual entity? |
|-----------|---------------------|
| Root is itself the schema (e.g. `CurrentUser`) | **Yes — `add_virtual_entities()` only** |
| DTO is a *subset* of an external BaseModel schema (e.g. third-party SDK class) | **Yes — `DefineSubset.__subset__` from BaseModel only** |
| Both — root is a subset of an external schema *and* has its own relationships | **Both APIs together** |
| Root maps to a SQLModel table | **No — use the existing SQLModel path** |

The two APIs (`add_virtual_entities()` and `DefineSubset` from BaseModel) are orthogonal — pick what fits your scenario.

## API: `ErManager.add_virtual_entities()`

```python
from pydantic import BaseModel
from nexusx import ErManager, Relationship, DefineSubset

class Agent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_oid: str
    name: str

class AgentDTO(DefineSubset):
    __subset__ = (Agent, ("id", "owner_oid", "name"))

async def load_agents_by_oid(keys: list[str]) -> list[list[AgentDTO]]:
    # batch loader — fetches from any source (DB, cache, external API)
    ...

class CurrentUserRoot(BaseModel):
    oid: str
    name: str
    agents: list[AgentDTO] = []

    __relationships__ = [
        Relationship(
            fk="oid",
            target=list[AgentDTO],
            name="agents",
            loader=load_agents_by_oid,
        ),
    ]

# Wire it up
er = ErManager(entities=[Agent], session_factory=async_session)
er.add_virtual_entities([CurrentUserRoot])      # ← register the virtual root
resolver = er.create_resolver()

# Resolve as normal — the root behaves exactly like a SQLModel-rooted tree.
root = CurrentUserRoot(oid="user-1", name="Alice")
result = await resolver.resolve(root)
assert {a.name for a in result.agents} == {"A1", "A2"}
```

### Method contract

```python
er.add_virtual_entities(entities: list[type[BaseModel]]) -> None
```

Must be called **before the first `er.create_resolver()`** — the registry is frozen at that point. Validation:

| Scenario | Result |
|----------|--------|
| `[A, B]` where A, B are plain BaseModel, not already registered | Both registered |
| `[]` (empty list) | No-op |
| `[42]` or `[int]` (non-class entry) | `TypeError("add_virtual_entities entries must be classes; ...")` |
| `[SomeRandomClass]` (not a BaseModel) | `TypeError(f"{name} must be a subclass of pydantic.BaseModel")` |
| `[User]` where `User(SQLModel, table=True)` | `TypeError(f"{name} is a SQLModel subclass; ...")` — SQLModel goes in `__init__`'s `entities=` / `base=` |
| `[A, A]` (duplicate in same call) or `[A]` then `[A]` | `ValueError(f"{name} is already registered")` |
| Called after `create_resolver()` | `RuntimeError("ErManager registry is frozen after first create_resolver() ...")` |

### What you get for free

After registration, a virtual entity participates in everything a SQLModel root does:

- **`Resolver().resolve(root)`** — full tree traversal with auto-load of `__relationships__`
- **`resolve_*` and `post_*` methods** — including `post_default_handler` finalizer
- **ExposeAs / SendTo / Collector** — cross-layer data flows work across the SQLModel / BaseModel boundary
- **Custom relationships** — declared via `__relationships__`, identical syntax to SQLModel side
- **ER diagram / Voyager visualization** — the entity appears as a *virtual node* visually distinguished from table-backed entities (yellow fill, `«virtual»` stereotype, separate `cluster_virtual` group)

### What you DON'T get

- **No `__table__`, no SQLAlchemy mapper** — the class is *not* a SQLModel subclass and will be rejected by raw SQLAlchemy query builders that need `__table__`. This is intentional; use `resolve_*` methods for data fetching.
- **No auto-discovery** — passing a `CurrentUserRoot` instance to `Resolver().resolve(...)` *before* calling `er.add_virtual_entities([CurrentUserRoot])` produces a clear error pointing at the registration API, not silent behavior.
- **No persistence** — virtual entities are response-assembly primitives; they have no DB session and no transactions.

## API: `DefineSubset.__subset__` from BaseModel

If your DTO is a *subset* of an external BaseModel schema (rather than being its own schema), use the widened `DefineSubset` source. SQLModel is no longer required:

```python
from oauth_sdk import OAuthClaims   # third-party BaseModel with 28 fields

class AuthSummaryDTO(DefineSubset):
    __subset__ = (OAuthClaims, ("sub", "email", "name"))
    # AuthSummaryDTO has only 3 of OAuthClaims's 28 fields

# Construct directly from kwargs — no ORM row needed.
dto = AuthSummaryDTO(sub="user-1", email="a@x.com", name="Alice")
```

If the BaseModel source *also* has `__relationships__` and you want auto-load to fire through them, register it via `add_virtual_entities()` in addition:

```python
class CurrentUser(BaseModel):
    oid: str
    name: str
    tenant_id: str       # plus 20 more fields from your auth context

    __relationships__ = [
        Relationship(fk="oid", target=list[AgentDTO], name="agents", loader=load_agents_by_oid),
    ]

class CurrentUserDTO(DefineSubset):
    __subset__ = (CurrentUser, ("oid", "name"))   # subset of CurrentUser's schema
    agents: list[AgentDTO] = []                    # auto-loaded via source's relationship

er = ErManager(entities=[Agent], session_factory=async_session)
er.add_virtual_entities([CurrentUser])             # ← so auto-load can find the source
resolver = er.create_resolver()

dto = CurrentUserDTO(oid="user-1", name="Alice")
result = await resolver.resolve(dto)
assert {a.name for a in result.agents} == {"A1", "A2"}
```

If you skip `add_virtual_entities()` for the source, schema subsetting still works (the DTO's `__subset_fields__` is populated), but auto-load does NOT fire — the source isn't discoverable in the registry.

## Migration: replacing the `_subset_registry` hack

Before this feature, projects worked around the limitation by mutating NexusX internals:

```python
# ❌ Old hack — fragile, undocumented, breaks on version bumps
from nexusx.subset import _subset_registry
_subset_registry[CurrentUserRootDTO] = CurrentUserRoot
```

Replace with the official API. The right pattern depends on what the hack was doing:

### Case A — registering a BaseModel as a "virtual source" for auto-load / ER visibility

```python
# ✅ Official: register via add_virtual_entities + DefineSubset widening
class CurrentUserRootDTO(DefineSubset):
    __subset__ = (CurrentUserRoot, ("oid", "name"))
    # ... resolve_*, post_*, __relationships__ on source or DTO ...

er = ErManager(entities=[...], session_factory=async_session)
er.add_virtual_entities([CurrentUserRoot])
```

### Case B — using a BaseModel root that is itself the schema (no subsetting)

```python
# ✅ Official: plain BaseModel + add_virtual_entities
class CurrentUserRoot(BaseModel):
    oid: str
    name: str
    __relationships__ = [...]

er = ErManager(entities=[...], session_factory=async_session)
er.add_virtual_entities([CurrentUserRoot])
```

The migration is **mechanical** (search-and-replaceable):

1. Find every `_subset_registry[X] = Y` line.
2. If `Y` has `__relationships__` or you want it visible in ER diagrams: add `er.add_virtual_entities([Y])` after `ErManager(...)`.
3. If `X` is a subset of `Y`'s schema: declare `class X(DefineSubset): __subset__ = (Y, ("field", "names"))`.
4. If `X` *is* `Y` (the root is its own schema): make `X` a plain `BaseModel` and `er.add_virtual_entities([X])`.
5. Delete the `_subset_registry` mutation.

No DTO hierarchy rewrite required. `ErManager.__init__` signature is unchanged.

## ER / Voyager visualization

A project that mixes SQLModel entities and virtual entities generates an ER diagram without exceptions, and the virtual entities appear visually distinguished from real DB-backed entities:

| Aspect | SQLModel entity | Virtual entity |
|--------|-----------------|----------------|
| Header fill | Theme primary (teal) | Light yellow (`#FFF9C4`) |
| Label | `{ClassName}` | `«virtual»\n{ClassName}` |
| Cluster | Grouped by module path | `cluster_virtual` (dashed border) |
| Edges | Drawn normally | Drawn normally (no special casing) |

```python
from nexusx import ErDiagram
from nexusx.voyager.er_diagram_dot import ErDiagramDotBuilder

er = ErManager(entities=[Agent], session_factory=async_session)
er.add_virtual_entities([CurrentUserRoot])

# Data API — inspect entities and relationships
diagram = ErDiagram.from_er_manager(er)
for e in diagram.entities:
    print(f"{e.name} (virtual={e.is_virtual}): {[r.name for r in e.relationships]}")

# DOT rendering — emit Voyager-compatible graphviz
builder = ErDiagramDotBuilder(er)
builder.analysis()
print(builder.render_dot())
```

## Constraints

- **`ErManager.__init__` requires at least one SQLModel entity** (via `base=` or `entities=`). A project with zero SQLModel entities is out of scope — there would be no loaders worth managing.
- **`add_virtual_entities()` must run before the first `create_resolver()`**. The registry is frozen afterward; ErManager is single-use by design (entity registration happens once at startup).
- **Custom relationships on virtual roots are declared explicitly** via `__relationships__`. AutoLoad's implicit "field name matches ORM relationship name" path still requires a real SQLModel source — virtual roots don't have ORM metadata to read from.
