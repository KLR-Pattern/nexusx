"""ComposedErManager 测试 —— 同进程多 engine 组合（specs/019）。

覆盖：
- US1 同进程多 engine UseCase 跨库 resolve（含二级钻取）
- US2 跨 engine ER 图合并
- US4 跨边界关系声明（组合体层）+ 构造期校验

实体类名用 Ce 前缀（composed-er）+ 唯一表名，避免与其它测试模块
（如 test_multi_app_tools.BlogUser）在 SQLModel 全局 metadata 撞表。
跨边界关系在组合体层 cross_relationships 声明（B 方式），成员无感。
"""

import pytest
import pytest_asyncio
from aiodataloader import DataLoader
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Relationship, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx import ComposedErManager, DefineSubset, ErManager
from nexusx import Relationship as NxRelationship
from nexusx.er_diagram import ErDiagram

# 不用 from __future__ import annotations —— SQLModel Relationship(list["X"]) 注解
# 在延迟注解下会被当成 relationship 字符串参数解析失败（spike 已踩坑）。


# ── 实体（module-level，Ce 前缀 + 唯一表名）──

class CeUser(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    posts: list["CePost"] = Relationship(
        back_populates="author",
        sa_relationship_kwargs={"order_by": "CePost.id"},
    )
    # 跨边界关系（orders）不在实体上声明 —— 组合体层集中声明（DD-02）


class CePost(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="ceuser.id")
    author: CeUser = Relationship(back_populates="posts")


class CeOrder(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int  # 跨库逻辑外键 → ceuser.id（不建 SQL FK）
    total: float
    items: list["CeOrderItem"] = Relationship(
        back_populates="order",
        sa_relationship_kwargs={"order_by": "CeOrderItem.id"},
    )


class CeOrderItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="ceorder.id")
    qty: int
    order: CeOrder = Relationship(back_populates="items")


class CeStranger(SQLModel, table=True):
    """未注册的实体（用于构造校验测试，不进任一 member）。"""
    id: int | None = Field(default=None, primary_key=True)


# ── 跨边界 loader（用 shop session；spike 模式：module-global holder）──
_shop_sf_holder: dict = {}


async def orders_by_user_id(user_ids: list[int]) -> list[list[CeOrder]]:
    sf = _shop_sf_holder["sf"]
    async with sf() as session:
        result = await session.exec(
            select(CeOrder).where(CeOrder.user_id.in_(user_ids))
        )
        orders = list(result.all())
    by_user: dict[int, list[CeOrder]] = {}
    for o in orders:
        by_user.setdefault(o.user_id, []).append(o)
    return [by_user.get(uid, []) for uid in user_ids]


# ── DTO ──

class CePostDTO(DefineSubset):
    __subset__ = (CePost, ("id", "title", "author_id"))


class CeOrderItemDTO(DefineSubset):
    __subset__ = (CeOrderItem, ("id", "qty"))


class CeOrderDTO(DefineSubset):
    __subset__ = (CeOrder, ("id", "total", "user_id"))
    items: list[CeOrderItemDTO] = []


class CeUserDTO(DefineSubset):
    __subset__ = (CeUser, ("id", "name"))
    posts: list[CePostDTO] = []
    orders: list[CeOrderDTO] = []


# ── fixture：两 engine + 数据 + 组合体 ──

@pytest_asyncio.fixture
async def composed_world():
    blog_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool
    )
    shop_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool
    )
    blog_sf = async_sessionmaker(blog_engine, class_=AsyncSession, expire_on_commit=False)
    shop_sf = async_sessionmaker(shop_engine, class_=AsyncSession, expire_on_commit=False)
    _shop_sf_holder["sf"] = shop_sf

    async with blog_engine.begin() as c:
        await c.run_sync(SQLModel.metadata.create_all)
    async with shop_engine.begin() as c:
        await c.run_sync(SQLModel.metadata.create_all)

    # blog 数据：Alice/Bob + Alice 2 posts
    async with blog_sf() as s:
        alice = CeUser(name="Alice")
        bob = CeUser(name="Bob")
        s.add(alice)
        s.add(bob)
        await s.commit()
        await s.refresh(alice)
        await s.refresh(bob)
        s.add(CePost(title="P1", author_id=alice.id))
        s.add(CePost(title="P2", author_id=alice.id))
        await s.commit()
        alice_id, bob_id = alice.id, bob.id

    # shop 数据：Alice 2 单(100/200) + Bob 1 单(50)，Alice 首单 2 items
    async with shop_sf() as s:
        o1 = CeOrder(user_id=alice_id, total=100.0)
        o2 = CeOrder(user_id=alice_id, total=200.0)
        o3 = CeOrder(user_id=bob_id, total=50.0)
        s.add_all([o1, o2, o3])
        await s.commit()
        for o in (o1, o2, o3):
            await s.refresh(o)
        s.add(CeOrderItem(order_id=o1.id, qty=1))
        s.add(CeOrderItem(order_id=o1.id, qty=2))
        await s.commit()

    blog_er = ErManager(session_factory=blog_sf, entities=[CeUser, CePost])
    shop_er = ErManager(session_factory=shop_sf, entities=[CeOrder, CeOrderItem])
    composed = ComposedErManager(
        members=[blog_er, shop_er],
        cross_relationships=[
            (
                CeUser,
                NxRelationship(
                    fk="id",
                    target=list[CeOrder],
                    name="orders",
                    loader=orders_by_user_id,
                    description="跨库：blog.CeUser → shop.CeOrder",
                ),
            )
        ],
    )

    yield {
        "composed": composed,
        "blog_er": blog_er,
        "shop_er": shop_er,
        "blog_sf": blog_sf,
        "alice_id": alice_id,
        "bob_id": bob_id,
    }

    await blog_engine.dispose()
    await shop_engine.dispose()


