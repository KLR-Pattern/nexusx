"""Tests for Voyager source-object resolution behavior."""

from nexusx.use_case.business import UseCaseService
from nexusx.voyager.voyager_context import VoyagerContext


class _DummyService(UseCaseService):
    pass


class _LocalSchema:
    pass


def _make_ctx() -> VoyagerContext:
    return VoyagerContext(services=[_DummyService], name="test")


def test_unknown_service_method_returns_none():
    ctx = _make_ctx()
    assert ctx._resolve_object("_DummyService.nonexistent_method") is None


def test_unknown_service_name_returns_none():
    ctx = _make_ctx()
    assert ctx._resolve_object("NonexistentService.anything") is None


def test_full_qualified_class_name_resolves_outside_service_module():
    ctx = _make_ctx()
    obj = ctx._resolve_object("tests.test_voyager_security._LocalSchema")
    assert obj is _LocalSchema


def test_get_source_code_supports_full_qualified_class_name():
    ctx = _make_ctx()
    result = ctx.get_source_code("tests.test_voyager_security._LocalSchema")
    assert "source_code" in result
    assert "class _LocalSchema" in result["source_code"]


def test_builtin_object_without_source_does_not_fail_format_validation():
    ctx = _make_ctx()
    # builtins.len is a C builtin — no source on every Python version.
    # (os.path.exists gained retrievable source on 3.14, so it no longer
    # exercises the no-source path there.)
    result = ctx.get_source_code("builtins.len")
    assert result == {"source_code": "failed to get source"}


def test_vscode_link_supports_non_service_module_symbol():
    ctx = _make_ctx()
    result = ctx.get_vscode_link("tests.test_voyager_security._LocalSchema")
    assert "link" in result
    assert "test_voyager_security.py" in result["link"]
