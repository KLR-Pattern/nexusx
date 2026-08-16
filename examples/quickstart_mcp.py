"""Quick start (MCP) — serve the same entity app to AI agents.

The companion of ``examples/quickstart.py``: same Team/Hero entities, same
in-memory database, but delivered over MCP instead of a GraphQL HTTP endpoint.

Run as a real MCP server (stdio transport, ready for any MCP client):

    uv run python examples/quickstart_mcp.py

Register it with an MCP client, e.g. Claude Code (one line):

    claude mcp add quickstart --
        uv --directory /path/to/nexusx run python examples/quickstart_mcp.py

Run the built-in self-check (seeds the database, calls every tool in-process
through a real MCP client, and prints the results):

    uv run python examples/quickstart_mcp.py --check

Requires the optional MCP integration:

    pip install "nexusx[fastmcp]"
"""

import asyncio
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Relationship, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx import AutoQueryConfig
from nexusx.mcp import create_single_app_mcp_server


class BaseEntity(SQLModel):
    pass


class Team(BaseEntity, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str

    heroes: list["Hero"] = Relationship(back_populates="team")


class Hero(BaseEntity, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    team_id: int | None = Field(default=None, foreign_key="team.id")

    team: Team | None = Relationship(back_populates="heroes")


engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
)
session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# One call replaces the Quick start's FastAPI wiring. The server exposes
# three tools (see the walkthrough below) instead of a /graphql endpoint.
mcp = create_single_app_mcp_server(
    base=BaseEntity,
    session_factory=session_factory,
    auto_query_config=AutoQueryConfig(),
    name="Quickstart API",
    desc="Teams and heroes",
)

# ─────────────────────────────────────────────────────────────────────────────
# How an AI agent uses this server
# ─────────────────────────────────────────────────────────────────────────────
# The agent sees three tools and walks them in order:
#
#   1. get_er_diagram()      → the data map: a Mermaid ER diagram showing
#                              Team/Hero, their fields, and the relationship
#                              edge between them. No operations yet — just
#                              "what exists and how it connects".
#
#   2. get_schema()          → the operations: GraphQL SDL listing what can
#                              be queried. AutoQueryConfig() gave every
#                              entity `by_id` and `by_filter` roots.
#
#   3. graphql_query(query)  → execution: send a GraphQL query, get JSON.
#
# This keeps the agent's context small: it learns the entity map first,
# pulls the SDL once, and then only pays tokens for data.
#
# What happens inside graphql_query("{ Team { by_filter { name heroes { name } } } }"):
#
#   query string
#     → parsed and validated against the schema generated from the entities
#     → the root field `Team.by_filter` resolves to one SQL query on `team`
#     → the nested `heroes` selection does NOT run per row: a DataLoader
#       batches the team IDs and loads ALL heroes in one extra SQL query
#       (relationship query count grows with nesting depth, not row count)
#     → only the selected fields are serialized; unselected columns are
#       never loaded from SQL in the first place
#
# ─────────────────────────────────────────────────────────────────────────────


async def seed() -> None:
    """Create tables and one row of sample data (same as the Quick start)."""
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)

    async with session_factory() as session:
        team = Team(name="Avengers")
        session.add(team)
        await session.flush()
        session.add(Hero(name="Spider-Man", team_id=team.id))
        await session.commit()


async def check() -> None:
    """Call every tool in-process through a real MCP client and print results."""
    from fastmcp import Client

    async with Client(mcp) as client:
        print("── tool 1: get_er_diagram ──────────────────────────────")
        er = await client.call_tool("get_er_diagram", {})
        print(er.data["data"]["mermaid"])

        print("── tool 2: get_schema (SDL excerpt) ────────────────────")
        schema = await client.call_tool("get_schema", {})
        sdl: str = schema.data["data"]["sdl"]
        print("\n".join(sdl.splitlines()[:8]) + "\n...")

        print("── tool 3: graphql_query ───────────────────────────────")
        query = "{ Team { by_filter { name heroes { name } } } }"
        result = await client.call_tool("graphql_query", {"query": query})
        print(f"query: {query}")
        print(f"result: {result.data}")


if __name__ == "__main__":
    if "--check" in sys.argv:
        asyncio.run(seed())  # one loop for DB setup...
        asyncio.run(check())  # ...one for the MCP client session
    else:
        asyncio.run(seed())
        # stdio transport: stdout carries the MCP protocol, so keep it clean —
        # any banner text goes to stderr.
        print("Quickstart MCP server running on stdio", file=sys.stderr)
        mcp.run()
