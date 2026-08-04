"""specs/016 远程 γ Paged 端到端(member public DTO + Annotated[..., Paged])。

catalog ProductDTO.reviews 挂 Paged(limit, order),member ReviewDTO 是 public
DTO(声明 __pagination_orders__)。federate 拉 member introspection(batch_root.page)
→ catalog _get_loader γ 分支 merge(Paged 默认 + caller context)→ side-channel
→ member batch root ROW_NUMBER top-N(SQL 层,resolve 前)。

种子: product 1 三条 review(rating 5/3/1)。TOP(rating desc)=[R5,R3,R1];limit=2 → [R5,R3]。
member resolve spy:rating_double 只在 top-2 上算(2 次,非 3)—— 证明数据爆炸避免。
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

rev_svc = RemoteService("reviews", url="http://test/reviews")


class _ReviewsBase(SQLModel):
    pass


class Review(_ReviewsBase, table=True):
    __tablename__ = "dprem_review"
    id: int | None = SQLField(default=None, primary_key=True)
    product_id: int
    title: str
    rating: int


class _CatalogBase(SQLModel):
    pass


class Product(_CatalogBase, table=True):
    __tablename__ = "dprem_product"
    id: int | None = SQLField(default=None, primary_key=True)
    name: str


# ── member public DTO(含 __pagination_orders__,order profiles 来源)────────
class ReviewDTO(DefineSubset):
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


# ── mounter DTO(reviews 挂 Paged,引用 member public ReviewDTO)─────────────
class ProductDTO(DefineSubset):
    __subset__ = (Product, ("id", "name"))
    reviews: Annotated[list[rev_svc.ReviewDTO], Paged(limit=2)] = SQLField(
        default_factory=list
    )

    def resolve_reviews(self, loader=Loader("reviews")):
        return loader.load(self.id)


# member-side resolve counter (spy): proves member only resolved top-N, not full.
_resolve_count = 0
_orig_resolve_rating_double = ReviewDTO.resolve_rating_double


def _counting_resolve(self) -> int:
    global _resolve_count
    _resolve_count += 1
    return _orig_resolve_rating_double(self)


ReviewDTO.resolve_rating_double = _counting_resolve


@pytest.fixture
async def federation():
    global _resolve_count
    _resolve_count = 0
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
        s.add(Review(id=1, product_id=1, title="R5", rating=5))
        s.add(Review(id=2, product_id=1, title="R3", rating=3))
        s.add(Review(id=3, product_id=1, title="R1", rating=1))
        await s.commit()
    async with sf("c")() as s:
        s.add(Product(id=1, name="Widget"))
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
    transport = GraphQLTransport(client=client)

    await reviews_h.er.initialize()
    await catalog_h.er.initialize(transport=transport)

    yield {"catalog": catalog_h}

    await client.aclose()
    for e in engines.values():
        await e.dispose()
    for cls in (Review, Product):
        for attr in list(cls.__dict__):
            if attr.startswith("by_") or attr.startswith("page_by_"):
                delattr(cls, attr)


@pytest.mark.asyncio
async def test_remote_paged_top_n_slice(federation):
    """catalog ProductDTO.reviews Paged(limit=2, order=TOP) → reviews top-2 by rating。"""
    catalog_h = federation["catalog"]
    async with catalog_h.session_factory() as s:
        products = (await s.exec(select(Product))).all()
    dtos = [ProductDTO(id=p.id, name=p.name) for p in products]

    ResolverCls = catalog_h._er_manager.create_resolver()
    resolved = await ResolverCls().resolve(dtos)

    widget = resolved[0]
    reviews = widget.reviews
    assert len(reviews) == 2  # top-N(原本 3)
    assert [r.rating for r in reviews] == [5, 3]  # TOP desc
    # member resolve 的字段(rating_double)在 top-N 上算
    assert {r.rating_double for r in reviews} == {10, 6}


@pytest.mark.asyncio
async def test_remote_paged_member_only_resolves_top_n(federation):
    """member 只 resolve top-N(rating_double 计数 = 2,非 3)—— 数据爆炸避免。"""
    catalog_h = federation["catalog"]
    async with catalog_h.session_factory() as s:
        products = (await s.exec(select(Product))).all()
    dtos = [ProductDTO(id=p.id, name=p.name) for p in products]

    ResolverCls = catalog_h._er_manager.create_resolver()
    await ResolverCls().resolve(dtos)

    # member batch root ROW_NUMBER 切 top-2(SQL 层)→ member 只 resolve 2 个 DTO
    # → rating_double 调 2 次(非 3)。证明数据爆炸避免。
    assert _resolve_count == 2, f"member resolved {_resolve_count} DTOs, expected 2 (top-N)"


@pytest.mark.asyncio
async def test_remote_paged_caller_overrides(federation):
    """caller context {limit:1} 覆盖 Paged 默认 limit=2 → top-1。"""
    catalog_h = federation["catalog"]
    async with catalog_h.session_factory() as s:
        products = (await s.exec(select(Product))).all()
    dtos = [ProductDTO(id=p.id, name=p.name) for p in products]

    ResolverCls = catalog_h._er_manager.create_resolver()
    resolved = await ResolverCls(context={"limit": 1}).resolve(dtos)

    assert len(resolved[0].reviews) == 1
    assert resolved[0].reviews[0].rating == 5  # top-1
