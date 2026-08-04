"""specs/016 γ+local: DefineSubset 字段 ``Annotated[..., Paged(...)]`` top-N。

DTO 字段引用 source entity 的 ``__pagination_orders__`` page_loader(specs/015),
Resolver(Core API 路径,非 β gql)检测 ``__paged_fields__`` → 路由 ``page_loader``
→ 构造 ``PageLoadCommand(limit, order)`` → per-parent top-N。

种子: T1 三条 comment,likes 5/3/None → MOST_LIKED desc nulls_last = [C1,C2,C3]。
Paged(limit=2) → top-2 = [C1,C2](C3 NULL 排末,被 limit 切掉)。
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
    __tablename__ = "dp_comment"
    id: int | None = Field(default=None, primary_key=True)
    text: str
    likes: int | None = Field(default=None)  # nullable → MOST_LIKED 用 nulls
    thread_id: int = Field(foreign_key="dp_thread.id")
    thread: Optional["DPThread"] = Relationship(back_populates="comments")


class DPThread(DPBase, table=True):
    __tablename__ = "dp_thread"
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
    """comments 字段声明 top-N:Paged(limit=2, default_order=MOST_LIKED)。"""

    __subset__ = (DPThread, ("id", "title"))
    comments: Annotated[list[DPCommentDTO], Paged(limit=2, default_order="MOST_LIKED")] = Field(
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
        s.add(DPComment(id=1, thread_id=1, text="C1", likes=5))
        s.add(DPComment(id=2, thread_id=1, text="C2", likes=3))
        s.add(DPComment(id=3, thread_id=1, text="C3", likes=None))
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


def test_paged_marker_stamped_at_class_creation():
    """SubsetMeta 识别 Annotated[..., Paged] → stamp __paged_fields__。"""
    assert hasattr(DPThreadDTO, "__paged_fields__")
    paged = DPThreadDTO.__paged_fields__["comments"]
    assert isinstance(paged, Paged)
    assert paged.limit == 2
    assert paged.default_order == "MOST_LIKED"
    # 内层 list[DPCommentDTO] 仍是有效字段(Paged 只是 metadata,未占位)。
    assert "comments" in DPThreadDTO.model_fields


@pytest.mark.asyncio
async def test_dto_paged_field_top_n_slice(handler):
    """Paged(limit=2) → resolve 后 comments 只 2 条 + 按 MOST_LIKED desc。

    MOST_LIKED(likes desc nulls_last) 全序 = [C1(5), C2(3), C3(None)];
    limit=2 切掉 C3 → top-2 = [C1, C2]。证明 Core API 路径打通了 page_loader
    (之前 resolver.py 完全不走 page_loader)。
    """
    resolver_cls = handler._er_manager.create_resolver()
    resolved = await resolver_cls().resolve([DPThreadDTO(id=1, title="T1")])

    comments = resolved[0].comments
    assert len(comments) == 2  # top-N 生效(原本会返 3 条)
    assert [c.text for c in comments] == ["C1", "C2"]  # likes desc: 5, 3
    # 返的是 DTO 实例(_orm_to_dto 投影过)
    assert all(isinstance(c, DPCommentDTO) for c in comments)
    assert comments[0].likes == 5


@pytest.mark.asyncio
async def test_dto_paged_default_order_uses_entity_default(handler):
    """Paged(default_order=None) → 用 source entity 的 default_order(MOST_LIKED)。"""

    class _DTODefault(DefineSubset):
        __subset__ = (DPThread, ("id", "title"))
        comments: Annotated[list[DPCommentDTO], Paged(limit=2)] = Field(
            default_factory=list
        )

    resolver_cls = handler._er_manager.create_resolver()
    resolved = await resolver_cls().resolve([_DTODefault(id=1, title="T1")])
    # entity default_order=MOST_LIKED → 同上 [C1, C2]
    assert [c.text for c in resolved[0].comments] == ["C1", "C2"]
