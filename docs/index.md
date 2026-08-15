---
template: home.html
home:
  hero:
    badge: "Next-Gen Business Modeling · AI-Native · SQLModel"
    title: "Model your business once —<br>for humans and AI alike."
    subtitle: "Model your business entities, relationships, and use cases once — GraphQL, REST, MCP, CLI, and TS SDK all derive from it. Data is a graph; tools are just its projections."
    install: "pip install nexusx"
    primary: {label: "Get Started", ref: "guide/quick_start"}
    secondary: {label: "GitHub", url: "https://github.com/allmonday/nexusx"}
  sections:
    # ── AI-native integration ──
    - type: cards
      muted: true
      two: true
      title: "AI-native integration — not bolted on"
      subtitle: "The same typed business model serves AI agents and developers as first-class consumers."
      cards:
        - icon: "🤖"
          title: "For AI — first-class"
          text: "MCP is a native protocol: strongly typed, GraphQL under the hood."
          bullets:
            - text: "<strong>Context efficiency</strong> — agents select exactly the fields they need; one call returns a nested, N+1-proof tree with only what was asked."
            - text: "<strong>Progressive disclosure</strong> — list_apps → describe_compose_schema → describe_compose_method → compose_query; the schema enters context piece by piece, never whole."
            - {label: "MCP & context efficiency →", ref: "mcp-context-efficiency"}
        - icon: "🧑‍💻"
          title: "For Human — same model"
          text: "Write SQLModel entities and typed DTOs; that is the whole job."
          bullets:
            - text: "REST routes, GraphQL schema, CLI, and TS SDK — zero boilerplate."
            - text: "Change business logic once — every protocol updates in sync."

    # ── The maintainability problem ──
    - type: cards
      title: "Any model can ship an app. Almost none can keep it maintainable."
      subtitle: "LLMs generate code fast — but without structural constraints, the debt surfaces weeks later: duplicated logic, components bleeding into each other, debugging by guesswork. The industry calls it the cost of vibe coding."
      lead: "nexusx narrows what AI writes to a <strong>declarative model</strong> — entities, relationships, and typed use-case methods. Structure is not something the AI has to get right; it is guaranteed by the model."
      cards:
        - icon: "✍️"
          title: "A small, typed surface"
          text: "AI writes the model and use-case methods — not scattered glue code. Small diffs, reviewable by humans."
        - icon: "📌"
          title: "One source of truth"
          text: "Change a business rule once; every protocol updates in sync. Maintenance cost does not multiply per delivery."
        - icon: "👁️"
          title: "Understandable by construction"
          text: "Typed contracts, plus Voyager: entities, relationships, use cases, and their dependencies rendered as one live ER view — grasp the whole project without reading code first, whether you are a new human or a fresh AI session."
          link: {label: "Voyager →", ref: "advanced/voyager"}

    # ── One model, six deliveries ──
    - type: comparison
      muted: true
      stack: true
      title: "One model, six deliveries"
      subtitle: "Semantic-level isomorphism — every protocol is generated from the same typed model, not wrapped around a copy of it."
      bad:
        title: "Same operation, three copies"
        code: |-
          # "list sprints" — written once per protocol

          @app.get("/sprints")
          async def rest_list_sprints() -> list[SprintOut]:
              ...  # query + assembly, again

          @strawberry.field
          async def graphql_sprints(self) -> list[SprintType]:
              ...  # types + loaders, again

          @mcp.tool()
          async def sprints_for_agents() -> str:
              ...  # JSON dumping, again

          # ↑ change the rule → fix every copy
      good:
        title: "One UseCaseService method"
        code: |-
          class SprintService(UseCaseService):
              """Sprint planning operations."""

              @query
              async def list_sprints(cls) -> list[SprintSummary]:
                  """List sprints with tasks, owners, and task count."""
                  return await load_sprints()

          # six deliveries, one model ↓
      deliveries:
        - {icon: "🌐", title: "REST + OpenAPI", text: "Typed FastAPI route, visible in OpenAPI.", code: "create_use_case_router(api)"}
        - {icon: "🟣", title: "GraphQL · data graph", text: "Entities become by_id / by_filter roots for exploring connected data.", code: "Sprint { by_filter(limit: 10) { ... } }"}
        - {icon: "🟣", title: "GraphQL · operation graph", text: "Use-case methods become typed fields via the compose schema.", code: "compose_query(app, query, args)"}
        - {icon: "🤖", title: "MCP", text: "Agents discover it progressively.", code: "create_use_case_graphql_mcp_server([api])"}
        - {icon: "⌨️", title: "CLI", text: "Services become command groups.", code: "list_sprints --select \"name task_count\""}
        - {icon: "📘", title: "TS SDK", text: "Typed client generated from the compose schema.", code: "sprintService.listSprints()"}

    # ── One model, two graphs ──
    - type: cards
      title: "One model, two graphs"
      subtitle: "Two GraphQL surfaces for two different jobs — use either one, or both."
      two: true
      cards:
        - icon: "🧭"
          title: "Data graph — explore and slice"
          text: "SQLModel entities and relationships become by_id / by_filter query roots. No relationship resolvers to write — DataLoader batching keeps it N+1-proof as callers traverse."
          chip: "GraphQLHandler"
        - icon: "⚙️"
          title: "Operation graph — invoke capabilities"
          text: "Typed business methods expose stable capabilities to web clients, integrations, and AI agents — served over REST, MCP, CLI, and SDK from one definition."
          chip: "UseCaseService"

    # ── Shape application responses ──
    - type: comparison
      muted: true
      title: "Shape application responses"
      subtitle: "Entities are not API contracts. DefineSubset hides internal columns, auto-loads relationships, and computes derived fields."
      bad:
        title: "Manual query + assembly"
        code: |-
          # Per-endpoint: manual SQL, N+1, dict munging
          async def get_sprints():
              sprints = await session.exec(select(Sprint))
              result = []
              for s in sprints:
                  tasks = await session.exec(
                      select(Task).where(Task.sprint_id == s.id))
                  for t in tasks:
                      t.owner = await session.get(User, t.owner_id)

          # N+1 queries, fragile dict construction
      good:
        title: "Declarative DTO + auto-loading"
        code: |-
          from nexusx import DefineSubset, ErManager, build_dto_select

          class UserDTO(DefineSubset):
              __subset__ = (User, ("id", "name"))

          class TaskDTO(DefineSubset):
              __subset__ = (Task, ("id", "title", "owner_id"))
              owner: UserDTO | None = None   # auto-loaded

          class SprintDTO(DefineSubset):
              __subset__ = (Sprint, ("id", "name"))
              tasks: list[TaskDTO] = []      # auto-loaded

          er = ErManager(entities=[User, Sprint, Task], session_factory=async_session)
          Resolver = er.create_resolver()

          async def load_sprints() -> list[SprintDTO]:
              stmt = build_dto_select(SprintDTO)          # root columns only
              async with async_session() as session:
                  rows = (await session.exec(stmt)).all()
              dtos = [SprintDTO(**dict(r._mapping)) for r in rows]
              return await Resolver().resolve(dtos)       # tree filled, batched

          # 1 query per relationship, zero N+1

    # ── Beyond one database ──
    - type: cards
      title: "Beyond one database"
      subtitle: "The same relationship model stretches into more advanced architectures."
      cards:
        - {icon: "⚡", title: "Performance by construction", text: "DataLoader batching, SQL column pruning, window-function pagination — and total_count computed only when the response asks for it."}
        - {icon: "🔀", title: "Derived Fields & Cross-Layer", text: "post_* for aggregations, ExposeAs / SendTo for cross-layer data flow."}
        - {icon: "🧲", title: "Virtual Entities", text: "Ordinary Pydantic models as non-table graph roots — Redis, search, and SDK-backed data join the same graph."}
        - {icon: "🌐", title: "Entity Federation", text: "Compose multiple nexusx data graphs without a central gateway — homogeneous federation of nexusx services."}
        - {icon: "🧱", title: "Composed & DTO Federation", text: "ComposedErManager composes multiple engines in one process; DTO federation loads public DTO trees across services."}
        - {icon: "🗃️", title: "Multi-App MCP", text: "Independently packaged applications and databases, combined into a single MCP server."}

    # ── Three ideas ──
    - type: cards
      muted: true
      title: "Three ideas behind nexusx"
      subtitle: "The principles that shape every API decision."
      cards:
        - {icon: "🎯", title: "Selection is first-class", text: "One field selection shapes the GraphQL response, the SQL columns loaded, the DTO fields copied, the MCP output, CLI --select, and whether total_count is even computed."}
        - {icon: "🌉", title: "Relationships beyond the ORM", text: "Redis, search engines, other databases, external APIs — declare a Relationship with an async batch function and they join the same loader, DTO, GraphQL, and ER-diagram infrastructure."}
        - {icon: "📦", title: "Delivery is layered on later", text: "Business methods depend on no protocol object — builders inspect the typed signature and attach REST / MCP / CLI / SDK adapters. FromContext injects trusted values (user, tenant) without exposing them as client arguments."}

    # ── Integrations ──
    - type: integrations
      title: "Built for your stack"
      subtitle: "Works with your existing frameworks and tools."
      badges:
        - {icon: "🌍", label: "GraphQL", ref: "guide/graphql_mode"}
        - {icon: "⚡", label: "FastAPI", ref: "guide/core_api"}
        - {icon: "🤖", label: "MCP", ref: "advanced/mcp_service"}
        - {icon: "🗂", label: "SQLAlchemy", ref: "guide/er_diagram"}
        - {icon: "👁", label: "Voyager", ref: "advanced/voyager"}
        - {icon: "📄", label: "TypeScript SDK", ref: "guide/graphql_mode"}

    # ── CTA ──
    - type: cta
      title: "Start from entities, not boilerplate"
      subtitle: "Declare the model once — the data graph, response DTOs, and every delivery follow."
      primary: {label: "Read the Guide", ref: "guide/quick_start"}
      secondary: {label: "View on GitHub", url: "https://github.com/allmonday/nexusx"}
