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
from nexusx.mcp import create_mcp_server  # noqa: E402
from src.database import init_db
from src.db import async_session
from src.models import BaseEntity, er, mount_method  # noqa: E402
from src.service.sprint.service import SprintService  # noqa: E402
from src.service.task.service import TaskService  # noqa: E402
from src.service.user.service import UserService  # noqa: E402

# ── Mount methods onto entities (must be called before GraphQL handler) ──

mount_method()

# ── GraphQL handler (must be created AFTER mount_method) ──────────────

graphql_handler = GraphQLHandler(
    base=BaseEntity,
    session_factory=async_session,
)

# ── base 实体层 MCP（与下方 UseCase 层 MCP 不同）──────────────────────
# 此处 `create_mcp_server` 暴露 BaseEntity 子类的 @query/@mutation（Phase 2 挂载的方法）。
# 与 UseCase 层 MCP（`create_use_case_graphql_mcp_server`）的区别：
#   - base 层：直接对应 SQLModel 实体的 GraphQL，开发期辅助测试用
#   - UseCase 层：经 DTO 组装的 GraphQL，含 4 层渐进披露，对 AI agent 友好
# 两者共存演示层级差异；生产可只保留 UseCase 层。
mcp = create_mcp_server(
    apps=[{
        "name": "template",
        "base": BaseEntity,
        "session_factory": async_session,
        "description": "Template entities CRUD.",
    }],
    name="Template MCP Server",
    allow_mutation=True,
)
mcp_http = mcp.http_app(path="/", transport="streamable-http", stateless_http=True)

use_case_config = UseCaseAppConfig(
    name="template",
    services=[UserService, TaskService, SprintService],
    description="User, Task & Sprint business services",
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
    services=[UserService, TaskService, SprintService],
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


# ── REST router（默认推荐出口 — OpenAPI / TS SDK 链路必经）─────────────

from nexusx import create_use_case_router  # noqa: E402

app.include_router(create_use_case_router(use_case_config))


# ── MCP mounts（默认推荐出口 — Voyager 见上方，UseCase 见下方）────────

app.mount("/mcp", mcp_http)              # base 实体层 MCP（可选，演示层级）
app.mount("/mcp-usecase", use_case_mcp_http)  # UseCase 层 MCP（默认推荐）


# ── 可选扩展（按需启用，默认不挂载）──────────────────────────────────
# JSON-RPC 2.0（替代 REST 的轻量 RPC）：
#     from nexusx import create_jsonrpc_router
#     app.include_router(create_jsonrpc_router(use_case_config))
# CLI（Typer 命令行工具，本地调试 / 脚本化任务）：
#     from nexusx import create_use_case_cli
#     cli = create_use_case_cli(use_case_config)
#     # 在 if __name__ == "__main__": cli() 中调用
# 决策引导参见 phases/phase3.md 的"推荐默认组合"与"可选扩展"两段
