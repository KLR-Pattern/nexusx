"""Tests for create_use_case_grpc_server — gRPC transport for UseCaseService."""

from __future__ import annotations

import json
from typing import Annotated

import pytest
from pydantic import BaseModel

from nexusx.decorator import mutation, query
from nexusx.use_case.business import UseCaseService
from nexusx.use_case.context import FromContext
from nexusx.use_case.grpc_server import create_use_case_grpc_server
from nexusx.use_case.types import UseCaseAppConfig

grpc = pytest.importorskip("grpc")
grpc_aio = pytest.importorskip("grpc.aio")

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
        return [UserDTO(id=1, name="Alice"), UserDTO(id=2, name="Bob")]

    @query
    async def get_user(cls, user_id: int) -> UserDTO | None:
        if user_id == 1:
            return UserDTO(id=1, name="Alice")
        return None

    @mutation
    async def create_user(cls, name: str) -> UserDTO:
        return UserDTO(id=99, name=name)


class PingService(UseCaseService):
    """Ping service."""

    @query
    async def ping(cls) -> str:
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


def _extract_user(adapter):
    return {"user_id": int(adapter.headers.get("x-user-id", "0"))}


TEST_PORT = 50099
TEST_HOST = "localhost"


@pytest.fixture
async def grpc_server_and_channel():
    config = UseCaseAppConfig(
        name="test",
        services=[UserService, PingService],
    )
    server = create_use_case_grpc_server(config, host=TEST_HOST, port=TEST_PORT)
    await server.start()
    async with grpc_aio.insecure_channel(f"{TEST_HOST}:{TEST_PORT}") as channel:
        yield channel
    await server.stop(grace=0)


TEST_PORT_CTX = 50098


@pytest.fixture
async def grpc_server_context():
    config = UseCaseAppConfig(
        name="test",
        services=[ContextService],
        context_extractor=_extract_user,
    )
    server = create_use_case_grpc_server(config, host=TEST_HOST, port=TEST_PORT_CTX)
    await server.start()
    async with grpc_aio.insecure_channel(f"{TEST_HOST}:{TEST_PORT_CTX}") as channel:
        yield channel
    await server.stop(grace=0)


async def _call(
    channel: grpc_aio.Channel,
    service: str,
    method: str,
    params: dict | None = None,
    metadata: list[tuple[str, str]] | None = None,
) -> tuple[bytes, grpc.StatusCode | None]:
    """Call a gRPC method and return (response_bytes, status_code)."""
    method_path = f"/{service}/{method}"
    call = channel.unary_unary(
        method_path,
        request_serializer=lambda d: json.dumps(d).encode("utf-8"),
        response_deserializer=lambda b: b,
    )
    request = params or {}
    try:
        response = await call(request, metadata=metadata)
        return response, None
    except grpc.aio.AioRpcError as e:
        return b"", e.code()


# ──────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────


class TestBasicInvocation:
    @pytest.mark.asyncio
    async def test_list_users(self, grpc_server_and_channel):
        channel = grpc_server_and_channel
        response, status = await _call(channel, "UserService", "list_users")
        assert status is None
        data = json.loads(response)
        assert len(data["result"]) == 2
        assert data["result"][0]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_get_user(self, grpc_server_and_channel):
        channel = grpc_server_and_channel
        response, status = await _call(channel, "UserService", "get_user", {"user_id": 1})
        assert status is None
        data = json.loads(response)
        assert data["result"]["id"] == 1
        assert data["result"]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_get_user_not_found(self, grpc_server_and_channel):
        channel = grpc_server_and_channel
        response, status = await _call(channel, "UserService", "get_user", {"user_id": 999})
        assert status is None
        data = json.loads(response)
        assert data["result"] is None

    @pytest.mark.asyncio
    async def test_mutation(self, grpc_server_and_channel):
        channel = grpc_server_and_channel
        response, status = await _call(channel, "UserService", "create_user", {"name": "Charlie"})
        assert status is None
        data = json.loads(response)
        assert data["result"]["id"] == 99
        assert data["result"]["name"] == "Charlie"

    @pytest.mark.asyncio
    async def test_ping(self, grpc_server_and_channel):
        channel = grpc_server_and_channel
        response, status = await _call(channel, "PingService", "ping")
        assert status is None
        data = json.loads(response)
        assert data["result"] == "pong"


