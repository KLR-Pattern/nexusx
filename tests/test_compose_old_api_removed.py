"""Tests for spec FR-010: legacy direct-call MCP entries must be hard-removed.

Importing either of the removed entries (``create_use_case_mcp_server`` /
``create_use_case_flat_server``) from any of the three paths must raise
``ImportError``. The error doesn't need to carry a custom message — Python's
default ``cannot import name 'X' from 'Y'`` is enough — but the test asserts
the replacement name appears in the migration guide so users have a clear
path forward.
"""

from __future__ import annotations

import importlib

import pytest

_REMOVED_NAMES = [
    "create_use_case_mcp_server",
    "create_use_case_flat_server",
]

_IMPORT_PATHS = [
    "nexusx",
    "nexusx.use_case",
]


def _assert_absent(module: str, name: str) -> None:
    """Import ``module`` and assert ``name`` is NOT an attribute."""
    mod = importlib.import_module(module)
    assert not hasattr(mod, name), (
        f"{module}.{name} unexpectedly present — should be removed in 3.0"
    )


@pytest.mark.parametrize("name", _REMOVED_NAMES)
@pytest.mark.parametrize("module", _IMPORT_PATHS)
def test_removed_names_not_importable_from_top_level(module: str, name: str) -> None:
    """Removed names must not be importable from ``nexusx`` or ``nexusx.use_case``.

    ``from nexusx import X`` raises ``ImportError``; ``getattr(module, X)``
    raises ``AttributeError``. Both mean "the name isn't there" — accept either.
    """
    importlib.invalidate_caches()
    mod = importlib.import_module(module)
    with pytest.raises((ImportError, AttributeError)):
        getattr(mod, name)
    _assert_absent(module, name)


@pytest.mark.parametrize(
    "path,name",
    [
        ("nexusx.use_case.server", "create_use_case_mcp_server"),
        ("nexusx.use_case.flat_server", "create_use_case_flat_server"),
    ],
)
def test_legacy_modules_removed(path: str, name: str) -> None:
    """The legacy source modules themselves must not exist."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(path)


def test_replacement_documented_in_migration_guide() -> None:
    """Migration guide names the replacement entry explicitly."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    guide = repo_root / "docs" / "migrations" / "3.0-use-case-graphql.md"
    assert guide.exists(), f"Migration guide missing at {guide}"
    text = guide.read_text(encoding="utf-8")
    assert "create_use_case_graphql_mcp_server" in text
    for removed in _REMOVED_NAMES:
        assert removed in text, (
            f"Migration guide must mention removed entry '{removed}'"
        )


def test_replacement_documented_in_changelog() -> None:
    """CHANGELOG entry for 3.0 must mention both removed names + replacement."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    changelog = repo_root / "CHANGELOG.md"
    assert changelog.exists()
    text = changelog.read_text(encoding="utf-8")
    assert "## 3.0.0" in text
    assert "create_use_case_graphql_mcp_server" in text
    for removed in _REMOVED_NAMES:
        assert removed in text
