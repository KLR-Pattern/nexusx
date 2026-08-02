"""specs/016 — DTO federation 端到端（γ 路径：member public DTO 自包含 + mounter 组合）。

拓扑：catalog → reviews(public ReviewDTO) → users
  - users: User 实体
  - reviews: Review 实体 + public ReviewDTO（subset of Review + resolve_*；author_name
    跨 service 取 users.User.name —— member 自包含）
  - catalog: Product 实体 + ProductDTO（reviews: list[reviews.ReviewDTO]，γ DTO RemoteRef）

catalog 的 Resolver 组合：resolve_reviews 用 Loader("reviews") → γ DTO RemoteLoader
POST /reviews/nexusx/dto-batch → reviews 跑 batch root（er.create_resolver().resolve）
→ 返已 resolve 的 ReviewDTO 树（含跨 service author_name）→ mounter model_validate。

β 路径（gql 实体）零回归：同 catalog handler 的 { Product { by_filter { reviews {} } } }
仍走实体 RemoteLoader。
"""

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
    DefineSubset,
    GraphQLHandler,
    Loader,
    SubsetConfig,
    UseCaseAppConfig,
    UseCaseService,
    query,
)
from nexusx.federation import RemoteRelationship, RemoteService
from nexusx.federation.http import GraphQLTransport
from nexusx.federation.introspect import build_federable_app

# 别名服务：字段名 `reviews` ≠ 命名空间变量 `rev_svc`，规避 Python 类体名字遮蔽。
rev_svc = RemoteService("reviews", url="http://test/reviews")
users_svc = RemoteService("users", url="http://test/users")


# ── users ────────────────────────────────────────────────────────────────
class _UsersBase(SQLModel):
    pass


class User(_UsersBase, table=True):
    __tablename__ = "dto_e2e_user"
    id: int | None = SQLField(default=None, primary_key=True)
    name: str


# ── reviews ──────────────────────────────────────────────────────────────
class _ReviewsBase(SQLModel):
    pass


class Review(_ReviewsBase, table=True):
    __tablename__ = "dto_e2e_review"
    id: int | None = SQLField(default=None, primary_key=True)
    product_id: int
    author_id: int
    title: str
    rating: int
    __relationships__ = [
        RemoteRelationship(
            fk="author_id", target=users_svc.User,
            name="author", join_remote="id",
        ),
    ]


class ReviewDTO(DefineSubset):
    """member public DTO：subset of Review + resolve_*（含跨 service author_name）。"""

    __subset__ = SubsetConfig(
        kls=Review,
        fields=("title", "rating", "product_id"),
        federation_public=True,
        federation_join_key="product_id",
    )
    rating_double: int | None = None
    author_name: str | None = None

    def resolve_rating_double(self) -> int:
        return self.rating * 2

    async def resolve_author_name(self, loader=Loader("author")) -> str | None:
        # 跨 service 出边：member 自己挂 users，Resolver 加工时解析（自包含）
        user = await loader.load(self.author_id)
        return user.name if user else None


# ── catalog ──────────────────────────────────────────────────────────────
class _CatalogBase(SQLModel):
    pass


class Product(_CatalogBase, table=True):
    __tablename__ = "dto_e2e_product"
    id: int | None = SQLField(default=None, primary_key=True)
    name: str
    # β 实体关系（保持 β 路径覆盖；γ 用同名 _dto_loaders，_get_loader 优先 γ）
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[rev_svc.Review],
            name="reviews", join_remote="product_id",
        ),
    ]


class ProductDTO(DefineSubset):
    """mounter DTO：reviews 引用 member public DTO（γ RemoteRef）。"""

    __subset__ = (Product, ("id", "name"))
    reviews: list[rev_svc.ReviewDTO] = SQLField(default_factory=list)

    def resolve_reviews(self, loader=Loader("reviews")):
        # sync resolve_* 返回 loader.load() 的 Future；Resolver 会 await 它。
        # （async def 里 `return loader.load()` 只 await 协程拿到 Future，不再 await Future。）
        return loader.load(self.id)


class CatalogProductDTO(DefineSubset):
    """US2: mounter 二次 resolve —— 读 member reviews（member 值），加 avg_rating。

    member 值只读契约：resolve_avg_rating 只读 self.reviews[i].rating（member 的），
    不改它；mounter 算的新字段 avg_rating 与 member 值共存。
    """

    __subset__ = (Product, ("id", "name"))
    reviews: list[rev_svc.ReviewDTO] = SQLField(default_factory=list)
    avg_rating: float | None = None

    def resolve_reviews(self, loader=Loader("reviews")):
        return loader.load(self.id)

    def post_avg_rating(self) -> float | None:
        # post_*（Phase B，resolve_* 之后）—— 读已被 resolve_reviews 填好的 reviews
        # 树里的 member rating，mounter 算均值。member 值只读：只读不改。
        if not self.reviews:
            return None
        return sum(r.rating for r in self.reviews) / len(self.reviews)


