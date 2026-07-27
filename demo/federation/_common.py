"""Shared helpers for the federation demo apps (users / reviews / catalog).

Each demo service is its own process with its own DB. Mounting services
(reviews, catalog) call ``handler.federate(...)`` in their lifespan; a small
retry loop tolerates the dependency service still starting up.
"""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from nexusx.federation.introspect import serialize_er_introspection


class GraphQLRequest(BaseModel):
    query: str
    variables: dict[str, Any] | None = None
    operation_name: str | None = None


def make_app(
    handler: Any,
    *,
    on_startup: Callable[[], Awaitable[None]] | None = None,
    title: str = "nexusx federation demo",
) -> FastAPI:
    """Build a FastAPI app exposing /graphql + /nexusx/er-introspection + GraphiQL."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if on_startup is not None:
            await on_startup()
        yield

    app = FastAPI(title=title, lifespan=lifespan)

    @app.post("/graphql")
    async def graphql_endpoint(req: GraphQLRequest) -> dict[str, Any]:
        return await handler.execute(req.query, req.variables, req.operation_name)

    @app.get("/nexusx/er-introspection")
    async def er_introspection_endpoint() -> dict[str, Any]:
        return serialize_er_introspection(handler._er_manager).model_dump()

    # GraphiQL HTML at / for interactive querying.
    from fastapi.responses import HTMLResponse

    @app.get("/", response_class=HTMLResponse)
    async def graphiql_page() -> str:
        return handler.get_graphiql_html(endpoint="/graphql")

    return app


async def federate_with_retry(
    handler: Any, services: dict[str, str], *, tries: int = 30, delay: float = 0.5
) -> None:
    """federate() with retry — tolerates a dependency service still booting."""
    last: Exception | None = None
    for _ in range(tries):
        try:
            await handler.federate(services)
            return
        except Exception as e:  # noqa: BLE001 — demo-only resilience
            last = e
            await asyncio.sleep(delay)
    msg = f"federate({services}) failed after {tries} retries: {last}"
    raise RuntimeError(msg) from last
