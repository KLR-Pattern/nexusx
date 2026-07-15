"""MCP server using demo entities.

Usage:
    # stdio mode (for Claude Desktop, etc.)
    uv run python -m demo.mcp_server

    # HTTP mode
    uv run python -m demo.mcp_server --http
"""

from demo.blog.database import async_session
from demo.blog.models import BaseEntity
from nexusx.mcp import Application, create_mcp_server


def main() -> None:
    import sys

    mcp = create_mcp_server(
        apps=[
            Application(
                name="Blog",
                base=BaseEntity,
                session_factory=async_session,
            )
        ],
        name="Demo Blog GraphQL MCP Server",
    )

    if "--http" in sys.argv:
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