# ── US1：跨 engine resolve ──

async def test_cross_engine_resolve(composed_world):
    """一次 resolve 跨两个 engine：同库 posts + 跨库 orders + 跨库二级钻取 items。"""
    composed = composed_world["composed"]
    blog_sf = composed_world["blog_sf"]

    Resolver = composed.create_resolver()
    resolver = Resolver()

    async with blog_sf() as s:
        result = await s.exec(select(CeUser).order_by(CeUser.id))
        # root DTO 只填 subset 标量字段（勿 model_validate orm —— 触发 lazy load）
        root = [CeUserDTO(id=u.id, name=u.name) for u in result.all()]

    resolved = await resolver.resolve(root)
    alice = next(u for u in resolved if u.name == "Alice")
    bob = next(u for u in resolved if u.name == "Bob")

    # 同库 ORM 关系（blog session）
    assert [p.title for p in alice.posts] == ["P1", "P2"]
    # 跨 engine 桥（shop session）
    assert [o.total for o in alice.orders] == [100.0, 200.0]
    assert [o.total for o in bob.orders] == [50.0]
    # 跨库二级钻取（shop session，委托 shop_er）
    assert [it.qty for o in alice.orders for it in o.items] == [1, 2]


async def test_root_dto_subset_only_not_model_validate(composed_world):
    """root DTO 用显式标量构造（不 model_validate orm），关系留给 auto-load。"""
    composed = composed_world["composed"]
    blog_sf = composed_world["blog_sf"]
    Resolver = composed.create_resolver()
    resolver = Resolver()

    async with blog_sf() as s:
        result = await s.exec(select(CeUser).where(CeUser.name == "Alice"))
        alice = result.first()
        root = [CeUserDTO(id=alice.id, name=alice.name)]

    resolved = await resolver.resolve(root)
    assert resolved[0].name == "Alice"
    assert [p.title for p in resolved[0].posts] == ["P1", "P2"]


# ── US2：跨 engine ER 图合并 ──

async def test_er_diagram_merge(composed_world):
    """ErDiagram.from_er_manager(composed) 含全部实体 + 跨库边（0 改动 ErDiagram）。"""
    composed = composed_world["composed"]
    diagram = ErDiagram.from_er_manager(composed)
    mermaid = diagram.to_mermaid()

    names = {e.name for e in diagram.entities}
    assert {"CeUser", "CePost", "CeOrder", "CeOrderItem"} <= names

    rels = {
        (r.source, r.target)
        for e in diagram.entities
        for r in e.relationships
    }
    assert ("CeUser", "CeOrder") in rels  # 跨库边（组合体叠加层）
    assert ("CeUser", "CePost") in rels  # 同库边
    assert ("CeOrder", "CeOrderItem") in rels
    assert "CeUser ||--o{ CeOrder : orders" in mermaid


# ── US4：跨边界关系声明（组合体层）+ 构造校验 ──

