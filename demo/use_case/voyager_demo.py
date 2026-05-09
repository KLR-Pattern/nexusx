"""RPC Voyager Demo — interactive visualization of RPC services and ER diagrams.

Demonstrates how to mount the voyager visualization UI on a FastAPI app,
showing both RPC service structure and entity-relationship diagrams.

Run:
    uv run uvicorn demo.rpc_voyager_demo:app --port 8008

Endpoints:
    http://localhost:8008/voyager     — Voyager visualization UI
    http://localhost:8008/api/users   — User list (API endpoint)
    http://localhost:8008/api/sprints — Sprint list (API endpoint)
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from demo.core_api.database import async_session, init_db
from demo.core_api.models import (
    Comment,
    Label,
    Project,
    Sprint,
    Tag,
    Task,
    TaskLabel,
    User,
)
from demo.rpc.mcp_server import SprintService, TaskService, UserService
from sqlmodel_nexus import ErManager
from sqlmodel_nexus.voyager import create_rpc_voyager

# ──────────────────────────────────────────────────
# ErManager
# ──────────────────────────────────────────────────

er = ErManager(
    entities=[User, Sprint, Task, Tag, Project, Comment, Label, TaskLabel],
    session_factory=async_session,
)

# ──────────────────────────────────────────────────
# Voyager app
# ──────────────────────────────────────────────────

voyager_app = create_rpc_voyager(
    services=[UserService, TaskService, SprintService],
    er_manager=er,
    name="Core API RPC Demo",
)

# ──────────────────────────────────────────────────
# FastAPI app
# ──────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="RPC Voyager Demo",
    description="Demonstrates voyager visualization for RPC services",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount voyager UI
app.mount("/voyager", voyager_app)


# ──────────────────────────────────────────────────
# Sample API endpoints
# ──────────────────────────────────────────────────


@app.get("/")
async def root():
    return {
        "message": "RPC Voyager Demo",
        "voyager": "/voyager — Interactive visualization UI",
        "endpoints": {
            "users": "/api/users",
            "sprints": "/api/sprints",
        },
    }


@app.get("/api/users", tags=["user"])
async def get_users():
    """List all users."""
    return await UserService.list_users()


@app.get("/api/sprints", tags=["sprint"])
async def get_sprints():
    """List all sprints with task counts."""
    return await SprintService.list_sprints()


if __name__ == "__main__":
    import os
    import webbrowser

    import uvicorn

    port = int(os.environ.get("PORT", 8008))
    webbrowser.open(f"http://localhost:{port}/voyager")
    uvicorn.run(app, host="0.0.0.0", port=port)
