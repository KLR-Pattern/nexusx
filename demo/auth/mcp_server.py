"""MCP server with API Key authentication for AI Agent access.

This demo shows how to protect MCP HTTP endpoints with API Key authentication.

Usage:
    # HTTP mode (requires API Key in X-API-Key header)
    uv run python -m auth_demo.mcp_server

Authentication:
    All MCP requests require X-API-Key header with admin role.

    Example with Claude Desktop config:
        {
            "mcpServers": {
                "auth-demo": {
                    "url": "http://localhost:8001/mcp",
                    "headers": {
                        "X-API-Key": "admin-secret-key"
                    }
                }
            }
        }
"""

from demo.auth.auth import MCPAuthMiddleware
from demo.blog.database import async_session, init_db
from demo.blog.models import BaseEntity
from nexusx.mcp import Application, create_mcp_server


async def lifespan(app):
    """Initialize database on startup."""
    await init_db()


def main() -> None:
    """Run MCP server with authentication middleware."""
    mcp = create_mcp_server(
        apps=[
            Application(
                name="Blog",
                base=BaseEntity,
                session_factory=async_session,
            )
        ],
        name="Auth Demo Blog GraphQL MCP Server",
    )

    # Get the underlying Starlette app and add auth middleware
    # Note: MCP uses streamable-http transport which creates a Starlette app
    mcp_app = mcp.http_app(transport="streamable-http")
    mcp_app.add_middleware(MCPAuthMiddleware)

    # Run with uvicorn
    import uvicorn

    print("=" * 60)
    print("MCP Server with API Key Authentication")
    print("=" * 60)
    print()
    print("Authentication required: X-API-Key header")
    print()
    print("API Keys:")
    print("  Admin:    admin-secret-key (full access)")
    print("  Readonly: readonly-key (no access)")
    print()
    print("Example curl:")
    print('  curl -H "X-API-Key: admin-secret-key" http://localhost:8001/mcp')
    print()
    print("Server starting on http://localhost:8001/mcp")
    print("=" * 60)

    port = int(__import__("os").environ.get("PORT", 8001))
    uvicorn.run(mcp_app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
