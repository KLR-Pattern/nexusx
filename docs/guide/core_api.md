# Core API Mode

GraphQL mode auto-generates a full query language. But many APIs are simpler — they just need well-shaped REST responses with related data loaded efficiently.

Core API gives you the same DataLoader batch loading and N+1 prevention, but as building blocks you control: define your DTOs, declare which fields need related data, and let the Resolver assemble the tree.

## Step 1: Define DTOs with DefineSubset

`DefineSubset` picks fields from your SQLModel entities and generates Pydantic models. Relationship fields declared in the class body are auto-loaded by name:

```python
from nexusx import DefineSubset

class UserDTO(DefineSubset):
    __subset__ = (User, ("id", "name"))

class TaskDTO(DefineSubset):
    __subset__ = (Task, ("id", "title", "owner_id"))
    owner: UserDTO | None = None   # Name matches Task.owner → auto-loaded

class SprintDTO(DefineSubset):
    __subset__ = (Sprint, ("id", "name"))
    tasks: list[TaskDTO] = []      # Name matches Sprint.tasks → auto-loaded
```

### What DefineSubset does

- Picks fields from the source entity — only the ones you list appear in the output
- Hides FK fields automatically — `owner_id` won't appear in the JSON response, but remains accessible internally in `resolve_*`
- Relationship fields go in the class body, not in `__subset__` — their types must be DTO types

!!! warning
    Relationship field types **must** be DTO types (`DefineSubset` or `BaseModel` subclasses). Using SQLModel entity types directly will raise a `TypeError`.

```python
# Wrong — SQLModel entity type
class TaskDTO(DefineSubset):
    __subset__ = (Task, ("id", "title"))
    owner: User | None = None  # TypeError!

# Correct — DTO type
class TaskDTO(DefineSubset):
    __subset__ = (Task, ("id", "title"))
    owner: UserDTO | None = None  # OK
```

## Step 2: Initialize ErManager and Resolver

At application startup — run once:

```python
from nexusx import ErManager

er = ErManager(base=SQLModel, session_factory=async_session)
Resolver = er.create_resolver()
```

- `ErManager` discovers all SQLModel entities and their relationships
- `create_resolver()` returns a Resolver class bound to the entity graph

!!! warning
    `base` and `entities` parameters are **mutually exclusive** — you can't pass both.

## Step 3: Resolve in Your Route

```python
from fastapi import FastAPI
from sqlmodel import select

app = FastAPI()

@app.get("/api/sprints")
async def get_sprints():
    async with async_session() as session:
        sprints = (await session.exec(select(Sprint))).all()
    dtos = [SprintDTO(id=s.id, name=s.name) for s in sprints]
    return await Resolver().resolve(dtos)
```

The Resolver traverses the DTO tree and fills in all relationship fields. You write the query, build the DTOs, and call `resolve()`.

## How Auto-Loading Works

When the Resolver encounters `SprintDTO`, it resolves the tree layer by layer:

```
SprintDTO(id=1, name="Sprint 1")
  → Auto-load: tasks → [TaskDTO(...), TaskDTO(...)]
    → Each TaskDTO: Auto-load: owner → UserDTO(...)
  → Result: complete nested response
```

Each relationship executes only one DataLoader query, regardless of how many Sprints or Tasks exist.

### Four conditions for implicit auto-loading

The Resolver auto-loads a field when **all four** conditions are met:

1. The field has no corresponding `resolve_*` method
2. The field is an extra field (not in `__subset__`)
3. The field name matches a registered ORM/custom relationship
4. The field type is a BaseModel DTO compatible with the relationship target

When the field name differs from the relationship name, use `AutoLoad(origin=...)`:

```python
from typing import Annotated
from nexusx import AutoLoad

class TaskDTO(DefineSubset):
    __subset__ = (Task, ("id", "title", "owner_id"))
    owner_summary: Annotated[UserDTO | None, AutoLoad(origin="owner")] = None
```

The override must name a registered relationship with a compatible target type.
A manual `resolve_*` method still takes priority over `AutoLoad`.

When any condition fails, you can use `resolve_*` to load the field manually — see [Core API Advanced](./core_api_advanced.md).

## Recap

- `DefineSubset` generates DTOs from SQLModel entities — pick fields, hide FKs, declare relationship fields
- Relationship fields are auto-loaded when the field name matches a registered relationship
- `ErManager` discovers entities; `Resolver` traverses and assembles the DTO tree
- Relationship field types must be DTO types, not SQLModel entities

## Next Steps

- [Core API Advanced](./core_api_advanced.md) — `resolve_*` / `post_*` / cross-layer data flow
- [Custom Relationships](./custom_relationship.md) — Non-ORM relationship declarations
- [ER Diagram](./er_diagram.md) — How ErManager discovers relationships
