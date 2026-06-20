"""End-to-end demo for flat MCP server — direct tools, no progressive disclosure.

Run:
    uv run --with fastmcp python -m demo.zhihu_article.flat_sample_output
"""

import asyncio
import json

from fastmcp import Client

from nexusx import ErManager, UseCaseAppConfig, create_use_case_graphql_mcp_server

from demo.zhihu_article.database import async_session, init_db
from demo.zhihu_article.models import Customer, Order, OrderItem, Product, Review
from demo.zhihu_article.services import CustomerService, OrderService, ProductService, set_resolver

# ErManager + Resolver
er = ErManager(
    entities=[Customer, Product, Order, OrderItem, Review],
    session_factory=async_session,
)
set_resolver(er.create_resolver())

# Flat MCP server
flat_mcp = create_use_case_graphql_mcp_server(
    apps=[
        UseCaseAppConfig(
            name="order_system",
            services=[OrderService, CustomerService, ProductService],
            description="订单管理系统 — 管理客户、订单和商品",
        ),
    ],
    name="nexusx 订单系统 (Flat)",
)


async def demo():
    await init_db()

    async with Client(flat_mcp) as client:
        # ── List all tools ──
        print("=" * 60)
        print("所有可用 Tools")
        print("=" * 60)
        tools = await client.list_tools()
        for t in tools:
            props = t.inputSchema.get("properties", {})
            param_names = [k for k in props if k != "selection"]
            print(f"  {t.name}({', '.join(param_names)})")
            if t.description:
                desc_line = t.description.split("\n")[0]
                print(f"    → {desc_line}")

        # ── List all resources ──
        print()
        print("=" * 60)
        print("所有可用 Resources")
        print("=" * 60)
        resources = await client.list_resources()
        for r in resources:
            print(f"  {r.uri}")

        # ── Read app resource ──
        print()
        print("=" * 60)
        print("Resource: nexusx://order_system")
        print("=" * 60)
        result = await client.read_resource("nexusx://order_system")
        # read_resource returns a list of content items
        if isinstance(result, list):
            print(result[0].text if hasattr(result[0], "text") else result[0])
        else:
            print(result.content[0].text if hasattr(result, "content") else result)

        # ── Read service resource ──
        print("=" * 60)
        print("Resource: nexusx://order_system/OrderService")
        print("=" * 60)
        result = await client.read_resource("nexusx://order_system/OrderService")
        if isinstance(result, list):
            print(result[0].text if hasattr(result[0], "text") else result[0])
        else:
            print(result.content[0].text if hasattr(result, "content") else result)

        # ── Call tools directly ──
        print()
        print("=" * 60)
        print("Tool 调用: OrderService_get_orders(status='pending')")
        print("=" * 60)
        result = await client.call_tool("OrderService_get_orders", {"status": "pending"})
        data = _extract_json(result)
        _print_json(data)

        print()
        print("=" * 60)
        print("Tool 调用: CustomerService_get_customer_history(customer_id=1)")
        print("=" * 60)
        result = await client.call_tool(
            "CustomerService_get_customer_history",
            {"customer_id": 1, "limit": 3},
        )
        data = _extract_json(result)
        _print_json(data)

        print()
        print("=" * 60)
        print("Tool 调用: ProductService_get_products()")
        print("=" * 60)
        result = await client.call_tool("ProductService_get_products", {})
        data = _extract_json(result)
        _print_json(data)


def _extract_json(result) -> dict:
    if hasattr(result, "content") and result.content:
        text = result.content[0].text
        return json.loads(text)
    if hasattr(result, "data"):
        return result.data if isinstance(result.data, dict) else {"data": result.data}
    return {"raw": str(result)}


def _print_json(data: dict) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(demo())
