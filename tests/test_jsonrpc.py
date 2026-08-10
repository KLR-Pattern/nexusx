"""Tests for create_use_case_jsonrpc_router — JSON-RPC 2.0 endpoint for UseCaseService."""

from __future__ import annotations

import threading
import time
from typing import Annotated

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from nexusx.decorator import mutation, query
from nexusx.use_case.business import UseCaseService
from nexusx.use_case.context import FromContext
from nexusx.use_case.jsonrpc import create_use_case_jsonrpc_router
from nexusx.use_case.types import UseCaseAppConfig

# ──────────────────────────────────────────────────
# Test DTOs
# ──────────────────────────────────────────────────


class UserDTO(BaseModel):
    id: int
    name: str


# ──────────────────────────────────────────────────
# Test Services
# ──────────────────────────────────────────────────


class UserService(UseCaseService):
    """User management service."""

    @query
    async def list_users(cls) -> list[UserDTO]:
        """Get all users."""
        return [UserDTO(id=1, name="Alice"), UserDTO(id=2, name="Bob")]

    @query
    async def get_user(cls, user_id: int) -> UserDTO | None:
        """Get a user by ID."""
        if user_id == 1:
            return UserDTO(id=1, name="Alice")
        return None

    @mutation
    async def create_user(cls, name: str, email: str) -> UserDTO:
        """Create a new user."""
        return UserDTO(id=99, name=name)


class PingService(UseCaseService):
    """Ping service."""

    @query
    async def ping(cls) -> str:
        """Return pong."""
        return "pong"


class ContextService(UseCaseService):
    """Service using FromContext."""

    @query
    async def whoami(cls, user_id: Annotated[int, FromContext()]) -> UserDTO:
        return UserDTO(id=user_id, name="from_context")

    @query
    async def greet(
        cls,
        user_id: Annotated[int, FromContext()],
        message: str,
    ) -> str:
        return f"user={user_id},msg={message}"


# ──────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────


def _extract_user(request):
    return {"user_id": int(request.headers.get("X-User-Id", "0"))}


def _make_app(config: UseCaseAppConfig, **kwargs) -> TestClient:
    app = FastAPI()
    router = create_use_case_jsonrpc_router(config, **kwargs)
    app.include_router(router)
    return TestClient(app)


