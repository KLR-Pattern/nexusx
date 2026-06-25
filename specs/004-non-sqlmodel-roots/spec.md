# Feature Specification: Non-SQLModel Root Objects

**Feature Branch**: `004-non-sqlmodel-roots`

**Created**: 2026-06-25

**Status**: Draft

**Input**: User description: "Issue #87: Support non-SQLModel root objects (pure Pydantic BaseModel) as first-class participants in Resolver / Relationship / ER flows. Today DefineSubset requires a SQLModel source — projects that need aggregate roots (CurrentUser, page wrappers, context-root DTOs) hack _subset_registry. Goal: make non-SQLModel roots officially supported — act as Resolver roots, declare custom relationships, run resolve_*/post_*, optionally render as virtual nodes in ER/Voyager. Three candidate directions to discuss: (A) new DefineModel/DefineVirtual API, (B) widen DefineSubset source to BaseModel, (C) official register_virtual_source/register_virtual_entity functions. Backward compat with SQLModel-first workflows required."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Authenticate-Driven Response Root (Priority: P1)

A backend developer is building a FastAPI endpoint that returns a response rooted at the **currently authenticated user**, with related data (their agents, notifications, recent activity) loaded dynamically. The `CurrentUser` object is assembled from request context (OIDC claims, headers), not from a SQLModel table. Today the developer must either bypass NexusX for this endpoint or hand-assemble the response. With this feature, the developer declares the root as a non-SQLModel DTO with `resolve_*` / `post_*` methods, and NexusX assembles the full tree just like it does for SQLModel-rooted responses.

**Why this priority**: This is the most common real-world shape that hits the limitation today — every authenticated endpoint with a "current user" root is affected. Shipping this slice alone already eliminates the most frequent reason projects reach for `_subset_registry` hacks.

**Independent Test**: Build a `CurrentUserRootDTO` whose `resolve_agents()` returns dynamic child DTOs and `post_agents()` annotates them. `Resolver().resolve(root)` returns the fully assembled tree. No internal registry mutation in the test.

**Acceptance Scenarios**:

1. **Given** a non-SQLModel Pydantic root DTO with `resolve_*` methods, **When** the developer calls `Resolver().resolve(root_instance)`, **Then** all `resolve_*` results are populated and traversal descends into child DTOs.
2. **Given** a non-SQLModel root DTO with `post_*` methods, **When** resolution completes, **Then** every `post_*` field has its computed value, exactly as it would for a SQLModel-rooted DTO.
3. **Given** a non-SQLModel root mixed in the same resolution tree as SQLModel-backed child DTOs, **When** resolution runs, **Then** both sides resolve correctly and ExposeAs / SendTo / Collector cross-layer flows work across the SQLModel / non-SQLModel boundary.

---

### User Story 2 - Composite / Page Wrapper Roots (Priority: P2)

A backend developer is assembling a **page-level response** that aggregates data from multiple services or repositories — e.g., a dashboard DTO with sections pulled from different sources. The page itself is not a SQLModel entity; it's a hand-defined Pydantic structure with custom relationships between sections. The developer wants this page DTO to participate in NexusX like any other root: declare fields, declare custom relationships to other (possibly SQLModel-backed) DTOs, run `resolve_*` to fetch section data, and use `post_*` to finalize.

**Why this priority**: Page / aggregate wrappers are the second-most-common shape. They differ from Story 1 in that they typically declare **custom relationships** between DTOs (not just dynamic `resolve_*`), so this story specifically exercises the relationship-declaration surface for non-SQLModel roots.

**Independent Test**: Build a `DashboardPageDTO` with a custom relationship `featured_agents: list[AgentDTO]`, where `AgentDTO` is itself a SQLModel-backed DefineSubset. Resolver correctly traverses both layers.

**Acceptance Scenarios**:

