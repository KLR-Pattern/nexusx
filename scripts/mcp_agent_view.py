"""Dump what an MCP client actually sees from the quickstart MCP server.

Writes the raw payloads to /tmp/mcp_view/ so the agent-side analysis can be
done against the on-disk text only (no library knowledge involved).
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

OUT = Path("/tmp/mcp_view")
OUT.mkdir(exist_ok=True)


async def main() -> None:
    from fastmcp import Client

    from examples.quickstart_mcp import mcp, seed

    await seed()

    async with Client(mcp) as client:
        # 0. What the client sees at startup: tool list with descriptions
        tools = await client.list_tools()
        tools_view = [
            {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
            for t in tools
        ]
        (OUT / "0_tools_list.json").write_text(json.dumps(tools_view, indent=2))

        # 1. Discovery step one: the ER diagram
        er = await client.call_tool("get_er_diagram", {})
        (OUT / "1_er_diagram.txt").write_text(er.data["data"]["mermaid"])

        # 2. Discovery step two: the SDL
        schema = await client.call_tool("get_schema", {})
        (OUT / "2_sdl.txt").write_text(schema.data["data"]["sdl"])

        # 3. Error-path probe: misspelled field
        bad = await client.call_tool(
            "graphql_query", {"query": "{ Team { by_filter { nam } } }"}
        )
        (OUT / "3_error_probe.json").write_text(json.dumps(bad.data, indent=2))

    print(f"written to {OUT}")


asyncio.run(main())
