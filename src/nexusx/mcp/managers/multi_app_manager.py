"""Multi-application manager for MCP support."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexusx.mcp.managers.app_resources import AppResources

if TYPE_CHECKING:
    from nexusx.mcp.application import Application


class MultiAppManager:
    """Manages multiple GraphQL applications in a single MCP server.

    This class is responsible for:
    - Initializing and storing resources for each application
    - Routing tool calls to the correct application
    - Providing app discovery functionality

    Accepts either :class:`Application` objects (preferred) or legacy
    ``AppConfig`` dicts (deprecated, triggers ``DeprecationWarning``).
    """

    def __init__(self, apps: list[Application | dict[str, Any]]):
        """Initialize the multi-app manager.

        Args:
            apps: List of :class:`Application` objects, or legacy ``AppConfig``
                dicts (deprecated).

        Example:
            ```python
            from nexusx.mcp import Application, MultiAppManager

            apps = [
                Application(name="blog", base=BlogBaseEntity, url=BLOG_DATABASE_URL),
                Application(name="shop", base=ShopBaseEntity, url=SHOP_DATABASE_URL),
            ]
            manager = MultiAppManager(apps)
            ```
        """
        if not apps:
            raise ValueError("At least one app configuration is required")

        # Lazy import to avoid circular dependency
        # (application.py imports managers.app_resources via this package's __init__).
        from nexusx.mcp.application import Application as _Application
        from nexusx.mcp.application import _coerce_to_application

        # Coerce each element to Application (dict → Application + DeprecationWarning)
        coerced: list[_Application] = [
            _coerce_to_application(app, index=i) for i, app in enumerate(apps)
        ]

        # Cross-app validation (unique names, alias collisions)
        self._validate_cross_app(coerced)

        self._applications: list[_Application] = coerced
        self.apps: dict[str, AppResources] = {}
        self.aliases: dict[str, str] = {}

        for app in coerced:
            self.apps[app.name] = app.resources
            for alias in app.aliases:
                self.aliases[alias] = app.name

    @staticmethod
    def _validate_cross_app(applications: list[Application]) -> None:
        """Validate unique names and aliases across all apps."""
        seen_names: set[str] = set()
        seen_aliases: set[str] = set()

        for app in applications:
            name = app.name
            if name in seen_names:
                raise ValueError(
                    f"Duplicate app name '{name}' is not allowed"
                )
            seen_names.add(name)

            for alias in app.aliases:
                if alias in seen_names or alias in seen_aliases:
                    raise ValueError(
                        f"Alias '{alias}' is already used by another app"
                    )
                seen_aliases.add(alias)

    async def dispose(self) -> None:
        """Dispose all owned resources held by managed applications.

        Idempotent: each Application.dispose() is itself idempotent, so calling
        this multiple times is safe.
        """
        for app in self._applications:
            await app.dispose()

    async def __aenter__(self) -> MultiAppManager:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.dispose()

    def get_app(self, name: str) -> AppResources:
        """Get resources for a specific application.

        Args:
            name: Application name (required)

        Returns:
            AppResources for the specified application

        Raises:
            ValueError: If application name is not found

        Example:
            ```python
            app = manager.get_app("blog")
            queries = app.tracer.list_group_operations("Query")
            ```
        """
        if name in self.apps:
            return self.apps[name]

        if name in self.aliases:
            return self.apps[self.aliases[name]]

        available = list(self.apps.keys())
        if self.aliases:
            available += [f"alias:{alias}" for alias in self.aliases]
        raise ValueError(
            f"App '{name}' not found. Available apps: {available}"
        )

    def list_apps(self) -> list[str]:
        """List all available application names.

        Returns:
            List of application names

        Example:
            ```python
            app_names = manager.list_apps()
            # ["blog", "shop"]
            ```
        """
        return list(self.apps.keys())
