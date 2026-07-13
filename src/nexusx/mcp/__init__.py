"""MCP (Model Context Protocol) integration for nexusx.

This module provides an MCP server that exposes multiple GraphQL applications as MCP tools,
allowing AI models to dynamically discover and execute GraphQL queries and mutations
across multiple independent databases.

Each app is represented as a self-contained :class:`Application` instance —封装
SQLModel ``base`` 加完整的数据库连接信息（``url`` / ``engine`` / ``session_factory``
三选一）。Application 可作为独立 Python 包发布，再由合并项目组装到
``create_mcp_server(apps=[...])`` 使用，无需在合并项目里重新声明连接资源。

Example:
    ```python
    from nexusx.mcp import Application, create_mcp_server

    apps = [
        Application(
            name="blog",
            base=BlogBaseEntity,
            url="sqlite+aiosqlite:///blog.db",  # app owns the engine
            description="Blog system API",
            query_description="Query users, posts, and comments",
            mutation_description="Create and update blog data",
        ),
        Application(
            name="shop",
            base=ShopBaseEntity,
            url="sqlite+aiosqlite:///shop.db",
            description="E-commerce system API",
        ),
    ]

    mcp = create_mcp_server(
        apps=apps,
        name="My Multi-App GraphQL API"
    )

    # Run with stdio transport (default)
    mcp.run()

    # Or run with HTTP transport
    mcp.run(transport="streamable-http")
    ```

For cross-project composition, each subproject can expose its own ``Application``
singleton via a Python package; the merging project simply imports and assembles:

    ```python
    # In subproject blog_app/__init__.py:
    from nexusx.mcp import Application
    blog = Application(name="blog", base=BlogBaseEntity, url=BLOG_DATABASE_URL)

    # In the merging project:
    from blog_app import blog
    from shop_app import shop
    mcp = create_mcp_server(apps=[blog, shop], name="Gateway")
    ```

The legacy ``AppConfig`` dict form is still accepted but triggers a
``DeprecationWarning``; it will be removed in a future release.
"""

from __future__ import annotations

__all__ = [
    "create_mcp_server",
    "create_simple_mcp_server",
    "Application",
    "AppConfig",  # deprecated; kept for compatibility window
    "MultiAppManager",
    "SingleAppManager",
    "AppResources",
]

from nexusx.mcp.application import Application
from nexusx.mcp.managers import AppResources, MultiAppManager, SingleAppManager
from nexusx.mcp.server import create_mcp_server, create_simple_mcp_server
from nexusx.mcp.types.app_config import AppConfig