---


# nexusx

**nexusx** is a next-generation business modeling tool with deep AI integration.
Model your business entities, relationships, and use cases once — GraphQL,
REST, MCP, CLI, and TS SDK all derive from that single model, sharing one
DataLoader-backed query graph (N+1-proof) and one set of typed DTOs
(`DefineSubset`): semantic-level isomorphism, not transport-level wrapping.

## Run It in 60 Seconds

Install the dependencies:

```bash
pip install "nexusx[demo]"
```

Create `app.py`:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Relationship, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx import AutoQueryConfig, GraphQLHandler


class BaseEntity(SQLModel):
    pass


class Team(BaseEntity, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    heroes: list["Hero"] = Relationship(back_populates="team")


class Hero(BaseEntity, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    team_id: int | None = Field(default=None, foreign_key="team.id")
    team: Team | None = Relationship(back_populates="heroes")


engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
)
session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
handler = GraphQLHandler(
    base=BaseEntity,
    session_factory=session_factory,
    auto_query_config=AutoQueryConfig(),
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)

    async with session_factory() as session:
        team = Team(name="Avengers")
        session.add(team)
        await session.flush()
        session.add(Hero(name="Spider-Man", team_id=team.id))
        await session.commit()

    try:
        yield
    finally:
        await handler.aclose()
        await engine.dispose()


app = FastAPI(lifespan=lifespan)


class GraphQLRequest(BaseModel):
    query: str


@app.get("/graphql", response_class=HTMLResponse)
async def graphiql() -> str:
    return handler.get_graphiql_html()


@app.post("/graphql")
async def graphql(request: GraphQLRequest):
    return await handler.execute(request.query)
```

Start the server:

```bash
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000/graphql` and query:

```graphql
{
  Team {
    by_filter {
      id
      name
      heroes {
        id
        name
      }
    }
  }
}
```

You now have a generated GraphQL schema and batched relationship loading. See
the [Quick Start](./guide/quick_start.md) for the walkthrough.

## What You'll Get

| You want... | You write... | nexusx handles... |
|------|----------------|---------------------------|
| A GraphQL API | `@query` / `@mutation` decorators | SDL generation, DataLoader batch-loading |
| REST or use-case DTOs | `DefineSubset` + field declarations | Implicit auto-loading, N+1 prevention, ORM→DTO conversion |
| Derived fields | `post_*` methods | Auto-execute after nested data is ready |
| Cross-layer data flow | `ExposeAs`, `SendTo`, `Collector` | Pass context downward, aggregate results upward |
| Non-ORM relationships | `Relationship(...)` | Same DataLoader infrastructure, supports auto-loading |
| An AI-ready API | `create_single_app_mcp_server(base=...)` | Progressive MCP tool exposure |
| Split into microservices | `RemoteRelationship` / `federation_public` DTO | Homogeneous federation: read-model composition across services, entity body unchanged |

## Who Is This For

- **Backend developers** building GraphQL and REST APIs from SQLModel entities
- **Teams** that want auto-generated APIs once models stabilize — no more hand-written schemas
- **Projects** that need both GraphQL for flexibility and REST for delivery
- **AI integrations** that expose the same models to AI agents via MCP

## Learning Path

```mermaid
flowchart LR
    p1["P1: ER Diagram<br/>SQLModel entities + non-ORM relationships<br/>+ visualized ER diagram"]
    --> p2["P2: GraphQL API<br/>@query / @mutation<br/>SDL auto-generation + DataLoader"]
    --> p3["P3: Core API<br/>DefineSubset DTOs<br/>Implicit auto-loading + post_*"]
    --> p4["MCP / UseCase<br/>AI agents + business services"]
```

Every guide reuses the same business scenario so you can follow along step by step:

```mermaid
erDiagram
    Sprint ||--o{ Task : "has many"
    Task }o--|| User : "owner"
```

### Guide (Tutorial Path)

| Page | What You'll Learn |
|------|------------------------|
| [Quick Start](./guide/quick_start.md) | Get a GraphQL API running in 30 seconds |
| [ER Diagram & Non-ORM Relationships](./guide/er_diagram.md) | Declare and visualize entity relationships |
| [GraphQL Mode](./guide/graphql_mode.md) | The full workflow from SQLModel to GraphQL API |
| [GraphQL Pagination](./guide/graphql_pagination.md) | Paginate list relationships |
| [Auto Query](./guide/graphql_auto_query.md) | Skip `@query` and auto-generate `by_id` / `by_filter` |
| [Core API Mode](./guide/core_api.md) | Build REST responses with `DefineSubset` + implicit auto-loading |
| [Core API Advanced](./guide/core_api_advanced.md) | Use `resolve_*` / `post_*` / cross-layer data flow |
| [Custom Relationships](./guide/custom_relationship.md) | Declare and use non-ORM relationships |
| [Virtual Entities](./guide/virtual_entities.md) | Use plain `BaseModel` roots (`CurrentUser`, page wrappers, third-party DTOs) via `add_virtual_entities()` |
| [ER Diagram Visualization](./guide/er_diagram_visual.md) | Generate and embed Mermaid ER diagrams |

### Advanced Guides

| Page | What You'll Learn |
|------|-------|
| [Cross-Service Federation](./advanced/federation.md) | Homogeneous federation: evolve a monolith into microservices incrementally, read-model composition across services (β entity graph / γ DTO) |
| [MCP Service](./advanced/mcp_service.md) | Expose SQLModel APIs to AI agents |
| [UseCase Service](./advanced/use_case_service.md) | Define business services serving both MCP and REST |
| [UseCase + FastAPI](./advanced/use_case_fastapi.md) | Embed the same service class into FastAPI routes |
| [Voyager Visualization](./advanced/voyager.md) | Interactive ERD browsing |

### API Reference

- [GraphQLHandler](./api/api_graphql_handler.md) — GraphQL entry point + SDL generation
- [Core API](./api/api_core.md) — ErManager / Resolver / DefineSubset / Loader
- [Cross-layer Data Flow](./api/api_cross_layer.md) — ExposeAs / SendTo / Collector
- [Relationships & ER Diagram](./api/api_relationship.md) — Relationship / ErDiagram
- [MCP API](./api/api_mcp.md) — MCP service configuration
- [UseCase API](./api/api_use_case.md) — UseCaseService / create_use_case_graphql_mcp_server
