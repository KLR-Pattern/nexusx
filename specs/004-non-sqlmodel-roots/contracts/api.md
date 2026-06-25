# Public API Contract: Non-SQLModel Root Objects

**Date**: 2026-06-25
**Spec**: [spec.md](./spec.md) | **Research**: [research.md](./research.md)

This contract is the **user-facing** surface for the feature. Internal data structures (`_registry`, `_frozen`) are documented in [data-model.md](./data-model.md) and are NOT part of this contract — users who touch `_registry` or `_frozen` directly are using a private API.

## Contract 1: `ErManager.add_virtual_entities()`

### Signature

```python
class ErManager:
    def add_virtual_entities(self, entities: list[type[BaseModel]]) -> None:
        """Register plain BaseModel subclasses as non-SQLModel virtual entities.

        Each entry becomes a first-class member of the ER graph: a valid
        Resolver root, a participant in custom relationships (declared via
        ``__relationships__``), and a virtual node in ER diagrams / Voyager.

        Must be called before the first ``create_resolver()`` — the registry
        is frozen at that point and subsequent calls raise ``RuntimeError``.

        Args:
            entities: A list of BaseModel subclasses. Each MUST NOT be a
                SQLModel subclass (those go in ``__init__``'s ``entities=``
                or via ``base=``).

        Raises:
            TypeError: If any entry is not a class, not a BaseModel subclass,
                or is a SQLModel subclass.
            ValueError: If any entry is already registered (in this ErManager
                via either ``add_virtual_entities`` or ``__init__``'s
                ``entities=`` / ``base=``).
            RuntimeError: If called after ``create_resolver()`` has already
                been invoked on this ErManager instance.
        """
```

### Behavioral contract

| Scenario | Input | Result |
|----------|-------|--------|
| Happy path | `[A, B]` where A and B are plain BaseModel, not registered | Both registered; `_registry[A]` and `_registry[B]` populated from their `__relationships__` |
| Empty list | `[]` | No-op, no error |
| Non-class entry | `[int]` or `[42]` | `TypeError("add_virtual_entities entries must be classes; got int")` |
| Non-BaseModel class | `[SomeRandomClass]` | `TypeError(f"{name} must be a subclass of pydantic.BaseModel")` |
| SQLModel subclass | `[User]` where `User(SQLModel, table=True)` | `TypeError(f"{name} is a SQLModel; pass it via __init__'s entities= or base=, not add_virtual_entities")` |
| Duplicate (within call) | `[A, A]` | `ValueError(f"{name} is already registered")` on second occurrence |
| Duplicate (across calls) | First `[A]`, then `[A]` | `ValueError(f"{name} is already registered")` on second call |
| Already in `entities=` | `[U]` where `U` was in `ErManager(entities=[U])` | `ValueError(f"{name} is already registered")` |
| After `create_resolver()` | Called post-resolver | `RuntimeError("ErManager registry is frozen after first create_resolver() call. Call add_virtual_entities() before any create_resolver().")` |

### Examples

```python
from pydantic import BaseModel
from nexusx import ErManager, Relationship
from nexusx.loader.registry import async_session
from myapp.models import SQLModel, User, Agent

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
        ),
    ]

# Happy path
er = ErManager(base=SQLModel, session_factory=async_session)
er.add_virtual_entities([CurrentUserRoot])
resolver = er.create_resolver()
# After this, calling add_virtual_entities again raises RuntimeError.
```

```python
# Lifecycle violation — caught at the call site
er = ErManager(base=SQLModel, session_factory=async_session)
resolver = er.create_resolver()
er.add_virtual_entities([CurrentUserRoot])  # raises RuntimeError
```

```python
# Type violation — caught at the call site
er = ErManager(base=SQLModel, session_factory=async_session)
er.add_virtual_entities([User])  # User is SQLModel — raises TypeError
```

## Contract 2: `__relationships__` on plain BaseModel

### Signature

Identical to the existing SQLModel-side declaration:

```python
class SomeVirtualEntity(BaseModel):
    # ... fields ...

    __relationships__ = [
        Relationship(
            fk="<field-name-on-this-class>",
            target=<TargetClass> | list[<TargetClass>],
            name="<unique-name-within-this-class>",
            loader=<async batch function>,
            description="<optional, used in ER diagrams>",
        ),
        # ... more Relationship entries ...
    ]
```

### Behavioral contract

| Aspect | Behavior |
|--------|----------|
| Reader | `nexusx.relationship.get_custom_relationships(entity)` — same function as SQLModel path; signature widened from `type[SQLModel]` to `type` (R2). |
| Loader signature | Identical to SQLModel-side loaders. Scalar target: `async def fn(keys: list[K]) -> list[V | None]`. List target: `async def fn(keys: list[K]) -> list[list[V]]`. |
| Conflict detection | A `Relationship` whose `name` collides with another on the same class raises `ValueError` (existing behavior on SQLModel; same path used). |
| Target type | Any class — SQLModel entity, DefineSubset DTO, plain BaseModel. The runtime handles each uniformly. |
| Description | Optional; surfaces in ER diagram edge labels and Voyager tooltips. |

## Contract 3: ER / Voyager virtual node rendering

### Visual rules