1. **Given** a non-SQLModel root with a declared custom relationship to a SQLModel-backed DTO, **When** the relationship field is auto-loaded by Resolver, **Then** the target DTOs are loaded via the registered loader and converted to the declared DTO type.
2. **Given** two non-SQLModel roots with a custom relationship between them, **When** Resolver traverses, **Then** the relationship field is populated correctly without requiring a SQLModel source on either side.
3. **Given** a non-SQLModel root whose `resolve_*` returns a SQLModel-backed DTO, **When** resolution runs, **Then** the returned DTO is treated as a traversable child and its own `resolve_*` / `post_*` fire normally.

---

### User Story 3 - ER / Voyager Visualization Without Crashes (Priority: P3)

A developer generates an ER diagram or opens Voyager for a project that **mixes SQLModel entities with non-SQLModel roots**. Today this either crashes (because ER tooling assumes every reachable type is a SQLModel entity) or silently drops the non-SQLModel portions. With this feature, non-SQLModel roots render as **virtual / context nodes** — clearly distinguishable from real DB tables — without crashing the diagram or hiding the relationship structure.

**Why this priority**: ER/Voyager is a developer-facing observability surface, not a runtime path. It's important for trust ("does NexusX see my full model?") but does not block production response assembly. Lower priority than the runtime stories.

**Independent Test**: A project that registers both SQLModel entities and non-SQLModel roots generates an ER diagram and opens Voyager without exceptions; the non-SQLModel roots appear as virtual nodes connected to the rest of the graph.

**Acceptance Scenarios**:

1. **Given** a project with both SQLModel entities and non-SQLModel roots, **When** the developer generates an ER diagram, **Then** generation completes without exceptions and every non-SQLModel root appears in the output.
2. **Given** a non-SQLModel root connected to a SQLModel-backed DTO via a custom relationship, **When** the diagram renders, **Then** the relationship is drawn between the virtual node and the real entity, visually distinguished.
3. **Given** a non-SQLModel root with no relationships at all, **When** Voyager opens, **Then** it appears as an isolated virtual node without crashing.

---

### Edge Cases

