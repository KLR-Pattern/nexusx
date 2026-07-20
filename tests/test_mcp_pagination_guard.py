"""Tests for MCP enable_pagination / auto_query_config threading + empty-schema guard.

Covers GitHub issue #117:

- ``create_simple_mcp_server`` / ``create_mcp_server`` / ``Application`` must thread
  ``enable_pagination`` and ``auto_query_config`` through to the underlying
  ``GraphQLHandler`` so the MCP surface matches the GraphQL surface.
- The MCP server builders must fail fast (``ValueError``) when a schema has no
  operations, instead of silently serving an empty schema. The guard lives at the
  server-builder layer, so ``Application`` standalone (schema-only / SDL-only,
  specs/009 US2) stays permissive.
"""

# NOTE: this module intentionally does NOT use ``from __future__ import
# annotations``. SQLModel must resolve relationship forward-refs (e.g.
# ``list["_ThreadingPost"]``) at class-definition time so SQLAlchemy's mapper
# can configure them; PEP 563 deferred evaluation leaves them as literal strings
# and breaks mapper configuration.
import pytest
from sqlmodel import Field, Relationship, SQLModel

from nexusx import AutoQueryConfig, GraphQLHandler, query
from nexusx.mcp import Application, create_mcp_server, create_simple_mcp_server
from nexusx.mcp.application import _coerce_to_application
from nexusx.mcp.managers.single_app_manager import SingleAppManager

try:
    import fastmcp  # noqa: F401

    HAS_MCP = True
except ImportError:
    HAS_MCP = False


# ---------------------------------------------------------------------------
# Module-level test entities (unique tablenames to avoid global-metadata clashes).
# Separated so add_standard_queries mutation in one test class cannot contaminate
# another class's assertions.
# ---------------------------------------------------------------------------


class _ThreadingBase(SQLModel):
    """Base with a list relationship so enable_pagination is observable in SDL."""


class _ThreadingUser(_ThreadingBase, table=True):
    __tablename__ = "mcp_guard_threading_user"

    id: int = Field(default=None, primary_key=True)
    name: str
    posts: list["_ThreadingPost"] = Relationship()

    @query
    def get_all(cls) -> list["_ThreadingUser"]:
        """Get all threading users."""
        return []


class _ThreadingPost(_ThreadingBase, table=True):
    __tablename__ = "mcp_guard_threading_post"

    id: int = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="mcp_guard_threading_user.id")
    author: _ThreadingUser | None = Relationship()


class _PlainBase(SQLModel):
    """Base with a @query but NO relationship and never given auto_query_config.

    Used to assert default (options-off) behaviour stays clean of by_id/by_filter.
    """


class _PlainUser(_PlainBase, table=True):
    __tablename__ = "mcp_guard_plain_user"

    id: int = Field(default=None, primary_key=True)
    name: str

    @query
    def get_all(cls) -> list["_PlainUser"]:
        """Get all plain users."""
        return []


class _AutoOnlyBase(SQLModel):
    """Base whose only entity has NO @query — survives only via auto_query_config."""


class _AutoOnlyItem(_AutoOnlyBase, table=True):
    __tablename__ = "mcp_guard_autoonly_item"

    id: int = Field(default=None, primary_key=True)
    name: str


class _EmptyBase(SQLModel):
    """Base with no subclasses at all — zero entities, zero operations."""


