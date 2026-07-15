"""Integration tests for FastMCP lifespan → manager.dispose() wiring.

Covers spec FR-006 (lifespan auto-dispose) and FR-007 (dispose idempotency).
"""

from __future__ import annotations

import pytest
from sqlmodel import Field, SQLModel

from nexusx.mcp import Application, MultiAppManager, create_mcp_server


class _TestBase(SQLModel):
    pass


class _Item(_TestBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str


def _make_app(url: str = "sqlite+aiosqlite:///:memory:") -> Application:
    return Application(name="x", base=_TestBase, url=url)


class TestMultiAppManagerDispose:
    @pytest.mark.asyncio
    async def test_dispose_releases_owned_engines(self):
        app = _make_app()
        manager = MultiAppManager([app])
        # Engine must exist before dispose
        assert app.owns_engine is True
        await manager.dispose()
        assert app.disposed is True

    @pytest.mark.asyncio
    async def test_dispose_idempotent_at_manager_level(self):
        app = _make_app()
        manager = MultiAppManager([app])
        await manager.dispose()
        await manager.dispose()  # must not raise
        await manager.dispose()
        assert app.disposed is True

    @pytest.mark.asyncio
    async def test_dispose_skips_non_owned_engines(self):
        # Application in schema-only mode → owns_engine=False → dispose no-op
        app = Application(name="x", base=_TestBase)
        manager = MultiAppManager([app])
        await manager.dispose()
        assert app.disposed is True  # manager marks it disposed even if no engine

    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        app = _make_app()
        async with MultiAppManager([app]) as manager:
            assert "x" in manager.apps
        assert app.disposed is True


class TestCreateMcpServerLifespan:
    """Verify FastMCP lifespan= wiring disposes manager on shutdown."""

    @pytest.mark.asyncio
    async def test_lifespan_disposes_on_exit(self):
        app = _make_app()
        mcp = create_mcp_server(apps=[app], name="Test Server")

        # FastMCP's _lifespan_manager is a no-arg async context manager method
        async with mcp._lifespan_manager():
            assert app.disposed is False

        # After lifespan exit, app should be disposed
        assert app.disposed is True

    @pytest.mark.asyncio
    async def test_lifespan_idempotent(self):
        """Verify _lifespan_manager is idempotent (FastMCP caches the result)."""
        app = _make_app()
        mcp = create_mcp_server(apps=[app], name="Test Server")

        async with mcp._lifespan_manager():
            pass
        assert app.disposed is True

        # Second entry should be a no-op (cached)
        async with mcp._lifespan_manager():
            pass

        # App remains disposed (not re-disposed, no exception)
        assert app.disposed is True
