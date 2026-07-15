"""FastAPI application entry point.

Phase 1: Voyager (ER diagram) + GraphiQL
Phase 2: + GraphQL with database + seed data
Phase 3: + REST + MCP + Voyager with services
"""
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

# ── MCP apps (must be created before lifespan to combine lifespans) ───
from nexusx import (  # noqa: E402
    GraphQLHandler,
    UseCaseAppConfig,
    create_use_case_graphql_mcp_server,
)
from nexusx.mcp import Application, create_mcp_server  # noqa: E402
from src.database import init_db
from src.db import async_session
from src.models import BaseEntity, er, mount_method  # noqa: E402
from src.service.sprint.service import SprintService  # noqa: E402
from src.service.task.service import TaskService  # noqa: E402

# ── Mount methods onto entities (must be called before GraphQL handler) ──

mount_method()

# ── GraphQL handler (must be created AFTER mount_method) ──────────────

graphql_handler = GraphQLHandler(
    base=BaseEntity,
    session_factory=async_session,
)

mcp = create_mcp_server(
    apps=[
        Application(
            name="template",
            base=BaseEntity,
            session_factory=async_session,
            description="Template entities CRUD.",
        )
    ],
    name="Template MCP Server",
    allow_mutation=True,
)
mcp_http = mcp.http_app(path="/", transport="streamable-http", stateless_http=True)

use_case_config = UseCaseAppConfig(
    name="template",
    services=[TaskService, SprintService],
    description="Task & Sprint business services",
)

use_case_mcp = create_use_case_graphql_mcp_server(
    apps=[use_case_config],
    name="Template UseCase MCP",
)
use_case_mcp_http = use_case_mcp.http_app(
    path="/",
    transport="streamable-http",
    stateless_http=True,
)


# ── FastAPI app ───────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with mcp_http.lifespan(mcp_http):
        async with use_case_mcp_http.lifespan(use_case_mcp_http):
            yield


app = FastAPI(
    title="nexusx Template",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Voyager visualization (Phase 1: ER diagram only) ──────────────────

from nexusx import create_use_case_voyager  # noqa: E402

voyager_app = create_use_case_voyager(
    services=[TaskService, SprintService],
    er_manager=er,
    name="Template API",
)
app.mount("/voyager", voyager_app)


# ── GraphQL endpoints (Phase 2+) ─────────────────────────────────────


class GraphQLRequest(BaseModel):
    query: str
    variables: dict[str, Any] | None = None
    operation_name: str | None = None


@app.get("/graphql", response_class=HTMLResponse)
async def graphiql():
    return graphql_handler.get_graphiql_html()


@app.post("/graphql")
async def graphql_endpoint(req: GraphQLRequest):
    return await graphql_handler.execute(
        query=req.query,
        variables=req.variables,
        operation_name=req.operation_name,
    )


@app.get("/schema", response_class=PlainTextResponse)
async def graphql_schema():
    return graphql_handler.get_sdl()


# ── REST router (Phase 3) ────────────────────────────────────────────

from nexusx import create_use_case_router  # noqa: E402

app.include_router(create_use_case_router(use_case_config))


# ── MCP mounts ───────────────────────────────────────────────────────

app.mount("/mcp", mcp_http)
app.mount("/mcp-usecase", use_case_mcp_http)
