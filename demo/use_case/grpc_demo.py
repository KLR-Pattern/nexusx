"""gRPC demo — UseCaseService exposed as gRPC server.

Run:
    uv run --with grpcio python -m demo.use_case.grpc_demo
"""

import asyncio
import json

from pydantic import BaseModel

from nexusx import UseCaseAppConfig, UseCaseService, create_use_case_grpc_server, query

# ── DTOs ──────────────────────────────────────────


class ItemDTO(BaseModel):
    id: int
    name: str
    price: float


# ── Service ───────────────────────────────────────


class CatalogService(UseCaseService):
    """Product catalog service."""

    @query
    async def list_items(cls) -> list[ItemDTO]:
        return [
            ItemDTO(id=1, name="Widget", price=9.99),
            ItemDTO(id=2, name="Gadget", price=19.99),
            ItemDTO(id=3, name="Doohickey", price=4.99),
        ]

    @query
    async def get_item(cls, item_id: int) -> ItemDTO | None:
        items = {
            1: ItemDTO(id=1, name="Widget", price=9.99),
            2: ItemDTO(id=2, name="Gadget", price=19.99),
            3: ItemDTO(id=3, name="Doohickey", price=4.99),
        }
        return items.get(item_id)


# ── Main ──────────────────────────────────────────

PORT = 50051


async def server():
    config = UseCaseAppConfig(
        name="catalog",
        services=[CatalogService],
    )
    server = create_use_case_grpc_server(config, port=PORT)
    await server.start()
    print(f"gRPC server listening on port {PORT}")
    await server.wait_for_termination()


async def client():
    from grpc import aio as grpc_aio

    await asyncio.sleep(0.5)  # wait for server

    async with grpc_aio.insecure_channel(f"localhost:{PORT}") as channel:
        call = channel.unary_unary(
            "/CatalogService/list_items",
            request_serializer=lambda d: json.dumps(d).encode(),
            response_deserializer=lambda b: b,
        )
        response = await call({})
        data = json.loads(response)
        print("\n── list_items ──")
        for item in data["result"]:
            print(f"  {item['id']}: {item['name']} — ${item['price']}")

        # Get single item
        call = channel.unary_unary(
            "/CatalogService/get_item",
            request_serializer=lambda d: json.dumps(d).encode(),
            response_deserializer=lambda b: b,
        )
        response = await call({"item_id": 2})
        data = json.loads(response)
        print("\n── get_item(2) ──")
        print(f"  {data['result']}")


async def main():
    server_task = asyncio.create_task(server())
    await client()
    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    asyncio.run(main())
