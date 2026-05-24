"""UseCase MCP Server — order system demo for Zhihu article.

Demonstrates how UseCaseService classes become AI-agent-callable tools
via four-layer progressive disclosure MCP.

Usage:
    # stdio mode (for Claude Desktop, etc.)
    uv run --with fastmcp python -m demo.zhihu_article.mcp_server

    # HTTP mode (for browser / MCP inspector)
    uv run --with fastmcp python -m demo.zhihu_article.mcp_server --http
"""

from nexusx import ErManager, UseCaseAppConfig, create_use_case_mcp_server

from demo.zhihu_article.database import async_session, init_db
from demo.zhihu_article.models import Customer, Order, OrderItem, Product, Review
from demo.zhihu_article.services import CustomerService, OrderService, ProductService

# ──────────────────────────────────────────────────
# ErManager: registers ORM + custom relationships, creates Resolver
# ──────────────────────────────────────────────────

er = ErManager(
    entities=[Customer, Product, Order, OrderItem, Review],
    session_factory=async_session,
)

# Inject resolver into services (avoids circular imports)
from demo.zhihu_article.services import set_resolver

set_resolver(er.create_resolver())


# ──────────────────────────────────────────────────
# MCP Server (created at module level for import by sample_output.py)
# ──────────────────────────────────────────────────

mcp = create_use_case_mcp_server(
    apps=[
        UseCaseAppConfig(
            name="order_system",
            services=[OrderService, CustomerService, ProductService],
            description="订单管理系统 — 管理客户、订单和商品",
        ),
    ],
    name="nexusx 订单系统 Demo",
)


def main() -> None:
    import asyncio
    import os
    import sys

    asyncio.run(init_db())

    if "--http" in sys.argv:
        import uvicorn
        from starlette.middleware.cors import CORSMiddleware

        mcp_app = mcp.http_app(transport="streamable-http", stateless_http=True)
        mcp_app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
        port = int(os.environ.get("PORT", 8008))
        uvicorn.run(mcp_app, host="0.0.0.0", port=port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
