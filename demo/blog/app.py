"""
GraphQL Demo FastAPI Application
Provides a GraphiQL interface for querying SQLModel entities.
"""

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from demo.blog.database import async_session, init_db
from demo.blog.models import BaseEntity
from nexusx import AutoQueryConfig, GraphQLHandler


class GraphQLRequest(BaseModel):
    """GraphQL request model."""

    query: str
    variables: dict[str, Any] | None = None
    operation_name: str | None = None


# Create GraphQL handler with auto query configuration and pagination
config = AutoQueryConfig(default_limit=20)
handler = GraphQLHandler(
    base=BaseEntity,
    session_factory=async_session,
    auto_query_config=config,
    enable_pagination=False,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    await init_db()
    yield


# Create FastAPI application
app = FastAPI(
    title="nexusx Demo",
    description="Demo application for nexusx with GraphiQL interface",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/graphql", response_class=HTMLResponse)
async def graphiql_playground():
    """GraphiQL interactive query interface."""
    return handler.get_graphiql_html()


@app.post("/graphql")
async def graphql_endpoint(req: GraphQLRequest):
    """GraphQL query endpoint."""
    return await handler.execute(
        query=req.query,
        variables=req.variables,
        operation_name=req.operation_name,
    )


@app.get("/schema", response_class=PlainTextResponse)
async def get_schema():
    """Get GraphQL schema in SDL format."""
    return handler.get_sdl()


@app.get("/")
async def root():
    """Root endpoint with usage instructions."""
    return {
        "message": "nexusx Demo Server",
        "endpoints": {
            "graphiql": "/graphql (GET - GraphiQL UI)",
            "graphql": "/graphql (POST - Query endpoint)",
            "schema": "/schema (GET - SDL schema)",
            "docs": "/docs (GET - FastAPI docs)",
        },
        "example_queries": [
            "query { users { id name } }",
            "query { user(id: 1) { name email } }",
            "mutation { create_user(name: 'Test', email: 'test@example.com') { id } }",
        ],
    }


if __name__ == "__main__":
    import os

    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
