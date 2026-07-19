"""Tests for create_router — auto-generating FastAPI routers from UseCaseService."""

from __future__ import annotations

from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from starlette.requests import Request

from nexusx.decorator import mutation, query
from nexusx.use_case.business import UseCaseService
from nexusx.use_case.context import FromContext
from nexusx.use_case.router import create_router
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


# ──────────────────────────────────────────────────
# Tests: Extensibility (dependencies, route_options, router_kwargs)
# ──────────────────────────────────────────────────


class TestRouterExtensibility:
    def test_router_dependencies_applied_to_all_routes(self):
        """Router-level dependencies are enforced on every route."""
        async def require_auth(request: Request) -> None:
            if request.headers.get("X-Auth") != "secret":
                raise HTTPException(status_code=403, detail="Forbidden")

        config = UseCaseAppConfig(name="test", services=[PingService])
        router = create_router(config, dependencies=[Depends(require_auth)])
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        # Without auth header → 403
        response = client.post("/api/ping_service/ping")
        assert response.status_code == 403

        # With auth header → 200
        response = client.post("/api/ping_service/ping", headers={"X-Auth": "secret"})
        assert response.status_code == 200
        assert response.json() == "pong"

    def test_route_options_status_code(self):
        """route_options can override status_code for a specific route."""
        config = UseCaseAppConfig(name="test", services=[PingService])
        router = create_router(
            config,
            route_options={
                "PingService.ping": {"status_code": 201},
            },
        )
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.post("/api/ping_service/ping")
        assert response.status_code == 201

    def test_route_options_per_route_dependencies(self):
        """Per-route dependencies only affect the targeted route."""
        async def require_admin(request: Request) -> None:
            if request.headers.get("X-Admin") != "yes":
                raise HTTPException(status_code=403, detail="Admin only")

        config = UseCaseAppConfig(name="test", services=[UserService, PingService])
        router = create_router(
            config,
            route_options={
                "UserService.create_user": {
                    "dependencies": [Depends(require_admin)],
                },
            },
        )
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        # create_user without admin → 403
        response = client.post(
            "/api/user_service/create_user",
            json={"name": "X", "email": "x@test.com"},
        )
        assert response.status_code == 403

        # list_users is unaffected → 200
        response = client.post("/api/user_service/list_users")
        assert response.status_code == 200

        # ping is unaffected → 200
        response = client.post("/api/ping_service/ping")
        assert response.status_code == 200

    def test_router_kwargs_passthrough(self):
        """**router_kwargs are forwarded to APIRouter constructor."""
        config = UseCaseAppConfig(name="test", services=[PingService])
        # Pass deprecated=True through router_kwargs
        router = create_router(config, deprecated=True)
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        # Route still works
        response = client.post("/api/ping_service/ping")
        assert response.status_code == 200

        # Deprecated flag appears in OpenAPI schema
        schema = client.get("/openapi.json").json()
        ping_op = schema["paths"]["/api/ping_service/ping"]["post"]
        assert ping_op.get("deprecated") is True

    def test_backward_compatible_no_new_args(self):
        """Existing call sites with no new arguments still work."""
        config = UseCaseAppConfig(name="test", services=[UserService])
        router = create_router(config)
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.post("/api/user_service/list_users")
        assert response.status_code == 200


# ──────────────────────────────────────────────────
# Tests: Nested BaseModel parameters (issue #107 regression)
# ──────────────────────────────────────────────────


class ItemInput(BaseModel):
    """Nested BaseModel used as method parameter."""
    text: str
    checked: bool = False


class ItemOutput(BaseModel):
    """Nested BaseModel returned by methods."""
    text: str
    checked: bool


