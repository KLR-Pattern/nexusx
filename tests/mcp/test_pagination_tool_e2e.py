"""MCP 工具层的分页契约 E2E（in-memory，源自 2026-11 手工 14 点验证的沉淀子集）.

覆盖工具层空白：graphql_query 工具 × 分页行为（窗口 / fetchAll 覆盖 / 无意图
错误信封），以及 multi-app 自有会话下的关系查询——后者的行为级锁定
（Application 拥有的 session 必须支持 .exec）正是当年只靠 hasattr 测试
漏掉、由手工 E2E 抓出的路径。HTTP/uvicorn 不在此文件：transport 是
FastMCP 的契约，内存 Client 已走到同一工具代码。

⚠️ 已知库限制（绕开而非修复，见记忆「关系变体重构计划/实施-参数契约」）：
``add_standard_queries`` 把生成的 by_id/by_filter **setattr 到实体类上**并闭包
捕获第一个 handler 的 session_factory，``not hasattr`` 守卫使后续 handler 跳过
生成——同一 base 在同进程内构建第二个 handler（不同 DB）时查询仍路由到第一个
工厂。因此本文件：
- PE* 实体（单 app 面）只建 **一个** handler（module 级 fixture）；
- multi-app 面用独立的 PM* 实体，与 PE* 零共享。
"""

import json
from typing import Optional

import pytest
from fastmcp import Client
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, Relationship, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx.mcp import Application
from nexusx.mcp.server import (
    PAGINATION_CONTRACT_NOTE,
    create_multi_app_mcp_server,
    create_single_app_mcp_server,
)
from nexusx.standard_queries import AutoQueryConfig

# 本文件不得加 from __future__ import annotations：关系注解需保持可求值
# （见 tests/mcp/_note_entities.py 头注）。


class PEBase(SQLModel):
    """非表基类；实体零手写方法——by_filter/by_id 由 AutoQueryConfig 生成。"""


class PEChild(PEBase, table=True):
    __tablename__ = "pe_child"
    __test__ = False

    id: int | None = Field(default=None, primary_key=True)
    parent_id: int = Field(foreign_key="pe_parent.id")
    parent: Optional["PEParent"] = Relationship(back_populates="children")


class PEParent(PEBase, table=True):
    __tablename__ = "pe_parent"
    __test__ = False

    id: int | None = Field(default=None, primary_key=True)
    # order_by 声明 → children 渲染为 Result-wrapped 分页字段（契约的靶子）
    children: list[PEChild] = Relationship(
        back_populates="parent",
        sa_relationship_kwargs={"order_by": "PEChild.id"},
    )


class PMBase(SQLModel):
    """multi-app 面专用基类——与 PE* 完全独立（见模块头注的绕开理由）。"""


class PMChild(PMBase, table=True):
    __tablename__ = "pm_child"
    __test__ = False

    id: int | None = Field(default=None, primary_key=True)
    parent_id: int = Field(foreign_key="pm_parent.id")
    parent: Optional["PMParent"] = Relationship(back_populates="children")


class PMParent(PMBase, table=True):
    __tablename__ = "pm_parent"
    __test__ = False

    id: int | None = Field(default=None, primary_key=True)
    children: list[PMChild] = Relationship(
        back_populates="parent",
        sa_relationship_kwargs={"order_by": "PMChild.id"},
    )


_WINDOW_FMT = (
    "{{ {root} {{ by_filter {{ id children(limit: 3) "
    "{{ items {{ id }} pagination {{ has_more total_count }} }} }} }} "
    "}}"
)
_OVERRIDE_FMT = (
    "{{ {root} {{ by_filter {{ id children(limit: 1, fetchAll: true) "
    "{{ items {{ id }} pagination {{ has_more total_count }} }} }} }} "
    "}}"
)
_NO_INTENT_FMT = "{{ {root} {{ by_filter {{ id children {{ items {{ id }} }} }} }} }}"


def _window(root: str) -> str:
    return _WINDOW_FMT.format(root=root)


def _override(root: str) -> str:
    return _OVERRIDE_FMT.format(root=root)


def _no_intent(root: str) -> str:
    return _NO_INTENT_FMT.format(root=root)


