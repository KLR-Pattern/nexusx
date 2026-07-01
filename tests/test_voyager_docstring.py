"""spec 006 — Tests for ``VoyagerContext.get_docstring`` and the ``POST /docstring`` endpoint.

Mirrors ``test_voyager_security.py`` pattern: instantiate ``VoyagerContext`` directly
with a dummy service, then call ``get_docstring`` with full-qualified schema names.
"""

from nexusx.use_case.business import UseCaseService
from nexusx.voyager.voyager_context import VoyagerContext


class _DummyService(UseCaseService):
    pass


class _DocumentedSchema:
    """A schema with a non-empty docstring.

    Used to verify the happy path of ``get_docstring``.
    """


class _UndocumentedSchema:
    pass


def _make_ctx() -> VoyagerContext:
    return VoyagerContext(services=[_DummyService], name="test")


# ──────────────────────────────────────────────────
# VoyagerContext.get_docstring — direct method tests
# ──────────────────────────────────────────────────


def test_get_docstring_returns_class_docstring_on_happy_path():
    ctx = _make_ctx()
    result = ctx.get_docstring("tests.test_voyager_docstring._DocumentedSchema")
    assert "docstring" in result
    assert "non-empty docstring" in result["docstring"]


def test_get_docstring_returns_empty_string_when_doc_is_none():
    ctx = _make_ctx()
    result = ctx.get_docstring("tests.test_voyager_docstring._UndocumentedSchema")
    assert result == {"docstring": ""}


def test_get_docstring_invalid_schema_name_format():
    ctx = _make_ctx()
    # No dot → _resolve_object returns None → "Invalid schema name format."
    result = ctx.get_docstring("no_dot_string")
    assert result == {"error": "Invalid schema name format."}


def test_get_docstring_module_not_found():
    # _resolve_object swallows ImportError and returns None (matches /source
    # behavior), so a nonexistent module surfaces as "Invalid schema name
    # format." rather than "Module not found." Test locks this in to guard
    # against future refactor that changes the contract.
    ctx = _make_ctx()
    result = ctx.get_docstring("nonexistent_module.Foo")
    assert result == {"error": "Invalid schema name format."}


def test_get_docstring_class_not_found():
    ctx = _make_ctx()
    result = ctx.get_docstring("tests.test_voyager_docstring.NoSuchClass")
    assert "error" in result
    assert "Class not found" in result["error"]