class _CountingTransport:
    """Transparent wrapper counting γ dto-batch POSTs (N+1-proof assertion)."""

    def __init__(self, inner):
        self._inner = inner
        self.dto_batch_calls = 0

    async def post_json(self, url, body):
        if "/nexusx/dto-batch" in url:
            self.dto_batch_calls += 1
        return await self._inner.post_json(url, body)

    async def get_json(self, url):
        return await self._inner.get_json(url)

    async def close(self):
        return await self._inner.close()


@pytest.fixture
async def federation(request):
    # indirect parametrization: the catalog DTO class under test
    # (ProductDTO for US1/β; CatalogProductDTO for US2 mounter二次resolve).
    catalog_dto = getattr(request, "param", ProductDTO)
    engines = {
        k: create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        for k in ("u", "r", "c")
    }
    for e in engines.values():
        async with e.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    def sf(k):
        return async_sessionmaker(engines[k], class_=AsyncSession, expire_on_commit=False)

    async with sf("u")() as s:
        s.add(User(id=1, name="Alice"))
        s.add(User(id=2, name="Bob"))
        await s.commit()
    async with sf("r")() as s:
        s.add(Review(id=1, product_id=10, author_id=1, title="Great", rating=5))
        s.add(Review(id=2, product_id=10, author_id=2, title="Okay", rating=3))
        s.add(Review(id=3, product_id=20, author_id=1, title="Meh", rating=2))
        await s.commit()
    async with sf("c")() as s:
        s.add(Product(id=10, name="Widget"))
        s.add(Product(id=20, name="Gadget"))
        await s.commit()

    users_h = GraphQLHandler(
        base=_UsersBase, session_factory=sf("u"),
        auto_query_config=AutoQueryConfig(batch_keys={"User": ["id"]}),
        service_name="users",
    )
    reviews_h = GraphQLHandler(
        base=_ReviewsBase, session_factory=sf("r"),
        auto_query_config=AutoQueryConfig(batch_keys={"Review": ["product_id", "author_id"]}),
        service_name="reviews",
        expose_mounted_endpoints=True,
        dto_classes=[ReviewDTO],
    )
    catalog_h = GraphQLHandler(
        base=_CatalogBase, session_factory=sf("c"),
        auto_query_config=AutoQueryConfig(), service_name="catalog",
        dto_classes=[catalog_dto],
    )

    composite = Starlette(routes=[
        Mount("/users", app=build_federable_app(users_h)),
        Mount("/reviews", app=build_federable_app(reviews_h)),
    ])
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=composite), base_url="http://test",
    )
    transport = _CountingTransport(GraphQLTransport(client=client))

    await users_h.er.initialize()
    await reviews_h.er.initialize(transport=transport)
    await catalog_h.er.initialize(transport=transport)

    yield {
        "users": users_h,
        "reviews": reviews_h,
        "catalog": catalog_h,
        "client": client,
        "transport": transport,
    }

    await client.aclose()
    for e in engines.values():
        await e.dispose()
    # add_standard_queries attaches by_*/page_by_* classmethods (capturing this
    # fixture's session_factory) onto the SHARED module-level entity classes, and
    # its ``hasattr`` guard then blocks the next test's handler from re-attaching.
    # Strip them so each test's handler re-attaches with its own session_factory.
    for cls in (User, Review, Product):
        for attr in list(cls.__dict__):
            # @query returns a classmethod (not callable as a raw __dict__ value),
            # so match by name prefix only — these are the auto-attached batch
            # roots / by_id / by_filter that captured this fixture's session_factory.
            if attr.startswith("by_") or attr.startswith("page_by_"):
                delattr(cls, attr)


