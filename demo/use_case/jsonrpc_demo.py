"""UseCase JSON-RPC Demo — remote-callable JSON-RPC 2.0 endpoint.

Demonstrates ``create_jsonrpc_router()`` with a running HTTP server,
plus a self-test client that calls every endpoint via httpx.

Run:
    # Start server (background)
    uv run uvicorn demo.use_case.jsonrpc_demo:app --port 8008 &

    # Test with curl
    curl -s -X POST http://localhost:8008/rpc \
      -H "Content-Type: application/json" \
      -d '{"jsonrpc":"2.0","method":"UserService.list_users","id":1}' | python -m json.tool

    # Run self-test client
    uv run python -m demo.use_case.jsonrpc_demo --test

    # Or start server + run tests in one command
    uv run python -m demo.use_case.jsonrpc_demo
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from demo.core_api.database import init_db
from demo.use_case.mcp_server import SprintService, TaskService, UserService

# JSON-RPC lives on feat/jsonrpc-router; this demo uses the same imports
# that would be available after that branch is merged.
from nexusx import UseCaseAppConfig
from nexusx.use_case.jsonrpc import create_jsonrpc_router

app_config = UseCaseAppConfig(
    name="project",
    services=[UserService, TaskService, SprintService],
    description="Project management with sprints, tasks, and users",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="UseCase JSON-RPC Demo",
    description="JSON-RPC 2.0 endpoint for UseCaseService methods",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(create_jsonrpc_router(app_config))


@app.get("/")
async def root():
    return {
        "message": "UseCase JSON-RPC Demo",
        "endpoint": "POST /rpc",
        "methods": [
            "UserService.list_users",
            "TaskService.list_tasks",
            "TaskService.get_tasks_by_sprint  (params: {sprint_id})",
            "TaskService.get_task  (params: {task_id})",
            "SprintService.list_sprints",
            "SprintService.get_sprint  (params: {sprint_id})",
            "SprintService.get_sprint_detail  (params: {sprint_id})",
        ],
    }


# ──────────────────────────────────────────────────
# Self-test client
# ──────────────────────────────────────────────────

_TESTS: list[dict] = [
    {
        "name": "list_users",
        "request": {"jsonrpc": "2.0", "method": "UserService.list_users", "id": 1},
        "check": lambda r: isinstance(r["result"], list) and len(r["result"]) >= 1,
    },
    {
        "name": "list_tasks",
        "request": {"jsonrpc": "2.0", "method": "TaskService.list_tasks", "id": 2},
        "check": lambda r: isinstance(r["result"], list) and len(r["result"]) >= 1,
    },
    {
        "name": "get_task (id=1)",
        "request": {
            "jsonrpc": "2.0",
            "method": "TaskService.get_task",
            "params": {"task_id": 1},
            "id": 3,
        },
        "check": lambda r: r["result"] is not None and r["result"]["id"] == 1,
    },
    {
        "name": "get_task (id=999, not found)",
        "request": {
            "jsonrpc": "2.0",
            "method": "TaskService.get_task",
            "params": {"task_id": 999},
            "id": 4,
        },
        "check": lambda r: r["result"] is None,
    },
    {
        "name": "get_tasks_by_sprint (sprint_id=1)",
        "request": {
            "jsonrpc": "2.0",
            "method": "TaskService.get_tasks_by_sprint",
            "params": {"sprint_id": 1},
            "id": 5,
        },
        "check": lambda r: isinstance(r["result"], list),
    },
    {
        "name": "list_sprints",
        "request": {"jsonrpc": "2.0", "method": "SprintService.list_sprints", "id": 6},
        "check": lambda r: isinstance(r["result"], list),
    },
    {
        "name": "get_sprint (id=1)",
        "request": {
            "jsonrpc": "2.0",
            "method": "SprintService.get_sprint",
            "params": {"sprint_id": 1},
            "id": 7,
        },
        "check": lambda r: r["result"] is not None,
    },
    {
        "name": "get_sprint_detail (id=1)",
        "request": {
            "jsonrpc": "2.0",
            "method": "SprintService.get_sprint_detail",
            "params": {"sprint_id": 1},
            "id": 8,
        },
        "check": lambda r: r["result"] is not None,
    },
    {
        "name": "method not found",
        "request": {"jsonrpc": "2.0", "method": "FooService.bar", "id": 9},
        "check": lambda r: r.get("error", {}).get("code") == -32601,
    },
    {
        "name": "invalid method format (no dot)",
        "request": {"jsonrpc": "2.0", "method": "no_dot", "id": 10},
        "check": lambda r: r.get("error", {}).get("code") == -32601,
    },
    {
        "name": "batch request",
        "request": [
            {"jsonrpc": "2.0", "method": "UserService.list_users", "id": 11},
            {"jsonrpc": "2.0", "method": "SprintService.list_sprints", "id": 12},
        ],
        "check": lambda r: isinstance(r, list) and len(r) == 2,
    },
]


async def run_tests(base_url: str) -> None:
    """Run all test cases against a running JSON-RPC server."""
    try:
        import httpx
    except ImportError:
        print("httpx is required for testing: pip install httpx")
        return

    url = f"{base_url}/rpc"
    passed = 0
    failed = 0

    async with httpx.AsyncClient() as client:
        for test in _TESTS:
            name = test["name"]
            try:
                resp = await client.post(url, json=test["request"])
                resp.raise_for_status()
                data = resp.json()

                if test["check"](data):
                    passed += 1
                    print(f"  PASS  {name}")
                else:
                    failed += 1
                    print(f"  FAIL  {name}")
                    print(f"        response: {json.dumps(data, indent=2)[:200]}")
            except Exception as e:
                failed += 1
                print(f"  ERROR {name}: {e}")

    print(f"\n{passed} passed, {failed} failed, {passed + failed} total")


async def run_server_then_test() -> None:
    """Start the server in-process, run tests, then shut down."""
    import threading
    import time

    import uvicorn

    port = int(os.environ.get("PORT", 8008))
    base_url = f"http://127.0.0.1:{port}"

    # Start server in background thread
    server_thread = threading.Thread(
        target=uvicorn.run,
        kwargs={"app": app, "host": "127.0.0.1", "port": port, "log_level": "warning"},
        daemon=True,
    )
    server_thread.start()
    time.sleep(1.0)

    print(f"Testing JSON-RPC at {base_url}/rpc\n")
    await run_tests(base_url)


if __name__ == "__main__":
    if "--test" in sys.argv:
        port = int(os.environ.get("PORT", 8008))
        asyncio.run(run_tests(f"http://127.0.0.1:{port}"))
    else:
        # Start server, run tests, exit
        asyncio.run(run_server_then_test())