| Property | SQLModel entity | Virtual entity |
|----------|-----------------|----------------|
| DOT shape | `record` (existing) | `note` |
| Fill color | None / existing theme | Light yellow (`#FFF9C4`) |
| Label format | `{TableName\|column: type\l...}` | `«virtual»\n{ClassName}` |
| Cluster | Main entity cluster | `cluster_virtual` (dashed border) |
| Edges | Same arrow style | Same arrow style (no special casing) |
| Columns shown | All `__table__.columns` | None (no table) |
| FKs shown | From SQLAlchemy mapper | None (no mapper) |

### What the user sees

For a project with `User`, `Agent` (SQLModel) and `CurrentUserRoot` (virtual, with a relationship to `AgentDTO`), the ER diagram contains:

- A main cluster with `User` and `Agent` as record-shaped nodes with their columns
- A dashed `cluster_virtual` containing `CurrentUserRoot` as a yellow note-shaped node labeled `«virtual»\nCurrentUserRoot`
- An edge from `CurrentUserRoot` to `AgentDTO` labeled `agents` with the same arrowhead as SQLModel-side relationships

### Voyager

Voyager renders the same DOT graph; no Voyager-specific changes are required beyond the DOT-level visual rules above. The interactive SVG / canvas view will display virtual nodes in their cluster with the same shape/fill rules.

## Contract 5: `DefineSubset.__subset__` accepts BaseModel source

### Signature

```python
class SubsetMeta(type):
    def __new__(mcs, name, bases, namespace):
        # __subset__ source widens from SQLModel to BaseModel
        entity_kls = namespace.get("__subset__", None)
        if entity_kls is not None:
            if not (isinstance(entity_kls, type) and issubclass(entity_kls, BaseModel)):
                raise TypeError(
                    f"DefineSubset source must be a BaseModel subclass, got {entity_kls}. "
                    f"Both SQLModel and plain BaseModel are accepted."
                )
        # ... rest unchanged ...
```

### Behavioral contract

| Source type | `__subset_fields__` populated? | `_orm_to_dto()` called at resolve time? | AutoLoad fires for source's `__relationships__`? |
|-------------|--------------------------------|----------------------------------------|--------------------------------------------------|
| SQLModel (existing) | Yes (from `model_fields`) | Yes (ORM row → DTO) | Yes |
| BaseModel (new) | Yes (from `model_fields`) | **No** (user constructs DTO directly) | Yes (if source is registered via `add_virtual_entities`) |

### Examples

```python
# Existing: SQLModel source (unchanged)
class UserSummary(DefineSubset):
    __subset__ = (User, ('id', 'name'))   # User is a SQLModel entity

# New: BaseModel source
class OAuthClaims(BaseModel):    # plain BaseModel, no SQLModel
    sub: str
    email: str
    name: str
    picture: str | None = None
    # ... 25 more fields from your OAuth provider

class AuthSummaryDTO(DefineSubset):
    __subset__ = (OAuthClaims, ('sub', 'email', 'name'))   # subset of OAuthClaims schema
    # DTO has only 3 of OAuthClaims's 28 fields

# Optional: register OAuthClaims as virtual entity if it has __relationships__
# (not required if you only want schema subsetting)
```

### Lifecycle interaction with `add_virtual_entities`

A BaseModel source can be in one of four states:

| State | Behavior |
|-------|----------|
| Not registered | Schema subsetting works (`__subset_fields__` populated). AutoLoad does NOT fire for the source's `__relationships__`. ER/Voyager does NOT show the source as a node. |
| Registered via `add_virtual_entities` | All of the above PLUS: AutoLoad fires (via R5 unified source resolution), ER/Voyager shows the source as a virtual node. |

The widening (Contract 5) and `add_virtual_entities` (Contract 1) are **orthogonal**: you can use either one without the other, or both together.

## Contract 6: What stays unchanged (backward compatibility)

These are NOT part of the new API — they are commitments to existing users that nothing breaks:

| Surface | Commitment |
|---------|-----------|
| `ErManager.__init__` signature | Unchanged. `base=` / `entities=` still required (one of). |
| `ErManager.__init__` validation | Unchanged. Empty `entities=[]` and missing `base=` still raise `ValueError`. |
| `Resolver.resolve(plain BaseModel)` behavior | Unchanged for trees without virtual entities. Already works (proven by `tests/test_resolver.py:22-32`). |
| `DefineSubset.__subset__` source | **Widened** to accept BaseModel (Contract 5). Existing SQLModel sources unaffected. |
| `Relationship` dataclass | Fields unchanged. Only `target_entity` return type annotation widens. |
| Existing tests | All 1025 pass without modification (SC-003). |
| `_subset_registry` direct mutation | Continues to "work" but is still undocumented; the official replacement is `add_virtual_entities()` + (optionally) DefineSubset-from-BaseModel. No deprecation warning added (private API). |

## Out of scope

These are explicitly NOT delivered by this feature:

- **Zero-SQLModel projects**: `ErManager(base=None, entities=None)` still raises `ValueError`. A project must have at least one SQLModel entity in `__init__`. (User-confirmed constraint.)
- **AutoLoad for unregistered BaseModel fields**: AutoLoad fires only when the source (SQLModel or BaseModel) is discoverable — via `get_subset_source()` (DefineSubset path) or via `_registry` lookup (virtual entity path). A plain BaseModel not registered anywhere still gets no auto-load (consistent with today).
- **Per-class customization hooks**: No "virtual entity metaclass", no decorator, no class-level marker. The class declaration alone is sufficient; behavior is uniform across all registered virtual entities.
- **`_orm_to_dto` rename**: The function name stays for backward source-compat. A future rename to `_source_to_dto` is optional polish, not part of this feature's contract.