class NestedModelService(UseCaseService):
    """Service exercising nested BaseModel parameters across all forms."""

    @mutation
    async def create_items(cls, owner_id: int, items: list[ItemInput]) -> list[ItemOutput]:
        # The bug: items arrives as list[dict] instead of list[ItemInput]
        # → AttributeError on it.text
        return [ItemOutput(text=it.text, checked=it.checked) for it in items]

    @mutation
    async def echo_single(cls, item: ItemInput) -> ItemOutput:
        return ItemOutput(text=item.text, checked=item.checked)

    @mutation
    async def echo_optional(
        cls,
        item: ItemInput | None = None,
    ) -> ItemOutput | None:
        if item is None:
            return None
        return ItemOutput(text=item.text, checked=item.checked)

    @mutation
    async def echo_optional_list(
        cls,
        items: list[ItemInput] | None = None,
    ) -> list[ItemOutput]:
        if items is None:
            return []
        return [ItemOutput(text=it.text, checked=it.checked) for it in items]

    @mutation
    async def echo_list_of_optional(
        cls,
        items: list[ItemInput | None],
    ) -> list[ItemOutput | None]:
        return [
            ItemOutput(text=it.text, checked=it.checked) if it is not None else None
            for it in items
        ]

    @mutation
    async def echo_nested_two_levels(
        cls,
        matrix: list[list[ItemInput]],
    ) -> list[ItemOutput]:
        flat: list[ItemOutput] = []
        for row in matrix:
            for it in row:
                flat.append(ItemOutput(text=it.text, checked=it.checked))
        return flat

    @query
    async def echo_with_context(
        cls,
        user_id: Annotated[int, FromContext()],
        items: list[ItemInput],
    ) -> str:
        # Case 1: body + FromContext. Both must arrive in correct types.
        first_text = items[0].text if items else "(empty)"
        return f"user={user_id},first={first_text}"


def _extract_user_id_from_header(request):
    return {"user_id": int(request.headers.get("X-User-Id", "0"))}


@pytest.fixture
def nested_client():
    return _make_app(
        UseCaseAppConfig(
            name="nested",
            services=[NestedModelService],
            context_extractor=_extract_user_id_from_header,
        )
    )


