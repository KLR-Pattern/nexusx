"""US1 (specs/015 T013): 本地分页 ``comments(order, direction)`` 端到端 —
page_loader 按 profile + direction 排序(复用 federation 的
``_build_order_expressions``/``_apply_direction``)。

US3 (T014): direction DESC↔ASC 翻转时 NULL 位置跟随(nulls_last→nulls_first)。

种子: C1 高赞旧(likes=5, created=100), C2 低起新(likes=3, created=300),
C3 NULL 赞(likes=None, created=200) → NEWEST/MOST_LIKED 反序, C3 验证 nulls。
"""
from typing import Optional

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, Relationship, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx import AutoQueryConfig, BatchPageConfig, GraphQLHandler, OrderTerm, PageOrder


class LOBase(SQLModel):
    pass


class LOComment(LOBase, table=True):
    __tablename__ = "lo_comment"
    id: int | None = Field(default=None, primary_key=True)
    text: str
    likes: int | None = Field(default=None)  # nullable → MOST_LIKED 用 nulls
    created_at: int = 0
    review_id: int = Field(foreign_key="lo_review.id")
    review: Optional["LOReview"] = Relationship(back_populates="comments")


class LOReview(LOBase, table=True):
    __tablename__ = "lo_review"
    id: int | None = Field(default=None, primary_key=True)
    title: str
    comments: list[LOComment] = Relationship(
        back_populates="review",
        sa_relationship_kwargs={"order_by": "LOComment.id"},
    )
    __pagination_orders__ = {
        "comments": BatchPageConfig(
            default_order="NEWEST",
            orders={
                "NEWEST": PageOrder([OrderTerm("created_at", "desc")]),
                "MOST_LIKED": PageOrder(
                    [OrderTerm("likes", "desc", nulls="last")]
                ),
            },
        ),
    }


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
        s.add(LOReview(id=1, title="R1"))
        s.add(LOComment(id=1, review_id=1, text="C1", likes=5, created_at=100))
        s.add(LOComment(id=2, review_id=1, text="C2", likes=3, created_at=300))
        s.add(LOComment(id=3, review_id=1, text="C3", likes=None, created_at=200))
        await s.commit()
    _seeded = True


@pytest.fixture
async def handler() -> GraphQLHandler:
    await _seed()
    return GraphQLHandler(
        base=LOBase,
        session_factory=_sf,
        auto_query_config=AutoQueryConfig(),
        enable_pagination=True,
    )


def _texts(res: dict) -> list[str]:
    return [i["text"] for i in res["data"]["LOReview"]["by_id"]["comments"]["items"]]


@pytest.mark.asyncio
async def test_us1_order_profile_switch(handler):
    """不同 order profile → 不同排序(NEWEST vs MOST_LIKED 反序)。SC-002。"""
    newest = await handler.execute(
        "{ LOReview { by_id(id: 1) { comments(limit: 5, order: NEWEST, "
        "direction: DESC) { items { text } } } } }"
    )
    assert not newest.get("errors"), newest
    assert _texts(newest) == ["C2", "C3", "C1"]  # created desc: 300,200,100

    most_liked = await handler.execute(
        "{ LOReview { by_id(id: 1) { comments(limit: 5, order: MOST_LIKED, "
        "direction: DESC) { items { text } } } } }"
    )
    assert not most_liked.get("errors"), most_liked
    assert _texts(most_liked) == ["C1", "C2", "C3"]  # likes desc, NULL 末(nulls_last)


@pytest.mark.asyncio
async def test_us1_direction_flip(handler):
    """direction DESC vs ASC 严格反序(含 NULL 位置翻转)。SC-001。"""
    desc = await handler.execute(
        "{ LOReview { by_id(id: 1) { comments(limit: 5, order: MOST_LIKED, "
        "direction: DESC) { items { text } } } } }"
    )
    asc = await handler.execute(
        "{ LOReview { by_id(id: 1) { comments(limit: 5, order: MOST_LIKED, "
        "direction: ASC) { items { text } } } } }"
    )
    assert _texts(desc) == ["C1", "C2", "C3"]  # likes desc, NULL 末
    assert _texts(asc) == ["C3", "C2", "C1"]  # likes asc, NULL 首(nulls 翻转)


@pytest.mark.asyncio
async def test_us1_default_order_when_omitted(handler):
    """不传 order → 用 default_order(NEWEST)。"""
    res = await handler.execute(
        "{ LOReview { by_id(id: 1) { comments(limit: 5, direction: DESC) "
        "{ items { text } } } } }"
    )
    assert not res.get("errors"), res
    assert _texts(res) == ["C2", "C3", "C1"]  # = NEWEST DESC


@pytest.mark.asyncio
async def test_us3_nulls_follow_direction(handler):
    """US3: direction 翻转 NULL 位置跟随(desc NULL末 ↔ asc NULL首)。"""
    desc = await handler.execute(
        "{ LOReview { by_id(id: 1) { comments(limit: 5, order: MOST_LIKED, "
        "direction: DESC) { items { text } } } } }"
    )
    asc = await handler.execute(
        "{ LOReview { by_id(id: 1) { comments(limit: 5, order: MOST_LIKED, "
        "direction: ASC) { items { text } } } } }"
    )
    desc_texts = _texts(desc)
    asc_texts = _texts(asc)
    assert desc_texts[-1] == "C3"  # NULL likes 在 desc 末(nulls_last)
    assert asc_texts[0] == "C3"  # NULL likes 在 asc 首(nulls_last→nulls_first)


@pytest.mark.asyncio
async def test_items_only_paged_query_no_internal_leak(handler):
    """specs/021 hardening: 分页字段只选 items(不选 pagination) 必须正确递归
    序列化 — 不得原样透传 RowMapping(内部列 _sg_rn/_sg_tc + 未选择字段泄漏)。
    此前 paged 包检测要求 items+pagination 同时存在, items-only 查询落入
    普通嵌套分支 → 原样透传。
    """
    r = await handler.execute(
        "{ LOReview { by_id(id: 1) { comments(limit: 5, order: NEWEST) "
        "{ items { text } } } } }"
    )
    assert not r.get("errors"), r
    items = r["data"]["LOReview"]["by_id"]["comments"]["items"]
    # 只输出选中的 text; 无内部列、无未选择字段
    assert items == [{"text": "C2"}, {"text": "C3"}, {"text": "C1"}]


@pytest.mark.asyncio
async def test_variable_paged_args_resolved(handler):
    """specs/021 hardening: gql 变量分页参数(limit/order)必须解析为真值 —
    此前 FieldSelection.arguments 里是 graphql Undefined, PageArgs 比较炸,
    整个查询 errors。
    """
    r = await handler.execute(
        "query Q($lim: Int, $ord: OrderTerm) { LOReview { by_id(id: 1) "
        "{ comments(limit: $lim, order: $ord) { items { text } } } } }",
        variables={"lim": 2, "ord": "NEWEST"},
    )
    assert not r.get("errors"), r
    items = r["data"]["LOReview"]["by_id"]["comments"]["items"]
    assert [i["text"] for i in items] == ["C2", "C3"]  # limit=2 生效