class TestErrors:
    @pytest.mark.asyncio
    async def test_service_not_found(self, grpc_server_and_channel):
        channel = grpc_server_and_channel
        _, status = await _call(channel, "UnknownService", "list_users")
        # gRPC returns UNIMPLEMENTED when no handler matches the service path
        assert status in (grpc.StatusCode.NOT_FOUND, grpc.StatusCode.UNIMPLEMENTED)

    @pytest.mark.asyncio
    async def test_method_not_found(self, grpc_server_and_channel):
        channel = grpc_server_and_channel
        _, status = await _call(channel, "UserService", "unknown_method")
        assert status == grpc.StatusCode.NOT_FOUND

    @pytest.mark.asyncio
    async def test_invalid_json(self, grpc_server_and_channel):
        channel = grpc_server_and_channel
        call = channel.unary_unary(
            "/UserService/get_user",
            request_serializer=lambda d: d,
            response_deserializer=lambda b: b,
        )
        try:
            await call(b"not json")
            raise AssertionError("Should have raised")
        except grpc.aio.AioRpcError as e:
            assert e.code() == grpc.StatusCode.INVALID_ARGUMENT

    @pytest.mark.asyncio
    async def test_non_object_params(self, grpc_server_and_channel):
        channel = grpc_server_and_channel
        call = channel.unary_unary(
            "/UserService/get_user",
            request_serializer=lambda d: json.dumps(d).encode("utf-8"),
            response_deserializer=lambda b: b,
        )
        try:
            await call([1, 2, 3])
            raise AssertionError("Should have raised")
        except grpc.aio.AioRpcError as e:
            assert e.code() == grpc.StatusCode.INVALID_ARGUMENT

    @pytest.mark.asyncio
    async def test_mutation_disabled(self):
        config = UseCaseAppConfig(
            name="test",
            services=[UserService],
            enable_mutation=False,
        )
        server = create_use_case_grpc_server(config, host=TEST_HOST, port=50097)
        await server.start()
        async with grpc_aio.insecure_channel(f"{TEST_HOST}:50097") as channel:
            _, status = await _call(channel, "UserService", "create_user", {"name": "X"})
            assert status == grpc.StatusCode.PERMISSION_DENIED
        await server.stop(grace=0)


class TestFromContext:
    @pytest.mark.asyncio
    async def test_context_from_metadata(self, grpc_server_context):
        channel = grpc_server_context
        response, status = await _call(
            channel,
            "ContextService",
            "whoami",
            metadata=[("x-user-id", "42")],
        )
        assert status is None
        data = json.loads(response)
        assert data["result"]["id"] == 42

    @pytest.mark.asyncio
    async def test_context_with_body_param(self, grpc_server_context):
        channel = grpc_server_context
        response, status = await _call(
            channel,
            "ContextService",
            "greet",
            params={"message": "hello"},
            metadata=[("x-user-id", "7")],
        )
        assert status is None
        data = json.loads(response)
        assert data["result"] == "user=7,msg=hello"


class TestServerLifecycle:
    def test_invalid_config_type(self):
        with pytest.raises(TypeError, match="UseCaseAppConfig"):
            create_use_case_grpc_server("not a config")

    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        config = UseCaseAppConfig(name="test", services=[PingService])
        server = create_use_case_grpc_server(config, host=TEST_HOST, port=50096)
        await server.start()

        async with grpc_aio.insecure_channel(f"{TEST_HOST}:50096") as channel:
            response, status = await _call(channel, "PingService", "ping")
            assert status is None
            data = json.loads(response)
            assert data["result"] == "pong"

        await server.stop(grace=0)
