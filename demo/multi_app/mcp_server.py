"""Multi-app MCP server demo.

This example demonstrates how to create an MCP server that exposes
multiple independent GraphQL applications as MCP tools.

Usage:
    uv run python demo_multiple_app/mcp_server.py

The server provides two applications:
- blog: Blog system with Users and Posts
- shop: E-commerce system with Products and Orders

All tools (except list_apps) require the app_name parameter to specify
which application to use.
"""

import asyncio

from nexusx.mcp import Application, create_mcp_server

from .database import BLOG_DATABASE_URL, SHOP_DATABASE_URL
from .models import BlogBaseEntity, ShopBaseEntity


def main():
    """Run the multi-app MCP server."""
    # Initialize databases with sample data (sync wrapper)
    from .database import init_databases

    asyncio.run(init_databases())

    # Define applications — each is self-contained with its own database URL,
    # so the merging project does not need to provide connection resources.
    apps = [
        Application(
            name="blog",
            base=BlogBaseEntity,
            url=BLOG_DATABASE_URL,
            description="Blog system API - Manage users and posts",
            query_description="Query users and posts",
            mutation_description="Create users and posts",
        ),
        Application(
            name="shop",
            base=ShopBaseEntity,
            url=SHOP_DATABASE_URL,
            description="E-commerce system API - Manage products and orders",
            query_description="Query products and orders",
            mutation_description="Create products, orders, and order items",
        ),
    ]

    # Create the MCP server
    mcp = create_mcp_server(
        apps=apps,
        name="Multi-App GraphQL MCP Server",
    )

    print("=" * 60)
    print("Multi-App GraphQL MCP Server")
    print("=" * 60)
    print("\nAvailable applications:")
    for app in apps:
        print(f"  - {app['name']}: {app['description']}")
    print("\nMCP Tools:")
    print("  - list_apps()")
    print("  - list_queries(app_name)")
    print("  - list_mutations(app_name)")
    print("  - get_query_schema(name, app_name, response_type)")
    print("  - get_mutation_schema(name, app_name, response_type)")
    print("  - graphql_query(query, app_name)")
    print("  - graphql_mutation(mutation, app_name)")
    print("\nExample queries:")
    print('  - list_apps()')
    print('  - list_queries(app_name="blog")')
    print('  - graphql_query(query="{ users { id name email } }", app_name="blog")')
    print('  - graphql_query(query="{ products { id name price } }", app_name="shop")')
    print("\n" + "=" * 60)
    print("Starting MCP server...")
    print("=" * 60 + "\n")

    # Run the server (mcp.run() handles its own event loop)
    port = int(__import__("os").environ.get("PORT", 8004))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