def _rpc(method: str, params: dict | None = None, req_id: int | None = 1) -> dict:
    return {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": req_id}


# ──────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────


@pytest.fixture
def client():
    return _make_app(
        UseCaseAppConfig(name="test", services=[UserService, PingService]),
    )


@pytest.fixture
def no_mutation_client():
    return _make_app(
        UseCaseAppConfig(name="test", services=[UserService], enable_mutation=False),
    )


@pytest.fixture
def context_client():
    return _make_app(
        UseCaseAppConfig(
            name="test",
            services=[ContextService],
            context_extractor=_extract_user,
        ),
    )


# ──────────────────────────────────────────────────
# Tests: Basic invocation
# ──────────────────────────────────────────────────


class TestBasicInvocation:
    def test_no_params_method(self, client):
        resp = client.post("/rpc", json=_rpc("UserService.list_users"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == 1
        assert len(body["result"]) == 2
        assert body["result"][0]["name"] == "Alice"

    def test_with_params_method(self, client):
        resp = client.post("/rpc", json=_rpc("UserService.get_user", {"user_id": 1}))
        assert resp.status_code == 200
        assert resp.json()["result"]["name"] == "Alice"

    def test_returns_none(self, client):
        resp = client.post("/rpc", json=_rpc("UserService.get_user", {"user_id": 999}))
        assert resp.status_code == 200
        assert resp.json()["result"] is None

    def test_mutation_method(self, client):
        resp = client.post(
            "/rpc",
            json=_rpc("UserService.create_user", {"name": "Charlie", "email": "c@t.com"}),
        )
        assert resp.status_code == 200
        assert resp.json()["result"]["name"] == "Charlie"

    def test_ping(self, client):
        resp = client.post("/rpc", json=_rpc("PingService.ping"))
        assert resp.status_code == 200
        assert resp.json()["result"] == "pong"

    def test_empty_params(self, client):
        resp = client.post("/rpc", json={"jsonrpc": "2.0", "method": "PingService.ping", "id": 1})
        assert resp.status_code == 200
        assert resp.json()["result"] == "pong"


# ──────────────────────────────────────────────────
# Tests: Error handling
# ──────────────────────────────────────────────────


class TestErrors:
    def test_method_not_found_service(self, client):
        resp = client.post("/rpc", json=_rpc("UnknownService.method"))
        assert resp.json()["error"]["code"] == -32601

    def test_method_not_found_method(self, client):
        resp = client.post("/rpc", json=_rpc("UserService.unknown_method"))
        assert resp.json()["error"]["code"] == -32601

    def test_invalid_method_format_no_dot(self, client):
        resp = client.post("/rpc", json=_rpc("list_users"))
        assert resp.json()["error"]["code"] == -32601

    def test_invalid_params_missing_required(self, client):
        resp = client.post("/rpc", json=_rpc("UserService.get_user", {}))
        assert resp.json()["error"]["code"] == -32602

    def test_invalid_jsonrpc_version(self, client):
        resp = client.post(
            "/rpc",
            json={"jsonrpc": "1.0", "method": "UserService.list_users", "id": 1},
        )
        assert resp.json()["error"]["code"] == -32600

    def test_missing_jsonrpc_field(self, client):
        resp = client.post("/rpc", json={"method": "UserService.list_users", "id": 1})
        assert resp.json()["error"]["code"] == -32600

    def test_missing_method_field(self, client):
        resp = client.post("/rpc", json={"jsonrpc": "2.0", "id": 1})
        assert resp.json()["error"]["code"] == -32600

    def test_empty_method(self, client):
        resp = client.post("/rpc", json={"jsonrpc": "2.0", "method": "", "id": 1})
        assert resp.json()["error"]["code"] == -32600

    def test_params_not_dict(self, client):
        resp = client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "UserService.list_users", "params": [1, 2], "id": 1},
        )
        assert resp.json()["error"]["code"] == -32602

    def test_mutation_disabled(self, no_mutation_client):
        resp = no_mutation_client.post(
            "/rpc",
            json=_rpc("UserService.create_user", {"name": "X", "email": "x@t.com"}),
        )
        assert resp.json()["error"]["code"] == -32601

    def test_error_preserves_id(self, client):
        resp = client.post("/rpc", json=_rpc("UnknownService.method", req_id=42))
        assert resp.json()["id"] == 42

    def test_error_id_is_none_when_no_id(self, client):
        resp = client.post("/rpc", json={"jsonrpc": "2.0", "method": "UnknownService.method"})
        assert resp.json()["id"] is None


# ──────────────────────────────────────────────────
# Tests: Batch requests
# ──────────────────────────────────────────────────


class TestBatch:
    def test_batch_multiple_requests(self, client):
        batch = [
            _rpc("UserService.list_users", req_id=1),
            _rpc("PingService.ping", req_id=2),
        ]
        resp = client.post("/rpc", json=batch)
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 2
        by_id = {r["id"]: r for r in results}
        assert len(by_id[1]["result"]) == 2
        assert by_id[2]["result"] == "pong"

    def test_batch_with_error(self, client):
        batch = [
            _rpc("UserService.list_users", req_id=1),
            _rpc("UnknownService.method", req_id=2),
        ]
        resp = client.post("/rpc", json=batch)
        results = resp.json()
        assert len(results) == 2
        by_id = {r["id"]: r for r in results}
        assert "result" in by_id[1]
        assert "error" in by_id[2]

    def test_empty_batch(self, client):
        resp = client.post("/rpc", json=[])
        assert resp.json()["error"]["code"] == -32600

    def test_body_not_dict_or_list(self, client):
        resp = client.post("/rpc", json="hello")
        assert resp.json()["error"]["code"] == -32600


# ──────────────────────────────────────────
# Tests: FromContext injection
# ──────────────────────────────────────────


class TestFromContext:
    def test_context_injected(self, context_client):
        resp = context_client.post(
            "/rpc", json=_rpc("ContextService.whoami"), headers={"X-User-Id": "42"},
        )
        assert resp.json()["result"]["id"] == 42

    def test_context_with_body_param(self, context_client):
        resp = context_client.post(
            "/rpc",
            json=_rpc("ContextService.greet", {"message": "hello"}),
            headers={"X-User-Id": "7"},
        )
        assert resp.json()["result"] == "user=7,msg=hello"

    def test_context_default(self, context_client):
        resp = context_client.post("/rpc", json=_rpc("ContextService.whoami"))
        assert resp.json()["result"]["id"] == 0


# ──────────────────────────────────────────────────
# Tests: Router configuration
# ──────────────────────────────────────────────────


class TestRouterConfig:
    def test_returns_api_router(self):
        from fastapi import APIRouter

        router = create_use_case_jsonrpc_router(UseCaseAppConfig(name="test", services=[UserService]))
        assert isinstance(router, APIRouter)

    def test_custom_path(self):
        app = FastAPI()
        router = create_use_case_jsonrpc_router(
            UseCaseAppConfig(name="test", services=[UserService]), path="/api/rpc",
        )
        app.include_router(router)
        client = TestClient(app)
        resp = client.post("/api/rpc", json=_rpc("UserService.list_users"))
        assert resp.status_code == 200

    def test_context_extractor_override(self):
        """Router-level context_extractor overrides config-level."""
        app = FastAPI()
        router = create_use_case_jsonrpc_router(
            UseCaseAppConfig(name="test", services=[ContextService]),
            context_extractor=lambda r: {"user_id": 999},
        )
        app.include_router(router)
        client = TestClient(app)
        resp = client.post("/rpc", json=_rpc("ContextService.whoami"))
        assert resp.json()["result"]["id"] == 999


# ──────────────────────────────────────────────────
# Tests: rpc.discover
# ──────────────────────────────────────────────────


class TestRpcDiscover:
    def test_returns_service_list(self, client):
        resp = client.post("/rpc", json=_rpc("rpc.discover"))
        assert resp.status_code == 200
        body = resp.json()
        services = body["result"]
        assert len(services) == 2
        names = {s["name"] for s in services}
        assert names == {"UserService", "PingService"}
        for s in services:
            assert "description" in s
            assert "methods_count" in s

    def test_discover_with_no_mutation(self, no_mutation_client):
        resp = no_mutation_client.post("/rpc", json=_rpc("rpc.discover"))
        assert resp.status_code == 200
        assert len(resp.json()["result"]) == 1

    def test_discover_in_batch(self, client):
        batch = [
            _rpc("rpc.discover", req_id=1),
            _rpc("PingService.ping", req_id=2),
        ]
        resp = client.post("/rpc", json=batch)
        results = resp.json()
        by_id = {r["id"]: r for r in results}
        assert isinstance(by_id[1]["result"], list)
        assert by_id[2]["result"] == "pong"


# ──────────────────────────────────────────────────
# Tests: rpc.describe
# ──────────────────────────────────────────────────


class TestRpcDescribe:
    def test_returns_service_detail(self, client):
        resp = client.post("/rpc", json=_rpc("rpc.describe", {"service": "UserService"}))
        assert resp.status_code == 200
        info = resp.json()["result"]
        assert info["name"] == "UserService"
        assert len(info["methods"]) == 3
        method_names = {m["name"] for m in info["methods"]}
        assert "list_users" in method_names
        assert "create_user" in method_names
        assert "types" in info

    def test_unknown_service(self, client):
        resp = client.post("/rpc", json=_rpc("rpc.describe", {"service": "Unknown"}))
        assert resp.json()["error"]["code"] == -32601

    def test_missing_service_param(self, client):
        resp = client.post("/rpc", json=_rpc("rpc.describe", {}))
        assert resp.json()["error"]["code"] == -32602


# ──────────────────────────────────────────────────
# Tests: rpc.schema
# ──────────────────────────────────────────────────


class TestRpcSchema:
    def test_returns_methods_and_defs(self, client):
        resp = client.post("/rpc", json=_rpc("rpc.schema"))
        assert resp.status_code == 200
        body = resp.json()["result"]
        assert "methods" in body
        assert "$defs" in body

    def test_defs_contains_dto_types(self, client):
        resp = client.post("/rpc", json=_rpc("rpc.schema"))
        defs = resp.json()["result"]["$defs"]
        assert "UserDTO" in defs
        user_def = defs["UserDTO"]
        assert user_def["type"] == "object"
        assert "id" in user_def["properties"]
        assert "name" in user_def["properties"]

    def test_params_basic_types(self, client):
        resp = client.post("/rpc", json=_rpc("rpc.schema"))
        methods = resp.json()["result"]["methods"]
        get_user = methods["UserService.get_user"]
        assert get_user["params"]["user_id"]["type"] == "integer"
        assert get_user["kind"] == "query"

    def test_result_ref_defs(self, client):
        resp = client.post("/rpc", json=_rpc("rpc.schema"))
        methods = resp.json()["result"]["methods"]
        list_users = methods["UserService.list_users"]
        result = list_users["result"]
        assert result["type"] == "array"
        assert "$ref" in result["items"]

    def test_mutation_filtered(self, no_mutation_client):
        resp = no_mutation_client.post("/rpc", json=_rpc("rpc.schema"))
        methods = resp.json()["result"]["methods"]
        assert "UserService.create_user" not in methods
        assert "UserService.list_users" in methods


# ──────────────────────────────────────────────────
# Tests: rpc.* error handling
# ──────────────────────────────────────────────────


class TestRpcErrors:
    def test_unknown_rpc_method(self, client):
        resp = client.post("/rpc", json=_rpc("rpc.unknown"))
        assert resp.json()["error"]["code"] == -32601

    def test_rpc_discover_ignores_extra_params(self, client):
        resp = client.post("/rpc", json=_rpc("rpc.discover", {"extra": "ignored"}))
        assert resp.status_code == 200
        assert isinstance(resp.json()["result"], list)


# ──────────────────────────────────────────────────
# Tests: Remote HTTP calls (real uvicorn + httpx)
# ──────────────────────────────────────────────────




@pytest.fixture(scope="module")
def remote_server():
    """Start a real HTTP server in a background thread."""
    _app = FastAPI()
    _router = create_use_case_jsonrpc_router(
        UseCaseAppConfig(
            name="test",
            services=[UserService, PingService, ContextService],
            context_extractor=_extract_user,
        ),
    )
    _app.include_router(_router)

    port = 18765
    thread = threading.Thread(
        target=uvicorn.run,
        kwargs={"app": _app, "host": "127.0.0.1", "port": port, "log_level": "error"},
        daemon=True,
    )
    thread.start()
    time.sleep(1.0)
    yield f"http://127.0.0.1:{port}"


class TestRemoteBasic:
    """Verify JSON-RPC over a real HTTP connection."""

    def test_remote_ping(self, remote_server):
        resp = httpx.post(
            f"{remote_server}/rpc",
            json=_rpc("PingService.ping"),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["jsonrpc"] == "2.0"
        assert body["result"] == "pong"

    def test_remote_list_users(self, remote_server):
        resp = httpx.post(
            f"{remote_server}/rpc",
            json=_rpc("UserService.list_users"),
        )
        assert resp.status_code == 200
        users = resp.json()["result"]
        assert len(users) == 2
        assert users[0]["name"] == "Alice"

    def test_remote_get_user_found(self, remote_server):
        resp = httpx.post(
            f"{remote_server}/rpc",
            json=_rpc("UserService.get_user", {"user_id": 1}),
        )
        assert resp.json()["result"]["id"] == 1

    def test_remote_get_user_not_found(self, remote_server):
        resp = httpx.post(
            f"{remote_server}/rpc",
            json=_rpc("UserService.get_user", {"user_id": 999}),
        )
        assert resp.json()["result"] is None

    def test_remote_mutation(self, remote_server):
        resp = httpx.post(
            f"{remote_server}/rpc",
            json=_rpc("UserService.create_user", {"name": "Zoe", "email": "z@t.com"}),
        )
        assert resp.json()["result"]["name"] == "Zoe"


class TestRemoteErrors:
    def test_remote_method_not_found(self, remote_server):
        resp = httpx.post(
            f"{remote_server}/rpc",
            json=_rpc("UnknownService.method"),
        )
        assert resp.json()["error"]["code"] == -32601

    def test_remote_invalid_params(self, remote_server):
        resp = httpx.post(
            f"{remote_server}/rpc",
            json=_rpc("UserService.get_user", {}),
        )
        assert resp.json()["error"]["code"] == -32602

    def test_remote_invalid_json_body(self, remote_server):
        resp = httpx.post(
            f"{remote_server}/rpc",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        body = resp.json()
        assert body.get("error", {}).get("code") == -32700


class TestRemoteBatch:
    def test_remote_batch_mixed(self, remote_server):
        resp = httpx.post(
            f"{remote_server}/rpc",
            json=[
                _rpc("UserService.list_users", req_id=1),
                _rpc("PingService.ping", req_id=2),
                _rpc("UnknownService.method", req_id=3),
            ],
        )
        results = resp.json()
        assert len(results) == 3
        by_id = {r["id"]: r for r in results}
        assert "result" in by_id[1]
        assert by_id[2]["result"] == "pong"
        assert by_id[3]["error"]["code"] == -32601


class TestRemoteContext:
    def test_remote_from_context(self, remote_server):
        resp = httpx.post(
            f"{remote_server}/rpc",
            json=_rpc("ContextService.whoami"),
            headers={"X-User-Id": "42"},
        )
        assert resp.json()["result"]["id"] == 42

    def test_remote_context_with_param(self, remote_server):
        resp = httpx.post(
            f"{remote_server}/rpc",
            json=_rpc("ContextService.greet", {"message": "hi"}),
            headers={"X-User-Id": "7"},
        )
        assert resp.json()["result"] == "user=7,msg=hi"


class TestRemoteIntrospection:
    def test_remote_rpc_discover(self, remote_server):
        resp = httpx.post(
            f"{remote_server}/rpc",
            json=_rpc("rpc.discover"),
        )
        services = resp.json()["result"]
        names = {s["name"] for s in services}
        assert "UserService" in names

    def test_remote_rpc_describe(self, remote_server):
        resp = httpx.post(
            f"{remote_server}/rpc",
            json=_rpc("rpc.describe", {"service": "UserService"}),
        )
        info = resp.json()["result"]
        assert info["name"] == "UserService"
        assert len(info["methods"]) >= 2

    def test_remote_rpc_schema(self, remote_server):
        resp = httpx.post(
            f"{remote_server}/rpc",
            json=_rpc("rpc.schema"),
        )
        body = resp.json()["result"]
        assert "methods" in body
        assert "$defs" in body