class TestNestedBaseModelParams:
    """Regression tests for issue #107: nested BaseModel parameters must be
    received as BaseModel instances by the method body, not as dicts.

    Before fix: router called body.model_dump(), flattening nested BaseModels.
    After fix:  router uses getattr(body, pname), preserving BaseModel instances.
    """

    def test_list_of_basemodel(self, nested_client):
        """list[ItemInput] arrives as list of ItemInput instances."""
        response = nested_client.post(
            "/api/nested_model_service/create_items",
            json={
                "owner_id": 1,
                "items": [
                    {"text": "a", "checked": True},
                    {"text": "b"},
                ],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json() == [
            {"text": "a", "checked": True},
            {"text": "b", "checked": False},
        ]

    def test_single_nested_basemodel(self, nested_client):
        """ItemInput (single, non-list) arrives as ItemInput instance."""
        response = nested_client.post(
            "/api/nested_model_service/echo_single",
            json={"item": {"text": "x", "checked": True}},
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"text": "x", "checked": True}

    def test_optional_basemodel_with_value(self, nested_client):
        """Optional[ItemInput] with a value arrives as ItemInput instance."""
        response = nested_client.post(
            "/api/nested_model_service/echo_optional",
            json={"item": {"text": "y"}},
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"text": "y", "checked": False}

    def test_optional_basemodel_with_none(self, nested_client):
        """Optional[ItemInput] with explicit null arrives as None."""
        response = nested_client.post(
            "/api/nested_model_service/echo_optional",
            json={"item": None},
        )
        assert response.status_code == 200, response.text
        assert response.json() is None

    def test_optional_list_of_basemodel(self, nested_client):
        """Optional[list[ItemInput]] preserves BaseModel instances."""
        response = nested_client.post(
            "/api/nested_model_service/echo_optional_list",
            json={"items": [{"text": "z"}]},
        )
        assert response.status_code == 200, response.text
        assert response.json() == [{"text": "z", "checked": False}]

    def test_optional_list_of_basemodel_omitted(self, nested_client):
        """Optional[list[ItemInput]] omitted entirely → None, not empty list."""
        response = nested_client.post(
            "/api/nested_model_service/echo_optional_list",
            json={},
        )
        assert response.status_code == 200, response.text
        assert response.json() == []

    def test_list_of_optional_basemodel(self, nested_client):
        """list[Optional[ItemInput]] handles null elements correctly."""
        response = nested_client.post(
            "/api/nested_model_service/echo_list_of_optional",
            json={"items": [{"text": "a"}, None, {"text": "b"}]},
        )
        assert response.status_code == 200, response.text
        assert response.json() == [
            {"text": "a", "checked": False},
            None,
            {"text": "b", "checked": False},
        ]

    def test_nested_two_levels(self, nested_client):
        """list[list[ItemInput]] preserves BaseModel instances at both levels."""
        response = nested_client.post(
            "/api/nested_model_service/echo_nested_two_levels",
            json={
                "matrix": [
                    [{"text": "r0a"}, {"text": "r0b"}],
                    [{"text": "r1a"}],
                ]
            },
        )
        assert response.status_code == 200, response.text
        assert response.json() == [
            {"text": "r0a", "checked": False},
            {"text": "r0b", "checked": False},
            {"text": "r1a", "checked": False},
        ]

    def test_basemodel_with_from_context(self, nested_client):
        """Case 1: body has nested BaseModel + FromContext scalar param."""
        response = nested_client.post(
            "/api/nested_model_service/echo_with_context",
            json={"items": [{"text": "alpha"}]},
            headers={"X-User-Id": "42"},
        )
        assert response.status_code == 200, response.text
        assert response.json() == "user=42,first=alpha"

    def test_explicit_type_check_list_of_basemodel(self, nested_client):
        """Explicit isinstance lock-in: list[ItemInput] elements must be
        ItemInput instances (not dicts). Documents the fix's invariant."""
        # Service method echoes the runtime type name of the first element.
        # We piggyback on create_items — if elements aren't ItemInput,
        # the method body's .text access raises AttributeError before this
        # assertion is reached. So this test is essentially a stronger
        # version of test_list_of_basemodel.
        response = nested_client.post(
            "/api/nested_model_service/create_items",
            json={"owner_id": 1, "items": [{"text": "a"}]},
        )
        assert response.status_code == 200, response.text
        assert response.json() == [{"text": "a", "checked": False}]


# ──────────────────────────────────────────────────
# Tests: Regression — scalar / list[scalar] / default / alias unchanged
# ──────────────────────────────────────────────────


class RegressionService(UseCaseService):
    """Service asserting scalar / list[scalar] / default / alias behavior
    is unchanged by the model_dump → getattr fix (issue #107)."""

    @query
    async def scalar_int(cls, n: int) -> int:
        # Assert exact type — not bool (which is a subclass of int).
        assert type(n) is int, f"expected int, got {type(n)}"
        return n

    @query
    async def scalar_str(cls, s: str) -> str:
        assert type(s) is str, f"expected str, got {type(s)}"
        return s

    @query
    async def scalar_list(cls, tags: list[str]) -> list[str]:
        assert isinstance(tags, list)
        assert all(type(t) is str for t in tags)
        return tags

    @query
    async def default_value(cls, count: int = 10) -> int:
        # Default must fire when client omits the field; explicit value must
        # override the default. Both paths exercise the same getattr route.
        return count

    @query
    async def aliased_field(
        cls,
        name: Annotated[str, Field(alias="userName")],
    ) -> str:
        # Pydantic alias: JSON key is "userName", Python field name is "name".
        # getattr(body, "name") must still resolve correctly.
        assert type(name) is str
        return name


@pytest.fixture
def regression_client():
    return _make_app(
        UseCaseAppConfig(name="regression", services=[RegressionService])
    )


class TestRouterRegression:
    """US2 regression: scalar / list[scalar] / default / alias must behave
    identically before and after the issue #107 fix."""

    def test_scalar_int_unchanged(self, regression_client):
        """Scalar int param: type preserved (not coerced, not dict'd)."""
        response = regression_client.post(
            "/api/regression_service/scalar_int",
            json={"n": 42},
        )
        assert response.status_code == 200, response.text
        assert response.json() == 42

    def test_scalar_str_unchanged(self, regression_client):
        """Scalar str param: type preserved."""
        response = regression_client.post(
            "/api/regression_service/scalar_str",
            json={"s": "hello"},
        )
        assert response.status_code == 200, response.text
        assert response.json() == "hello"

    def test_scalar_list_unchanged(self, regression_client):
        """list[str] param: stays list of str (was already correct pre-fix)."""
        response = regression_client.post(
            "/api/regression_service/scalar_list",
            json={"tags": ["a", "b", "c"]},
        )
        assert response.status_code == 200, response.text
        assert response.json() == ["a", "b", "c"]

    def test_default_value_omitted(self, regression_client):
        """Default value fires when client omits the field."""
        response = regression_client.post(
            "/api/regression_service/default_value",
            json={},
        )
        assert response.status_code == 200, response.text
        assert response.json() == 10

    def test_default_value_overridden(self, regression_client):
        """Explicit value overrides the default."""
        response = regression_client.post(
            "/api/regression_service/default_value",
            json={"count": 42},
        )
        assert response.status_code == 200, response.text
        assert response.json() == 42

    def test_alias_field_unchanged(self, regression_client):
        """Annotated[..., Field(alias=...)]: JSON key is alias, Python
        attribute access uses field name. Both must resolve."""
        response = regression_client.post(
            "/api/regression_service/aliased_field",
            json={"userName": "alice"},
        )
        assert response.status_code == 200, response.text
        assert response.json() == "alice"
