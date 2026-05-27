"""Tests for create_cli — Typer CLI generator for UseCaseService."""

from __future__ import annotations

import json
from typing import Annotated

import pytest
from pydantic import BaseModel
from typer.testing import CliRunner

from nexusx.decorator import mutation, query
from nexusx.use_case.business import UseCaseService
from nexusx.use_case.cli import create_cli
from nexusx.use_case.context import FromContext
from nexusx.use_case.types import UseCaseAppConfig

runner = CliRunner()

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
    """Service with FromContext params."""

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
# Fixtures
# ──────────────────────────────────────────────────


@pytest.fixture
def basic_cli():
    return create_cli(UseCaseAppConfig(name="test", services=[UserService, PingService]))


@pytest.fixture
def no_mutation_cli():
    return create_cli(
        UseCaseAppConfig(name="test", services=[UserService], enable_mutation=False),
    )


@pytest.fixture
def context_cli():
    return create_cli(UseCaseAppConfig(name="test", services=[ContextService]))


# ──────────────────────────────────────────────────
# Tests: Basic invocation
# ──────────────────────────────────────────────────


class TestBasicInvocation:
    def test_list_users(self, basic_cli):
        result = runner.invoke(basic_cli, ["user-service", "list_users"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 2
        assert data[0]["name"] == "Alice"

    def test_get_user(self, basic_cli):
        result = runner.invoke(basic_cli, ["user-service", "get_user", "--user-id", "1"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["name"] == "Alice"

    def test_get_user_not_found(self, basic_cli):
        result = runner.invoke(basic_cli, ["user-service", "get_user", "--user-id", "999"])
        assert result.exit_code == 0
        assert json.loads(result.output) is None

    def test_create_user(self, basic_cli):
        result = runner.invoke(
            basic_cli,
            ["user-service", "create_user", "--name", "Charlie", "--email", "c@t.com"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["name"] == "Charlie"

    def test_ping(self, basic_cli):
        result = runner.invoke(basic_cli, ["ping-service", "ping"])
        assert result.exit_code == 0
        assert json.loads(result.output) == "pong"

    def test_no_args_shows_help(self, basic_cli):
        result = runner.invoke(basic_cli, ["--help"])
        assert result.exit_code == 0
        assert "user-service" in result.output


# ──────────────────────────────────────────────────
# Tests: Mutation filtering
# ──────────────────────────────────────────────────


class TestMutationFiltering:
    def test_mutation_excluded(self, no_mutation_cli):
        result = runner.invoke(no_mutation_cli, ["user-service", "create_user", "--help"])
        assert result.exit_code != 0  # command should not exist

    def test_query_still_works(self, no_mutation_cli):
        result = runner.invoke(no_mutation_cli, ["user-service", "list_users"])
        assert result.exit_code == 0


# ──────────────────────────────────────────────────
# Tests: FromContext as plain params
# ──────────────────────────────────────────────────


class TestFromContext:
    def test_from_context_as_plain_param(self, context_cli):
        result = runner.invoke(context_cli, ["context-service", "whoami", "--user-id", "42"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["id"] == 42

    def test_from_context_with_body_param(self, context_cli):
        result = runner.invoke(
            context_cli,
            ["context-service", "greet", "--user-id", "7", "--message", "hello"],
        )
        assert result.exit_code == 0
        assert json.loads(result.output) == "user=7,msg=hello"


# ──────────────────────────────────────────────────
# Tests: Output format
# ──────────────────────────────────────────────────


class TestOutputFormat:
    def test_list_output_is_json(self, basic_cli):
        result = runner.invoke(basic_cli, ["user-service", "list_users"])
        data = json.loads(result.output)
        assert isinstance(data, list)

    def test_dto_output_is_json(self, basic_cli):
        result = runner.invoke(basic_cli, ["user-service", "get_user", "--user-id", "1"])
        data = json.loads(result.output)
        assert isinstance(data, dict)
        assert "id" in data

    def test_none_output(self, basic_cli):
        result = runner.invoke(basic_cli, ["user-service", "get_user", "--user-id", "999"])
        assert json.loads(result.output) is None


# ──────────────────────────────────────────────────
# Tests: CLI structure
# ──────────────────────────────────────────────────


class TestCLIStructure:
    def test_returns_typer_app(self):
        import typer

        cli = create_cli(UseCaseAppConfig(name="test", services=[UserService]))
        assert isinstance(cli, typer.Typer)

    def test_custom_app_name(self):
        cli = create_cli(
            UseCaseAppConfig(name="test", services=[UserService]),
            app_name="myapp",
        )
        result = runner.invoke(cli, ["--help"])
        assert "myapp" in result.output.lower()

    def test_service_groups_appear_in_help(self, basic_cli):
        result = runner.invoke(basic_cli, ["--help"])
        assert "user-service" in result.output
        assert "ping-service" in result.output

    def test_invalid_config_type(self):
        with pytest.raises(TypeError):
            create_cli("not a config")