class _DummySessionFactory:
    """No-op async session factory; SDL-only tests never open a real session."""

    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class TestThreadingBothOptions:
    """enable_pagination + auto_query_config thread through every MCP path."""

    def test_single_app_manager_sdl_matches_bare_handler(self) -> None:
        cfg = AutoQueryConfig()
        sf = _DummySessionFactory()
        bare = GraphQLHandler(
            base=_ThreadingBase,
            session_factory=sf,
            enable_pagination=True,
            auto_query_config=cfg,
        ).get_sdl()
        via_manager = SingleAppManager(
            base=_ThreadingBase,
            session_factory=sf,
            enable_pagination=True,
            auto_query_config=cfg,
        ).handler.get_sdl()

        # Strongest proof of correct threading: byte-identical SDL.
        assert via_manager == bare
        # And the two features are actually visible.
        assert "by_id(" in via_manager
        assert "by_filter(" in via_manager
        assert "Result" in via_manager or "Pagination" in via_manager

    def test_application_sdl_matches_bare_handler(self) -> None:
        cfg = AutoQueryConfig()
        sf = _DummySessionFactory()
        bare = GraphQLHandler(
            base=_ThreadingBase,
            session_factory=sf,
            enable_pagination=True,
            auto_query_config=cfg,
        ).get_sdl()
        via_app = Application(
            name="x",
            base=_ThreadingBase,
            session_factory=sf,
            enable_pagination=True,
            auto_query_config=cfg,
        ).resources.handler.get_sdl()

        assert via_app == bare
        assert "by_id(" in via_app and "by_filter(" in via_app

    def test_dict_coerce_threads_both_options(self) -> None:
        cfg = AutoQueryConfig()
        app = _coerce_to_application(
            {
                "name": "x",
                "base": _ThreadingBase,
                "session_factory": _DummySessionFactory(),
                "enable_pagination": True,
                "auto_query_config": cfg,
            }
        )
        sdl = app.resources.handler.get_sdl()
        assert "by_id(" in sdl and "by_filter(" in sdl
        assert "Result" in sdl or "Pagination" in sdl

    def test_defaults_off_match_bare_handler(self) -> None:
        """Backward-compat: omitting both options == bare handler without them."""
        bare = GraphQLHandler(base=_PlainBase).get_sdl()
        via_manager = SingleAppManager(base=_PlainBase).handler.get_sdl()
        assert via_manager == bare
        assert "by_id(" not in via_manager
        assert "by_filter(" not in via_manager


@pytest.mark.skipif(not HAS_MCP, reason="fastmcp package not installed")
class TestEmptySchemaGuard:
    """Server builders raise on empty schemas; Application alone stays permissive."""

    def test_simple_server_raises_on_empty_schema(self) -> None:
        with pytest.raises(ValueError, match="no operations"):
            create_simple_mcp_server(base=_EmptyBase)

    def test_multi_app_server_raises_and_names_app(self) -> None:
        with pytest.raises(ValueError, match=r"app 'solo-empty'"):
            create_mcp_server(
                apps=[Application(name="solo-empty", base=_EmptyBase)]
            )

    def test_application_alone_allows_empty_schema(self) -> None:
        """specs/009 US2: schema-only Application construction stays permissive."""
        app = Application(name="solo", base=_EmptyBase)
        assert app.resources.handler.has_operations is False

    def test_auto_query_counts_as_operation(self) -> None:
        """auto_query_config injects by_id → non-empty → no raise."""
        cfg = AutoQueryConfig()
        mcp = create_simple_mcp_server(
            base=_AutoOnlyBase,
            session_factory=_DummySessionFactory(),
            auto_query_config=cfg,
        )
        assert mcp is not None

    def test_simple_server_default_with_query_succeeds(self) -> None:
        """Backward-compat: a normal base with @query builds fine, no guard trip."""
        mcp = create_simple_mcp_server(base=_PlainBase)
        assert mcp is not None


class TestAutoQueryConfigPurePolicy:
    """AutoQueryConfig is pure policy — the container owns the session_factory."""

    def test_handler_rejects_auto_query_without_session_factory(self) -> None:
        """auto_query_config requires a session_factory on the container."""
        with pytest.raises(ValueError, match="session_factory"):
            GraphQLHandler(base=_PlainBase, auto_query_config=AutoQueryConfig())

    @pytest.mark.asyncio
    async def test_by_id_uses_container_session_factory(self) -> None:
        """Regression: by_id executes against the container's connection.

        Pre-fix, by_id closed over ``config.session_factory`` (None when the
        config wasn't given one), so ``Application(url=...) + AutoQueryConfig()``
        crashed at execution. Now the config carries no factory and by_id uses
        the handler/Application's session_factory.
        """
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlmodel.ext.asyncio.session import AsyncSession

        class RegBase(SQLModel):
            pass

        class RegItem(RegBase, table=True):
            __tablename__ = "reg_byid_item"

            id: int = Field(default=None, primary_key=True)
            name: str

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: RegItem.__table__.create(c, checkfirst=True))
        async with sf() as session:
            session.add(RegItem(id=1, name="alice"))
            await session.commit()

        try:
            app = Application(
                name="reg",
                base=RegBase,
                session_factory=sf,
                auto_query_config=AutoQueryConfig(),
            )
            result = await app.resources.handler.execute(
                "{ RegItem { by_id(id: 1) { id name } } }"
            )
            assert result == {
                "data": {"RegItem": {"by_id": {"id": 1, "name": "alice"}}}
            }
        finally:
            await engine.dispose()
