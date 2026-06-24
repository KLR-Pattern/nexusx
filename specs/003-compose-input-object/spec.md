# Feature Specification: Compose Schema — INPUT_OBJECT Handling for Method Args

**Feature Branch**: `003-compose-input-object`

**Created**: 2026-06-24

**Status**: Implemented (2026-06-24, PR #84)

**Input**: User description: "Port the three INPUT_OBJECT introspection fixes from pydantic-resolve v5.10.2 into nexusx's own compose_schema surface."

**Reference**: pydantic-resolve v5.10.2, commit `184886d` (2026-6-24). Upstream changelog + `tests/use_case/test_compose_introspection.py` are the source of truth for expected behavior.

## Context

nexusx's UseCase compose surface (`src/nexusx/use_case/compose_schema.py` + `compose_type_mapper.py`) builds a GraphQL schema from `UseCaseService` classes for the introspection / SDL / executor pipeline. Today every Pydantic `BaseModel` is registered as a GraphQL `OBJECT` regardless of whether it appears as a method **return** or a method **argument**. That violates the GraphQL spec (input types must be `INPUT_OBJECT`, not `OBJECT`) and produces introspection output that GraphiQL / graphql-core reject.

pydantic-resolve v5.10.2 just fixed exactly this class of bug upstream. nexusx maintains a parallel implementation and has the same three bugs. This feature ports the fixes.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - BaseModel arg surfaces as INPUT_OBJECT (Priority: P1)

A developer writes a `@mutation` method that takes a Pydantic payload, e.g. `create_task(payload: CreateTaskInput) -> TaskDTO`. They open GraphiQL against the compose introspection endpoint and run `__schema { types { name kind fields args { type { kind name } } } } }`.

Today: the `payload` arg's type shows `kind=INPUT_OBJECT` at the type-ref layer but no `INPUT_OBJECT` entry exists in `schema.types` (or worse, the entry exists as `OBJECT`), and `inputFields` is null/empty. GraphiQL refuses to build the explorer.

After the fix: the schema contains an `INPUT_OBJECT` named `CreateTaskInput` with `inputFields` populated from the pydantic model's fields, including `defaultValue` rendered as a GraphQL literal (`10`, `null`, `"hi"`, `true`) when the field has a pydantic default.

**Why this priority**: This is the core spec violation. Without it, every method that accepts a BaseModel arg produces invalid GraphQL. P2 and P3 build on top of it.

**Independent Test**: Register a single service with one method that takes a BaseModel arg, call `build_compose_schema(app)`, assert the registry contains an `INPUT_OBJECT` entry whose `inputFields` match the model's fields and whose `defaultValue`s match the pydantic defaults. No execution of the method required.

**Acceptance Scenarios**:

1. **Given** a method `create_task(payload: CreateTaskInput)` where `CreateTaskInput` has fields `title: str`, `priority: int = 5`, `note: str | None = None`, **When** the compose schema is built, **Then** the registry contains an `INPUT_OBJECT` named `CreateTaskInput` with three `inputFields` whose `defaultValue`s serialize as `<none>` / `5` / `null` respectively.
2. **Given** the same schema, **When** `__schema { types { name kind } }` is queried via `compose_introspect`, **Then** exactly one entry with `name=CreateTaskInput` exists and its `kind=INPUT_OBJECT`.
3. **Given** a method whose BaseModel arg has a field with `Field(default_factory=list)`, **When** the schema is built, **Then** the build fails with a clear error (mutable defaults are not representable as GraphQL literals) — same behavior as for method-arg defaults today.

---

### User Story 2 - Same model as return AND arg does not crash (Priority: P2)

A developer writes a method that uses the same Pydantic class on both sides, e.g. `upsert_task(task_id: int, patch: TaskDTO) -> TaskDTO`. (Common when the DTO is the natural shape for both partial input and full output.)

Today: `build_compose_schema` raises `DuplicateTypeError` because `_register_object` sees the class name twice (once for the return, once for the arg). The developer gets a startup crash with no clear remediation.

After the fix: the return side registers `TaskDTO` as an `OBJECT`; the arg side detects the name collision and registers the same class again as an `INPUT_OBJECT` named `TaskDTOInput`. The arg's `type_ref` points at `TaskDTOInput`, and any field of any other input type that references `TaskDTO` also resolves to `TaskDTOInput`. No spec violation, no crash.

**Why this priority**: This is the failure mode that takes an app from "weird introspection" to "won't start at all". P3 depends on the SDL renderer picking up the renamed leaf correctly.

**Independent Test**: Register a service with a method whose return and arg types are the same BaseModel class. Assert the registry contains both `TaskDTO` (OBJECT) and `TaskDTOInput` (INPUT_OBJECT), and that the method field's `args[0].type_ref.leaf_name == "TaskDTOInput"`.

**Acceptance Scenarios**:

1. **Given** `upsert_task(patch: TaskDTO) -> TaskDTO`, **When** `build_compose_schema(app)` runs, **Then** the registry contains `TaskDTO` (kind=OBJECT, with `fields`) AND `TaskDTOInput` (kind=INPUT_OBJECT, with `inputFields`), and no exception is raised.
2. **Given** the same schema, **When** the method field is inspected, **Then** `args[0].type_ref` walks to a leaf named `TaskDTOInput` (not `TaskDTO`).
3. **Given** a nested input model `OuterInput { inner: InnerInput }` where `InnerInput` is also used as a return elsewhere, **When** the schema is built, **Then** `OuterInput.inner`'s type_ref leaf is `InnerInputInput` (renamed consistently through the input closure).

---

### User Story 3 - Method SDL expands INPUT_OBJECT types (Priority: P3)

A developer calls `describe_compose_method` (or `compose_schema.render_method_sdl(...)`) to get a focused, single-method SDL for an LLM / docs / explorer. The method takes a BaseModel arg.

Today: `_render_method_sdl` collects the transitive closure of the **return** type only, and `_collect_closure` doesn't recurse into `INPUT_OBJECT` kind. So the SDL references `input CreateTaskInput { ... }` without ever defining it.

After the fix: the closure walk (i) starts from BOTH the return type AND each arg's type_ref, and (ii) recurses through `INPUT_OBJECT` entries' `inputFields`. A new SDL emitter branch renders the collected INPUT_OBJECT types as `input X { ... }` blocks.

**Why this priority**: Cosmetic in the sense that no spec validator runs on the SDL string, but it's the surface AI agents and developers actually read. Surfaced wrong, it undermines trust in the whole compose surface.

**Independent Test**: Build a schema with a method `create_task(payload: CreateTaskInput) -> TaskDTO` where `CreateTaskInput` has a nested BaseModel field. Call `render_method_sdl`. Assert the output contains both `input CreateTaskInput { ... }` and the nested `input NestedInput { ... }` blocks, and that no referenced type is left undefined.

**Acceptance Scenarios**:

1. **Given** the schema from User Story 1, **When** `render_method_sdl(service, "create_task")` is called, **Then** the SDL contains an `input CreateTaskInput { ... }` block with the three fields and matching default literals.
2. **Given** the schema from User Story 2, **When** `render_method_sdl(service, "upsert_task")` is called, **Then** the SDL contains a `type TaskDTO { ... }` block (for the return) AND an `input TaskDTOInput { ... }` block (for the arg), with no name reused across both.
3. **Given** any method, **When** the method SDL is rendered, **Then** every type name referenced in any field or arg has a corresponding `type`/`input`/`enum`/`scalar` definition in the output.

---

### Edge Cases

- **BaseModel arg with `Annotated[T, FromContext()]`**: FromContext params are skipped from the public schema before type mapping — unaffected by these fixes. Verify the skip still happens on the input codepath.
- **`Optional[SomeInput]` arg**: the nullable wrapper must still apply on top of `INPUT_OBJECT` (arg type_ref = `INPUT_OBJECT` nullable, not `OBJECT` nullable).
- **`list[SomeInput]` arg**: list wrapper around input object — `list[SomeInput!]!` semantics preserved.
- **Two distinct BaseModel classes that happen to share a Python class name** (different modules, same `__name__`): `DuplicateTypeError` still fires — this fix does NOT weaken that guard for genuinely distinct classes. Only the *same class* used as both return and arg triggers the `{Name}Input` rename.
- **BaseModel arg with a field whose type is itself used as a return**: the nested-field type_ref must also rename consistently (recursive rename through the input closure).
- **No BaseModel args at all** (the common app today): schemas must be byte-identical to the pre-fix output (regression gate).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The compose type mapper MUST accept an `is_input: bool` parameter on the leaf-registration codepath. When `is_input=True`, a Pydantic `BaseModel` leaf MUST register as kind `INPUT_OBJECT` with `inputFields` populated from the model's fields; when `is_input=False` (default, return side), behavior MUST be unchanged (kind `OBJECT` with `fields`).
- **FR-002**: For each input field on an `INPUT_OBJECT`, `FieldInfo.default_value` MUST be populated from the corresponding pydantic field's default and rendered into introspection `inputFields[i].defaultValue` as a GraphQL literal (Int → `10`, String → `"hi"`, Boolean → `true`, None → `null`). A missing default MUST render no `= ...` clause in SDL and no `defaultValue` key in introspection (matching method-arg default behavior).
- **FR-003**: `_build_method_arguments` MUST pass `is_input=True` when mapping each BaseModel arg's type. Non-BaseModel args (scalars, enums, list/Optional wrappers) MUST be unaffected by the `is_input` flag.
- **FR-004**: `build_compose_schema` MUST run in two phases: (a) walk every method's **return** type and register all reachable Pydantic models as OBJECT; (b) then walk every method's **args** and register all reachable Pydantic models as INPUT_OBJECT via the `is_input=True` codepath. Phase ordering is load-bearing — returns win the bare class name.
- **FR-005**: During phase (b), if a Pydantic class's bare name is already registered as an OBJECT (from phase a), the input-side registration MUST rename to `{Name}Input`. The registry's id→TypeInfo map MUST be consulted so subsequent references to the same class (from sibling input fields or nested input models) resolve to the renamed `INPUT_OBJECT` leaf.
- **FR-006**: `_render_method_sdl` / `_collect_closure` MUST (a) seed the closure walk from BOTH the method's return type_ref AND every arg's type_ref, and (b) recurse through `INPUT_OBJECT` entries' `inputFields` (not treat INPUT_OBJECT as a leaf).
- **FR-007**: The SDL emitter MUST choose `input` (not `type`) as the block keyword for any TypeInfo whose `kind == INPUT_OBJECT`. OBJECT / ENUM / SCALAR rendering MUST be unchanged.
- **FR-008**: The introspection JSON produced by `compose_introspect` for a schema with INPUT_OBJECT types MUST validate against the GraphQL spec — i.e., feeding it to `graphql-core`'s `build_client_schema` MUST NOT raise, and GraphiQL MUST render the input type with its fields populated.
- **FR-009 (regression gate)**: Apps that declare no BaseModel method args MUST produce a schema registry byte-for-byte identical (same set of type names, same kinds, same fields) to the pre-fix implementation. No existing passing test in `tests/test_compose_*.py` may break.

### Key Entities *(metadata model — not business entities)*

- **TypeInfo**: a registered GraphQL type. Already present; this feature extends its use to `kind=INPUT_OBJECT` with `inputFields` (previously the `INPUT_OBJECT` kind existed in the literal but was never produced by the builder).
- **FieldInfo**: a field on an OBJECT (already present) or an input field on an INPUT_OBJECT (new use). Same shape — `name`, `type_ref`, `has_default`, `default_value`, `description`.
- **ArgumentInfo**: a method argument (already present). Unchanged shape; only the `type_ref` it carries may now point at an `INPUT_OBJECT` leaf.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of the pydantic-resolve v5.10.2 `test_compose_introspection.py` edge cases (ported to nexusx's test layout) pass against the new implementation — i.e., the three upstream fixes are faithfully reproduced.
- **SC-002**: 0 schema-validation errors when a representative compose schema (covering all three user stories) is fed to `graphql.build_client_schema` from `graphql-core`.
- **SC-003**: The full existing `tests/test_compose_*.py` suite passes unchanged — i.e., zero regressions for apps without BaseModel args.
- **SC-004**: The same Python service class (`upsert_task(patch: TaskDTO) -> TaskDTO`) round-trips through `build_compose_schema` → introspection → SDL without raising, where the pre-fix implementation raised `DuplicateTypeError`.

## Assumptions

- The upstream pydantic-resolve v5.10.2 fix (`commit 184886d`) is the reference implementation. Where nexusx's internal structure differs (it has a separate `ComposeTypeMapper` class rather than a free-function `_build_type_ref`), the fix is adapted to nexusx's shape rather than copy-pasted.
- pydantic-resolve and nexusx are sibling projects by the same author; behavior parity on the compose surface is the goal, not API parity.
- The `{Name}Input` rename convention is taken verbatim from upstream. If the user prefers a different suffix (e.g. `{Name}Arg`), that's a small adjustment.
- Mutable pydantic defaults (`default_factory=list`) on input fields remain unsupported, mirroring the existing constraint on method-arg defaults.
- The introspection JSON shape already matches what GraphiQL expects for OBJECT/ENUM/SCALAR; only INPUT_OBJECT was missing. No introspection renderer rewrite is in scope.

## Phase 0: Requirements Confirmation (nexusx)

> **Applicability note**: This feature is a **bug-fix port** into an existing internal module (`src/nexusx/use_case/compose_schema.py`), not a new business application built on nexusx. Most Phase 0 steps (entities / relationships / aggregate roots / service partitioning / DB persistence) describe the **consumer** of nexusx, not nexusx itself, and do not apply here. Steps that DO apply are filled in; the rest are marked `N/A — see note` with a one-line rationale. Confirm or override with the user before `/speckit-plan`.

### Step 0-1: Entities & Fields

**N/A — see note.** This feature changes how nexusx represents GraphQL metadata (`TypeInfo` / `FieldInfo` / `ArgumentInfo`) internally. It does not introduce or alter any business entity. The metadata-model changes are documented under *Key Entities* above.

### Step 0-2: Relationships

**N/A — see note.** No new entity relationships. The one structural relationship added is internal: an `INPUT_OBJECT` TypeInfo may reference other TypeInfo leaves through its `inputFields`, parallel to how OBJECT already referencesTypeInfo through `fields`.

### Step 0-3: Aggregate Roots

**N/A — see note.** No aggregate root involved. The unit of work is `build_compose_schema(app)` — already an existing function whose signature is unchanged.

### Step 0-4: Service Partitioning

**N/A — see note.** No UseCaseService split decisions. The fix is internal to the schema builder; service authors see no API change beyond the bug disappearing.

### Step 0-5: GraphQL Positioning

**Confirmed (no change).** GraphQL introspection remains an **auxiliary testing interface** in nexusx. This feature makes that interface spec-compliant for input types — it does not promote GraphQL to a primary API.

### Step 0-6: Third-Party Library Selection

**None new.** The fix uses the existing `pydantic`, `graphql-core` dependencies already in `pyproject.toml`. No new third-party concern is introduced. Reference: `graphql.build_client_schema` (already a transitive dep) is used only in tests to assert spec-compliance (FR-008 / SC-002).

### Step 0-7: DB Persistence & Migration Strategy

**N/A — see note.** This feature touches the metadata builder only. No DB schema change, no migration, no `DATABASE_URL` decision.

### Step 0-8: Phase 0 Checklist

- [x] Entities & fields step reviewed — N/A for a bug-fix port (justified above)
- [x] Relationships step reviewed — N/A (justified above)
- [x] Aggregate root step reviewed — N/A (justified above)
- [x] Service partitioning step reviewed — N/A (justified above)
- [x] GraphQL positioning confirmed — no change to its auxiliary role
- [x] Third-party libraries reviewed — none new
- [x] DB / migration step reviewed — N/A (justified above)
- [x] **User confirms** the Phase 0 N/A markings above are acceptable for this feature type — confirmed 2026-06-24

> All boxes ticked. User accepted the N/A treatment for this bug-fix port on 2026-06-24; Phase 0 gate is satisfied and `/speckit-plan` may proceed.
