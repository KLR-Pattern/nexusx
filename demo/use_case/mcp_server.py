"""UseCase GraphQL MCP Server Demo — expose Core API services via GraphQL MCP.

Demonstrates how UseCaseService classes can be exposed to AI agents via the
4-layer progressive-disclosure GraphQL MCP (3.0+):
- list_apps
- describe_compose_schema
- describe_compose_method
- compose_query  (executes standard GraphQL queries)

Uses the Core API demo's models/database, providing Sprint and Task business
services with DefineSubset DTOs and Resolver.

Usage:
    # stdio mode (for Claude Desktop, etc.)
    uv run --with fastmcp python -m demo.use_case.mcp_server

    # HTTP mode (for browser / MCP inspector)
    uv run --with fastmcp python -m demo.use_case.mcp_server --http
"""

from demo.core_api.database import async_session, init_db
from demo.core_api.dtos import SprintDetail, SprintSummary, TaskSummary
from demo.core_api.models import Sprint, Task, User
from nexusx import (
    ErManager,
    UseCaseAppConfig,
    UseCaseService,
    build_dto_select,
    create_use_case_graphql_mcp_server,
    query,
)

# ──────────────────────────────────────────────────
# ErManager & Resolver
# ──────────────────────────────────────────────────

er = ErManager(
    entities=[User, Sprint, Task],
    session_factory=async_session,
)
Resolver = er.create_resolver()


# ──────────────────────────────────────────────────
# Services
# ──────────────────────────────────────────────────


class UserService(UseCaseService):
    """User management — query users."""

    @query
    async def list_users(cls) -> list[dict]:
        """Get all users as simple dicts."""
        from sqlmodel import select

        async with async_session() as session:
            users = (await session.exec(select(User))).all()
        return [{"id": u.id, "name": u.name} for u in users]


class TaskService(UseCaseService):
    """Task management — query tasks with auto-loaded owner."""

    @query
    async def list_tasks(cls) -> list[TaskSummary]:
        """Get all tasks with their owner (auto-loaded via DataLoader)."""
        stmt = build_dto_select(TaskSummary)
        async with async_session() as session:
            rows = (await session.exec(stmt)).all()
        dtos = [TaskSummary(**dict(row._mapping)) for row in rows]
        return await Resolver().resolve(dtos)

    @query
    async def get_tasks_by_sprint(cls, sprint_id: int) -> list[TaskSummary]:
        """Get tasks for a specific sprint, with owner auto-loaded."""
        stmt = build_dto_select(TaskSummary, where=Task.sprint_id == sprint_id)
        async with async_session() as session:
            rows = (await session.exec(stmt)).all()
        dtos = [TaskSummary(**dict(row._mapping)) for row in rows]
        return await Resolver().resolve(dtos)

    @query
    async def get_task(cls, task_id: int) -> TaskSummary | None:
        """Get a single task by ID."""
        stmt = build_dto_select(TaskSummary, where=Task.id == task_id)
        async with async_session() as session:
            rows = (await session.exec(stmt)).all()
        if not rows:
            return None
        dto = TaskSummary(**dict(rows[0]._mapping))
        return await Resolver().resolve(dto)


class SprintService(UseCaseService):
    """Sprint management — query sprints with task statistics."""

    @query
    async def list_sprints(cls) -> list[SprintSummary]:
        """Get all sprints with task counts and contributor names.

        Returns each sprint with:
        - tasks: list of tasks (auto-loaded via DataLoader)
        - task_count: derived from post_task_count
        - contributor_names: derived from post_contributor_names
        """
        stmt = build_dto_select(SprintSummary)
        async with async_session() as session:
            rows = (await session.exec(stmt)).all()
        dtos = [SprintSummary(**dict(row._mapping)) for row in rows]
        return await Resolver().resolve(dtos)

    @query
    async def get_sprint(cls, sprint_id: int) -> SprintSummary | None:
        """Get a single sprint by ID with full details."""
        stmt = build_dto_select(SprintSummary, where=Sprint.id == sprint_id)
        async with async_session() as session:
            rows = (await session.exec(stmt)).all()
        if not rows:
            return None
        dto = SprintSummary(**dict(rows[0]._mapping))
        return await Resolver().resolve(dto)

    @query
    async def get_sprint_detail(cls, sprint_id: int) -> SprintDetail | None:
        """Get sprint with cross-layer data flow (ExposeAs + SendTo + Collector).

        Returns sprint with:
        - tasks that have full_title (includes sprint name from ancestor_context)
        - contributors: aggregated from task owners via Collector
        """
        stmt = build_dto_select(SprintDetail, where=Sprint.id == sprint_id)
        async with async_session() as session:
            rows = (await session.exec(stmt)).all()
        if not rows:
            return None
        dto = SprintDetail(**dict(rows[0]._mapping))
        return await Resolver().resolve(dto)


# ──────────────────────────────────────────────────
# MCP Server
# ──────────────────────────────────────────────────


def main() -> None:
    import asyncio
    import os
    import sys

    asyncio.run(init_db())

    mcp = create_use_case_graphql_mcp_server(
        apps=[
            UseCaseAppConfig(
                name="project",
                services=[UserService, TaskService, SprintService],
                description="Project management with sprints, tasks, and users",
            ),
        ],
        name="Core API UseCase Demo",
    )

    if "--http" in sys.argv:
        import uvicorn
        from starlette.middleware.cors import CORSMiddleware

        # Use stateless HTTP so one-shot clients (e.g. list-tools probes)
        # can call MCP endpoints without managing mcp-session-id.
        mcp_app = mcp.http_app(transport="streamable-http", stateless_http=True)
        # Demo server is often called from browser-based MCP tooling.
        # Enable permissive CORS to avoid cross-origin preflight failures.
        mcp_app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
        port = int(os.environ.get("PORT", 8006))
        uvicorn.run(mcp_app, host="0.0.0.0", port=port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
