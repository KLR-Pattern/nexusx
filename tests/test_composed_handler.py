"""US3: GraphQLHandler / Application 的 er_manager 注入（specs/019 阶段2）。

验证 entity-first 路径能注入 ComposedErManager：
- GraphQLHandler(er_manager=composed, entities=[...])：一个 schema 暴露多 engine @query
- Application(er_manager=composed)：透传 handler
- 关系解析走 composed.create_resolver()（US1/US5 已验证，此处聚焦 handler 注入与 SDL）
- 现有 base= 路径零回归（非 breaking）

@query 方法用静态返回（不查 db），聚焦注入路径正确性而非数据访问。
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx import ComposedErManager, ErManager, GraphQLHandler, query
from nexusx.loader import LoaderRegistry
from nexusx.mcp import Application


# ── 实体（Ch 前缀，带静态 @query，不查 db）──

class ChUser(SQLModel, table=True):
    __tablename__ = "ch_handler_user"
    id: int | None = Field(default=None, primary_key=True)
    name: str

    @query
    async def get_users(cls, limit: int = 10):
        """Get users."""
        return [cls(id=1, name="Alice"), cls(id=2, name="Bob")]


class ChOrder(SQLModel, table=True):
    __tablename__ = "ch_handler_order"
    id: int | None = Field(default=None, primary_key=True)
    total: float

    @query
    async def get_orders(cls, limit: int = 10):
        """Get orders."""
        return [cls(id=1, total=9.9)]


class _Base(SQLModel):
    """base 路径回归用 base。"""
    pass


class _BaseEntity(_Base, table=True):
    __tablename__ = "ch_handler_base_entity"
    id: int | None = Field(default=None, primary_key=True)
    name: str


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as c:
        await c.run_sync(SQLModel.metadata.create_all)
    yield sf
    await engine.dispose()


# ── GraphQLHandler 注入 ──

async def test_handler_er_manager_injection(session_factory):
    """GraphQLHandler(er_manager=composed) 注入：er 是组合体 + SDL 含多 engine @query。"""
    blog_er = ErManager(session_factory=session_factory, entities=[ChUser])
    shop_er = ErManager(session_factory=session_factory, entities=[ChOrder])
    composed = ComposedErManager(members=[blog_er, shop_er])

    handler = GraphQLHandler(er_manager=composed, entities=[ChUser, ChOrder])

    # handler.er 是注入的组合体（LoaderRegistry）
    assert isinstance(handler.er, LoaderRegistry)
    assert handler.er is composed
    # entities 是合并集
    assert {ChUser, ChOrder} <= set(handler.entities)
    # SDL 同时含两个 engine 的 @query group
    sdl = handler.get_sdl()
    assert "ChUser" in sdl and "ChOrder" in sdl
    assert "getUsers" in sdl or "get_users" in sdl.lower().replace(" ", "")


async def test_handler_er_manager_and_base_mutually_exclusive(session_factory):
    """er_manager 与 base 互斥（FR-009）。"""
    blog_er = ErManager(session_factory=session_factory, entities=[ChUser])
    composed = ComposedErManager(members=[blog_er])
    with pytest.raises(ValueError, match="at most one of: base, er_manager"):
        GraphQLHandler(base=_Base, er_manager=composed, entities=[ChUser])


async def test_handler_er_manager_rejects_auto_query_config(session_factory):
    """注入路径不支持 auto_query_config（FR-012 多 engine session 归属）。"""
    from nexusx import AutoQueryConfig

    blog_er = ErManager(session_factory=session_factory, entities=[ChUser])
    composed = ComposedErManager(members=[blog_er])
    with pytest.raises(ValueError, match="auto_query_config is not supported"):
        GraphQLHandler(
            er_manager=composed,
            entities=[ChUser],
            session_factory=session_factory,  # 让 auto_query_config 的 session_factory 校验先过
            auto_query_config=AutoQueryConfig(),
        )


async def test_handler_er_management_interface_unavailable(session_factory):
    """注入路径下 handler.er 是组合体，federation 管理接口不可用（FR-013 语义边界）。"""
    blog_er = ErManager(session_factory=session_factory, entities=[ChUser])
    composed = ComposedErManager(members=[blog_er])
    handler = GraphQLHandler(er_manager=composed, entities=[ChUser])
    # 组合体无管理接口（在子 member 上做）
    assert not hasattr(handler.er, "initialize")
    assert not hasattr(handler.er, "federate")


async def test_handler_base_path_regression(session_factory):
    """现有 base= 单 base 路径零回归（非 breaking）。"""
    handler = GraphQLHandler(base=_Base, session_factory=session_factory)
    assert handler.er is not None
    assert hasattr(handler.er, "initialize")  # base 路径 er 是 ErManager，有管理接口


# ── Application 注入 ──

async def test_application_er_manager_injection(session_factory):
    """Application(er_manager=composed) 透传 GraphQLHandler。"""
    blog_er = ErManager(session_factory=session_factory, entities=[ChUser])
    shop_er = ErManager(session_factory=session_factory, entities=[ChOrder])
    composed = ComposedErManager(members=[blog_er, shop_er])

    app = Application(
        name="composed-app",
        er_manager=composed,
        entities=[ChUser, ChOrder],
        description="multi-engine app",
    )
    assert app.name == "composed-app"
    # handler.er 是组合体
    assert isinstance(app.resources.handler.er, LoaderRegistry)
    assert app.resources.handler.er is composed


async def test_application_er_manager_and_base_mutually_exclusive(session_factory):
    """Application: er_manager 与 base 互斥。"""
    blog_er = ErManager(session_factory=session_factory, entities=[ChUser])
    composed = ComposedErManager(members=[blog_er])
    with pytest.raises(ValueError, match="at most one of: base, er_manager"):
        Application(name="x", base=_Base, er_manager=composed, entities=[ChUser])


async def test_application_er_manager_rejects_connection_args(session_factory):
    """Application: er_manager 与 url/engine/session_factory 互斥（registry 自带 session）。"""
    blog_er = ErManager(session_factory=session_factory, entities=[ChUser])
    composed = ComposedErManager(members=[blog_er])
    with pytest.raises(ValueError, match="mutually exclusive"):
        Application(
            name="x", er_manager=composed, entities=[ChUser],
            url="sqlite+aiosqlite:///:memory:",
        )


async def test_application_base_path_regression(session_factory):
    """Application 现有 base= 路径零回归。"""
    app = Application(
        name="base-app",
        base=_Base,
        url="sqlite+aiosqlite:///:memory:",
    )
    assert app.name == "base-app"
    assert app.owns_engine is True  # url= 自造 engine 拥有
    await app.dispose()