async def test_cross_rel_in_composed_layer_members_unaware(composed_world):
    """跨边界关系在组合体层声明，成员 ErManager 对其无感（DD-02）。"""
    composed = composed_world["composed"]
    blog_er = composed_world["blog_er"]

    composed_rels = composed.get_relationships(CeUser)
    assert "orders" in composed_rels
    assert "posts" in composed_rels

    # blog_er 单独看不到 orders（成员无感 = 单独使用纯粹）
    blog_rels = blog_er.get_relationships(CeUser)
    assert "orders" not in blog_rels
    assert "posts" in blog_rels


async def test_construct_empty_members():
    """空 members → ValueError（FR-016）。"""
    with pytest.raises(ValueError, match="at least one member"):
        ComposedErManager(members=[])


async def test_construct_duplicate_entity(composed_world):
    """同一实体被多 member 注册 → ValueError（FR-014）。"""
    blog_er = composed_world["blog_er"]
    other_er = ErManager(
        session_factory=composed_world["blog_sf"], entities=[CeUser]
    )
    with pytest.raises(ValueError, match="multiple members"):
        ComposedErManager(members=[blog_er, other_er])


async def test_construct_cross_target_missing(composed_world):
    """跨边界 target 不在任一 member → ValueError（FR-008）。"""
    blog_er = composed_world["blog_er"]

    async def _noop(keys):
        return [[] for _ in keys]

    with pytest.raises(ValueError, match="target"):
        ComposedErManager(
            members=[blog_er],
            cross_relationships=[
                (CeUser, NxRelationship(
                    fk="id", target=list[CeStranger], name="x", loader=_noop))
            ],
        )


async def test_construct_cross_source_missing(composed_world):
    """跨边界 source 不在任一 member → ValueError（FR-008）。"""
    blog_er = composed_world["blog_er"]

    async def _noop(keys):
        return [[] for _ in keys]

    with pytest.raises(ValueError, match="source"):
        ComposedErManager(
            members=[blog_er],
            cross_relationships=[
                (CeStranger, NxRelationship(
                    fk="id", target=list[CeUser], name="x", loader=_noop))
            ],
        )


async def test_construct_cross_name_collides_local(composed_world):
    """cross 关系名撞 member 本地关系 → ValueError（#8）。

    构造期 fail-fast，避免 get_relationships 静默用 cross 顶替本地 ORM 关系。
    CeUser.posts 是 blog_er 的本地 ORM 关系；声明同名 cross 必须报错。
    """
    blog_er = composed_world["blog_er"]

    async def _noop(keys):
        return [[] for _ in keys]

    with pytest.raises(ValueError, match="shadows a member-local"):
        ComposedErManager(
            members=[blog_er],
            cross_relationships=[
                (CeUser, NxRelationship(
                    fk="id", target=list[CePost], name="posts", loader=_noop)),
            ],
        )


async def test_composed_satisfies_loader_registry_protocol(composed_world):
    """ComposedErManager 满足 LoaderRegistry Protocol（runtime checkable）。"""
    from nexusx.loader import LoaderRegistry

    composed = composed_world["composed"]
    assert isinstance(composed, LoaderRegistry)
    assert isinstance(composed_world["blog_er"], LoaderRegistry)


async def test_clear_cache_aggregates_members(composed_world):
    """clear_cache 聚合所有成员 + 清跨边界 loader 缓存。"""
    composed = composed_world["composed"]
    composed.get_loader_for_entity(CeUser, "posts")
    composed.get_loader_for_entity(CeUser, "orders")  # 跨边界 loader
    assert composed._cross_loader_cache

    composed.clear_cache()
    assert not composed._cross_loader_cache


async def test_paginated_loader_reachable_through_compose(composed_world):
    """member 分页关系（page_loader）经组合体 get_loader 可取（回归 #1）。

    page_loader 是与 loader 不同的独立类；组合体的路由表/动态查找须同时覆盖
    loader 与 page_loader，否则分页查询路径 composed.get_loader(page_loader)
    会 KeyError。CeUser.posts 带 order_by="CePost.id" → 构造期已生成 page_loader。
    """
    composed = composed_world["composed"]
    blog_er = composed_world["blog_er"]

    rel_info = composed.get_relationship(CeUser, "posts")
    assert rel_info.page_loader is not None  # order_by 触发独立分页 loader 类

    # 组合体层面取 page_loader 实例（修复前这里 KeyError）
    page_loader = composed.get_loader(rel_info.page_loader)
    assert page_loader is not None

    # 委托正确：与直接走 member 取到同一缓存实例（同一 owner.get_loader）
    member_page = blog_er.get_loader(rel_info.page_loader)
    assert page_loader is member_page


