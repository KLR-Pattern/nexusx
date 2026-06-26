# Changelog

## Unreleased

### Added

- **Non-SQLModel root objects (virtual entities)** — plain `pydantic.BaseModel` subclasses are now first-class participants in NexusX resolution and ER visualization, without requiring a SQLModel subclass or an underlying table. Three capabilities land together:
  - `ErManager.add_virtual_entities([...])` registers plain BaseModel classes in the ER graph. Must be called before `create_resolver()`; the registry freezes afterward. SQLModel classes are rejected here and continue to go through `__init__`'s `entities=` / `base=`.
  - **`DefineSubset.__subset__` source widening** — source can now be any `BaseModel` (SQLModel or plain). Useful for subsetting external schemas (OAuth claims, SDK response classes) without an ORM table.
  - **ER / Voyager virtual node rendering** — virtual entities render with a yellow fill (`#FFF9C4`), `«virtual»` UML stereotype, and a dashed `cluster_virtual` subgraph, visually distinguished from real DB-backed entities. Use `ErDiagram.from_er_manager(er)` (data API) or `ErDiagramDotBuilder(er).render_dot()` (DOT path).

- **Unified source-resolution in Resolver** — `_resolve_source()` provides a single helper backing both `_get_loader` and `_scan_auto_load_fields`. A clear `RuntimeError` is raised when a class declares `__relationships__` but is not registered via `add_virtual_entities()`, instead of silently skipping auto-load.

- **Migration path** — projects using the `_subset_registry[X] = Y` hack can migrate mechanically. See the [migration guide](./migration.md) and the [Virtual Entities guide](../guide/virtual_entities.md).

## 1.4.0

!!! warning "Breaking Change: rpc → use_case Refactor"

    `RpcService` → `UseCaseService`, `create_rpc_mcp_server` → `create_use_case_mcp_server`, `create_rpc_voyager` → `create_use_case_voyager`.

    Added four-layer MCP tools (`list_apps` → `list_services` → `describe_service` → `call_use_case`), multi-app management support (`UseCaseAppConfig`), and context injection (`FromContext`).

!!! warning "Breaking Change: Removal of `RpcServiceConfig` (Historical)"

    The `RpcServiceConfig` TypedDict has been removed. Services now directly accept a list of subclasses.

    - Service names are derived from `cls.__name__`
    - Service descriptions are derived from `cls.__doc__`

## 1.3.3

!!! warning "Breaking Change: Removal of `Loader(str)` Support"

    Removed the string-based `Loader('relationship_name')` pattern. Only `Loader(DataLoaderClass)` and `Loader(async_callable)` are supported.

!!! tip
    Implicit auto-loading (field name matching relationship + compatible type) already covers common scenarios without needing `resolve_*` methods.

## 1.3.2

**Bug Fix**: Fixed `IntrospectionGenerator` default value serialization, changing from Python `repr()` to JSON format (`json.dumps`).

## 1.3.1

- Full documentation for Core API, RPC + Voyager modes from v1.3.0 onwards
- Updated `llms-full.txt` to reflect current API

---

For the complete changelog, see [CHANGELOG.md on GitHub](https://github.com/allmonday/nexusx/blob/master/CHANGELOG.md).
