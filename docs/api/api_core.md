# Core API Reference

Manage entities, register relationships, and resolve DTO trees with ErManager, Resolver, DefineSubset, and Loader.

## ErManager

Create an entity relationship manager to discover entities, register relationships, and create Resolvers.

```python
from nexusx import ErManager

er = ErManager(
    base=SQLModel,                    # SQLModel base class (mutually exclusive with entities)
    entities=None,                    # Explicit entity list (mutually exclusive with base)
    session_factory=async_session,    # Async session factory
)
```

!!! warning
    The `base` and `entities` parameters are mutually exclusive — you cannot pass both. Choose one approach: either provide a base class for auto-discovery or explicitly list your entities.

### Methods

| Method | Description |
|--------|-------------|
| `create_resolver()` | Returns a Resolver class bound to the entity graph |
| `get_diagram()` | Returns an ErDiagram instance |
| `add_virtual_entities(entities)` | Registers plain BaseModel subclasses as virtual entities (see below) |

### add_virtual_entities

Register plain `pydantic.BaseModel` subclasses as **virtual entities** — non-SQLModel roots that participate in resolution, custom relationships, and ER visualization alongside SQLModel entities. Typical use cases: `CurrentUser` assembled from OIDC claims, page wrappers aggregating multiple services, third-party SDK DTOs.

```python
from pydantic import BaseModel
from nexusx import ErManager, Relationship

class CurrentUserRoot(BaseModel):
    oid: str
    name: str
    agents: list[AgentDTO] = []

    __relationships__ = [
        Relationship(fk="oid", target=list[AgentDTO],
                     name="agents", loader=load_agents_by_oid),
    ]

er = ErManager(entities=[Agent], session_factory=async_session)
er.add_virtual_entities([CurrentUserRoot])          # ← must be before create_resolver()
Resolver = er.create_resolver()
```

Must be called **before** the first `create_resolver()` — the registry freezes at that point.

| Input | Result |
|-------|--------|
| `[A, B]` (plain BaseModel, not yet registered) | Both registered |
| `[]` (empty list) | No-op |
| `[42]` or `[int]` (non-class) | `TypeError` |
| `[SomeRandomClass]` (not a BaseModel) | `TypeError` |
| `[User]` where `User(SQLModel, table=True)` | `TypeError` — SQLModel goes in `__init__`'s `entities=` / `base=` |
| `[A, A]` (duplicate within or across calls) | `ValueError` |
| Called after `create_resolver()` | `RuntimeError` ("registry is frozen") |

See the [Virtual Entities guide](../guide/virtual_entities.md) for usage patterns, ER visualization rules, and migration from the `_subset_registry` hack.

## Resolver

Resolve DTO trees by traversing relationships and executing resolver methods.

```python
Resolver = er.create_resolver()

result = await Resolver().resolve(dtos)
```

### Constructor Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `context` | `dict` | Global context, accessible via `ancestor_context` |
| `loader_params` | `dict` | DataLoader extra parameters |
| `debug` | `bool` | Enable debug logging |

### resolve Method

Execute the resolution process on a DTO or list of DTOs.

```python
result = await Resolver().resolve(dtos)
```

The `dtos` parameter can be a single DTO instance or a list of DTOs. Returns the same objects after in-place modification.

### Execution Order

The Resolver executes methods in a specific order:

1. Execute all `resolve_*` methods (load relationship data)
2. Traverse existing object fields
3. Execute all `post_*` methods (compute derived fields)
4. Collect SendTo values to ancestor Collectors

## DefineSubset

Create DTO base classes that generate Pydantic models from SQLModel entities.

```python
from nexusx import DefineSubset

class UserDTO(DefineSubset):
    __subset__ = (User, ("id", "name"))
```

!!! tip
    Think of `DefineSubset` as a lens that focuses on specific fields of an entity. You declare which fields to include, and the framework generates a clean Pydantic model with those fields — automatically hiding FK fields while keeping them accessible for relationship loading.

### __subset__ Syntax

Accepts either a tuple `(Entity, ('field1', 'field2'))` or a `SubsetConfig` object.

### Rules

- FK fields are automatically hidden from serialization output (`exclude=True`), but remain internally accessible for `resolve_*` methods
- Relationship fields are declared in the class body (not in `__subset__`), and must use DTO types
- Direct use of SQLModel entities as field types is prohibited

!!! warning
    You cannot use SQLModel entities as field types in your DTOs. Always use DTO types for relationships — declaring `author: User | None` will raise a TypeError. Instead, use `author: UserDTO | None`.

!!! tip
    The `__subset__` source can be any `BaseModel` subclass, not just `SQLModel`. This lets you subset external schemas (OAuth claims, third-party SDK classes) without an ORM table behind them. When the source is a plain BaseModel, no `_orm_to_dto` conversion runs — the user constructs DTO instances directly. See the [Virtual Entities guide](../guide/virtual_entities.md) for details.

## SubsetConfig

Configure DTOs declaratively as an alternative to the `__subset__` tuple syntax.

```python
from nexusx import SubsetConfig

class UserDTO(DefineSubset):
    __subset__ = SubsetConfig(entity=User, fields=("id", "name"))
```

## Loader

Declare DataLoader dependencies in `resolve_*` methods to load relationship data.

```python
from nexusx import Loader

# DataLoader class
def resolve_tags(self, loader=Loader(TagLoader)):
    return loader.load(self.id)

# Async batch function
async def load_users(user_ids):
    ...
def resolve_owner(self, loader=Loader(load_users)):
    return loader.load(self.owner_id)
```

!!! warning
    Your Loader dependency names must match relationship names in ErManager. For example, `Loader('author')` requires that ErManager has a relationship named `author` registered.

## build_dto_select

Build a SELECT statement for querying DTO fields from the SQL database.

```python
from nexusx import build_dto_select

stmt = build_dto_select(SprintSummary)
stmt = build_dto_select(SprintSummary, where=Sprint.id == sprint_id)
```

!!! tip
    When ORM relationships use `lazy="noload"` (the recommended pattern with ErManager + Resolver), this function provides minimal benefit since the only pruning is on scalar columns. You can achieve the same result with `select(Entity)` and `DTO.model_validate(entity)`. Use this function when the DTO selects a small subset of scalar columns from a wide table.
