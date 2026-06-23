# Feature Specification: Resolver `loader_instances` Parameter

**Feature Branch**: `002-resolver-loader-instances`

**Created**: 2026-06-23

**Status**: Draft

**Input**: User description: "~/pydantic-resolve 中 Resolver 方法支持 loader_instances, 我需要确认 nexusx 中也支持， 否则需要移植过来"

## Context & Gap

`pydantic-resolve` exposes a `Resolver(loader_instances={LoaderClass: instance})` parameter that lets callers pass in **pre-created DataLoader instances** — typically so they can `loader.prime(key, value)` ahead of time and skip redundant queries during resolution.

nexusx's `Resolver` (`src/nexusx/resolver.py:350`) currently accepts only `loader_registry` and `context`. The internal `Loader(DataLoaderClass)` dependency path always calls `loader_cls()` to create a fresh instance (`_get_or_create_loader` at `resolver.py:408-412`) — there is no way for a caller to inject an already-constructed (and possibly pre-primed) loader.

This gap is already listed in `docs/superpowers/specs/2026-04-29-audit.md:143` as **missing**.

**Out of scope** (per user direction): `loader_params`, `global_loader_param`, Resolver-level `split_loader_by_type`. Only `loader_instances` is in scope.

## Clarifications

### Session 2026-06-23

- Q: `loader_instances` 是否应该覆盖 ErManager 中 `__relationships__` 自定义 Relationship 生成的 loader（Path 2），以及 ORM 原生 SQLModel relationship 的内部 loader？ → A: **两者都不处理。** `loader_instances` 严格保持 pydantic-resolve 的语义：仅按 DataLoader **类** 匹配，仅作用于 `resolve_*` 方法中 `Loader(Cls)` 显式声明的依赖（Path 1）。`__relationships__` 自定义 Relationship 的 loader（`CustomLoader_{name}`）以及 ORM 原生 relationship 的内部 loader 都通过 ErManager 的按名字查找，**不**受 `loader_instances` 影响。决策依据：pydantic-resolve 没有 Path 2 先例（其所有 loader 都是 `Loader(Cls)` 扫描出来的类键控实例，无 name-based 路径），所以为保持移植等价性，nexusx 也不引入 Path 2。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Skip a redundant query by pre-priming (Priority: P1)

