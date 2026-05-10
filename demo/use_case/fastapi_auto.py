"""UseCase FastAPI Auto-Router Demo — auto-generated routes from UseCaseService.

Demonstrates ``create_use_case_router()`` which generates POST routes
automatically from the same UseCaseService classes used by MCP.

Compared to the manual ``fastapi.py`` demo, this file requires zero
boilerplate — just pass a UseCaseAppConfig and include the router.

Run:
    uv run uvicorn demo.use_case.fastapi_auto:app --port 8008

Endpoints (all POST):
    /api/user_service/list_users
    /api/task_service/list_tasks
    /api/task_service/get_tasks_by_sprint
    /api/task_service/get_task
    /api/sprint_service/list_sprints
    /api/sprint_service/get_sprint
    /api/sprint_service/get_sprint_detail
    /api/report_service/my_tasks          (FromContext: user_id from header)
    /api/report_service/create_report     (FromContext + body params)
"""

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from demo.core_api.database import async_session, init_db
from demo.core_api.models import Task, User
from demo.use_case.mcp_server import SprintService, TaskService, UserService
from sqlmodel_nexus import (
    FromContext,
    UseCaseAppConfig,
    UseCaseService,
    create_use_case_router,
    query,
)


# ──────────────────────────────────────────────────
# Service with FromContext
# ──────────────────────────────────────────────────


class ReportService(UseCaseService):
    """Report service — demonstrates FromContext parameter injection."""

    @query
    async def my_tasks(cls, user_id: Annotated[int, FromContext()]) -> list[dict]:
        """Get tasks assigned to the current user (user_id from context).

        In FastAPI: user_id is extracted from X-User-Id header via
        context_extractor. In MCP: extracted from MCP context.
        """
        from sqlmodel import select

        async with async_session() as session:
            tasks = (await session.exec(select(Task))).all()
        return [
            {"id": t.id, "title": t.title, "done": t.done}
            for t in tasks
            if t.owner_id == user_id
        ]

    @query
    async def create_report(
        cls,
        user_id: Annotated[int, FromContext()],
        title: str,
    ) -> dict:
        """Create a report for the current user.

        Demonstrates mixed params: user_id from context, title from body.
        """
        from sqlmodel import select

        async with async_session() as session:
            user = (await session.exec(select(User).where(User.id == user_id))).first()

        return {
            "report_title": title,
            "author": user.name if user else f"user_{user_id}",
            "task_count": "N/A",
        }


def _extract_user_from_request(request):
    """Extract user_id from X-User-Id header for FromContext injection."""
    user_id = request.headers.get("X-User-Id", "1")
    return {"user_id": int(user_id)}


# ──────────────────────────────────────────────────
# App setup
# ──────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="UseCase FastAPI Auto-Router Demo",
    description="Auto-generated POST routes from UseCaseService",
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

# Services without FromContext
config = UseCaseAppConfig(
    name="project",
    services=[UserService, TaskService, SprintService],
    description="Project management with sprints, tasks, and users",
)
app.include_router(create_use_case_router(config))

# Services with FromContext — context_extractor adapts FastAPI Request → dict
context_config = UseCaseAppConfig(
    name="reports",
    services=[ReportService],
    description="Report service with FromContext (user_id from X-User-Id header)",
    context_extractor=_extract_user_from_request,
)
app.include_router(create_use_case_router(context_config))


if __name__ == "__main__":
    import os

    import uvicorn

    port = int(os.environ.get("PORT", 8008))
    uvicorn.run(app, host="0.0.0.0", port=port)