@pytest.mark.asyncio
async def test_gamma_combines_member_public_dto_self_contained(federation):
    """US1 核心：mounter γ 组合 member public DTO，返回 member 业务字段 + 跨 service。"""
    catalog_h = federation["catalog"]
    async with catalog_h.session_factory() as s:
        products = (await s.exec(select(Product))).all()
    dtos = [ProductDTO(id=p.id, name=p.name) for p in products]

    ResolverCls = catalog_h._er_manager.create_resolver()
    resolved = await ResolverCls().resolve(dtos)

    by_name = {p.name: p for p in resolved}
    widget = by_name["Widget"]
    # reviews 是物化的 ReviewDTO 实例（member public DTO）
    assert len(widget.reviews) == 2
    review_titles = {r.title for r in widget.reviews}
    assert review_titles == {"Great", "Okay"}
    # member Resolver 算的字段（rating_double）
    great = next(r for r in widget.reviews if r.title == "Great")
    assert great.rating_double == 10
    # 跨 service 出边（author_name）—— member 自包含解析了 users
    assert great.author_name == "Alice"
    okay = next(r for r in widget.reviews if r.title == "Okay")
    assert okay.author_name == "Bob"

    gadget = by_name["Gadget"]
    assert len(gadget.reviews) == 1
    assert gadget.reviews[0].title == "Meh"
    assert gadget.reviews[0].author_name == "Alice"


@pytest.mark.asyncio
async def test_gamma_dto_loader_registered_and_beta_coexists(federation):
    """γ DTO loader 注册到 _dto_loaders；β entity reviews 关系仍在（同名共存）。"""
    catalog_er = federation["catalog"]._er_manager
    # γ DTO loader 在 _dto_loaders["reviews"]
    assert catalog_er.get_dto_loader("reviews") is not None
    # β entity 关系仍在 Product.reviews（gql 路径用）
    assert "reviews" in catalog_er.get_relationships(Product)


@pytest.mark.asyncio
async def test_beta_entity_path_zero_regression(federation):
    """β gql 实体路径不受 γ 污染：{ Product { by_filter { reviews { title } } } } 走实体。"""
    catalog_h = federation["catalog"]
    res = await catalog_h.execute(
        "{ Product { by_filter { id name reviews { title rating } } } }"
    )
    assert not res.get("errors"), res
    products = (((res.get("data") or {}).get("Product") or {}).get("by_filter") or [])
    by_name = {p["name"]: p for p in products}
    widget = by_name["Widget"]
    # β 返的是实体 Review 的裸字段（无 rating_double / author_name —— 那是 DTO 的）
    assert {r["title"] for r in widget["reviews"]} == {"Great", "Okay"}
    assert all("rating_double" not in r for r in widget["reviews"])


@pytest.mark.asyncio
@pytest.mark.parametrize("federation", [CatalogProductDTO], indirect=True)
async def test_us2_mounter_reresolve_member_value_readonly(federation):
    """US2: mounter 二次 resolve 读 member 值算新字段，member 值不被覆盖。"""
    catalog_h = federation["catalog"]
    async with catalog_h.session_factory() as s:
        products = (await s.exec(select(Product))).all()
    dtos = [CatalogProductDTO(id=p.id, name=p.name) for p in products]

    ResolverCls = catalog_h._er_manager.create_resolver()
    resolved = await ResolverCls().resolve(dtos)

    by_name = {p.name: p for p in resolved}
    widget = by_name["Widget"]
    # mounter 算的 avg_rating（读 member reviews 的 rating：5+3 / 2 = 4.0）
    assert widget.avg_rating == 4.0
    # member 值只读：rating 仍是 member 原值，未被 mounter 改（Great=5, Okay=3）
    ratings = {r.title: r.rating for r in widget.reviews}
    assert ratings == {"Great": 5, "Okay": 3}
    # member 自包含字段仍在（rating_double 是 reviews 端 resolve_* 算的，未被覆盖）
    assert {r.title: r.rating_double for r in widget.reviews} == {"Great": 10, "Okay": 6}
    gadget = by_name["Gadget"]
    assert gadget.avg_rating == 2.0  # 单条 rating=2


@pytest.mark.asyncio
async def test_us3_fk_batch_join_reuses_gamma_mechanism(federation):
    """US3: DTO 的 FK（product_id，派生自 Review）按 batch join，复用 γ 机制。

    多个 product 的 reviews 在一次 DTO batch 调用里按 product_id 批量取回
    （N+1-proof）。US1 已隐含覆盖；这里显式断言多 key 批量对齐。
    """
    catalog_h = federation["catalog"]
    async with catalog_h.session_factory() as s:
        products = (await s.exec(select(Product))).all()
    dtos = [ProductDTO(id=p.id, name=p.name) for p in products]

    ResolverCls = catalog_h._er_manager.create_resolver()
    resolved = await ResolverCls().resolve(dtos)

    by_id = {p.id: p for p in resolved}
    # 两个 product 的 reviews 都按 product_id 对齐返回（join key = FK）
    assert {r.title for r in by_id[10].reviews} == {"Great", "Okay"}
    assert [r.title for r in by_id[20].reviews] == ["Meh"]
    # join key 本身（product_id）是 DTO 字段，派生自实体 FK
    assert all(r.product_id == 10 for r in by_id[10].reviews)
    assert all(r.product_id == 20 for r in by_id[20].reviews)


