"""
GraphQL Demo with Pagination — FastAPI Application

Identical to demo/app.py but with enable_pagination=True.
Lists are wrapped in { items, pagination { has_more, total_count } } types.
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


# Pagination enabled — all list relationships return Page types
config = AutoQueryConfig(session_factory=async_session, default_limit=20)
handler = GraphQLHandler(
    base=BaseEntity,
    auto_query_config=config,
    enable_pagination=True,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    await init_db()
    yield


app = FastAPI(
    title="nexusx Demo (Paginated)",
    description="Demo with enable_pagination=True — lists wrapped in Page types",
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
    """Root endpoint with usage instructions and pagination examples."""
    return {
        "message": "nexusx Demo (Paginated)",
        "endpoints": {
            "graphiql": "/graphql (GET - GraphiQL UI)",
            "graphql": "/graphql (POST - Query endpoint)",
            "schema": "/schema (GET - SDL schema)",
        },
        "example_queries": [
            # Basic paginated list
            {
                "description": "Paginate user posts (limit + offset)",
                "query": """
query {
  User {
    get_user(id: 1) {
      name
      posts(limit: 3, offset: 0) {
        items { id title }
        pagination { has_more total_count }
      }
    }
  }
}""",
            },
            # Nested pagination
            {
                "description": "Paginate comments inside posts",
                "query": """
query {
  User {
    get_user(id: 1) {
      name
      posts(limit: 2) {
        items {
          title
          comments(limit: 2) {
            items { content }
            pagination { has_more }
          }
        }
        pagination { has_more total_count }
      }
    }
  }
}""",
            },
            # M2M with pagination
            {
                "description": "Paginate favorite posts",
                "query": """
query {
  User {
    get_user(id: 1) {
      name
      favorite_posts(limit: 2) {
        items { id title }
        pagination { has_more total_count }
      }
    }
  }
}""",
            },
        ],
    }


if __name__ == "__main__":
    import os

    import uvicorn

    port = int(os.environ.get("PORT", 8015))
    uvicorn.run(app, host="0.0.0.0", port=port)
