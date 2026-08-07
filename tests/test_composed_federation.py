"""US5: federation × ComposedErManager 叠加测试矩阵（specs/019，FR-017）。

验证组合 × 组合的组合性边界（user 明确要求完整覆盖）：

- B（mounter 端组合）：子 ErManager 各自 federate 远程 service，物化的 remote type
  经组合体委托可见 + resolve 通；且 resolve 同时跨 engine（进程内）+ 跨 service（federation）。
- C（状态聚合）：_fed_registry 聚合视图正确（remote type 判断）。
- D（约束）：ComposedErManager 不实现 federate/initialize（FR-013）；子 member initialize 成功。
- E（回归）：现有 federation 测试零回归（由 Polish 全量覆盖）。

核心论点（FR-017）：federation mutating 操作落子 ErManager，ComposedErManager 只查询委托
+ _fed_registry 聚合。spec 起草期间曾误判 mounter 冲突，本测试矩阵兜底。
"""

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.applications import Starlette
from starlette.routing import Mount

from nexusx import AutoQueryConfig, ComposedErManager, DefineSubset, ErManager
from nexusx import GraphQLHandler
from nexusx import Relationship as NxRelationship
from nexusx.federation import RemoteRelationship, RemoteService
from nexusx.federation.http import GraphQLTransport
from nexusx.federation.introspect import build_federable_app


# ── RemoteService 声明（cfreviews = composed-federation reviews）──
cfreviews = RemoteService("cfreviews", url="http://test/cfreviews")


# ── 实体（Cf 前缀 + 唯一表名）──

class _CfReviewsBase(SQLModel):
    pass


class CfReview(_CfReviewsBase, table=True):
    __tablename__ = "cf_composed_review"
    id: int | None = Field(default=None, primary_key=True)
    product_id: int
    title: str


class _CfCatalogBase(SQLModel):
    pass


class CfProduct(_CfCatalogBase, table=True):
    __tablename__ = "cf_composed_product"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    # federation 关系：CfProduct → 远程 cfreviews.CfReview（声明在实体上，子 ErManager federate）
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[cfreviews.CfReview],
            name="reviews", join_remote="product_id",
        ),
    ]


class _CfShopBase(SQLModel):
    pass


class CfOrder(_CfShopBase, table=True):
    __tablename__ = "cf_composed_order"
    id: int | None = Field(default=None, primary_key=True)
    product_id: int  # 跨 engine 逻辑外键 → cf_composed_product.id（不建 SQL FK）
    total: float


# ── DTO ──

class CfReviewDTO(DefineSubset):
    __subset__ = (cfreviews.CfReview, ("id", "title"))


class CfOrderDTO(DefineSubset):
    __subset__ = (CfOrder, ("id", "total"))


class CfProductDTO(DefineSubset):
    __subset__ = (CfProduct, ("id", "name"))
    reviews: list[CfReviewDTO] = []  # federation（catalog_er 物化的 CfReview）
    orders: list[CfOrderDTO] = []    # 跨 engine（组合体叠加层）


# ── 跨 engine loader（CfProduct → CfOrder，用 shop session）──
_shop_sf_holder: dict = {}


async def orders_by_product_id(product_ids: list[int]) -> list[list[CfOrder]]:
    sf = _shop_sf_holder["sf"]
    async with sf() as session:
        result = await session.exec(
            select(CfOrder).where(CfOrder.product_id.in_(product_ids))
        )
        orders = list(result.all())
    by_prod: dict[int, list[CfOrder]] = {}
    for o in orders:
        by_prod.setdefault(o.product_id, []).append(o)
    return [by_prod.get(pid, []) for pid in product_ids]


# ── fixture：reviews service（被 federate）+ catalog_er + shop_er + 组合体 ──

@pytest_asyncio.fixture(scope="module")
async def composed_federation_world():
    reviews_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool
    )
    catalog_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool
    )
    shop_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool
    )
    reviews_sf = async_sessionmaker(reviews_engine, class_=AsyncSession, expire_on_commit=False)
    catalog_sf = async_sessionmaker(catalog_engine, class_=AsyncSession, expire_on_commit=False)
    shop_sf = async_sessionmaker(shop_engine, class_=AsyncSession, expire_on_commit=False)
    _shop_sf_holder["sf"] = shop_sf

    for eng in (reviews_engine, catalog_engine, shop_engine):
        async with eng.begin() as c:
            await c.run_sync(SQLModel.metadata.create_all)

    # reviews 数据
    async with reviews_sf() as s:
        s.add(CfReview(id=1, product_id=10, title="R1"))
        s.add(CfReview(id=2, product_id=10, title="R2"))
        await s.commit()
    # catalog 数据
    async with catalog_sf() as s:
        s.add(CfProduct(id=10, name="Widget"))
        await s.commit()
    # shop 数据（跨 engine）
    async with shop_sf() as s:
        s.add(CfOrder(id=1, product_id=10, total=9.9))
        s.add(CfOrder(id=2, product_id=10, total=19.9))
        await s.commit()

    # reviews member app（被 federate 的远程 service）
    reviews_h = GraphQLHandler(
        base=_CfReviewsBase,
        session_factory=reviews_sf,
        auto_query_config=AutoQueryConfig(batch_keys={"CfReview": ["product_id"]}),
        service_name="cfreviews",
    )
    composite_app = Starlette(routes=[
        Mount("/cfreviews", app=build_federable_app(reviews_h)),
    ])
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=composite_app), base_url="http://test"
    )
    transport = GraphQLTransport(client=client)

    # 子 ErManager：catalog_er 声明了 RemoteRelationship，将 federate reviews
    catalog_er = ErManager(session_factory=catalog_sf, entities=[CfProduct])
    shop_er = ErManager(session_factory=shop_sf, entities=[CfOrder])

    # 组合体：catalog_er（含 federation）+ shop_er（跨 engine）+ 跨边界关系
    composed = ComposedErManager(
        members=[catalog_er, shop_er],
        cross_relationships=[
            (CfProduct, NxRelationship(
                fk="id", target=list[CfOrder], name="orders",
                loader=orders_by_product_id,
            )),
        ],
    )

    # federation mutating 操作落子 ErManager（FR-017）—— 在子 member 上 initialize
    await catalog_er.initialize(transport=transport)

    yield {
        "composed": composed,
        "catalog_er": catalog_er,
        "shop_er": shop_er,
        "transport": transport,
        "client": client,
    }

    await catalog_er.aclose_federation()
    await client.aclose()
    for eng in (reviews_engine, catalog_engine, shop_engine):
        await eng.dispose()


