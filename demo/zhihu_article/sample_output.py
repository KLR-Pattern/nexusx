"""End-to-end MCP Client demo — prints 4-layer progressive disclosure results.

This script creates a UseCase MCP server in-process and calls it through
FastMCP's Client, producing the exact output an AI agent would see.

Run:
    uv run --with fastmcp python -m demo.zhihu_article.sample_output

The printed output can be used directly in the Zhihu article.
"""

import asyncio
import json

from fastmcp import Client

from demo.zhihu_article.database import init_db
from demo.zhihu_article.mcp_server import mcp


async def demo():
    await init_db()

    async with Client(mcp) as client:
        print("=" * 60)
        print("第一层：发现应用 (list_apps)")
        print("=" * 60)
        result = await client.call_tool("list_apps", {})
        data = _extract_json(result)
        _print_json(data)

        print()
        print("=" * 60)
        print("第二层：发现服务 (list_services)")
        print("=" * 60)
        result = await client.call_tool("list_services", {"app_name": "order_system"})
        data = _extract_json(result)
        _print_json(data)

        print()
        print("=" * 60)
        print("第三层：理解能力 (describe_service — OrderService)")
        print("=" * 60)
        result = await client.call_tool(
            "describe_service",
            {"app_name": "order_system", "service_name": "OrderService"},
        )
        data = _extract_json(result)
        _print_json(data)

        print()
        print("=" * 60)
        print("第四层：调用 (call_use_case — get_orders)")
        print("=" * 60)
        result = await client.call_tool(
            "call_use_case",
            {
                "app_name": "order_system",
                "service_name": "OrderService",
                "method_name": "get_orders",
                "params": '{"status": "pending"}',
            },
        )
        data = _extract_json(result)
        _print_json(data)

        print()
        print("=" * 60)
        print("调用示例：客户历史订单")
        print("=" * 60)
        result = await client.call_tool(
            "call_use_case",
            {
                "app_name": "order_system",
                "service_name": "CustomerService",
                "method_name": "get_customer_history",
                "params": '{"customer_id": 1, "limit": 3}',
            },
        )
        data = _extract_json(result)
        _print_json(data)

        print()
        print("=" * 60)
        print("调用示例：商品评价（自定义 Relationship）")
        print("=" * 60)
        result = await client.call_tool(
            "call_use_case",
            {
                "app_name": "order_system",
                "service_name": "ProductService",
                "method_name": "get_products",
                "params": "{}",
            },
        )
        data = _extract_json(result)
        _print_json(data)


def _extract_json(result) -> dict:
    """Extract JSON from MCP tool result."""
    # FastMCP Client returns content items; first one has text
    if hasattr(result, 'content') and result.content:
        text = result.content[0].text
        return json.loads(text)
    # Fallback for different result formats
    if hasattr(result, 'data'):
        return result.data if isinstance(result.data, dict) else {"data": result.data}
    return {"raw": str(result)}


def _print_json(data: dict) -> None:
    """Pretty-print JSON with Chinese characters preserved."""
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(demo())
