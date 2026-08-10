"""Simple MCP server demo using create_single_app_mcp_server.

This demo shows how to create a simplified MCP server for single-app scenarios
with only 3 tools: get_schema, graphql_query, graphql_mutation.
"""

import asyncio
import sys
from pathlib import Path

from sqlmodel import Field, select

# Add parent directory to path to import from demo
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import SQLModel

from demo.blog.database import async_session
from nexusx import mutation, query
from nexusx.mcp import create_single_app_mcp_server


# Define base entity
class BaseEntity(SQLModel):
    """Base class for all demo entities."""

    pass


# Define User entity
class User(BaseEntity, table=True):
    """User entity."""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str

    @query
    async def get_users(cls, limit: int = 10) -> list["User"]:
        """Get all users with optional limit."""
        async with async_session() as session:
            result = await session.exec(select(cls).limit(limit))
            return list(result.all())

    @query
    async def get_user(cls, id: int) -> "User | None":
        """Get a user by ID."""
        async with async_session() as session:
            return await session.get(cls, id)

    @mutation
    async def create_user(cls, name: str, email: str) -> "User":
        """Create a new user."""
        async with async_session() as session:
            user = cls(name=name, email=email)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user


# Initialize database
async def init_db():
    """Initialize the database with sample data."""
    async with async_session() as session:
        # Create tables
        from demo.blog.database import engine

        async with engine.begin() as conn:
            await conn.run_sync(BaseEntity.metadata.create_all)

        # Check if we have users
        result = await session.exec(select(User))
        users = result.all()

        if not users:
            # Add sample users
            session.add(User(name="Alice", email="alice@example.com"))
            session.add(User(name="Bob", email="bob@example.com"))
            session.add(User(name="Charlie", email="charlie@example.com"))
            await session.commit()
            print("✅ Added sample users")


# Create simplified MCP server
mcp = create_single_app_mcp_server(
    base=BaseEntity,
    name="Demo Simple Blog GraphQL MCP Server",
    desc="Blog system with users (simplified 3-tool version)",
    allow_mutation=True,
)

# Tool usage examples (for documentation purposes):
"""
# 1. Get Schema
result = get_schema()
# Returns: {"success": true, "data": {"sdl": "type Query { ... }"}}

# 2. Execute Query
result = graphql_query(query="{ users(limit: 5) { id name email } }")
# Returns: {"success": true, "data": {"users": [...]}}

# 3. Execute Mutation
result = graphql_mutation(
    mutation='mutation { createUser(name: "Dave", email: "dave@example.com") { id name } }'
)
# Returns: {"success": true, "data": {"createUser": {...}}}
"""

if __name__ == "__main__":
    # Initialize database
    print("🔧 Initializing database...")
    asyncio.run(init_db())
    print("✅ Database initialized\n")

    # Check command line arguments for transport mode
    if "--http" in sys.argv:
        print("🚀 Starting MCP server with HTTP transport...")
        print("   Connect to: http://localhost:8000/mcp")
        print("   Press Ctrl+C to stop\n")
        mcp.run(transport="streamable-http")
    else:
        print("🚀 Starting MCP server with stdio transport...")
        print("   This is the default mode for MCP clients\n")
        mcp.run()
