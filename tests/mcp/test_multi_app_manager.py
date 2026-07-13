"""Unit tests for MultiAppManager.

Most tests construct apps via the preferred :class:`Application` form.
A handful of tests at the bottom intentionally use the legacy ``AppConfig``
dict form to verify the deprecation compatibility path (and its error messages).
"""

import pytest
from sqlmodel import Field, SQLModel

from nexusx.mcp import Application, MultiAppManager
from nexusx.mcp.managers import AppResources


# Mock models for testing (not test classes)
class MockBaseEntity1(SQLModel):
    """Base entity for mock app 1."""

    pass


class MockUser(MockBaseEntity1, table=True):
    """Mock user entity."""

    id: int | None = Field(default=None, primary_key=True)
    name: str


class MockBaseEntity2(SQLModel):
    """Base entity for mock app 2."""

    pass


class MockProduct(MockBaseEntity2, table=True):
    """Mock product entity."""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    price: float


class TestMultiAppManager:
    """Test cases for MultiAppManager."""

    def test_init_with_single_app(self):
        manager = MultiAppManager(
            [Application(name="test_app", base=MockBaseEntity1, description="Test application")]
        )
        assert len(manager.apps) == 1
        assert "test_app" in manager.apps
        assert isinstance(manager.apps["test_app"], AppResources)

    def test_init_with_multiple_apps(self):
        manager = MultiAppManager(
            [
                Application(name="app1", base=MockBaseEntity1, description="Application 1"),
                Application(name="app2", base=MockBaseEntity2, description="Application 2"),
            ]
        )
        assert len(manager.apps) == 2
        assert "app1" in manager.apps
        assert "app2" in manager.apps

    def test_get_app_success(self):
        manager = MultiAppManager(
            [Application(name="test_app", base=MockBaseEntity1, description="Test application")]
        )
        app = manager.get_app("test_app")

        assert app.name == "test_app"
        assert app.description == "Test application"
        assert isinstance(app, AppResources)

    def test_get_app_not_found(self):
        manager = MultiAppManager(
            [Application(name="test_app", base=MockBaseEntity1, description="Test application")]
        )

        with pytest.raises(ValueError) as exc_info:
            manager.get_app("nonexistent")

        assert "App 'nonexistent' not found" in str(exc_info.value)
        assert "Available apps: ['test_app']" in str(exc_info.value)

    def test_list_apps_single(self):
        manager = MultiAppManager(
            [Application(name="test_app", base=MockBaseEntity1, description="Test application")]
        )
        assert manager.list_apps() == ["test_app"]

    def test_list_apps_multiple(self):
        manager = MultiAppManager(
            [
                Application(name="app1", base=MockBaseEntity1, description="Application 1"),
                Application(name="app2", base=MockBaseEntity2, description="Application 2"),
            ]
        )
        app_names = manager.list_apps()
        assert len(app_names) == 2
        assert "app1" in app_names
        assert "app2" in app_names

    def test_app_resources_have_handler(self):
        manager = MultiAppManager(
            [Application(name="test_app", base=MockBaseEntity1, description="Test application")]
        )
        app = manager.get_app("test_app")
        assert app.handler is not None
        assert hasattr(app.handler, "execute")

    def test_app_resources_have_tracer(self):
        manager = MultiAppManager(
            [Application(name="test_app", base=MockBaseEntity1, description="Test application")]
        )
        app = manager.get_app("test_app")
        assert app.tracer is not None
        assert hasattr(app.tracer, "list_operation_fields")

    def test_app_resources_have_sdl_generator(self):
        manager = MultiAppManager(
            [Application(name="test_app", base=MockBaseEntity1, description="Test application")]
        )
        app = manager.get_app("test_app")
        assert app.sdl_generator is not None
        assert hasattr(app.sdl_generator, "generate_operation_sdl")

    def test_app_resources_entity_names(self):
        manager = MultiAppManager(
            [Application(name="test_app", base=MockBaseEntity1, description="Test application")]
        )
        app = manager.get_app("test_app")
        entity_names = app.entity_names
        # entity_names is a set; may be empty without @query decorators (expected)
        assert isinstance(entity_names, set)

    def test_optional_description(self):
        manager = MultiAppManager([Application(name="test_app", base=MockBaseEntity1)])
        app = manager.get_app("test_app")
        assert app.description == ""

    def test_custom_descriptions(self):
        manager = MultiAppManager(
            [
                Application(
                    name="test_app",
                    base=MockBaseEntity1,
                    description="Test application",
                    query_description="Custom query description",
                    mutation_description="Custom mutation description",
                )
            ]
        )
        app = manager.get_app("test_app")
        assert app.description == "Test application"
        assert app.handler is not None

    def test_get_app_with_explicit_alias(self):
        manager = MultiAppManager(
            [
                Application(
                    name="todo",
                    base=MockBaseEntity1,
                    description="Todo application",
                    aliases=["todo_app", "todo-app"],
                )
            ]
        )

        app = manager.get_app("todo_app")
        assert app.name == "todo"
        assert app.description == "Todo application"

        app = manager.get_app("todo-app")
        assert app.name == "todo"
        assert app.description == "Todo application"

    def test_get_app_exact_match_priority(self):
        manager = MultiAppManager(
            [
                Application(
                    name="test_app",
                    base=MockBaseEntity1,
                    description="App with _app in name",
                ),
                Application(
                    name="test",
                    base=MockBaseEntity2,
                    description="App without suffix",
                    aliases=["test_alias"],
                ),
            ]
        )

        app = manager.get_app("test_app")
        assert app.name == "test_app"
        assert app.description == "App with _app in name"

    def test_get_app_requires_explicit_alias(self):
        """Implicit suffix normalization no longer happens."""
        manager = MultiAppManager(
            [Application(name="shop", base=MockBaseEntity1, description="Shop application")]
        )

        with pytest.raises(ValueError) as exc_info:
            manager.get_app("shop_app")

        assert "App 'shop_app' not found" in str(exc_info.value)

    def test_get_app_still_raises_error_for_invalid_names(self):
        manager = MultiAppManager(
            [Application(name="todo", base=MockBaseEntity1, description="Todo application")]
        )

        with pytest.raises(ValueError) as exc_info:
            manager.get_app("invalid_name")

        assert "App 'invalid_name' not found" in str(exc_info.value)
        assert "Available apps: ['todo']" in str(exc_info.value)

    # ── Cross-app validation (Application form) ───────────────────────────

    def test_duplicate_app_names_raise_error(self):
        with pytest.raises(ValueError) as exc_info:
            MultiAppManager(
                [
                    Application(name="dup", base=MockBaseEntity1),
                    Application(name="dup", base=MockBaseEntity2),
                ]
            )
        assert "Duplicate app name 'dup'" in str(exc_info.value)

    def test_empty_apps_raise_error(self):
        with pytest.raises(ValueError) as exc_info:
            MultiAppManager([])
        assert "At least one app configuration is required" in str(exc_info.value)

    def test_duplicate_aliases_raise_error(self):
        with pytest.raises(ValueError) as exc_info:
            MultiAppManager(
                [
                    Application(name="app1", base=MockBaseEntity1, aliases=["shared"]),
                    Application(name="app2", base=MockBaseEntity2, aliases=["shared"]),
                ]
            )
        assert "Alias 'shared' is already used" in str(exc_info.value)

    def test_aliases_must_be_list_of_strings(self):
        with pytest.raises(ValueError):
            Application(name="app", base=MockBaseEntity1, aliases="alias")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            Application(name="app", base=MockBaseEntity1, aliases=[""])

    # ── Legacy dict compat path (verifies deprecation behavior) ──────────

    def test_dict_form_triggers_deprecation_warning(self):
        """Passing a dict should emit DeprecationWarning but still work."""
        import warnings

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            manager = MultiAppManager([{"name": "x", "base": MockBaseEntity1}])
            assert "x" in manager.apps
            assert len(caught) == 1
            assert issubclass(caught[0].category, DeprecationWarning)

    def test_dict_missing_name_raises(self):
        with pytest.raises(ValueError, match="missing required field 'name'"):
            MultiAppManager([{"base": MockBaseEntity1}])  # type: ignore[list-item]

    def test_dict_missing_base_raises(self):
        with pytest.raises(ValueError, match="missing required field 'base'"):
            MultiAppManager([{"name": "invalid"}])  # type: ignore[list-item]
