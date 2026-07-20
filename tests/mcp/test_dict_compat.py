"""Dict compatibility tests for the AppConfig deprecation window.

Verifies that legacy dict-form app configurations still work end-to-end
(construct MultiAppManager, expose via create_mcp_server), while emitting
a clear ``DeprecationWarning`` directing users to migrate to ``Application``.

Covers spec FR-009 and SC-003.
"""

from __future__ import annotations

import warnings

import pytest
from sqlmodel import Field, SQLModel

from nexusx import query
from nexusx.mcp import create_mcp_server


class _CompatBase(SQLModel):
    pass


class _Widget(_CompatBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str

    @query
    async def list_all(cls) -> list[_Widget]:
        return []


class TestDictCompatPath:
    """The dict form must continue to work (with DeprecationWarning) during the
    deprecation window so existing user code does not break on upgrade.
    """

    def test_dict_form_triggers_deprecation_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            mcp = create_mcp_server(
                apps=[{"name": "x", "base": _CompatBase}],
                name="Compat Test",
            )
            assert mcp is not None
            assert any(issubclass(w.category, DeprecationWarning) for w in caught)

    def test_dict_form_with_url(self):
        """Dict with ``url`` field coerces to Application(url=...)."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            mcp = create_mcp_server(
                apps=[
                    {
                        "name": "x",
                        "base": _CompatBase,
                        "url": "sqlite+aiosqlite:///:memory:",
                    }
                ],
                name="URL Dict Test",
            )
            assert mcp is not None

    def test_dict_form_with_session_factory(self):
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        sf = async_sessionmaker(engine, expire_on_commit=False)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                mcp = create_mcp_server(
                    apps=[{"name": "x", "base": _CompatBase, "session_factory": sf}],
                    name="SF Dict Test",
                )
                assert mcp is not None
        finally:
            import asyncio

            asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
                engine.dispose()
            )

    def test_dict_form_with_aliases(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            mcp = create_mcp_server(
                apps=[
                    {
                        "name": "todo",
                        "base": _CompatBase,
                        "aliases": ["todo_app"],
                    }
                ],
                name="Alias Dict Test",
            )
            assert mcp is not None

    def test_dict_form_missing_name_clear_error(self):
        with pytest.raises(ValueError, match="missing required field 'name'"):
            create_mcp_server(apps=[{"base": _CompatBase}], name="Bad")

    def test_dict_form_missing_base_clear_error(self):
        with pytest.raises(ValueError, match="missing required field 'base'"):
            create_mcp_server(apps=[{"name": "x"}], name="Bad")

    def test_warning_message_mentions_application(self):
        """The DeprecationWarning must mention Application to guide migration."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            create_mcp_server(apps=[{"name": "x", "base": _CompatBase}], name="X")
            msgs = [str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)]
            assert any("Application" in m for m in msgs), msgs
