"""UseCase CLI Demo — auto-generated Typer CLI from UseCaseService.

Demonstrates ``create_use_case_cli()``: the same UseCaseService classes
exposed by MCP / REST / GraphQL become a layered Typer CLI — each service
is a command group, each ``@query``/``@mutation`` method a command, with
``--select`` for GraphQL-like field projection.

This is the CLI counterpart of ``mcp_server.py`` / ``fastapi_auto.py`` —
same services, same DTOs, different delivery.

Run:
    uv run python -m demo.use_case.cli_demo --help
    uv run python -m demo.use_case.cli_demo sprint-service list_sprints
    uv run python -m demo.use_case.cli_demo sprint-service list_sprints --select "name task_count"
    uv run python -m demo.use_case.cli_demo task-service get_task --task-id 1 --select "title owner { name }"
"""

import asyncio

from demo.core_api.database import init_db
from demo.use_case.mcp_server import SprintService, TaskService, UserService
from nexusx import UseCaseAppConfig, create_use_case_cli

config = UseCaseAppConfig(
    name="project",
    services=[UserService, TaskService, SprintService],
    description="Project management with sprints, tasks, and users",
)

cli = create_use_case_cli(config)


def main() -> None:
    # Build tables + seed demo data before the CLI runs, so queries return rows.
    asyncio.run(init_db())
    cli()


if __name__ == "__main__":
    main()