A caller knows ahead of time that certain entity keys will be requested during resolution (e.g. the current request's user is always needed). The caller creates a DataLoader, primes it with the already-fetched row, passes it to Resolver, and the resolver observes the primed value — no extra DB round-trip.

**Why this priority**: This is the primary motivation for `loader_instances` in pydantic-resolve and the reason it exists in the upstream library. It unlocks an optimization that is otherwise impossible in nexusx today.

**Independent Test**: Construct a DataLoader subclass that records every batch call, prime one key, pass the loader to Resolver, then assert that resolving a tree whose `resolve_*` method calls `loader.load(primed_key)` does NOT trigger a batch call and returns the primed value.

**Acceptance Scenarios**:

1. **Given** a DataLoader subclass `UserLoader` with a counting batch function, **When** the caller does `loader = UserLoader(); loader.prime(42, user_dto); resolver = Resolver(loader_instances={UserLoader: loader})` and resolves a tree where a `resolve_*` method calls `loader.load(42)`, **Then** the batch function is NOT invoked and the primed `user_dto` is returned.
2. **Given** a partially primed loader (key 42 primed, key 7 not), **When** the tree loads both keys, **Then** key 42 returns the primed value with no DB hit, and key 7 falls through to the batch function exactly once.

---

### User Story 2 - Inject a custom-configured DataLoader instance (Priority: P2)

A caller wants to supply a DataLoader subclass that was constructed with non-default constructor arguments (e.g. a custom cache key function, a pre-wrapped batch function with extra closure state). Resolver uses the supplied instance as-is.

**Why this priority**: Enables use cases the default `Loader(Subclass)` instantiation path cannot support, but less common than pre-priming.

**Independent Test**: Define a `ConfigurableLoader` whose constructor stores a tag; supply an instance; resolve a tree that uses it; assert the same instance (identical by `id()`, with its tag) is what `resolve_*` receives.

**Acceptance Scenarios**:

1. **Given** `loader = ConfigurableLoader(tag="abc")`, **When** passed via `loader_instances={ConfigurableLoader: loader}`, **Then** `id(loader_in_resolve) == id(loader)` and `loader_in_resolve.tag == "abc"`.
2. **Given** two different instances of the same DataLoader subclass supplied under different Resolver instances, **When** both resolve trees concurrently, **Then** each Resolver uses its own supplied instance (no cross-talk).

---

### User Story 3 - Fail fast on misuse (Priority: P3)

Passing a non-DataLoader class, an instance whose type does not match its key, or a malformed dict fails immediately at Resolver construction with a clear error — not silently later during traversal.

**Why this priority**: Matches pydantic-resolve's `_validate_loader_instance` behavior; prevents confusing mid-traversal errors.

**Independent Test**: Assert each malformed input raises a typed error before any traversal begins.

**Acceptance Scenarios**:

1. **Given** `loader_instances={dict: some_dict}`, **When** Resolver is constructed, **Then** a `TypeError` (or equivalent typed error) is raised because `dict` is not a DataLoader subclass.
2. **Given** `loader_instances={UserLoader: object()}`, **When** Resolver is constructed, **Then** a typed error is raised because the value is not an instance of `UserLoader`.
3. **Given** an empty dict `{}`, **When** Resolver is constructed, **Then** no error is raised and Resolver behaves identically to today (loader_instances simply not used).

---

### Edge Cases

- What happens if the caller supplies a loader class that no `resolve_*` method ever references? → Accepted silently; the entry is simply unused. Matches pydantic-resolve.
- What happens if a `resolve_*` method declares `Loader(UserLoader)` but `loader_instances` does NOT contain `UserLoader`? → Resolver creates a fresh instance via the existing `_get_or_create_loader` path. No error.
- What happens if the same Resolver instance is reused across multiple `.resolve()` calls while sharing a supplied loader? → Today's `Resolver.resolve()` clears `_loader_cache` per call (`resolver.py:1282-1283`); the supplied instance is NOT cleared (it is owned by the caller). Document this in the docstring.
- What happens with the auto-load path (relationship-name based, `_get_loader` → `ErManager`)? → **Confirmed out of scope.** Auto-load goes through `ErManager` and is keyed by relationship name, not by DataLoader class. `loader_instances` does not affect auto-load, regardless of whether the underlying relationship is a custom `__relationships__` entry or an ORM-native SQLModel relationship. See Clarifications session 2026-06-23.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `Resolver.__init__` MUST accept a new keyword parameter `loader_instances: dict[type[DataLoader], DataLoader] | None = None` without breaking existing positional/keyword usage of `loader_registry` and `context`.
- **FR-002**: When `loader_instances` is provided, Resolver MUST validate that every key is a subclass of `aiodataloader.DataLoader` and every value is an instance of its key. Invalid input MUST raise a typed error before traversal begins.
- **FR-003**: When a `resolve_*` method declares `loader=Loader(SomeLoader)`, Resolver MUST return the user-supplied instance from `loader_instances[SomeLoader]` if present; otherwise it MUST fall back to creating a fresh instance (today's behavior).
- **FR-004**: The supplied loader instance MUST be used by reference (not copied). Mutations performed by `resolve_*` (e.g. `loader.clear()`) MUST be visible to the caller after `resolve()` returns.
- **FR-005**: `ErManager.create_resolver()` MUST return a `Resolver` subclass whose `__init__` accepts `loader_instances` and forwards it to the underlying `Resolver.__init__`, so callers using the pre-wired Resolver class can also inject loaders.
- **FR-006**: Pre-primed values in a supplied loader (via `loader.prime(k, v)`) MUST be observable by `resolve_*` methods, and MUST suppress the corresponding batch call for that key (standard DataLoader semantics — the requirement is that Resolver does not bypass or wrap the supplied instance in a way that breaks this).
- **FR-007**: The existing `Loader(async_callable)` path (wrapping a function in a fresh DataLoader) MUST remain unchanged — `loader_instances` only matches by DataLoader **class**, not by callable.

### Key Entities *(include if feature involves data)*

This feature does not introduce new business entities. It modifies the `Resolver` constructor surface and the `ErManager.create_resolver()` factory.

- **Resolver**: model-driven traversal engine; gains a new optional constructor parameter.
- **ErManager**: produces a pre-wired `Resolver` class; its `create_resolver()` factory must thread the new parameter through.
- **DataLoader** (from `aiodataloader`): the unit of batched loading; instances are now potentially caller-supplied.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A caller can eliminate at least one redundant backend call per resolve by pre-priming a known key, verified by a batch-call counter that stays at zero for that key.
- **SC-002**: Behavior for any existing nexusx program (no `loader_instances` passed) is observably unchanged — the full existing test suite passes without modification.
- **SC-003**: Misuse of `loader_instances` (non-DataLoader key, mismatched instance type) is caught at construction time with a typed, identifiable error — never reaches the traversal loop.
- **SC-004**: Callers using the `ErManager.create_resolver()` factory can inject pre-created loaders with the same ergonomics as callers constructing `Resolver` directly.

## Assumptions

- Callers own the lifecycle of any supplied loader instance: Resolver does not copy, reset, or clear it. Callors that need per-request isolation pass a fresh instance per `resolve()` call.
- The supplied loader is shared across all uses of its class within a single Resolver instance (matches pydantic-resolve). This is incompatible with any future Resolver-level `split_loader_by_type` flag — a constraint to document but not enforce in code for this feature (since that flag is out of scope).
- `loader_instances` only overrides the explicit `Loader(DataLoaderClass)` Depends path. The auto-load path (`_get_loader` → `ErManager`) is keyed by relationship name and is **confirmed out of scope** — this applies uniformly to both custom `__relationships__` loaders and ORM-native SQLModel relationship loaders (see Clarifications session 2026-06-23). The split mirrors pydantic-resolve, which has no name-based loader path.
- This feature is API-surface parity with pydantic-resolve's `loader_instances`; semantically equivalent behavior is the success bar.