async def _seed(factory, parent_cls, child_cls) -> None:
    async with factory() as session:
        parent = parent_cls()
        session.add(parent)
        await session.flush()
        session.add_all([child_cls(parent_id=parent.id) for _ in range(10)])
        await session.commit()


def _query_result(res) -> dict:
    return json.loads(res.content[0].text)


async def _make_factory(url: str):
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="module")
async def pe_server():
    """单 app 面：每 base 只建一个 handler（库限制，见模块头注）。

    引擎与工厂 module 级存活；:memory: + aiosqlite 自动 StaticPool，
    单连接内建表持久（与 tests/conftest.py 同款）。
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await _seed(factory, PEParent, PEChild)
    mcp = create_single_app_mcp_server(
        PEBase,
        name="pe-single",
        session_factory=factory,
        auto_query_config=AutoQueryConfig(),
    )
    yield mcp
    await engine.dispose()


class TestGraphqlQueryToolPagination:
    """graphql_query 工具 × 分页契约（工具信封下的行为不变）。"""

    async def test_limit_window(self, pe_server):
        async with Client(pe_server) as c:
            r = _query_result(
                await c.call_tool("graphql_query", {"query": _window("PEParent")})
            )
            children = r["data"]["PEParent"]["by_filter"][0]["children"]
            assert len(children["items"]) == 3
            assert children["pagination"] == {"has_more": True, "total_count": 10}

    async def test_fetch_all_overrides_limit(self, pe_server):
        async with Client(pe_server) as c:
            r = _query_result(
                await c.call_tool("graphql_query", {"query": _override("PEParent")})
            )
            children = r["data"]["PEParent"]["by_filter"][0]["children"]
            assert len(children["items"]) == 10
            assert children["pagination"] == {"has_more": False, "total_count": 10}

    async def test_no_intent_error_envelope_carries_guidance(self, pe_server):
        async with Client(pe_server) as c:
            r = _query_result(
                await c.call_tool("graphql_query", {"query": _no_intent("PEParent")})
            )
            # 优雅错误：工具信封 success=False + 指引文本存活（Agent 一轮自愈）
            assert r["success"] is False
            assert "pagination intent is required" in r["error"]
            assert "fetchAll" in r["error"]

    async def test_get_schema_tool_sdl_carries_volume_args(self, pe_server):
        async with Client(pe_server) as c:
            r = _query_result(await c.call_tool("get_schema", {}))
            assert (
                "(limit: Int, offset: Int = 0, fetchAll: Boolean)"
                in r["data"]["sdl"]
            )

    async def test_instructions_riding_initialize(self, pe_server):
        async with Client(pe_server) as c:
            assert (c.instructions or "").startswith(PAGINATION_CONTRACT_NOTE)


class TestMultiAppOwnedSessionRelationshipQuery:
    """multi-app 自有会话 × 关系查询——session 类 bug 的行为级锁定。

    Application(url=) 自建 session 工厂（sqlmodel AsyncSession）；关系加载走
    session.exec。类级回归在 test_application.py，这里是整条路径的行为证明。
    用独立 PM* 实体：Application 也会向基类 setattr 标准查询（同 PE* 会撞上
    模块头注的库限制）。
    """

    async def test_relationship_query_through_owned_session(self, tmp_path):
        app = Application(
            name="pm",
            base=PMBase,
            url=f"sqlite+aiosqlite:///{tmp_path}/pm_multi.db",
            auto_query_config=AutoQueryConfig(),
        )
        try:
            async with app._engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.create_all)
            await _seed(app._session_factory, PMParent, PMChild)

            mcp = create_multi_app_mcp_server(apps=[app], name="pm-multi")
            async with Client(mcp) as c:
                assert (c.instructions or "").startswith(PAGINATION_CONTRACT_NOTE)
                r = _query_result(await c.call_tool("graphql_query", {
                    "app_name": "pm",
                    "query": _window("PMParent"),
                }))
                children = r["data"]["PMParent"]["by_filter"][0]["children"]
                assert len(children["items"]) == 3
                assert children["pagination"]["total_count"] == 10
        finally:
            await app.dispose()
