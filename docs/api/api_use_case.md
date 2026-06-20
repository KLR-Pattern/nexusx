# UseCase API Reference

Define business services with `UseCaseService`, expose them via the 3.0+ GraphQL MCP (`create_use_case_graphql_mcp_server`), FastAPI REST (`create_use_case_router`), JSON-RPC (`create_jsonrpc_router`), CLI (`create_use_case_cli`), or a plain GraphQL HTTP endpoint (`build_compose_schema` + `compose_introspect`).

## UseCaseService

Define business services with query and mutation methods for AI agent integration.

```python
from nexusx.use_case import UseCaseService
from nexusx import query, mutation

class SprintService(UseCaseService):
    """Sprint management service."""

    @query
    async def list_sprints(cls) -> list[SprintSummary]:
        ...

    @query
    async def get_sprint(cls, sprint_id: int) -> SprintSummary | None:
        ...

    @mutation
    async def create_sprint(cls, name: str) -> SprintSummary:
        ...
```

!!! warning
    Follow these rules when defining UseCase methods:
    - Methods must be decorated with `@query` or `@mutation`
    - Methods must be `async` with `cls` as the first parameter
    - Methods starting with `_` are not auto-discovered
    - Docstrings become MCP tool descriptions

### Rules

- Methods must be decorated with `@query` or `@mutation`
- Methods must be `async` with `cls` as first parameter
- Methods starting with `_` are not auto-discovered
- Docstrings become MCP tool descriptions

### Methods

| Method | Description |
|--------|-------------|
| `get_tag_name()` | Returns the class name as a tag (e.g., `"SprintService"`) |

## UseCaseAppConfig

Organize a group of UseCaseServices into one application configuration.

```python
from nexusx.use_case import UseCaseAppConfig

config = UseCaseAppConfig(
    name="project",
    services=[SprintService, TaskService],
    description="Project management API",
)
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | `str` | Yes | Application name |
| `services` | `list[type[UseCaseService]]` | Yes | List of UseCaseService subclasses |
| `description` | `str \| None` | No | Application description |
| `context_extractor` | `Callable \| None` | No | MCP context extraction function |

## create_use_case_graphql_mcp_server

Create an MCP server for UseCase services with multi-app support and four-layer progressive disclosure. Generates a real GraphQL schema (introspection-compatible, GraphiQL-friendly) from `UseCaseService` signatures; Layer 3 accepts standard GraphQL query strings.

```python
from nexusx.use_case import create_use_case_graphql_mcp_server, UseCaseAppConfig

mcp = create_use_case_graphql_mcp_server(
    apps=[
        UseCaseAppConfig(
            name="project",
            services=[SprintService, TaskService],
            description="Project management",
        ),
    ],
    name="Project UseCase API",
)
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `apps` | `list[UseCaseAppConfig]` | Yes | Application configuration list |
| `name` | `str` | No | Service name |

### Generated MCP Tools

| Tool | Description | Response envelope |
|------|-------------|-------------------|
| `list_apps()` | List all available apps | `{success, data}` |
| `describe_compose_schema(app_name)` | Compact service+method listing (no args/return types) | `{success, data}` |
| `describe_compose_method(app_name, service_name, method_name)` | Args + return type + SDL fragment (transitive closure of return type) | `{success, data}` |
| `compose_query(app_name, query)` | Execute GraphQL query string | `{data, errors}` (GraphQL standard) |

### Schema structure (fixed three layers)

```graphql
type Query {
  SprintService: SprintServiceQuery!
  TaskService: TaskServiceQuery!
}
type SprintServiceQuery {
  list_sprints: [SprintSummary!]!
  get_sprint(sprint_id: Int!): SprintSummary
}
type Mutation {  # only when @mutation methods exist
  SprintService: SprintServiceMutation!
}
```

### Layer 3 execution contract

- Accepts standard GraphQL query strings (e.g. `{ SprintService { list_sprints { id title owner { name } } } }`)
- Field projection: only requested fields are returned (via `subset.build_subset_model`)
- **Rejects introspection** (`__schema` / `__type` / `__typename`) — use Layers 1/2 for schema discovery. This keeps MCP responses compact.
- **Does NOT wrap results in `Resolver()`** — service methods own Resolver invocation (call `Resolver().resolve(dtos)` inside the method body when needed)
- Concurrent `@query` methods via `asyncio.gather`; serial `@mutation` methods in query order

### Migrating from 2.x

The 2.x direct-call MCP entries (`create_use_case_mcp_server`, `create_use_case_flat_server`) were removed in 3.0. See [`docs/migrations/3.0-use-case-graphql.md`](../migrations/3.0-use-case-graphql.md) for the before/after mapping.

## build_compose_schema / ComposeSchema / compose_introspect

Direct schema access for non-MCP use cases (e.g. building a GraphQL HTTP endpoint with GraphiQL).

```python
from nexusx import build_compose_schema, compose_introspect, UseCaseAppConfig

app_config = UseCaseAppConfig(name="project", services=[SprintService, TaskService])
schema = build_compose_schema(app_config)

# Three render views over the same registry:
schema.render_sdl()                          # full SDL string
schema.render_introspection()                # graphql __schema payload (GraphiQL-compatible)
schema.render_method_sdl("SprintService", "list_sprints")  # single-method SDL fragment

# Services real introspection queries (for GraphiQL HTTP endpoints):
compose_introspect(schema, "{ __schema { types { name } } }")
# → {"data": {"__schema": {...}}, "errors": None}
```

See [`demo/use_case/graphql_server.py`](https://github.com/KLR-Pattern/nexusx/blob/master/demo/use_case/graphql_server.py) for a complete FastAPI `/graphql` endpoint example.

## create_use_case_voyager

Create a Voyager visualization ASGI sub-application for exploring UseCase services.

```python
from nexusx.voyager import create_use_case_voyager

voyager = create_use_case_voyager(
    apps=[
        UseCaseAppConfig(
            name="project",
            services=[SprintService, TaskService],
        ),
    ],
)
```

### REST Endpoints

| Endpoint | Description |
|----------|-------------|
| `/dot` | DOT format service dependency graph |
| `/dot-search` | Searchable DOT graph |
| `/er-diagram` | Mermaid ER diagram |
| `/source` | Source code information |

## FromContext

Mark parameters for injection from MCP context.

```python
from typing import Annotated
from nexusx.use_case import FromContext

class SprintService(UseCaseService):
    @query
    async def list_sprints(cls, tenant_id: Annotated[int, FromContext()]) -> list[SprintSummary]:
        ...
```

## build_dto_select

Build a SELECT statement for querying DTO fields from the SQL database.

```python
from nexusx import build_dto_select

stmt = build_dto_select(SprintSummary)
stmt = build_dto_select(SprintSummary, where=Sprint.id == sprint_id)
```

!!! tip
    When ORM relationships use `lazy="noload"` (the recommended pattern with ErManager + Resolver), this function provides minimal benefit since the only pruning is on scalar columns. You can achieve the same result with `select(Entity)` and `DTO.model_validate(entity)`. Use this function when the DTO selects a small subset of scalar columns from a wide table.
