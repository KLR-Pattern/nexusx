"""specs/016 Paged 字段声明分页(完整四参 limit/offset/order/direction + caller 覆盖)。

``Paged(...)`` 挂 ER relationship 字段(``Annotated[list[Target], Paged(...)]``),
提供默认分页参数;caller ``Resolver(context=...)`` 可逐字段覆盖。映射 PO2M 完整
分页(ROW_NUMBER BETWEEN offset+1 AND offset+limit,ORDER BY <order> <direction>)。

种子: T1 三条 comment(likes 5/3/1)。MOST_LIKED(likes desc nulls_last)=[C5,C3,C1]。
"""
from typing import Annotated, Optional

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, Relationship, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx import (
    AutoQueryConfig,
    BatchPageConfig,
    DefineSubset,
    GraphQLHandler,
    OrderTerm,
    PageOrder,
)
from nexusx.loader.pagination import Paged


class DPBase(SQLModel):
    pass


class DPComment(DPBase, table=True):
    __tablename__ = "dpp_comment"
    id: int | None = Field(default=None, primary_key=True)
    text: str
    likes: int | None = Field(default=None)
    thread_id: int = Field(foreign_key="dpp_thread.id")
    thread: Optional["DPThread"] = Relationship(back_populates="comments")


class DPThread(DPBase, table=True):
    __tablename__ = "dpp_thread"
    id: int | None = Field(default=None, primary_key=True)
    title: str
    comments: list[DPComment] = Relationship(
        back_populates="thread",
        sa_relationship_kwargs={"order_by": "DPComment.id"},
    )
    __pagination_orders__ = {
        "comments": BatchPageConfig(
            default_order="MOST_LIKED",
            orders={
                "MOST_LIKED": PageOrder([OrderTerm("likes", "desc", nulls="last")]),
            },
        ),
    }


class DPCommentDTO(DefineSubset):
    __subset__ = (DPComment, ("id", "text", "likes"))


class DPThreadDTO(DefineSubset):
    """comments 挂 Paged(limit=2, order=MOST_LIKED) 默认(ER relationship 字段)。"""

    __subset__ = (DPThread, ("id", "title"))
    comments: Annotated[list[DPCommentDTO], Paged(limit=2, order="MOST_LIKED")] = Field(
        default_factory=list
    )


_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
_sf = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
_seeded = False


async def _seed() -> None:
    global _seeded
    if _seeded:
        return
    async with _engine.begin() as c:
        await c.run_sync(SQLModel.metadata.create_all)
    async with _sf() as s:
        s.add(DPThread(id=1, title="T1"))
        s.add(DPComment(id=1, thread_id=1, text="C5", likes=5))
        s.add(DPComment(id=2, thread_id=1, text="C3", likes=3))
        s.add(DPComment(id=3, thread_id=1, text="C1", likes=1))
        await s.commit()
    _seeded = True


@pytest.fixture
async def handler() -> GraphQLHandler:
    await _seed()
    h = GraphQLHandler(
        base=DPBase,
        session_factory=_sf,
        auto_query_config=AutoQueryConfig(),
        enable_pagination=True,
    )
    await h.er.initialize()
    return h


def test_paged_stamp_at_class_creation():
    """SubsetMeta 识别 Annotated[..., Paged] → stamp __paged_fields__(完整四参)。"""
    assert hasattr(DPThreadDTO, "__paged_fields__")
    paged = DPThreadDTO.__paged_fields__["comments"]
    assert isinstance(paged, Paged)
    assert paged.limit == 2
    assert paged.order == "MOST_LIKED"
    assert paged.offset == 0
    assert paged.direction is None
    # 内层 list[DPCommentDTO] 仍是有效字段(Paged 只是 metadata)。
    assert "comments" in DPThreadDTO.model_fields