# ── D（约束）──

async def test_composed_has_no_federation_management_methods(composed_federation_world):
    """ComposedErManager 不实现 federate/initialize/add_virtual_entities（FR-013）。"""
    composed = composed_federation_world["composed"]
    for attr in ("initialize", "federate", "add_virtual_entities", "aclose_federation"):
        assert not hasattr(composed, attr), f"组合体不应实现管理接口 {attr}"


async def test_member_initialize_exists_and_worked(composed_federation_world):
    """子 ErManager 有 initialize，且已成功 federate（物化的 remote type 经组合体委托可见）。"""
    catalog_er = composed_federation_world["catalog_er"]
    composed = composed_federation_world["composed"]

    assert hasattr(catalog_er, "initialize")  # 子 member 有管理接口
    # federate 已在 fixture 完成：CfReview 物化进 catalog_er._fed_registry
    assert catalog_er._fed_registry is not None
    # 组合体委托看到物化的 CfReview（按类名比较——物化副本是 federation.registry.CfReview）
    all_cls = composed._fed_registry.all_classes()
    assert any(c.__name__ == "CfReview" for c in all_cls)


# ── C（状态聚合）──

async def test_fed_registry_aggregates_members(composed_federation_world):
    """_fed_registry 聚合视图：子 member federate 后，组合体能判断 remote type。"""
    composed = composed_federation_world["composed"]
    fr = composed._fed_registry
    assert fr is not None
    # CfReview 被 catalog_er 物化 → 聚合视图能识别（按类名——物化副本不同于本地 CfReview）
    all_cls = list(fr.all_classes())
    review_cls = next((c for c in all_cls if c.__name__ == "CfReview"), None)
    assert review_cls is not None
    assert fr.qualified_of(review_cls) is not None
    assert fr.qualified_of(CfProduct) is None  # 本地实体，非 remote


# ── B（mounter 端组合 + 跨 engine 混合）──

async def test_mount_federation_through_composed_resolve(composed_federation_world):
    """B3: resolve 同时跨 service（federation，经 catalog_er）+ 跨 engine（组合体叠加）。

    核心验证 FR-017：federation 在子 member（catalog_er）层发生，物化的 CfReview
    经组合体委托可见、resolve 通；跨 engine 的 CfOrder 经组合体叠加层 resolve。
    """
    composed = composed_federation_world["composed"]

    Resolver = composed.create_resolver()
    resolver = Resolver()
    resolved = await resolver.resolve([CfProductDTO(id=10, name="Widget")])
    product = resolved[0]

    # federation（catalog_er federate reviews → 物化 CfReview，经组合体委托 resolve）
    assert [r.title for r in product.reviews] == ["R1", "R2"]
    # 跨 engine（组合体叠加层 CfProduct → CfOrder，shop session）
    assert [o.total for o in product.orders] == [9.9, 19.9]


async def test_mount_federation_relationships_visible_via_compose(composed_federation_world):
    """B1: 物化的 federation 关系经组合体 get_relationships 可见（FR-017 委托）。"""
    composed = composed_federation_world["composed"]
    catalog_er = composed_federation_world["catalog_er"]

    # 组合体看到 CfProduct.reviews（物化的 federation 关系，经委托 catalog_er）
    composed_rels = composed.get_relationships(CfProduct)
    assert "reviews" in composed_rels  # federation（catalog_er 物化）
    assert "orders" in composed_rels   # 跨 engine（组合体叠加）

    # 子 member 自己也看到 reviews（federation 物化进 catalog_er）
    catalog_rels = catalog_er.get_relationships(CfProduct)
    assert "reviews" in catalog_rels
    assert "orders" not in catalog_rels  # 跨 engine 只在组合体层


async def test_member_side_compose_serialize_introspection(composed_federation_world):
    """A2（部分）：组合体作 member 暴露时，service_name + 实体聚合可被 introspect 序列化。

    完整 A（组合体作 federation member 被 mounter 消费）依赖 US3 的 GraphQLHandler
    er_manager 注入，此处先验证 introspection 序列化层（serialize_er_introspection）
    能读组合体的聚合字段。
    """
    from nexusx.federation.introspect import serialize_er_introspection

    composed = composed_federation_world["composed"]
    composed._service_name = "composed_member"  # 模拟作 member 时的统一名

    # serialize_er_introspection 读 service_name + get_all_entities（组合体聚合）
    payload = serialize_er_introspection(composed)
    assert payload.service_name == "composed_member"
    entity_typenames = {e.typename for e in payload.entities}
    assert {"CfProduct", "CfOrder"} <= entity_typenames  # 跨 engine 实体都暴露
