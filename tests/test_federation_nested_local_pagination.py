"""验证两套分页机制能否叠加：外层 federation 分页（catalog→reviews 的
Product.reviews）+ 内层 reviews 本地分页（Review.comments，enable_pagination）。

reviews 开 enable_pagination=True 且 comments 配 order_by → comments 变本地分页字段。
catalog 查 reviews(limit) { items { comments(limit,offset) { items pagination } } } 时，
items 子树选区（含 comments(limit)）原样透传给 reviews 的 page_by_product_id_in；
reviews 自己的 executor 在 items 子树里把 comments 分页解析好返回。

两测试通过 = 两套分页可正常叠加使用。
"""

import os
import tempfile

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, Relationship, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.applications import Starlette
from starlette.routing import Mount

from nexusx import AutoQueryConfig, BatchPageConfig, GraphQLHandler, OrderTerm, PageOrder
from nexusx.federation import RemoteRelationship, RemoteService
from nexusx.federation.http import GraphQLTransport
from nexusx.federation.introspect import build_federable_app

reviews = RemoteService("reviews", url="http://test/reviews")


class NLCatalogBase(SQLModel):
    pass


class NLReviewsBase(SQLModel):
    pass


class NLComment(NLReviewsBase, table=True):
    __tablename__ = "nl_comment"
    id: int | None = Field(default=None, primary_key=True)
    review_id: int = Field(foreign_key="nl_review.id")
    text: str
    review: "NLReview" = Relationship(back_populates="comments")


class NLReview(NLReviewsBase, table=True):
    __tablename__ = "nl_review"
    id: int | None = Field(default=None, primary_key=True)
    product_id: int
    title: str
    rating: int
    comments: list["NLComment"] = Relationship(
        back_populates="review",
        sa_relationship_kwargs={"order_by": "NLComment.id"},
    )


class NLProduct(NLCatalogBase, table=True):
    __tablename__ = "nl_product"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[reviews.NLReview],
            name="reviews", join_remote="product_id",
            pagination=True,
        ),
    ]


def _engine():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return create_async_engine(f"sqlite+aiosqlite:///{path}")


_cat_engine = _engine()
_rev_engine = _engine()
_cat_sf = async_sessionmaker(_cat_engine, class_=AsyncSession, expire_on_commit=False)
_rev_sf = async_sessionmaker(_rev_engine, class_=AsyncSession, expire_on_commit=False)
_seeded = False


async def _ensure_seed():
    global _seeded
    if _seeded:
        return
    async with _cat_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with _rev_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with _cat_sf() as s:
        s.add(NLProduct(id=1, name="P1"))
        await s.commit()
    async with _rev_sf() as s:
        s.add(NLReview(id=1, product_id=1, title="R1", rating=5))
        # 5 comments on R1 — enough to paginate (limit 2 → has_more, total_count 5)
        for i in range(1, 6):
            s.add(NLComment(id=i, review_id=1, text=f"C{i}"))
        await s.commit()
    _seeded = True


@pytest.fixture
async def federation():
    await _ensure_seed()
    reviews_handler = GraphQLHandler(
        base=NLReviewsBase, session_factory=_rev_sf,
        auto_query_config=AutoQueryConfig(
            batch_keys={"NLReview": ["product_id"]},
            batch_pages={"NLReview": {"product_id": BatchPageConfig(
                default_order="HIGHEST_RATING",
                orders={"HIGHEST_RATING": PageOrder([OrderTerm("rating", "desc")])},
            )}},
        ),
        service_name="reviews",
        enable_pagination=True,  # ← 内层本地分页开关
    )
    reviews_app = build_federable_app(reviews_handler)
    catalog_handler = GraphQLHandler(
        base=NLCatalogBase, session_factory=_cat_sf,
        auto_query_config=AutoQueryConfig(), service_name="catalog",
    )
    composite = Starlette(routes=[Mount("/reviews", app=reviews_app)])
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=composite), base_url="http://test",
    )
    transport = GraphQLTransport(client=client)
    await catalog_handler.er.initialize(transport=transport)
    yield catalog_handler
    await client.aclose()


@pytest.mark.asyncio
async def test_nested_local_pagination_first_page(federation):
    """外层 federation 分页 + 内层本地分页叠加：两层首页都正常。"""
    catalog_handler = federation
    res = await catalog_handler.execute(
        "{ NLProduct { by_id(id: 1) { reviews(limit: 5) { "
        "items { title comments(limit: 2, offset: 0) { "
        "items { text } pagination { has_more total_count } } } "
        "pagination { has_more total_count } } } } }"
    )
    assert not res.get("errors"), res
    reviews_pkg = res["data"]["NLProduct"]["by_id"]["reviews"]
    # 外层 federation 分页：1 条 review
    assert [it["title"] for it in reviews_pkg["items"]] == ["R1"]
    assert reviews_pkg["pagination"] == {"has_more": False, "total_count": 1}
    # 内层本地分页：R1 的 5 条 comment，limit 2 → C1,C2 + has_more + total_count 5
    comments_pkg = reviews_pkg["items"][0]["comments"]
    assert [it["text"] for it in comments_pkg["items"]] == ["C1", "C2"]
    assert comments_pkg["pagination"] == {"has_more": True, "total_count": 5}


@pytest.mark.asyncio
async def test_nested_local_pagination_offset(federation):
    """内层本地分页 offset 翻页也正常。"""
    catalog_handler = federation
    res = await catalog_handler.execute(
        "{ NLProduct { by_id(id: 1) { reviews(limit: 5) { "
        "items { comments(limit: 2, offset: 2) { "
        "items { text } pagination { has_more total_count } } } "
        "pagination { has_more } } } } }"
    )
    assert not res.get("errors"), res
    comments_pkg = res["data"]["NLProduct"]["by_id"]["reviews"]["items"][0]["comments"]
    assert [it["text"] for it in comments_pkg["items"]] == ["C3", "C4"]
    assert comments_pkg["pagination"] == {"has_more": True, "total_count": 5}