# ── get_loader_by_name 跨 member ambiguity（#5）──

async def test_get_loader_by_name_ambiguous_across_members(composed_world):
    """跨 member 同名关系 → ambiguity 错，不静默首个获胜（#5）。

    与 ErManager 单 member 内同名抛 ValueError 的安全网对齐：跨 engine 同名
    （如 owner/tags）若静默首个，会用 A engine 的 session 取本该走 B 的关系。
    """
    sf = composed_world["blog_sf"]

    async def _noop(keys):
        return [None for _ in keys]

    class CeAmbA(SQLModel, table=True):
        __tablename__ = "ce_amb_a"
        id: int | None = Field(default=None, primary_key=True)
        __relationships__ = [NxRelationship(
            fk="id", target=list[CePost], name="shared", loader=_noop)]

    class CeAmbB(SQLModel, table=True):
        __tablename__ = "ce_amb_b"
        id: int | None = Field(default=None, primary_key=True)
        __relationships__ = [NxRelationship(
            fk="id", target=list[CePost], name="shared", loader=_noop)]

    er_a = ErManager(session_factory=sf, entities=[CeAmbA])
    er_b = ErManager(session_factory=sf, entities=[CeAmbB])
    composed = ComposedErManager(members=[er_a, er_b])

    with pytest.raises(ValueError, match="Ambiguous"):
        composed.get_loader_by_name("shared")


async def test_get_loader_by_name_unique_still_works(composed_world):
    """单来源唯一命中时 get_loader_by_name 正常返回（#5 回归保护）。"""
    composed = composed_world["composed"]
    # blog_er 独占 "posts" 关系
    loader = composed.get_loader_by_name("posts")
    assert loader is not None


# ── version 聚合对任意成员变化单调（#4）──

async def test_version_reflects_any_member_bump(composed_world):
    """version 聚合须对任意成员变化单调（#4）。

    GraphQLHandler 以 er_manager.version 作 SDL/introspection 缓存 key。
    用 max 时高版本 member 主导，低版本 member federate（version+1）不改变
    max → 缓存不刷新、schema 缺新物化的 remote type。sum 在只增语义下严格单调。
    """
    blog_er = composed_world["blog_er"]
    shop_er = composed_world["shop_er"]
    composed = composed_world["composed"]

    # 模拟 blog_er 历史多次 federate（高版本主导），shop_er 尚未 federate
    blog_er._version = 5
    shop_er._version = 0
    v0 = composed.version              # sum=5

    shop_er._version = 1               # 低版本 member「federate」
    v1 = composed.version              # sum=6（max 仍为 5 → 旧逻辑漏检）

    assert v1 != v0, "低版本 member 变化后组合体 version 必须变化"
    assert v1 == 6


# ── get_loader_by_name / get_loader 边界分支覆盖 ──

async def test_get_loader_by_name_cross_only(composed_world):
    """cross 层独有的关系名经 get_loader_by_name 能取到（cross-only 命中分支）。"""
    composed = composed_world["composed"]
    loader = composed.get_loader_by_name("orders")  # orders 仅在跨边界层
    assert loader is not None


async def test_get_loader_by_name_missing_returns_none(composed_world):
    """不存在的关系名 → None（total==0 分支）。"""
    composed = composed_world["composed"]
    assert composed.get_loader_by_name("nonexistent_rel") is None


async def test_get_loader_cross_loader_class(composed_world):
    """get_loader(cross_loader_cls) 取组合体自持的跨边界 loader（cross 分支）。"""
    composed = composed_world["composed"]
    rel_info = composed.get_relationship(CeUser, "orders")
    loader = composed.get_loader(rel_info.loader)  # cross loader 类 → _cross_loader_classes
    assert loader is not None


async def test_get_loader_unknown_class_raises_keyerror(composed_world):
    """不属于任何 member/cross 的 loader 类 → KeyError。"""
    composed = composed_world["composed"]

    class _Unknown(DataLoader):
        async def batch_load_fn(self, keys):
            return [None] * len(keys)

    with pytest.raises(KeyError):
        composed.get_loader(_Unknown)
