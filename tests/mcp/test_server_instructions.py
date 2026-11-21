"""Server ``instructions`` — the agent's first read (MCP initialize field).

Locks the pass-through on all three server surfaces: the value must ride the
initialize handshake (read back via the era-neutral ``client.instructions``),
and ``None`` (default) must send nothing.
"""

from __future__ import annotations

from pydantic import BaseModel

from fastmcp import Client

from nexusx import query
from nexusx.decorator import mutation
from nexusx.mcp import Application
from nexusx.mcp.server import (
    PAGINATION_CONTRACT_NOTE,
    create_multi_app_mcp_server,
    create_single_app_mcp_server,
)
from nexusx.use_case.business import UseCaseService
from nexusx.use_case.compose_mcp_server import create_use_case_graphql_mcp_server
from nexusx.use_case.types import UseCaseAppConfig

_GUIDE = "One shared tree. get_tree reads the outline; apply_outline writes."


# ── fixtures（最小可构建的 app/service，见 test_tool_annotations 同款）──


try:
    from sqlmodel import Field, SQLModel

    # 非表基类（Application(base=…) 的约定入参：管理器从基类下扫描实体，
    # 见 test_tool_annotations 同款结构）
    class _InstBase(SQLModel):
        pass

    class _InstEntity(_InstBase, table=True):
        __tablename__ = "inst_entity"
        __test__ = False

        id: int | None = Field(default=None, primary_key=True)

        @query
        async def get_all(cls) -> list["_InstEntity"]:
            return []

        @mutation
        async def create(cls) -> "_InstEntity":
            return _InstEntity(id=1)

    _HAS_SQLMODEL = True
except Exception:  # pragma: no cover — sqlmodel always present in this repo
    _HAS_SQLMODEL = False


# 分页面 fixture 独立成模块：关系注解必须保持可求值（无 future annotations，
# 见 test_local_pagination_order.py 同款），与本文件的 PEP 563 头互斥
try:
    from tests.mcp._note_entities import NoteBase as _NoteBase

    _HAS_NOTE = True
except Exception:  # pragma: no cover — sqlmodel always present in this repo
    _HAS_NOTE = False


class _InstItem(BaseModel):
    id: int


class _InstService(UseCaseService):
    @query
    async def list_items(cls) -> list[_InstItem]:
        return [_InstItem(id=1)]


def _compose(instructions: str | None):
    return create_use_case_graphql_mcp_server(
        apps=[UseCaseAppConfig(name="inst", services=[_InstService])],
        name="inst-compose",
        instructions=instructions,
    )


class TestInstructionsPassThrough:
    async def test_compose_surface_sends_instructions(self):
        async with Client(_compose(_GUIDE)) as c:
            assert c.instructions == _GUIDE

    async def test_compose_surface_default_sends_nothing(self):
        async with Client(_compose(None)) as c:
            assert c.instructions is None

    async def test_multi_app_surface_sends_instructions(self):
        if not _HAS_SQLMODEL:  # pragma: no cover
            return
        mcp = create_multi_app_mcp_server(
            apps=[Application(name="inst-app", base=_InstBase)],
            name="inst-multi",
            instructions=_GUIDE,
        )
        async with Client(mcp) as c:
            assert c.instructions == _GUIDE

    async def test_single_app_surface_sends_instructions(self):
        if not _HAS_SQLMODEL:  # pragma: no cover
            return
        mcp = create_single_app_mcp_server(
            _InstBase,
            name="inst-single",
            instructions=_GUIDE,
        )
        async with Client(mcp) as c:
            assert c.instructions == _GUIDE


class TestPaginationContractNote:
    """Auto-append semantics (2026-11 contract): the note rides instructions
    exactly once when the schema paginates — global layer, so tool
    descriptions don't repeat the prose."""

    async def test_auto_appended_when_schema_paginates(self):
        if not _HAS_NOTE:  # pragma: no cover
            return
        mcp = create_single_app_mcp_server(_NoteBase, name="note-single")
        async with Client(mcp) as c:
            assert c.instructions == PAGINATION_CONTRACT_NOTE

    async def test_not_appended_without_paginated_fields(self):
        if not _HAS_SQLMODEL:  # pragma: no cover
            return
        mcp = create_single_app_mcp_server(_InstBase, name="plain-single")
        async with Client(mcp) as c:
            assert c.instructions is None

    async def test_custom_instructions_come_first(self):
        if not _HAS_NOTE:  # pragma: no cover
            return
        mcp = create_single_app_mcp_server(
            _NoteBase, name="note-merged", instructions=_GUIDE
        )
        async with Client(mcp) as c:
            assert c.instructions == f"{_GUIDE}\n\n{PAGINATION_CONTRACT_NOTE}"

    async def test_verbatim_caller_copy_not_duplicated(self):
        if not _HAS_NOTE:  # pragma: no cover
            return
        mcp = create_single_app_mcp_server(
            _NoteBase,
            name="note-dedup",
            instructions=f"{_GUIDE}\n\n{PAGINATION_CONTRACT_NOTE}",
        )
        async with Client(mcp) as c:
            assert c.instructions.count(PAGINATION_CONTRACT_NOTE) == 1
            assert c.instructions.startswith(_GUIDE)

    async def test_multi_app_appends_when_any_app_paginates(self):
        if not _HAS_NOTE:  # pragma: no cover
            return
        mcp = create_multi_app_mcp_server(
            apps=[
                Application(name="plain", base=_InstBase),
                Application(name="paged", base=_NoteBase),
            ],
            name="note-multi",
        )
        async with Client(mcp) as c:
            assert PAGINATION_CONTRACT_NOTE in (c.instructions or "")

    async def test_multi_app_plain_apps_send_nothing(self):
        if not _HAS_SQLMODEL:  # pragma: no cover
            return
        mcp = create_multi_app_mcp_server(
            apps=[Application(name="plain", base=_InstBase)],
            name="plain-multi",
        )
        async with Client(mcp) as c:
            assert c.instructions is None
