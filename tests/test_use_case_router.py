"""Tests for create_router — auto-generating FastAPI routers from UseCaseService."""

from __future__ import annotations

from typing import Annotated

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from sqlmodel_nexus.decorator import mutation, query
from sqlmodel_nexus.use_case.business import UseCaseService
from sqlmodel_nexus.use_case.context import FromContext
from sqlmodel_nexus.use_case.router import create_router
from sqlmodel_nexus.use_case.types import UseCaseAppConfig

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
    """Ping service with no params."""

    @query
    async def ping(cls) -> str:
        """Return pong."""
        return "pong"


class ContextService(UseCaseService):
    """Service using FromContext."""

    @query
    async def whoami(cls, user_id: Annotated[int, FromContext()]) -> UserDTO:
        """Return current user from context."""
        return UserDTO(id=user_id, name="from_context")

    @query
    async def whoami_with_param(
        cls,
        user_id: Annotated[int, FromContext()],
        extra: str,
    ) -> str:
        """Return greeting using context + body param."""
        return f"user={user_id},extra={extra}"


def _extract_user_from_request(request):
    """Simulate extracting user_id from request headers."""
    user_id = request.headers.get("X-User-Id", "0")
    return {"user_id": int(user_id)}


# ──────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────


def _make_app(config: UseCaseAppConfig, **kwargs) -> TestClient:
    app = FastAPI()
    router = create_router(config, **kwargs)
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def basic_client():
    return _make_app(
        UseCaseAppConfig(
            name="test",
            services=[UserService, PingService],
        )
    )


@pytest.fixture
def no_mutation_client():
    return _make_app(
        UseCaseAppConfig(
            name="test",
            services=[UserService],
            enable_mutation=False,
        )
    )


@pytest.fixture
def context_client():
    return _make_app(
        UseCaseAppConfig(
            name="test",
            services=[ContextService],
            context_extractor=_extract_user_from_request,
        )
    )


# ──────────────────────────────────────────────────
# Tests: Router structure
# ──────────────────────────────────────────────────


class TestRouterStructure:
    def test_returns_api_router(self):
        """create_router returns a FastAPI APIRouter."""
        from fastapi import APIRouter

        router = create_router(
            UseCaseAppConfig(name="test", services=[UserService]),
        )
        assert isinstance(router, APIRouter)

    def test_routes_generated_for_all_methods(self, basic_client):
        """Each @query/@mutation method gets a route."""
        routes = basic_client.app.routes
        # UserService: list_users, get_user, create_user
        # PingService: ping
        post_routes = [r for r in routes if hasattr(r, "methods") and "POST" in r.methods]
        assert len(post_routes) == 4

    def test_all_routes_are_post(self, basic_client):
        """All generated routes use POST method."""
        for route in basic_client.app.routes:
            if hasattr(route, "methods") and hasattr(route, "path") and "/api/" in route.path:
                assert route.methods == {"POST"}, (
                    f"Route {route.path} has methods {route.methods}"
                )

    def test_route_path_format(self, basic_client):
        """Route paths follow /{prefix}/{service_url}/{method_name} format."""
        paths = {r.path for r in basic_client.app.routes if hasattr(r, "path")}
        assert "/api/user_service/list_users" in paths
        assert "/api/user_service/get_user" in paths
        assert "/api/user_service/create_user" in paths
        assert "/api/ping_service/ping" in paths

    def test_custom_prefix(self):
        """Custom prefix is applied to all routes."""
        client = _make_app(
            UseCaseAppConfig(name="test", services=[UserService]),
            prefix="/v1",
        )
        paths = {r.path for r in client.app.routes if hasattr(r, "path")}
        assert "/v1/user_service/list_users" in paths

    def test_custom_url_mapper(self):
        """url_mapper overrides the default URL segment."""
        client = _make_app(
            UseCaseAppConfig(name="test", services=[UserService]),
            url_mapper=lambda svc: svc.__name__.replace("Service", "").lower(),
        )
        paths = {r.path for r in client.app.routes if hasattr(r, "path")}
        assert "/api/user/list_users" in paths

    def test_tags_from_service(self, basic_client):
        """Tags are derived from get_tag_name()."""
        for route in basic_client.app.routes:
            if hasattr(route, "tags") and hasattr(route, "path"):
                if "user_service" in route.path:
                    assert "UserService" in route.tags
                elif "ping_service" in route.path:
                    assert "PingService" in route.tags

    def test_empty_services(self):
        """Empty services list produces an empty router."""
        from fastapi import APIRouter

        router = create_router(
            UseCaseAppConfig(name="test", services=[]),
        )
        assert isinstance(router, APIRouter)
        assert len(router.routes) == 0