@pytest.mark.asyncio
async def test_paged_default_top_n(handler):
    """Paged(limit=2, order=MOST_LIKED) 默认 → top-2 by likes desc(无 caller context)。

    证明 Paged 提供默认:不传 context 也能分页(不像 context-only 版要 caller 传)。
    """
    ResolverCls = handler._er_manager.create_resolver()
    resolver = ResolverCls()  # 无 context
    resolved = await resolver.resolve([DPThreadDTO(id=1, title="T1")])

    comments = resolved[0].comments
    assert len(comments) == 2  # top-N(Paged 默认 limit=2)
    assert [c.text for c in comments] == ["C5", "C3"]  # likes desc: 5, 3


@pytest.mark.asyncio
async def test_caller_overrides_paged_default(handler):
    """caller context {limit:1} 覆盖 Paged 默认 limit=2 → top-1。

    Paged 默认 limit=2,caller 传 limit=1 → merged limit=1(caller 赢)。
    static-ness 解:Paged 是默认,caller 可覆盖。
    """
    ResolverCls = handler._er_manager.create_resolver()
    resolver = ResolverCls(context={"limit": 1})
    resolved = await resolver.resolve([DPThreadDTO(id=1, title="T1")])
    assert [c.text for c in resolved[0].comments] == ["C5"]  # top-1


@pytest.mark.asyncio
async def test_paged_offset_second_page(handler):
    """caller context {offset:1} → 第 2 页(merged offset=1 覆盖 Paged 默认 0)。

    MOST_LIKED 全序 [C5,C3,C1];offset=1 limit=2 → rn BETWEEN 2 AND 3 → [C3,C1]。
    """
    ResolverCls = handler._er_manager.create_resolver()
    resolver = ResolverCls(context={"offset": 1})
    resolved = await resolver.resolve([DPThreadDTO(id=1, title="T1")])
    assert [c.text for c in resolved[0].comments] == ["C3", "C1"]


@pytest.mark.asyncio
async def test_paged_order_none_uses_entity_default(handler):
    """Paged(order=None) + caller 不传 → 用 entity default_order(MOST_LIKED)。"""

    class _DTO(DefineSubset):
        __subset__ = (DPThread, ("id", "title"))
        comments: Annotated[list[DPCommentDTO], Paged(limit=2)] = Field(
            default_factory=list
        )

    ResolverCls = handler._er_manager.create_resolver()
    resolver = ResolverCls()
    resolved = await resolver.resolve([_DTO(id=1, title="T1")])
    assert [c.text for c in resolved[0].comments] == ["C5", "C3"]  # entity default


@pytest.mark.asyncio
async def test_paged_multi_parent_batch(handler):
    """多 parent batch(各 top-N per-parent ROW_NUMBER 独立)。"""
    async with _sf() as s:
        s.add(DPThread(id=2, title="T2"))
        s.add(DPComment(id=4, thread_id=2, text="C4", likes=4))
        s.add(DPComment(id=5, thread_id=2, text="C2", likes=2))
        await s.commit()

    ResolverCls = handler._er_manager.create_resolver()
    resolver = ResolverCls()
    resolved = await resolver.resolve([
        DPThreadDTO(id=1, title="T1"), DPThreadDTO(id=2, title="T2"),
    ])
    by_id = {t.id: t for t in resolved}
    assert [c.text for c in by_id[1].comments] == ["C5", "C3"]
    assert [c.text for c in by_id[2].comments] == ["C4", "C2"]


@pytest.mark.asyncio
async def test_caller_only_no_paged_default(handler):
    """DTO 无 Paged + caller context → caller 驱动(back-compat,Paged default None)。

    没有 Paged 默认时,caller context 单独驱动分页(merged = merge(None, caller) = caller)。
    """
    class _DTO(DefineSubset):
        __subset__ = (DPThread, ("id", "title"))
        comments: list[DPCommentDTO] = Field(default_factory=list)  # 无 Paged

    ResolverCls = handler._er_manager.create_resolver()
    resolver = ResolverCls(context={"limit": 1, "order": "MOST_LIKED"})
    resolved = await resolver.resolve([_DTO(id=1, title="T1")])
    assert [c.text for c in resolved[0].comments] == ["C5"]  # caller limit=1