@pytest.mark.asyncio
async def test_gamma_full_fetch_then_graphql_projection(federation):
    """γ graphql 语义（用户重点确认）：全量获取 → graphql 层字段剪裁。

    走完整 ``execute_compose_query`` 链路（service method → Resolver 全量 resolve
    → ``_project_result`` / ``build_subset_model`` 剪裁），验证两点：
    ① 全量获取：member batch root 返完整 ReviewDTO 树（含 rating_double + 跨 service
       author_name）—— DTO RemoteLoader 不带 selection，不在 fetch 阶段剪裁；
    ② graphql 字段剪裁：query 只请求 ``{ id reviews { title } }`` 时，结果剪掉
       name / rating / rating_double / author_name（剪裁发生在 resolve 完成之后）。
    """
    from nexusx.use_case import build_compose_schema
    from nexusx.use_case.compose_executor import execute_compose_query

    catalog_h = federation["catalog"]
    captured: dict = {}  # 捕获剪裁前的全量 resolved 树

    class CatalogService(UseCaseService):
        @query
        async def composed_tree(cls) -> list[ProductDTO]:
            async with catalog_h.session_factory() as s:
                products = (await s.exec(select(Product))).all()
            dtos = [ProductDTO(id=p.id, name=p.name) for p in products]
            resolver = catalog_h._er_manager.create_resolver()
            resolved = await resolver().resolve(dtos)
            captured["tree"] = resolved  # 全量（剪裁前）
            return resolved

    app = UseCaseAppConfig(name="catalog", services=[CatalogService])
    schema = build_compose_schema(app)

    result = await execute_compose_query(
        app, schema,
        "{ CatalogService { composed_tree { id reviews { title } } } }",
    )
    assert result["errors"] == [], result
    tree = result["data"]["CatalogService"]["composed_tree"]

    # ① 全量获取（剪裁前 captured 树含所有字段，含跨 service）
    full = captured["tree"]
    widget_full = next(p for p in full if p.name == "Widget")
    assert {r.author_name for r in widget_full.reviews} == {"Alice", "Bob"}
    assert {r.rating_double for r in widget_full.reviews} == {10, 6}

    # ② graphql 字段剪裁：结果只剩请求的字段
    widget = next(p for p in tree if p.id == 10)
    assert set(widget.model_dump().keys()) == {"id", "reviews"}  # name 被剪掉
    assert all(set(r.model_dump().keys()) == {"title"} for r in widget.reviews)
    assert {r.title for r in widget.reviews} == {"Great", "Okay"}


@pytest.mark.asyncio
async def test_gamma_n_plus_one_proof(federation):
    """A: 多 parent 一次 resolve → 单次 dto-batch 调用（N+1-proof，γ 核心承诺）。

    2 个 product（key 10, 20）经同一 DTO RemoteLoader 实例（Resolver 内 cached），
    aiodataloader batch 成一次 batch_load_fn → 1 次 POST /nexusx/dto-batch。
    """
    catalog_h = federation["catalog"]
    transport = federation["transport"]
    assert transport.dto_batch_calls == 0  # federate 期不 POST dto-batch

    async with catalog_h.session_factory() as s:
        products = (await s.exec(select(Product))).all()
    dtos = [ProductDTO(id=p.id, name=p.name) for p in products]
    ResolverCls = catalog_h._er_manager.create_resolver()
    await ResolverCls().resolve(dtos)

    assert len(dtos) == 2
    assert transport.dto_batch_calls == 1  # 2 key → 1 batch 调用


@pytest.mark.asyncio
async def test_gamma_member_resolver_failure_propagates(federation, monkeypatch):
    """B: member Resolver 加工失败 → mounter RemoteQueryError（spec Edge Case）。

    member batch root 跑 resolve 时 resolve_* 抛错 → dto_batch_endpoint catch 返
    {"errors":[...]} → mounter DTO RemoteLoader 包成 RemoteQueryError 透传。
    """
    from nexusx.federation.remote_loader import RemoteQueryError
    from nexusx.resolver import _clear_resolver_caches

    async def boom(self, loader=Loader("author")) -> str:
        raise RuntimeError("discount service down")

    # 清 class-meta cache 让 monkeypatch 在 member 端 resolve 时生效
    _clear_resolver_caches()
    monkeypatch.setattr(ReviewDTO, "resolve_author_name", boom)

    catalog_h = federation["catalog"]
    ResolverCls = catalog_h._er_manager.create_resolver()
    with pytest.raises(RemoteQueryError, match="discount service down"):
        await ResolverCls().resolve([ProductDTO(id=10, name="W")])