- A non-SQLModel root declares a relationship whose target is another non-SQLModel root — both sides must be recognized without SQLModel subclassing.
- A non-SQLModel root is passed to `Resolver.resolve()` before `add_virtual_entities()` has been called for its type — the system must produce a clear error pointing the user at the registration API (no silent auto-discovery from runtime instances).
- A class is passed to `add_virtual_entities()` that is a `SQLModel` subclass — the system MUST reject it with a clear `TypeError` directing the user to `__init__`'s `entities=` / `base=`.
- The same class is passed to `add_virtual_entities()` twice (or was already in `entities=` / discovered via `base=`) — the system MUST reject the duplicate with a clear `ValueError`.
- `add_virtual_entities()` is called after `er.create_resolver()` has already been invoked — the system MUST raise `RuntimeError` ("registry is frozen after first resolver creation").
- A non-SQLModel root is later converted into a SQLModel entity (or vice versa) — the migration path should be mechanical: move the class out of `add_virtual_entities()` and into `entities=` / let `base=` pick it up. No call-site rewrite beyond that.
- A non-SQLModel root participates in SendTo / Collector flows alongside SQLModel-backed DTOs — values must aggregate correctly across the boundary.
- The same BaseModel class is referenced by multiple custom relationships across the ER graph — both references must resolve to the same virtual node without conflict.
- A `DefineSubset` DTO is declared with `__subset__ = (SomeBaseModel, fields)` where `SomeBaseModel` is **not** registered via `add_virtual_entities` — schema subsetting still works (the DTO's `__subset_fields__` is populated), but auto-load of `SomeBaseModel`'s `__relationships__` does NOT fire because the source isn't in `_registry`. The user must either register it (`add_virtual_entities`) or write `resolve_*` methods manually on the DTO.
- A `DefineSubset` DTO sourced from a BaseModel has the same field declared as both a subset field AND a `__relationships__` target on the source — the relationship loader takes precedence (matches today's SQLModel behavior).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST accept a pure Pydantic `BaseModel` (not a SQLModel) as a valid root object for `Resolver().resolve(...)`.
- **FR-002**: The system MUST allow non-SQLModel roots to declare `resolve_*` methods that load child data dynamically, identically to SQLModel-rooted DTOs.
- **FR-003**: The system MUST allow non-SQLModel roots to declare `post_*` methods (including `post_default_handler`) and execute them at the correct phase of resolution.
- **FR-004**: The system MUST allow non-SQLModel roots to declare **custom relationships** to other DTOs (SQLModel-backed or not), and have Resolver traverse those relationships correctly.
- **FR-005**: The system MUST support cross-layer data flow (ExposeAs, SendTo, Collector) on trees that include non-SQLModel roots, with no behavioral difference from SQLModel-rooted trees.
- **FR-006**: The system MUST provide an **official, documented** API for declaring / registering non-SQLModel roots, replacing today's `_subset_registry` mutation hack.
- **FR-007**: The system MUST reject ambiguous registrations with a clear error (e.g., registering the same class twice with conflicting sources, or mixing incompatible declaration styles).
- **FR-008**: The system MUST preserve **full backward compatibility** for every existing SQLModel-only workflow — no existing DefineSubset declaration, ErManager call, or Resolver call may change behavior.
- **FR-009**: The system MUST allow non-SQLModel roots to be rendered in ER diagrams and Voyager as **virtual / context nodes**, visually distinguished from real DB-backed entities.
- **FR-010**: The system MUST NOT require non-SQLModel roots to fake a SQLModel table, primary key, or session — the capability is independent of any persistence concern.
- **FR-011**: The system MUST treat any plain `pydantic.BaseModel` subclass as a valid non-SQLModel root, without requiring the developer to inherit from a NexusX-specific base class, apply a decorator, or call a registration function. The class declaration alone is sufficient. [Resolves Issue #87's API-direction question per user direction: "any plain BaseModel will do, just needs to be addable in the ER diagram configuration".]
- **FR-012**: The system MUST allow custom relationships to be declared on a plain `BaseModel` non-SQLModel root using the **same `__relationships__` class attribute** mechanism that already exists for SQLModel entities today. No new declaration site, no new decorator, no separate registration call.
- **FR-013**: The system MUST provide an official `ErManager.add_virtual_entities(entities: list[type[BaseModel]])` method that registers plain `BaseModel` subclasses as non-SQLModel roots in the ER graph. After registration, the roots participate in ER diagram generation, Voyager rendering, and any ER-driven tooling exactly like SQLModel entities, except they have no table behind them. Specifics:
    - The method MUST be called **before** the first `er.create_resolver()` call. Calling it after the first resolver creation MUST raise a clear `RuntimeError` ("registry is frozen after first resolver creation") — once a Resolver has been built from the ErManager, the loader wiring and relationship registry cannot be safely mutated.
    - Each entry MUST be validated as a `BaseModel` subclass that is **not** a `SQLModel` subclass — SQLModel entities go in `__init__`'s `entities=` / `base=` and are rejected here with a clear `TypeError`.
    - Duplicate registration (the same class registered twice, or a class already present in `base=` / `entities=`) MUST be rejected with a clear `ValueError`.
    - `ErManager.__init__`'s requirement that **`base=` or `entities=` must be provided** is unchanged — the method is purely additive on top of an already-constructed ErManager. (A project with zero SQLModel entities remains unsupported; that edge case is out of scope.)
- **FR-014**: `DefineSubset`'s public API surface MUST stay unchanged in shape (same `__subset__` tuple, same metaclass, same `__subset_fields__` output). The **source** element of `__subset__` widens to accept any `BaseModel` subclass, not just `SQLModel` subclasses. Semantically, "subset" means "a subset of the source's schema (its `model_fields`)"; SQLModel and BaseModel both have well-defined schemas, so both fit. The difference is purely about **data provisioning**: SQLModel sources have ORM providing data automatically; BaseModel sources get data from other channels (user construction, external APIs, request context). `_orm_to_dto()` (the ORM-row → DTO conversion) is only invoked when the source is a SQLModel; for BaseModel sources, the user constructs DTO instances directly (no conversion needed).
- **FR-015**: When a non-SQLModel root is reachable from a SQLModel entity's relationship graph (or vice versa), the system MUST treat the boundary transparently — the developer must not write boundary-aware code.
- **FR-016**: The system MUST NOT silently impersonate a SQLModel for non-SQLModel roots — they are not subclasses of SQLModel, do not acquire SQLAlchemy table metadata, and are rejected by any code path that genuinely requires a SQLModel (e.g., raw SQLAlchemy query builders that need `__table__`).
- **FR-017**: The Resolver's source-resolution logic MUST be unified across SQLModel and BaseModel sources. Concretely: `_scan_auto_load_fields` resolves the source class for a given `node_type` via `get_subset_source(node_type)`, and if that returns `None` (the node is not a DefineSubset), falls back to checking whether `node_type` itself is registered in `_registry`. The subsequent relationship lookup (`_registry.get_relationships(source)`) is identical regardless of whether `source` is a SQLModel or a BaseModel. The principle: **the goal is always to find the relevant source class, then look up its relationships** — source type is irrelevant to that goal.

### Key Entities *(include if feature involves data)*

- **Non-SQLModel Root**: A plain `pydantic.BaseModel` subclass that participates in resolution and ER visualization without an underlying SQLModel source. Declares `resolve_*`, `post_*`, ExposeAs, SendTo, Collector, and `__relationships__` like any other model. No NexusX-specific base class, decorator, or registration call is required to mark it as a non-SQLModel root.
- **ER Configuration** (existing concept, broadened): The `ErManager` configuration (today `entities=[...]` accepts only SQLModel classes) is the integration point. After this feature, the same configuration accepts plain `BaseModel` classes alongside SQLModel entities; the non-SQLModel roots become first-class members of the ER graph.
- **Virtual Node (ER/Voyager concept)**: A node in the ER graph that represents a Non-SQLModel Root. Has no underlying table, no primary key, and no foreign keys; appears in diagrams as a peer to SQLModel entities but visually distinguished (so developers can tell at a glance "this is data-assembled, not table-backed").
- **Custom Relationship (existing concept, broadened)**: A declared edge via the `__relationships__` class attribute and the existing `Relationship` dataclass. Today only read from SQLModel entities; after this feature, also read from plain `BaseModel` classes that have been added to the ER configuration. Runtime semantics (auto-load, traversal, type compatibility) are identical regardless of which side declares the relationship.
- **`DefineSubset` (existing concept, broadened)**: The DTO base for schema subsetting. Source widens from `type[SQLModel]` to `type[BaseModel]` — both have well-defined `model_fields` schemas that can be subsetted. The "subset" semantics are about schema, not data source: SQLModel sources come with ORM-provisioned data; BaseModel sources come with data from other channels (user construction, external APIs, request context). `_orm_to_dto()` is only invoked for SQLModel sources; BaseModel sources are constructed directly by the user.
- **Source Resolution (existing concept, broadened)**: The Resolver's process for "given a `node_type`, find its source class". Today: `get_subset_source(node_type)` returns the SQLModel source for DefineSubset DTOs, or `None` for plain BaseModel. After this feature: returns SQLModel OR BaseModel source for DefineSubset DTOs; for plain BaseModel, falls back to checking whether `node_type` itself is registered in `_registry`. The downstream `_registry.get_relationships(source)` is source-type-agnostic.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A developer can assemble a non-SQLModel-rooted response (CurrentUser, page wrapper, context aggregate) end-to-end — `resolve_*`, `post_*`, custom relationships, cross-layer flows — with **zero** mutation of NexusX internal registries.
- **SC-002**: Every example called out in Issue #87's "Minimum Acceptance Criteria" section (CurrentUser → AgentDTO with `resolve_agents` / `post_agents`) runs to completion and produces the expected assembled result.
- **SC-003**: All existing SQLModel-only test suites continue to pass without modification — backward compatibility is verifiable, not just claimed.
- **SC-004**: ER diagram generation and Voyager opening succeed (no exceptions) for any project that mixes SQLModel entities with non-SQLModel roots; every reachable non-SQLModel root is visible in the output.
- **SC-005**: A developer reading only the official docs (no source-code archaeology) can implement a non-SQLModel root in under 15 minutes — the API is discoverable and documented as a first-class path, not a workaround.
- **SC-006**: The official migration path from a project currently relying on the `_subset_registry` hack is mechanical (search-and-replaceable), documented, and does not require re-architecting existing DTO hierarchies.

## Assumptions

- The "non-SQLModel root" capability is aimed at **response assembly** use cases (FastAPI endpoints, GraphQL resolvers, MCP tool responses). It is **not** aimed at making Pydantic classes behave like ORM entities — no DB queries, no sessions, no transactions.
- Existing SQLModel-first workflows remain the default and the recommended path for any DTO that *does* map to a table; non-SQLModel roots are an additional capability, not a replacement.
- **Architectural decision (from user direction):** The capability is intentionally minimal — a non-SQLModel root is a **plain `pydantic.BaseModel`** subclass with no NexusX-specific base class, no decorator, and no `__init__`-time registration. The only required integration is calling `ErManager.add_virtual_entities([...])` after constructing the ErManager but before its first `create_resolver()`. This rules out Issue #87's Option A (new declarative base), and uses a slice of Option C in method form (`add_virtual_entities()`) rather than as a free function.
- **DefineSubset widening decision (from user direction):** `DefineSubset.__subset__`'s source element widens to accept any `BaseModel` subclass, not just `SQLModel`. "Subset" is understood as **schema subset** (a selection of `model_fields`) — both SQLModel and BaseModel have well-defined schemas, so both fit. The difference is purely about data provisioning: SQLModel sources have ORM auto-provisioning (via `_orm_to_dto()`); BaseModel sources get data from other channels and the user constructs DTO instances directly. This widening is **orthogonal to** `add_virtual_entities`: a BaseModel class can be (a) only registered as virtual entity, (b) only used as DefineSubset source, (c) both, or (d) neither. The two APIs serve different real scenarios and compose cleanly.
- **Resolver unification principle (from user direction):** Source resolution follows the same logic regardless of source type — "find the source class for this `node_type`, then look up its relationships". `get_subset_source(node_type)` returns the source (SQLModel or BaseModel) for DefineSubset DTOs; for plain BaseModel roots, the fallback is "am I registered in `_registry` myself?". The subsequent `_registry.get_relationships(source)` is source-type-agnostic.
- **Lifecycle decision (from user direction):** `add_virtual_entities()` MUST be called before the first `er.create_resolver()`. After that, the ErManager registry is frozen and any further call raises `RuntimeError`. ErManager is therefore **immutable at runtime** — all entity registration (SQLModel via `__init__`, non-SQLModel via `add_virtual_entities`) happens at startup, before any request is served.
- **`__init__` signature decision (from user direction):** `ErManager.__init__`'s requirement that `base=` or `entities=` must be provided is **unchanged**. A project with zero SQLModel entities is out of scope (and would also have no loaders worth managing). `add_virtual_entities()` is purely additive on top of an already-constructed ErManager.
- Custom relationships on non-SQLModel roots use the **existing `__relationships__` class attribute** (same mechanism as SQLModel entities today). The relationship loader is supplied by the developer; there is no ORM metadata to read from. AutoLoad's implicit "field name matches ORM relationship" path still requires a real SQLModel source — non-SQLModel roots declare relationships explicitly via `__relationships__`.
- ER/Voyager "virtual node" rendering is a visualization concern only — it does not affect runtime resolution semantics. Virtual nodes have no table, no columns, and no foreign keys in the diagram. Visual distinction from real SQLModel entities is required (so developers can see at a glance "this is data-assembled, not table-backed").
- The feature targets Python 3.10+ (the same baseline as the rest of NexusX per `pyproject.toml`).
- The public API for adding a non-SQLModel root to ER configuration MUST be official and documented — direct mutation of `_subset_registry` or other internals by downstream code is the pattern being eliminated.
