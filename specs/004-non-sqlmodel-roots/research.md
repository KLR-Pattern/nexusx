# Phase 0 Research: Non-SQLModel Root Objects

**Date**: 2026-06-25
**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

Resolves the open design questions surfaced during spec writing. All answers derive from the existing nexusx codebase (no external research needed) — `loader/registry.py`, `relationship.py`, `er_diagram.py`, `voyager/`, and the existing `tests/test_resolver.py` proof that plain BaseModel roots already work.

## R1: Where does `add_virtual_entities()` write, and with what shape?

**Decision**: `add_virtual_entities()` writes into the **same `self._registry: dict[type, dict[str, RelationshipInfo]]`** that `__init__` populates for SQLModel entities. The dict value is `dict[rel_name, RelationshipInfo]` — identical shape, populated only from `__relationships__` (no `_inspect_relationships()` call, since there's no SQLAlchemy mapper to inspect).

**Rationale**:
- `self._registry` is the single source of truth that downstream code (`get_relationships()`, `get_all_entities()`, `get_relationship()`, etc.) reads. Writing into the same dict means zero branching in those readers.
- `RelationshipInfo` is already polymorphic enough — its `direction="CUSTOM"` branch is the same one used for SQLModel entities' `__relationships__` today (registry.py:358). Virtual entities simply produce only CUSTOM-direction relationships.
- No new internal data structure → smaller diff, less to test.

**Alternatives considered**:
- Separate `self._virtual_registry` keyed only on BaseModel — rejected; forces every reader (`get_relationships`, `get_relationship`, ER rendering) to consult two dicts. Higher blast radius.
- Wrap entries in a `VirtualEntityInfo` marker — rejected; the polymorphism lives in `RelationshipInfo` already.

**Touch point**: `loader/registry.py:337` (the `_registry` declaration's type annotation `dict[type[SQLModel], ...]` widens to `dict[type, ...]` — purely a typing change; the dict itself already accepts any hashable key).

## R2: How does `Relationship.target_entity` behave when `target` is a plain BaseModel?

**Decision**: `Relationship.target_entity` already returns the bare class via `get_args(self.target)[0]` (relationship.py:69-75) — works for any class including BaseModel. The return-type annotation `type[SQLModel]` widens to `type` (or `type[BaseModel]`).

`get_custom_relationships(entity)` signature widens from `entity: type[SQLModel]` to `entity: type` — the function body only does `getattr(entity, RELATIONSHIPS_ATTR, None)` and `isinstance(item, Relationship)` checks, neither of which depends on SQLModel.

**Rationale**: The function is already shape-agnostic; only the type annotations were lying. Widening them is a non-behavioral change.

**Alternatives considered**:
- Sibling function `get_custom_relationships_for_virtual(entity)` — rejected; duplicates the function for no behavioral difference.
- Runtime `issubclass(entity, BaseModel)` check inside `get_custom_relationships` that raises on non-BaseModel input — rejected; the function doesn't care, the caller (ErManager) cares and validates.

## R3: How is the "frozen after first create_resolver()" guard implemented?

**Decision**: Add a private `self._frozen: bool = False` flag on ErManager, set to `True` at the top of `create_resolver()`. `add_virtual_entities()` checks `if self._frozen` and raises `RuntimeError("ErManager registry is frozen after first create_resolver() call. Call add_virtual_entities() before any create_resolver().")`.

**Rationale**:
- Single bool, single check — minimal overhead.
- The flag is set, never reset — ErManager is single-use by design (one ErManager → many Resolver instances; entity registration happens once at startup).
- The check fires on the first line of `add_virtual_entities()`, before any other validation, so the error message is unambiguous.

**Touch points**:
- `loader/registry.py:303` — add `self._frozen = False` in `__init__`
- `loader/registry.py:491` — set `self._frozen = True` at top of `create_resolver()`
- `loader/registry.py` — new `add_virtual_entities()` method with the guard

**Alternatives considered**:
- `_frozen_counter` (increment on each `create_resolver()`) — rejected; the binary state is sufficient and clearer.
- Threading lock — rejected; ErManager is constructed at process startup before any async loop runs. No concurrency to protect against.
- Refcounting Resolvers and unfreezing when the last one is GC'd — rejected; massive complexity for zero practical value.

## R4: ER/Voyager rendering — what's the branch for virtual nodes?

**Decision**: Virtual nodes are rendered as a **separate DOT cluster** (`cluster_virtual`) with:
- **Shape**: `shape=note` (vs SQLModel's `shape=record` with table-like cell layout)
- **Label**: the class name with a `«virtual»` UML stereotype prefix, e.g. `«virtual»\nCurrentUser`
- **No table, no columns, no FKs**: the record body is empty; the node is purely a relationship endpoint

The branch is added at the rendering layer (`er_diagram.py` + `voyager/er_diagram_dot.py`), not at the data layer. The data model for ER (`ErDiagram`) gains a `virtual_entities: list[type]` field alongside the existing `entities: list[type[SQLModel]]`.

For each virtual entity, the rendering iterates its `__relationships__` (read via the same `get_custom_relationships()` widened in R2) and draws edges to the target entity (whether SQLModel or another virtual). No `sa_inspect()` is called on virtual entities — that's the crash point today (`er_diagram.py:81-82`).

**Rationale**:
- Visual distinction via standard DOT shape + UML stereotype is consistent with how ER diagrams conventionally mark non-table-backed entities.
- Keeping virtual nodes in a separate cluster makes the diagram readable when many are present (they don't pollute the main entity cluster).
- Empty record body + edges-only participation is the minimal representation; trying to render "fields" would suggest table-like structure that doesn't exist.

**Touch points**:
- `er_diagram.py:64` (`ErDiagram.from_sqlmodel()`) — split: SQLModel branch stays, new `_from_virtual_entity()` helper for BaseModel branch
- `er_diagram.py:81-82` — guard `sa_inspect()` with `if isinstance(entity, SQLModel)` (or pre-partition the input list)
- `voyager/er_diagram_dot.py` — DOT emission branch for virtual nodes (cluster + shape=note)
- `voyager/type_helper.py:191` — already handles `ICollector`; verify it doesn't crash on plain BaseModel sources (may not need any change)

**Alternatives considered**:
- Render virtual nodes with the same shape as SQLModel but with dashed border — rejected; harder to discern at a glance than a different shape entirely.
- Skip rendering virtual nodes entirely (just draw edges to "anonymous") — rejected; defeats the purpose (FR-009 requires visibility).
- Put virtual nodes in the main cluster — rejected; mixes "table-backed" and "data-assembled" semantics in the same visual region.

## R5: Resolver source-resolution — unified logic for SQLModel and BaseModel

**Decision**: `_scan_auto_load_fields` (resolver.py:519) gains a unified source-resolution step:

```python
source_entity = get_subset_source(node_type)
if source_entity is None and self._registry is not None:
    # Plain BaseModel root registered directly via add_virtual_entities
    if self._registry.has_entity(node_type):
        source_entity = node_type
if source_entity is None:
    self._auto_load_cache[node_type] = []
    return []

entity_rels = self._registry.get_relationships(source_entity)
# ... rest unchanged
```

The principle: **the goal is always to find the relevant source class, then look up its relationships** — source type is irrelevant to that goal. `get_subset_source()` handles DefineSubset DTOs (now returning SQLModel OR BaseModel sources, per R8). The fallback handles plain BaseModel roots that bypass DefineSubset. The downstream `_registry.get_relationships(source)` is source-type-agnostic.

**Rationale**:
- ~10 LOC change, isolated to one function.
- Preserves today's behavior bit-identically when `node_type` is not a DefineSubset AND not in `_registry` (the fallback's `if` is False, source stays None, function returns []).
- The unified path is conceptually correct: both branches answer the same question ("what's the source for this node?"), just with different lookup strategies.

**Touch points**:
- `resolver.py:519` (`_scan_auto_load_fields`) — add the fallback, ~10 LOC
- `loader/registry.py` — add `has_entity(entity: type) -> bool` convenience method if not already present (today's `get_relationships()` returns `{}` for unknown entities, which conflates "no relationships" with "not registered"; `has_entity` makes the check explicit)

**Alternatives considered**:
- Force every virtual root to be a DefineSubset (no fallback needed) — rejected; clunky for the common case where root = self (see R8 discussion).
- Make `get_subset_source()` itself consult `_registry` as a fallback — rejected; `_subset_registry` is the DefineSubset → source mapping, semantically narrow. Polluting it with self-mappings ("X is its own source") muddies the data model.

## R6: Visual distinction specifics — DOT shape and label?

**Decision**:
- **Shape**: `shape=note` for virtual, `shape=record` (or M-record) for SQLModel entities — the visual contrast is immediate.
- **Fill**: light yellow fill (`style=filled, fillcolor="#FFF9C4"`) for virtual nodes; SQLModel entities keep their current fill (or none).
- **Label**: `«virtual»\n{ClassName}` — UML stereotype prefix is the canonical way to mark non-standard entities.
- **Edges**: same arrow style as SQLModel relationships (no special casing).

**Rationale**:
- `shape=note` is the most common Graphviz convention for "this is a non-database concept" (used in ORM diagrams for views, in domain diagrams for value objects).
- Light yellow is light enough to not dominate, distinct enough to be spotted.
- The `«virtual»` stereotype survives black-and-white printing (the shape change alone might be missed; the text label is unambiguous).

**Alternatives considered**:
- `shape=component` (box with "component" look) — rejected; suggests software architecture rather than data.
- Bright red fill — rejected; triggers "error" connotation. Yellow is neutral-warning.
- Suffix the class name with `*` instead of a stereotype — rejected; less self-documenting than `«virtual»`.

## R7: Migration path from `_subset_registry` hacks

**Decision**: Document a one-shot migration in `quickstart.md`. The right migration depends on what the hack was doing:

**Case A — registering a BaseModel as a "virtual source" for auto-load / ER visibility:**
```python
# Before (hack):
from nexusx.subset import _subset_registry
_subset_registry[CurrentUserRootDTO] = CurrentUserRoot  # fragile, undocumented

# After (official, with widened DefineSubset):
class CurrentUserRootDTO(DefineSubset):
    __subset__ = (CurrentUserRoot, ('oid', 'name'))   # source can now be BaseModel
    # ... resolve_*, post_*, __relationships__ on source or DTO ...

er = ErManager(base=SQLModel, session_factory=async_session)
er.add_virtual_entities([CurrentUserRoot])  # register source for ER + relationship lookup
```

**Case B — using a BaseModel root that is itself the schema (no subsetting):**
```python
# Before (hack): mutation of _subset_registry to make Resolver recognize the root

# After (official, plain BaseModel path):
class CurrentUserRoot(BaseModel):    # no DefineSubset wrapper
    oid: str
    name: str
    __relationships__ = [...]

er = ErManager(base=SQLModel, session_factory=async_session)
er.add_virtual_entities([CurrentUserRoot])
```

The migration is **mechanical** because:
- `DefineSubset` widening preserves existing DTO hierarchies (no rewrite).
- `ErManager.__init__` signature is unchanged.
- The single conceptual change is "remove the `_subset_registry[X] = Y` line; instead, `er.add_virtual_entities([X])` after construction; if X was wrapped in DefineSubset, that now works directly".

**Rationale**: SC-006 requires the migration to be search-and-replaceable. The mechanical mappings above satisfy that.

**Alternatives considered**:
- Deprecation warning when `_subset_registry` is mutated directly — rejected; the dict is a private implementation detail. We don't add public deprecation paths for private APIs. Just document the migration.

## R8: DefineSubset source widening — semantics and impact

**Decision**: `DefineSubset.__subset__`'s source element widens from `type[SQLModel]` to `type[BaseModel]`. The "subset" semantics are about **schema** (a selection of `model_fields`), not about data source — both SQLModel and BaseModel have well-defined schemas that can be subsetted.

The difference between SQLModel sources and BaseModel sources is purely about **data provisioning**:

| Aspect | SQLModel source | BaseModel source |
|--------|-----------------|------------------|
| Schema source | `__table__.columns` + `model_fields` | `model_fields` only |
| Data provisioning | ORM (auto via `_orm_to_dto`) | User constructs directly |
| `_orm_to_dto()` invoked? | Yes (ORM row → DTO) | No (no ORM row exists) |
| `__relationships__` source | ORM mapper + custom | Custom only (no ORM mapper) |
| AutoLoad field-name match | Yes (existing) | Yes (after R5 Resolver unification) |

**Touch points**:
- `subset.py:544` — `if not (isinstance(entity_kls, type) and issubclass(entity_kls, SQLModel)):` widens to `issubclass(entity_kls, BaseModel)`. The error message ("DefineSubset source must be a SQLModel subclass") updates accordingly.
- `resolver.py:663` (`_orm_to_dto`) — the function body uses `getattr(orm_instance, f, None)` which works on BaseModel instances too. The only change is renaming/relabeling: the function should be understood as "source instance → DTO", and the call sites that pass ORM rows keep working. For BaseModel sources, the function is simply never called — the user constructs DTO instances directly. (Optionally rename `_orm_to_dto` → `_source_to_dto` for clarity, but this is a refactoring concern, not a behavioral change.)
- `_subset_registry: dict[type[BaseModel], type[SQLModel]]` (subset.py:53) — type annotation widens to `dict[type[BaseModel], type[BaseModel]]` (DTO → source, where source can be SQLModel or BaseModel). The dict shape is unchanged.

**Rationale**:
- Conceptually clean: "subset" applies uniformly to any schema, regardless of how that schema is provisioned with data.
- Orthogonal to `add_virtual_entities`: a BaseModel can be (a) registered as virtual entity only, (b) used as DefineSubset source only, (c) both, or (d) neither. The two APIs serve different real scenarios (root-is-self vs. root-is-subset-of-external-schema) and compose cleanly.
- Existing DefineSubset usage (SQLModel sources) is bit-identical — the widening is purely permissive (accepts more types), not restrictive.
- Resolver's source-resolution logic (R5) handles the unified flow: `get_subset_source()` returns SQLModel or BaseModel, `_registry.get_relationships()` is source-type-agnostic.

**Specific non-problems** (recorded because they were raised and dismissed during design):

- **`_orm_to_dto` semantic breakage**: NOT a problem. The function is the ORM-provisioned-data conversion path, named for its historical role. BaseModel sources simply don't invoke it. No rename is strictly required (the function body is type-agnostic via `getattr`); a rename to `_source_to_dto` is optional polish.
- **`__subset__` becomes a "lie"**: NOT a problem. The user's framing — "subset means subset of some schema, regardless of where data comes from" — is the correct semantics. SQLModel and BaseModel both have well-defined schemas.
- **Field type validation in subset.py:325-331**: NOT a problem. The check rejects DefineSubset field types that are raw SQLModel (because SQLModel fields have ORM lazy-load side effects). BaseModel field types don't have these side effects, so the check is correctly silent for them.
- **Two declaration patterns causing user confusion**: MINOR concern, addressed by clear docs. The patterns serve different scenarios (see R7 Case A vs. Case B) and the recommendation is straightforward: "use DefineSubset when you're subsetting an external schema; use plain BaseModel + `add_virtual_entities` when the root IS the schema".

**Alternatives considered**:
- Keep DefineSubset SQLModel-only, force all virtual roots through plain BaseModel + `add_virtual_entities` — rejected; loses the legitimate "subset of an external BaseModel schema" use case (e.g., third-party SDK class, OAuth claims class).
- Drop `add_virtual_entities` entirely, force all virtual roots through DefineSubset (self-referencing source or wrapping a separate source class) — rejected; clunky for the common "root is its own schema" case, requiring users to declare two classes for one concept.
