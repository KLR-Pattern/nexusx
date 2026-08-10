"""Self-contained :class:`Application` —— nexusx mcp 的最小可导出单元。

一个 :class:`Application` 封装 SQLModel 业务模型 + 数据库连接信息 + GraphQL 元数据，
可作为独立 Python 包导出，再由合并项目组装到 ``create_multi_app_mcp_server(apps=[...])``。

详见 ``specs/009-app-self-contained/``（spec、plan、contracts、quickstart）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from nexusx.handler import GraphQLHandler
from nexusx.mcp.builders.type_tracer import TypeTracer
from nexusx.mcp.managers.app_resources import AppResources

if TYPE_CHECKING:
    from sqlmodel import SQLModel

    from nexusx.standard_queries import AutoQueryConfig


def _redact_url(url: str) -> str:
    """把 URL 中的密码字段替换为 ``***``，用于日志/错误消息/``__repr__``。

    若 URL 不含密码或解析失败，原样返回。
    """
    if not url:
        return url
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return url


class Application:
    """自包含的 GraphQL 业务应用 —— nexusx mcp 中可独立导出、可合并的最小单元。

    封装：

    - SQLModel ``base`` 类（业务模型）
    - 数据库连接信息（``url`` / ``engine`` / ``session_factory`` 三选一，或全缺）
    - GraphQL 元数据（``description`` 等）

    构造完全同步，``AppResources`` 在 ``__init__`` 期 eager 填充。
    仅 ``dispose()`` 是异步。``dispose()`` 幂等。

    资源所有权按来源判定：

    - ``url=`` 自造 engine → 拥有，``dispose()`` 释放
    - ``engine=`` / ``session_factory=`` 外部资源 → 不拥有，``dispose()`` no-op
    """

    def __init__(
        self,
        *,
        name: str,
        base: type[SQLModel] | None = None,
        url: str | None = None,
        engine: AsyncEngine | None = None,
        session_factory: Callable[..., Any] | None = None,
        description: str = "",
        query_description: str | None = None,
        mutation_description: str | None = None,
        aliases: list[str] | None = None,
        engine_kwargs: dict[str, Any] | None = None,
        enable_pagination: bool = False,
        auto_query_config: AutoQueryConfig | None = None,
        er_manager: Any = None,
        entities: list[type] | None = None,
    ) -> None:
        # ── 必填字段 ────────────────────────────────────────────────────
        if not name or not isinstance(name, str):
            raise ValueError("'name' must be a non-empty string")
        self._name = name
        self._base = base
        self._er_manager = er_manager  # specs/019 US3 注入路径
        self._entities = entities

        # ── base / er_manager 互斥（specs/019 US3）─────────────────────
        if er_manager is not None and base is not None:
            raise ValueError("Provide at most one of: base, er_manager")
        if er_manager is None and base is None:
            raise ValueError("Application requires either base= or er_manager=")
        if er_manager is not None and (url or engine or session_factory):
            raise ValueError(
                "er_manager injection is mutually exclusive with "
                "url/engine/session_factory (the registry carries its own sessions)"
            )

        # ── 资源所有权判定 ──────────────────────────────────────────────
        self._owns_engine = False
        self._engine: AsyncEngine | None = None
        self._session_factory: Callable[..., Any] | None = None
        self._url_for_repr: str | None = None

        if er_manager is not None:
            # 注入路径：不构造连接（er_manager 自带 session）；资源所有权由各子 member 自管
            pass
        else:
            # ── 连接信息互斥校验（至多一个） ────────────────────────────────
            provided = sum(1 for x in (url, engine, session_factory) if x is not None)
            if provided > 1:
                raise ValueError(
                    "Provide at most one of: url, engine, session_factory"
                )
            if url is not None:
                kwargs = {"echo": False}
                if engine_kwargs:
                    kwargs.update(engine_kwargs)
                self._engine = create_async_engine(url, **kwargs)
                self._session_factory = async_sessionmaker(
                    self._engine,
                    class_=AsyncSession,
                    expire_on_commit=False,
                )
                self._owns_engine = True
                self._url_for_repr = _redact_url(url)
            elif engine is not None:
                self._engine = engine
                self._session_factory = async_sessionmaker(
                    engine,
                    class_=AsyncSession,
                    expire_on_commit=False,
                )
                self._url_for_repr = _redact_url(str(engine.url))
            elif session_factory is not None:
                self._session_factory = session_factory
                self._url_for_repr = None

        # ── 元数据 ──────────────────────────────────────────────────────
        self._description = description or ""
        self._query_description = query_description
        self._mutation_description = mutation_description
        self._aliases: list[str] = self._validate_aliases(aliases, name)
        self._enable_pagination = enable_pagination
        self._auto_query_config = auto_query_config

        # ── eager 构造 AppResources（全同步） ───────────────────────────
        self._resources = self._build_resources()
        self._disposed = False

    # ── 公共属性 ─────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def aliases(self) -> list[str]:
        return list(self._aliases)

    @property
    def resources(self) -> AppResources:
        return self._resources

    @property
    def session_factory(self) -> Callable[..., Any] | None:
        return self._session_factory

    @property
    def owns_engine(self) -> bool:
        """是否拥有 engine（仅当通过 ``url=`` 自造时为 True）。"""
        return self._owns_engine

    @property
    def disposed(self) -> bool:
        return self._disposed

    # ── 异步生命周期 ─────────────────────────────────────────────────────

    async def dispose(self) -> None:
        """释放自身拥有的 engine。幂等。

        - 若 ``owns_engine=True`` 且未 disposed：``await engine.dispose()``，置 disposed
        - 若 ``owns_engine=False``：no-op（外部 engine/session_factory 不释放）
        - 若已 disposed：no-op
        """
        if self._disposed:
            return
        if self._owns_engine and self._engine is not None:
            try:
                await self._engine.dispose()
            finally:
                self._engine = None
        self._disposed = True

    async def __aenter__(self) -> Application:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.dispose()

    def __repr__(self) -> str:
        url_part = f", url={self._url_for_repr!r}" if self._url_for_repr else ""
        owns = ", owned=True" if self._owns_engine else ""
        base_name = self._base.__name__ if self._base is not None else "<injected>"
        return (
            f"Application(name={self._name!r}, base={base_name}"
            f"{url_part}{owns})"
        )

    # ── 内部辅助 ─────────────────────────────────────────────────────────

    @staticmethod
    def _validate_aliases(aliases: list[str] | None, name: str) -> list[str]:
        if aliases is None:
            return []
        if not isinstance(aliases, list):
            raise ValueError(
                f"App '{name}' aliases must be a list of strings"
            )
        normalized: list[str] = []
        for alias in aliases:
            if not isinstance(alias, str) or not alias:
                raise ValueError(
                    f"App '{name}' aliases must contain only non-empty strings"
                )
            if alias == name:
                raise ValueError(
                    f"App '{name}' alias '{alias}' conflicts with own name"
                )
            normalized.append(alias)
        return normalized

    def _build_resources(self) -> AppResources:
        handler = GraphQLHandler(
            base=self._base,
            er_manager=self._er_manager,
            entities=self._entities,
            session_factory=self._session_factory,
            query_description=self._query_description,
            mutation_description=self._mutation_description,
            enable_pagination=self._enable_pagination,
            auto_query_config=self._auto_query_config,
        )
        introspection_data = handler.get_introspection_data()
        entity_names = {e.__name__ for e in handler.entities}
        tracer = TypeTracer(introspection_data, entity_names)
        return AppResources(
            name=self._name,
            description=self._description,
            handler=handler,
            tracer=tracer,
            sdl_generator=handler.get_sdl_generator(),
        )


def _coerce_to_application(app: Application, index: int = 0) -> Application:
    """Validate ``app`` is an :class:`Application` (dict form removed)."""
    if not isinstance(app, Application):
        raise TypeError(
            f"App at index {index} must be an Application instance, "
            f"got {type(app).__name__}"
        )
    return app


@asynccontextmanager
async def lifespan_dispose_hook(manager: Any) -> AsyncIterator[None]:
    """为 :class:`MultiAppManager` 提供的 FastMCP lifespan 钩子。

    进入时无操作（资源已在 ``__init__`` eager 构造），退出时调 ``await manager.dispose()``。
    """
    try:
        yield
    finally:
        await manager.dispose()
