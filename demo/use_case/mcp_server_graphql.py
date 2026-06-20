"""Minimal UseCase GraphQL MCP demo — no ErManager, no DataLoader, no Resolver.

Shows the smallest possible ``create_use_case_graphql_mcp_server`` setup so
the new 3.0 entry point is easy to evaluate without pulling in the full
Core API stack. For a richer example with ErManager + Resolver + DefineSubset
DTOs, see ``demo/use_case/mcp_server.py``.

Usage:
    uv run --with fastmcp python -m demo.use_case.mcp_server_graphql
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from nexusx import (
    UseCaseAppConfig,
    UseCaseService,
    create_use_case_graphql_mcp_server,
    mutation,
    query,
)


class UserSummary(BaseModel):
    """User summary DTO returned by UserService methods."""

    id: int
    name: str
    email: Optional[str] = None


class UserService(UseCaseService):
    """User management — pure in-memory demo."""

    _users: list[UserSummary] = [
        UserSummary(id=1, name="Alice", email="alice@example.com"),
        UserSummary(id=2, name="Bob", email="bob@example.com"),
    ]

    @query
    async def list_users(cls) -> list[UserSummary]:
        """Return all users."""
        return list(cls._users)

    @query
    async def get_user(cls, user_id: int) -> Optional[UserSummary]:
        """Look up a user by id."""
        return next((u for u in cls._users if u.id == user_id), None)

    @mutation
    async def rename_user(cls, user_id: int, new_name: str) -> Optional[UserSummary]:
        """Rename a user; returns the updated user or None if id not found."""
        for i, u in enumerate(cls._users):
            if u.id == user_id:
                cls._users[i] = u.model_copy(update={"name": new_name})
                return cls._users[i]
        return None


def main() -> None:
    mcp = create_use_case_graphql_mcp_server(
        apps=[
            UseCaseAppConfig(
                name="demo",
                services=[UserService],
                description="Minimal UseCase GraphQL MCP demo",
            ),
        ],
        name="UseCase GraphQL MCP (minimal)",
    )
    mcp.run()


if __name__ == "__main__":
    main()
