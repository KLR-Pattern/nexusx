# Data Model: Non-SQLModel Root Objects

**Date**: 2026-06-25
**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Research**: [research.md](./research.md)

This feature adds **no new persisted data** (virtual entities are intentionally non-persistent). The data model below describes the **in-memory state** added to `ErManager` and the **rendered output shape** for ER/Voyager.

## ErManager internal state

### Existing (unchanged)

```python
class ErManager:
    def __init__(self, session_factory, base=None, entities=None, ...):
        # ...
        # entity -> {rel_name -> RelationshipInfo}
        self._registry: dict[type, dict[str, RelationshipInfo]] = {}
        self._loader_instances: dict = {}
        # ...
```

The `_registry` type annotation widens from `dict[type[SQLModel], ...]` to `dict[type, ...]` (R1) — no behavioral change, the dict already accepted any hashable key.

### New (added by this feature)

```python
class ErManager:
    def __init__(self, ...):
        # ... existing ...
        self._frozen: bool = False   # R3 — set True on first create_resolver()
        # Note: virtual entities live in the SAME _registry, not a separate dict.

    def add_virtual_entities(self, entities: list[type[BaseModel]]) -> None:
        """See contracts/api.md for the public contract."""

    def create_resolver(self, ...) -> Resolver:
        self._frozen = True   # R3 — gate set BEFORE construction proceeds
        # ... existing body ...
```

**State transitions**:

| Event | `_frozen` | `_registry` |
|-------|-----------|-------------|
| `ErManager()` returns | `False` | populated with SQLModel entities from `base=` / `entities=` |
| `add_virtual_entities([A, B])` called (pre-freeze) | `False` | `A` and `B` added with their `__relationships__` |
| `create_resolver()` returns | `True` | **frozen** — further writes raise `RuntimeError` |
| `add_virtual_entities([C])` called (post-freeze) | `True` | raises `RuntimeError`, no mutation |

## Virtual entity shape (in the registry)

After `er.add_virtual_entities([CurrentUserRoot])`, `_registry[CurrentUserRoot]` looks like:

```python
{
    "agents": RelationshipInfo(
        name="agents",
        direction="CUSTOM",
        fk_field="oid",            # whatever __relationships__ declared
        target_entity=AgentDTO,    # may be SQLModel-backed DTO, BaseModel, or DefineSubset
        is_list=True,
        loader=<the async batch fn from __relationships__>,
        # ... other fields as today
    ),
    # ... one entry per Relationship in __relationships__
}
```

**Invariants**:
- Every entry has `direction="CUSTOM"` — virtual entities have no ORM metadata, so every relationship is custom.
- `target_entity` can be **any** class (SQLModel entity, DefineSubset DTO, plain BaseModel) — the runtime handles all three uniformly.
- The class itself is **never** a `SQLModel` subclass — validated at `add_virtual_entities()` entry.

## Relationship dataclass (signature widening)

```python
# src/nexusx/relationship.py

# Before (type-annotation only — body unchanged):
def get_custom_relationships(entity: type[SQLModel]) -> list[Relationship]: ...

# After:
def get_custom_relationships(entity: type) -> list[Relationship]: ...

# Property return type widens similarly:
@property
def target_entity(self) -> type: ...   # was type[SQLModel]
```

No new fields, no new methods. Pure type-annotation widening (R2).

## DefineSubset source widening

```python
# src/nexusx/subset.py

# Before:
_subset_registry: dict[type[BaseModel], type[SQLModel]] = {}

class SubsetMeta(type):
    def __new__(mcs, name, bases, namespace):
        # ...
        if not (isinstance(entity_kls, type) and issubclass(entity_kls, SQLModel)):
            raise TypeError(f"DefineSubset source must be a SQLModel subclass, got {entity_kls}")
        # ...

# After:
_subset_registry: dict[type[BaseModel], type[BaseModel]] = {}   # source may be SQLModel OR BaseModel

class SubsetMeta(type):
    def __new__(mcs, name, bases, namespace):
        # ...
        if not (isinstance(entity_kls, type) and issubclass(entity_kls, BaseModel)):
            raise TypeError(f"DefineSubset source must be a BaseModel subclass, got {entity_kls}")
        # ...
```

Behavioral change: permissive widening. Existing SQLModel sources continue to work; BaseModel sources now also accepted.

**`_orm_to_dto` invocation rule** (resolver.py:663): only called when the source is a SQLModel (i.e., when there's an ORM row to convert). For BaseModel sources, the user constructs DTO instances directly — the function is never invoked. The function body (`getattr(instance, f, None)` over `__subset_fields__`) is type-agnostic and would technically work on BaseModel instances too, but the call sites that pass ORM rows are the only callers.

## Resolver source-resolution (unified)

```python
# src/nexusx/resolver.py:_scan_auto_load_fields

# Before:
source_entity = get_subset_source(node_type)
if source_entity is None:
    return []
entity_rels = self._registry.get_relationships(source_entity)

# After:
source_entity = get_subset_source(node_type)
if source_entity is None and self._registry is not None:
    if self._registry.has_entity(node_type):
        source_entity = node_type
if source_entity is None:
    return []
entity_rels = self._registry.get_relationships(source_entity)   # unchanged — source-type-agnostic
```

The unified principle: **find the source for this `node_type`, then look up its relationships**. `get_subset_source()` returns SQLModel or BaseModel for DefineSubset DTOs (after R8 widening); the fallback handles plain BaseModel roots. The downstream `_registry.get_relationships(source)` doesn't care which.

## ER diagram output shape

### Existing: SQLModel entity → DOT record

```dot
"User" [shape=record, label="{User|id: int\lname: str\l|...}"]
```

### New: Virtual entity → DOT note

```dot
subgraph cluster_virtual {
    label = "Virtual Entities";
    style = dashed;
    "CurrentUserRoot" [
        shape=note,
        style=filled,
        fillcolor="#FFF9C4",
        label="«virtual»\nCurrentUserRoot"
    ];
}
```

Edges between virtual and SQLModel entities are drawn with the same arrow style as SQLModel-to-SQLModel edges:

```dot
"CurrentUserRoot" -> "AgentDTO" [label="agents", arrowhead=crow];
```

### `ErDiagram` data class

```python
@dataclass
class ErDiagram:
    entities: list[type[SQLModel]]            # existing
    virtual_entities: list[type[BaseModel]]   # NEW — populated from ErManager._registry
    relationships: list[RelationshipEdge]     # existing — may now reference virtual endpoints
```

The `relationships` list is unified: edges between two SQLModel entities, virtual-to-SQLModel, SQLModel-to-virtual, and virtual-to-virtual all live in the same list, distinguished only by their endpoint types.

## Test fixtures shape

The new tests will use these minimal fixtures (no real DB; in-memory loaders):

```python
# A plain BaseModel virtual entity
class CurrentUserRoot(BaseModel):
    oid: str
    name: str
    agents: list["AgentDTO"] = []

    __relationships__ = [
        Relationship(
            fk="oid",
            target=list["AgentDTO"],
            name="agents",
            loader=load_agents_by_user_oid,
        )
    ]

# A SQLModel entity (existing pattern)
class Agent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_oid: str
    name: str

# A DefineSubset DTO sourcing from Agent
class AgentDTO(DefineSubset):
    __subset__ = (Agent, ("id", "owner_oid", "name"))
```

This triangle (virtual root → SQLModel entity → DefineSubset DTO) exercises every boundary in one fixture and is reused across `test_virtual_entities.py` and `test_virtual_entities_er.py`.
