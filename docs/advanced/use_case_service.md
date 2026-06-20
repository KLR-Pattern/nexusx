# UseCase Service

Define business logic once as a service class — serve it to both MCP (AI agents) and FastAPI (REST API) without duplication.

```
UseCaseService subclass ──┬── MCP server (AI agents, four-layer progressive discovery)
                         └── FastAPI routes (auto-generated POST endpoints)
```

One service class. Two presentation modes. No duplication.

## Step 1: Define a UseCaseService

Subclass `UseCaseService` and declare `async classmethod` methods. The metaclass auto-discovers all public methods:

```python
from nexusx.use_case import UseCaseService

class SprintService(UseCaseService):
    """Sprint management service."""

    @classmethod
    async def list_sprints(cls) -> list[SprintSummary]:
        """Get all sprints with their task counts."""
        stmt = build_dto_select(SprintSummary)
        async with async_session() as session:
            rows = (await session.exec(stmt)).all()
        dtos = [SprintSummary(**dict(row._mapping)) for row in rows]
        return await Resolver().resolve(dtos)

    @classmethod
    async def get_sprint(cls, sprint_id: int) -> SprintSummary | None:
        """Get a sprint by ID."""
        stmt = build_dto_select(SprintSummary, where=Sprint.id == sprint_id)
        async with async_session() as session:
            rows = (await session.exec(stmt)).all()
        if not rows:
            return None
        dto = SprintSummary(**dict(rows[0]._mapping))
        return await Resolver().resolve(dto)
```

!!! tip
    Method docstrings become MCP tool descriptions — write them clearly so AI agents know when to use each method. Private methods (starting with `_`) are excluded from discovery.

## Step 2: Expose to MCP

Wrap your services in an MCP server. The 3.0+ entry point is `create_use_case_graphql_mcp_server` — it generates a real GraphQL schema from your `UseCaseService` signatures and exposes it through a four-layer progressive-disclosure MCP:

```python
from nexusx.use_case import UseCaseAppConfig, create_use_case_graphql_mcp_server

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
mcp.run()  # stdio mode
```

### How the four layers work

AI agents explore your API progressively — they start broad, then drill into specifics:

| Tool | Layer | What the agent learns | Response envelope |
|------|-------|----------------------|-------------------|
| `list_apps()` | App discovery | "What domains are available?" | `{success, data}` |
| `describe_compose_schema(app_name)` | Service listing | "What services/methods does this app have?" (compact: no args or return types) | `{success, data}` |
| `describe_compose_method(app_name, service_name, method_name)` | Method details | Args + return type + an SDL fragment covering the method's transitive closure | `{success, data}` |
| `compose_query(app_name, query)` | Execution | Run a GraphQL query string, get `{data, errors}` back | `{data, errors}` |

### compose_query example

Layer 3 (`compose_query`) takes standard GraphQL query strings — agents compose multi-service queries with field selection in a single round-trip:

```graphql
{
  SprintService {
    list_sprints {
      id
      name
      tasks { id title owner { id name } }
    }
  }
  TaskService {
    list_tasks { id title }
  }
}
```

The response is GraphQL-standard `{data, errors}`. Field projection means only requested fields come back — agents can shave response size by selecting fewer fields.

**Introspection queries (`__schema` / `__type` / `__typename`) are rejected in Layer 3** to keep MCP responses compact — agents use Layers 1 and 2 for schema discovery instead. For a GraphQL HTTP endpoint that services introspection (GraphiQL), use `compose_introspect` directly; see the `demo/use_case/graphql_server.py` example.

### Migration from 2.x

3.0 removed the legacy direct-call MCP entries (`create_use_case_mcp_server`, `create_use_case_flat_server`). See [`docs/migrations/3.0-use-case-graphql.md`](../migrations/3.0-use-case-graphql.md) for the before/after mapping.

## Step 3: Generate FastAPI Routes

The same service class also generates REST API routes via `create_use_case_router`:

```python
from fastapi import FastAPI
from nexusx import UseCaseAppConfig, create_use_case_router

config = UseCaseAppConfig(
    name="project",
    services=[SprintService, TaskService],
    description="Project management",
)

app = FastAPI()
app.include_router(create_use_case_router(config))
```

Each `@classmethod` in your services becomes a POST endpoint:

```
POST /api/sprint_service/list_sprints
POST /api/sprint_service/get_sprint
POST /api/task_service/list_tasks
POST /api/task_service/get_task
```

URL pattern: `{prefix}/{service_name}/{method_name}`. Service names default to snake_case of the class name (`SprintService` → `sprint_service`).

### How parameters map to routes

Method parameters are split into two categories:

| Parameter type | Example | Route handling |
|----------------|---------|----------------|
| **Body parameters** | `sprint_id: int` | Collected into a Pydantic request model |
| **FromContext parameters** | `user_id: Annotated[int, FromContext()]` | Injected via `context_extractor` |

```python
from typing import Annotated
from nexusx import FromContext

class ReportService(UseCaseService):
    @classmethod
    async def my_tasks(cls, user_id: Annotated[int, FromContext()]) -> list[dict]:
        """Get tasks for the current user."""
        ...

    @classmethod
    async def create_report(
        cls,
        user_id: Annotated[int, FromContext()],
        title: str,
    ) -> dict:
        """Create a report. user_id from context, title from body."""
        ...
```

To inject context values from the FastAPI Request, pass a `context_extractor`:

```python
def extract_user(request):
    user_id = request.headers.get("X-User-Id", "1")
    return {"user_id": int(user_id)}

context_config = UseCaseAppConfig(
    name="reports",
    services=[ReportService],
    context_extractor=extract_user,
)
app.include_router(create_use_case_router(context_config))
```

OpenAPI documentation is generated automatically — visit `/docs` to see the interactive API docs.

## Recap

- `UseCaseService` subclasses define business logic as `async classmethod` methods
- Method docstrings become MCP tool descriptions — write them clearly
- `create_use_case_graphql_mcp_server` creates a four-layer progressive-discovery GraphQL MCP service
- `create_use_case_router` generates FastAPI POST routes from the same service class
- Body parameters become request body; `FromContext` parameters are injected via `context_extractor`

## Next Steps

- [UseCase + FastAPI](./use_case_fastapi.md) — Manual thin-route pattern for finer control
- [MCP Service](./mcp_service.md) — Pure MCP integration using GraphQL mode
