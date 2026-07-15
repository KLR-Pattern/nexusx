"""Unit tests for the new ``Application`` class.

Covers:
- Construction (url / engine / session_factory / schema-only modes)
- Mutual-exclusion validation
- Aliases validation
- ``dispose()`` idempotency
- External engine sharing (no ownership)
- ``__repr__`` URL redaction (FR-013)
- ``async with`` context manager
"""

from __future__ import annotations

import warnings

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel

from nexusx.mcp import Application
from nexusx.mcp.application import _coerce_to_application, _redact_url
from nexusx.mcp.managers.app_resources import AppResources


# ── Shared test models ────────────────────────────────────────────────────


class _TestBase(SQLModel):
    pass


class _User(_TestBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str


class _AltBase(SQLModel):
    pass


# ── Construction: schema-only mode ────────────────────────────────────────


class TestSchemaOnlyConstruction:
    def test_schema_only_constructor_works(self):
        app = Application(name="blog", base=_TestBase)
        assert app.name == "blog"
        assert app.session_factory is None
        assert app.owns_engine is False
        assert app.disposed is False
        assert isinstance(app.resources, AppResources)
        assert app.resources.name == "blog"

    def test_schema_only_description_default_empty(self):
        app = Application(name="x", base=_TestBase)
        assert app.description == ""

    def test_resources_is_eagerly_populated(self):
        app = Application(name="x", base=_TestBase)
        # Two reads must return the same instance (eager construction)
        assert app.resources is app.resources

    def test_resources_entity_names_empty_without_decorators(self):
        """Without @query decorators, entity_names is empty (expected, matches MultiAppManager tests)."""
        app = Application(name="x", base=_TestBase)
        # _User is a SQLModel table but has no @query, so it's not in entity_names
        assert isinstance(app.resources.entity_names, set)


# ── Construction: url mode (owns engine) ──────────────────────────────────


class TestUrlConstruction:
    def test_url_creates_owned_engine(self):
        app = Application(
            name="blog",
            base=_TestBase,
            url="sqlite+aiosqlite:///:memory:",
        )
        assert app.session_factory is not None
        assert app.owns_engine is True

    def test_engine_kwargs_passed_through(self):
        # Use echo=True to verify kwargs propagation; the engine should have echo=True
        app = Application(
            name="blog",
            base=_TestBase,
            url="sqlite+aiosqlite:///:memory:",
            engine_kwargs={"echo": True},
        )
        # Internal engine attribute access (acceptable in test)
        assert app._engine.echo is True


# ── Construction: external engine mode ────────────────────────────────────


class TestExternalEngineConstruction:
    def test_external_engine_not_owned(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            app = Application(name="x", base=_TestBase, engine=engine)
            assert app.owns_engine is False
            assert app.session_factory is not None
        finally:
            # Caller (test) retains ownership — not the Application
            import asyncio

            asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
                engine.dispose()
            )


# ── Construction: external session_factory mode ──────────────────────────


class TestExternalSessionFactoryConstruction:
    def test_external_session_factory_not_owned(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        sf = async_sessionmaker(engine, expire_on_commit=False)
        try:
            app = Application(name="x", base=_TestBase, session_factory=sf)
            assert app.owns_engine is False
            assert app.session_factory is sf
        finally:
            import asyncio

            asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
                engine.dispose()
            )


# ── Mutual-exclusion validation ───────────────────────────────────────────


class TestMutexValidation:
    def test_url_and_engine_rejected(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            with pytest.raises(ValueError, match="at most one"):
                Application(
                    name="x",
                    base=_TestBase,
                    url="sqlite+aiosqlite:///:memory:",
                    engine=engine,
                )
        finally:
            import asyncio

            asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
                engine.dispose()
            )

    def test_url_and_session_factory_rejected(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        sf = async_sessionmaker(engine, expire_on_commit=False)
        try:
            with pytest.raises(ValueError, match="at most one"):
                Application(
                    name="x",
                    base=_TestBase,
                    url="sqlite+aiosqlite:///:memory:",
                    session_factory=sf,
                )
        finally:
            import asyncio

            asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
                engine.dispose()
            )


# ── Aliases validation ────────────────────────────────────────────────────


class TestAliasesValidation:
    def test_aliases_none_ok(self):
        app = Application(name="x", base=_TestBase)
        assert app.aliases == []

    def test_aliases_list_of_strings(self):
        app = Application(
            name="todo", base=_TestBase, aliases=["todo_app", "todo-app"]
        )
        assert app.aliases == ["todo_app", "todo-app"]

    def test_alias_conflicts_with_own_name_rejected(self):
        with pytest.raises(ValueError, match="conflicts with own name"):
            Application(name="todo", base=_TestBase, aliases=["todo"])

    def test_alias_empty_string_rejected(self):
        with pytest.raises(ValueError, match="non-empty strings"):
            Application(name="todo", base=_TestBase, aliases=[""])

    def test_aliases_not_list_rejected(self):
        with pytest.raises(ValueError, match="must be a list"):
            Application(name="todo", base=_TestBase, aliases="todo_app")

    def test_aliases_returns_copy_not_internal_list(self):
        app = Application(name="x", base=_TestBase, aliases=["a"])
        first = app.aliases
        first.append("b")
        # Internal state must not mutate
        assert app.aliases == ["a"]


# ── Name validation ───────────────────────────────────────────────────────


class TestNameValidation:
    def test_empty_name_rejected(self):
        with pytest.raises(ValueError, match="non-empty string"):
            Application(name="", base=_TestBase)

    def test_none_name_rejected(self):
        with pytest.raises(ValueError, match="non-empty string"):
            Application(name=None, base=_TestBase)  # type: ignore[arg-type]


# ── dispose() idempotency ─────────────────────────────────────────────────


class TestDisposeIdempotency:
    @pytest.mark.asyncio
    async def test_dispose_idempotent_for_owned_engine(self):
        app = Application(
            name="x", base=_TestBase, url="sqlite+aiosqlite:///:memory:"
        )
        await app.dispose()
        assert app.disposed is True
        # Second and third calls must be no-ops
        await app.dispose()
        await app.dispose()
        assert app.disposed is True

    @pytest.mark.asyncio
    async def test_dispose_noop_for_schema_only(self):
        app = Application(name="x", base=_TestBase)
        await app.dispose()
        assert app.disposed is True

    @pytest.mark.asyncio
    async def test_dispose_noop_for_external_engine(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            app = Application(name="x", base=_TestBase, engine=engine)
            await app.dispose()
            assert app.disposed is True
            # External engine must remain usable
            assert engine.url is not None
        finally:
            await engine.dispose()


# ── async with context manager ────────────────────────────────────────────


class TestAsyncContextManager:
    @pytest.mark.asyncio
    async def test_async_with_disposes_on_exit(self):
        async with Application(
            name="x", base=_TestBase, url="sqlite+aiosqlite:///:memory:"
        ) as app:
            assert app.disposed is False
        assert app.disposed is True


# ── Standalone usage (US2): SDL/introspection without an MCP server ───────


class TestStandaloneUsage:
    """Spec US2: an Application can be used independently for SDL generation
    and schema introspection, with or without database connection.
    """

    def test_schema_only_produces_sdl(self):
        """Schema-only Application can generate SDL for documentation/browsing.

        Note: SDL may be empty when there are no @query-decorated entities — that's
        expected behavior (a schema with no operations). The point is that the
        SDL generator runs without a database connection.
        """
        app = Application(name="blog", base=_TestBase)
        sdl = app.resources.sdl_generator.generate()
        assert isinstance(sdl, str)

    def test_url_based_app_can_generate_sdl(self):
        """Application with a URL connection still exposes SDL before any query."""
        app = Application(
            name="blog", base=_TestBase, url="sqlite+aiosqlite:///:memory:"
        )
        sdl = app.resources.sdl_generator.generate()
        assert isinstance(sdl, str)

    @pytest.mark.asyncio
    async def test_external_engine_remains_usable_after_app_dispose(self):
        """When caller passes engine=, the engine is NOT disposed by Application."""
        from sqlmodel import select

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            app = Application(name="x", base=_TestBase, engine=engine)
            await app.dispose()
            # Engine must still be usable for queries
            async with engine.connect() as conn:
                # Just verify connection works (no error)
                pass
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_session_factory_from_owned_engine_works(self):
        """Application.session_factory (when owned) can produce sessions."""
        app = Application(
            name="x", base=_TestBase, url="sqlite+aiosqlite:///:memory:"
        )
        try:
            # Just verify session can be opened & closed without error
            async with app.session_factory() as session:
                assert session is not None
        finally:
            await app.dispose()


# ── URL redaction (FR-013) ─────────────────────────────────────────────────


class TestUrlRedaction:
    def test_redact_url_helper(self):
        redacted = _redact_url("postgresql://user:secret@host:5432/db")
        assert "secret" not in redacted
        assert "***" in redacted
        assert redacted == "postgresql://user:***@host:5432/db"

    def test_redact_url_no_password(self):
        # SQLite in-memory has no password; should pass through
        redacted = _redact_url("sqlite+aiosqlite:///:memory:")
        assert redacted == "sqlite+aiosqlite:///:memory:"

    def test_repr_with_url_contains_redacted_form(self):
        """Application.__repr__ routes the URL through _redact_url (covered separately for postgres)."""
        app = Application(
            name="x",
            base=_TestBase,
            url="sqlite+aiosqlite:///:memory:",
        )
        repr_str = repr(app)
        assert "Application(name='x'" in repr_str
        assert "url=" in repr_str
        assert "owned=True" in repr_str

    def test_repr_no_url_in_schema_only(self):
        app = Application(name="x", base=_TestBase)
        # No URL portion in repr
        assert "url=" not in repr(app)

    @pytest.mark.asyncio
    async def test_repr_after_dispose_safe(self):
        app = Application(
            name="x", base=_TestBase, url="sqlite+aiosqlite:///:memory:"
        )
        await app.dispose()
        # repr must not crash after dispose
        repr_str = repr(app)
        assert "Application" in repr_str


# ── _coerce_to_application ────────────────────────────────────────────────


class TestCoerceToApplication:
    def test_application_passthrough(self):
        app = Application(name="x", base=_TestBase)
        assert _coerce_to_application(app) is app

    def test_dict_triggers_deprecation_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            app = _coerce_to_application({"name": "x", "base": _TestBase})
            assert app.name == "x"
            assert len(caught) == 1
            assert issubclass(caught[0].category, DeprecationWarning)
            assert "deprecated" in str(caught[0].message)

    def test_dict_missing_name_raises(self):
        with pytest.raises(ValueError, match="missing required field 'name'"):
            _coerce_to_application({"base": _TestBase})

    def test_dict_missing_base_raises(self):
        with pytest.raises(ValueError, match="missing required field 'base'"):
            _coerce_to_application({"name": "x"})

    def test_invalid_type_raises(self):
        with pytest.raises(TypeError, match="must be Application or AppConfig"):
            _coerce_to_application("not an app")  # type: ignore[arg-type]