# ──────────────────────────────────────────────────
# Tests: Mutation filtering
# ──────────────────────────────────────────────────


class TestMutationFiltering:
    def test_mutation_filtered_when_disabled(self, no_mutation_client):
        """Mutation methods are excluded when enable_mutation=False."""
        paths = {r.path for r in no_mutation_client.app.routes if hasattr(r, "path")}
        assert "/api/user_service/list_users" in paths
        assert "/api/user_service/get_user" in paths
        assert "/api/user_service/create_user" not in paths

    def test_query_still_works_without_mutation(self, no_mutation_client):
        """Query methods work normally when enable_mutation=False."""
        response = no_mutation_client.post("/api/user_service/list_users")
        assert response.status_code == 200
        assert len(response.json()) == 2


# ──────────────────────────────────────────────────
# Tests: Endpoint invocation
# ──────────────────────────────────────────────────


class TestEndpointInvocation:
    def test_no_params_method(self, basic_client):
        """POST to method with no parameters succeeds."""
        response = basic_client.post("/api/user_service/list_users")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["name"] == "Alice"

    def test_with_params_method(self, basic_client):
        """POST with body parameters passes them to the method."""
        response = basic_client.post(
            "/api/user_service/get_user",
            json={"user_id": 1},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Alice"

    def test_with_params_returns_none(self, basic_client):
        """POST that returns None is handled."""
        response = basic_client.post(
            "/api/user_service/get_user",
            json={"user_id": 999},
        )
        assert response.status_code == 200

    def test_mutation_method(self, basic_client):
        """Mutation methods work via POST."""
        response = basic_client.post(
            "/api/user_service/create_user",
            json={"name": "Charlie", "email": "c@test.com"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Charlie"

    def test_ping_no_body(self, basic_client):
        """Method with no params works without body."""
        response = basic_client.post("/api/ping_service/ping")
        assert response.status_code == 200
        assert response.json() == "pong"

    def test_missing_required_param(self, basic_client):
        """Missing required parameter returns 422."""
        response = basic_client.post(
            "/api/user_service/get_user",
            json={},
        )
        assert response.status_code == 422


# ──────────────────────────────────────────────────
# Tests: FromContext injection
# ──────────────────────────────────────────────────


class TestFromContext:
    def test_from_context_injected(self, context_client):
        """FromContext parameters are injected via context_extractor."""
        response = context_client.post(
            "/api/context_service/whoami",
            headers={"X-User-Id": "42"},
        )
        assert response.status_code == 200
        assert response.json()["id"] == 42

    def test_from_context_with_body_param(self, context_client):
        """FromContext + body params work together."""
        response = context_client.post(
            "/api/context_service/whoami_with_param",
            json={"extra": "hello"},
            headers={"X-User-Id": "7"},
        )
        assert response.status_code == 200
        assert response.json() == "user=7,extra=hello"

    def test_from_context_missing_header(self, context_client):
        """Missing context value defaults (header not set -> user_id=0)."""
        response = context_client.post(
            "/api/context_service/whoami",
        )
        # context_extractor defaults to 0 when header missing
        assert response.status_code == 200
        assert response.json()["id"] == 0


# ──────────────────────────────────────────────────
# Tests: OpenAPI documentation
# ──────────────────────────────────────────────────


class TestOpenAPI:
    def test_openapi_schema_generated(self, basic_client):
        """OpenAPI schema is generated for the app."""
        response = basic_client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert "paths" in schema

    def test_path_in_openapi(self, basic_client):
        """Generated paths appear in OpenAPI schema."""
        schema = basic_client.get("/openapi.json").json()
        assert "/api/user_service/list_users" in schema["paths"]
        assert "/api/ping_service/ping" in schema["paths"]

    def test_post_method_in_openapi(self, basic_client):
        """All generated routes are POST in OpenAPI."""
        schema = basic_client.get("/openapi.json").json()
        for path, methods in schema["paths"].items():
            if "/api/" in path:
                assert "post" in methods, f"Path {path} missing POST method"

    def test_tags_in_openapi(self, basic_client):
        """Tags appear in OpenAPI schema."""
        schema = basic_client.get("/openapi.json").json()
        user_path = schema["paths"].get("/api/user_service/list_users", {})
        if "post" in user_path:
            assert "UserService" in user_path["post"].get("tags", [])
