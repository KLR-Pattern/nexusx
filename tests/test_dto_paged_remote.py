"""specs/016 Phase 2 — 远程 γ DTO federation top-N(Annotated[..., Paged])。

member ReviewDTO 声明 __pagination_orders__(order profiles),catalog ProductDTO.reviews
挂 Paged(limit, default_order)。mounter federate 拉 member introspection(batch_root.page)
+ wire Paged → create_dto_remote_loader POST {order, limit} → member batch root
ROW_NUMBER per-parent top-N(SQL 层,resolve 前)。

种子: product 10 三条 review,rating 5/3/1 → TOP(rating desc) = [5,3,1];limit=2 → [5,3]。
"""
from typing import Annotated

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.applications import Starlette
from starlette.routing import Mount

from nexusx import (
    AutoQueryConfig,
    BatchPageConfig,
    DefineSubset,
    GraphQLHandler,
    Loader,
    OrderTerm,
    PageOrder,
    SubsetConfig,
)
from nexusx.federation import RemoteService
from nexusx.federation.http import GraphQLTransport
from nexusx.federation.introspect import build_federable_app
from nexusx.loader.pagination import Paged

# 别名服务:字段名 `reviews` ≠ 命名空间变量 `rev_svc`(规避类体遮蔽)。
rev_svc = RemoteService("reviews", url="http://test/reviews")


class _ReviewsBase(SQLModel):
    pass


class Review(_ReviewsBase, table=True):
    __tablename__ = "dpr_review"
    id: int | None = SQLField(default=None, primary_key=True)
    product_id: int
    title: str
    rating: int


class _CatalogBase(SQLModel):
    pass


class Product(_CatalogBase, table=True):
    __tablename__ = "dpr_product"
    id: int | None = SQLField(default=None, primary_key=True)
    name: str


class ReviewDTO(DefineSubset):
    """member public DTO:subset of Review + __pagination_orders__(TOP=rating desc)。"""

    __subset__ = SubsetConfig(
        kls=Review,
        fields=("title", "rating", "product_id"),
        federation_public=True,
        federation_join_key="product_id",
    )
    __pagination_orders__ = BatchPageConfig(
        default_order="TOP",
        orders={"TOP": PageOrder([OrderTerm("rating", "desc")])},
    )
    rating_double: int | None = None

    def resolve_rating_double(self) -> int:
        return self.rating * 2


class ProductDTO(DefineSubset):
    """mounter DTO:reviews 挂 Paged(limit=2, default_order=TOP) → 远程 top-N。"""

    __subset__ = (Product, ("id", "name"))
    reviews: Annotated[list[rev_svc.ReviewDTO], Paged(limit=2, default_order="TOP")] = SQLField(
        default_factory=list
    )

    def resolve_reviews(self, loader=Loader("reviews")):
        return loader.load(self.id)


class _SpyTransport:
    """记录 dto-batch POST body(order/limit 验证)。"""

    def __init__(self, inner):
        self._inner = inner
        self.posts: list[tuple[str, dict]] = []

    async def post_json(self, url, body):
        if "/nexusx/dto-batch" in url:
            self.posts.append((url, dict(body)))
        return await self._inner.post_json(url, body)

    async def get_json(self, url):
        return await self._inner.get_json(url)

    async def close(self):
        return await self._inner.close()


@pytest.fixture
async def federation():
    engines = {
        k: create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        for k in ("r", "c")
    }
    for e in engines.values():
        async with e.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    def sf(k):
        return async_sessionmaker(engines[k], class_=AsyncSession, expire_on_commit=False)

    async with sf("r")() as s:
        s.add(Review(id=1, product_id=10, title="R5", rating=5))
        s.add(Review(id=2, product_id=10, title="R3", rating=3))
        s.add(Review(id=3, product_id=10, title="R1", rating=1))
        await s.commit()
    async with sf("c")() as s:
        s.add(Product(id=10, name="Widget"))
        await s.commit()

    reviews_h = GraphQLHandler(
        base=_ReviewsBase, session_factory=sf("r"),
        auto_query_config=AutoQueryConfig(batch_keys={"Review": ["product_id"]}),
        service_name="reviews", expose_mounted_endpoints=True,
        dto_classes=[ReviewDTO],
    )
    catalog_h = GraphQLHandler(
        base=_CatalogBase, session_factory=sf("c"),
        auto_query_config=AutoQueryConfig(), service_name="catalog",
        dto_classes=[ProductDTO],
    )

    composite = Starlette(routes=[
        Mount("/reviews", app=build_federable_app(reviews_h)),
    ])
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=composite), base_url="http://test",
    )
    transport = _SpyTransport(GraphQLTransport(client=client))

    await reviews_h.er.initialize()
    await catalog_h.er.initialize(transport=transport)

    yield {"catalog": catalog_h, "transport": transport}

    await client.aclose()
    for e in engines.values():
        await e.dispose()
    for cls in (Review, Product):
        for attr in list(cls.__dict__):
            if attr.startswith("by_") or attr.startswith("page_by_"):
                delattr(cls, attr)


@pytest.mark.asyncio
async def test_remote_paged_top_n_slice(federation):
    """Paged(limit=2) → reviews 只 2 条 + 按 TOP(rating desc) = [5, 3]。"""
    catalog_h = federation["catalog"]
    transport = federation["transport"]

    async with catalog_h.session_factory() as s:
        products = (await s.exec(select(Product))).all()
    dtos = [ProductDTO(id=p.id, name=p.name) for p in products]

    resolver_cls = catalog_h._er_manager.create_resolver()
    resolved = await resolver_cls().resolve(dtos)

    widget = resolved[0]
    reviews = widget.reviews
    assert len(reviews) == 2  # top-N(原本会返 3 条)
    assert [r.rating for r in reviews] == [5, 3]  # TOP desc
    # member resolve 的字段(rating_double)在 top-N 上算
    assert {r.rating_double for r in reviews} == {10, 6}

    # POST body 含 order/limit(mounter → member 透传)
    assert len(transport.posts) == 1
    _url, body = transport.posts[0]
    assert body["dto"] == "ReviewDTO"
    assert body["order"] == "TOP"
    assert body["limit"] == 2


def test_remote_paged_stamp_coexists_with_remote_ref():
    """远程 γ 字段 Paged + RemoteRef 协调:两个 stamp 都在。

    _collect_paged_fields 必须在 _collect_remote_field_refs 占位前跑(否则
    Annotated 的 Paged metadata 被 Any 占位丢失)。
    """
    assert hasattr(ProductDTO, "__paged_fields__")
    paged = ProductDTO.__paged_fields__["reviews"]
    assert paged.limit == 2
    assert paged.default_order == "TOP"
    # RemoteRef stamp 也在(_collect 顺序让两者共存)
    assert hasattr(ProductDTO, "__nexusx_remote_field_refs__")
    assert "reviews" in ProductDTO.__nexusx_remote_field_refs__
