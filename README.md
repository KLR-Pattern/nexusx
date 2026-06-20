# nexusx

Write SQLModel classes. Get a complete API.

[![pypi](https://img.shields.io/pypi/v/nexusx.svg)](https://pypi.python.org/pypi/nexusx)
[![PyPI Downloads](https://static.pepy.tech/badge/nexusx/month)](https://pepy.tech/projects/nexusx)

Define your entities once in SQLModel, and you get GraphQL, REST, and MCP — no repeated data models.

```mermaid
flowchart LR
    sqlmodel["SQLModel"]

    sqlmodel --> graphql["GraphQL"]
    graphql --> mcp1["MCP"]

    sqlmodel --> usecase["UseCaseService"]
    usecase --> rest["REST"]
    usecase --> mcp2["MCP"]
    usecase --> cli["CLI"]
```

## Install

```bash
pip install nexusx
pip install nexusx[fastmcp]  # with MCP support
```

Requires Python ≥ 3.10.

## Quick Start

**Step 1 — Entities + GraphQL**

```python
from sqlmodel import SQLModel, Field, Relationship, select
from nexusx import query, mutation, GraphQLHandler

class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    posts: list["Post"] = Relationship(back_populates="author")

    @query
    async def get_users(cls, limit: int = 10) -> list["User"]:
        async with get_session() as session:
            return (await session.exec(select(cls).limit(limit))).all()

class Post(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="user.id")
    author: User | None = Relationship(back_populates="posts")

handler = GraphQLHandler(base=SQLModel, session_factory=async_session)
```

Relationships resolve automatically — DataLoader batches queries, one SQL per level:

```graphql
{ userGetUsers(limit: 5) { name posts { title } } }
```

**Step 2 — Typed REST with DTOs**

```python
from nexusx import DefineSubset, ErManager

class UserDTO(DefineSubset):
    __subset__ = (User, ("id", "name"))

class PostDTO(DefineSubset):
    __subset__ = (Post, ("id", "title", "author_id"))
    author: UserDTO | None = None  # auto-loaded — field name matches relationship

Resolver = ErManager(base=SQLModel, session_factory=async_session).create_resolver()
dtos = await Resolver().resolve(posts)
```

`DefineSubset` is GraphQL field selection in Python — declare which fields you want, get a typed DTO. Relationship fields auto-load when the name matches. Add `resolve_*` for custom loading, `post_*` for derived fields.

**Step 3 — MCP + REST from business logic**

```python
from nexusx import UseCaseService, UseCaseAppConfig, create_use_case_graphql_mcp_server, create_use_case_router

class SprintService(UseCaseService):
    @query
    async def list_sprints(cls) -> list[SprintSummary]:
        """Get all sprints with task counts."""
        ...

config = UseCaseAppConfig(name="project", services=[SprintService])

# MCP for AI agents
mcp = create_use_case_graphql_mcp_server(apps=[config])
mcp.run()

# REST for frontend
app.include_router(create_use_case_router(config))
```

Same service class, two protocols. Methods can internally use `Resolver().resolve(dtos)` — the modes compose.

## How It Compares

| | nexusx | Strawberry | FastAPI + SQLModel | FastMCP |
|---|:---:|:---:|:---:|:---:|
| GraphQL auto-gen | ✓ | ✓ | — | — |
| REST + OpenAPI | ✓ | — | ✓ (manual) | — |
| MCP | ✓ | — | — | ✓ |
| N+1 prevention | ✓ DataLoader | manual | — | — |
| Relationship auto-loading | ✓ implicit | manual | — | — |

## Demos

```bash
git clone https://github.com/allmonday/nexusx.git && cd nexusx && bash start_all.sh
```

| Port | Mode |
|-----:|------|
| 8000 | GraphQL playground |
| 8001 | Core API (REST + DTOs) |
| 8005 | Paginated GraphQL |
| 8006 | UseCase MCP (4-layer) |
| 8007 | UseCase FastAPI (REST) |
| 8008 | Voyager visualization |

## AI Agent Skill

A [4-phase skill](./skill/) guides AI coding agents: clarify requirements → build POC → add queries → productize.

```bash
ln -s $(pwd)/skill ~/.claude/skills/nexusx-4phase
```

## Development

```bash
./scripts/check-ci.sh       # lint + type-check + tests
uv run pytest               # tests only
uv run ruff check src/ tests/  # lint only
uv run mypy src/            # type-check only
```

## Documentation

- [API docs](docs/) — per-mode guides for GraphQL, Core API, and UseCase
- [Clean Architecture comparison](docs/clean-architecture-comparison.md)

## License

MIT
