"""UseCase GraphQL HTTP server demo — exposes compose schema via plain GraphQL endpoint.

Unlike the MCP demos (``mcp_server.py`` / ``mcp_server_graphql.py``), this one
serves a **standard GraphQL HTTP endpoint** with GraphiQL UI. Anyone with a
GraphQL client (browser, curl, Apollo, etc.) can query it directly — no MCP
protocol knowledge required.

Routing inside the POST handler:
- ``is_introspection_query(query)`` → ``compose_introspect(schema, query)``
  (services ``__schema`` / ``__type`` / ``__typename`` so GraphiQL can boot)
- otherwise → ``execute_compose_query(app, schema, query, context)``
  (real data fetch; ``__schema`` etc. are rejected here per spec FR-008,
  redirecting clients to the schema-discovery MCP layers when relevant)

Reuses the full Core API demo's services (UserService / TaskService /
SprintService) — same business logic the MCP demo exposes, just via a
different transport.

Usage:
    uv run uvicorn demo.use_case.graphql_server:app --port 8012
    # then open http://127.0.0.1:8012/graphql in a browser
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse

from nexusx import (
    UseCaseAppConfig,
    build_compose_schema,
)
from nexusx.graphiql import GRAPHIQL_HTML
from nexusx.use_case.compose_executor import (
    compose_introspect,
    execute_compose_query,
    is_introspection_query,
)

# Reuse the full demo's services — same ErManager + DefineSubset DTOs +
# Resolver-powered auto-loading as the MCP path.
from demo.use_case.mcp_server import SprintService, TaskService, UserService

APP_CONFIG = UseCaseAppConfig(
    name="project",
    services=[UserService, TaskService, SprintService],
    description="Project management with sprints, tasks, and users",
)
SCHEMA = build_compose_schema(APP_CONFIG)

app = FastAPI(title="nexusx UseCase GraphQL Demo")


@app.post("/graphql")
async def graphql_endpoint(request: Request) -> JSONResponse:
    """Standard GraphQL HTTP endpoint.

    Accepts ``{"query": "...", "variables": {...}, "operationName": "..."}``.
    Routes introspection to ``compose_introspect``; everything else to
    ``execute_compose_query``.
    """
    body: dict[str, Any] = await request.json()
    query: str = body.get("query", "")
    variables: dict[str, Any] | None = body.get("variables")
    operation_name: str | None = body.get("operationName")

    # Variables aren't currently supported by execute_compose_query — inline
    # them if you need parametrized queries. Fail loudly so callers notice.
    if variables:
        return JSONResponse(
            status_code=400,
            content={
                "data": None,
                "errors": [
                    {
                        "message": (
                            "Variables are not yet supported by the compose "
                            "executor; inline arguments in the query string."
                        )
                    }
                ],
            },
        )
    if operation_name:
        # operationName selection is silently accepted (single-op queries
        # work without it); multi-op queries aren't currently supported.
        pass

    if is_introspection_query(query):
        return JSONResponse(compose_introspect(SCHEMA, query))

    result = await execute_compose_query(
        app=APP_CONFIG,
        schema=SCHEMA,
        query=query,
        context={},  # no FromContext params in this demo
    )
    # ``execute_compose_query`` returns Pydantic subset-model instances inside
    # the ``data`` tree; JSONResponse can't serialize them directly. Run them
    # through ``jsonable_encoder`` first so Pydantic models become plain dicts.
    return JSONResponse(jsonable_encoder(result))


@app.get("/graphql")
async def graphiql_ui() -> HTMLResponse:
    """Serve the GraphiQL IDE pointed at this server's POST /graphql."""
    html = GRAPHIQL_HTML.replace("{graphql_url}", "/graphql")
    return HTMLResponse(html)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "nexusx UseCase GraphQL Demo", "graphiql": "/graphql"}


def main() -> None:
    """Run via ``python -m demo.use_case.graphql_server`` (uses uvicorn)."""
    import asyncio
    import os

    from demo.core_api.database import init_db

    asyncio.run(init_db())

    import uvicorn

    port = int(os.environ.get("PORT", 8012))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
