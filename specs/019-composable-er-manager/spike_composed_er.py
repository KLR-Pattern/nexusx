"""Spike: 验证 ComposedErManager 能产出"总代理 Resolver"，跨两个 db engine 一次 resolve。

目标：证明「可组合 ErManager」这条路成立 ——
  - 两个独立 engine（blog SQLite + shop SQLite）
  - 各自一个自洽的 ErManager（loader 焊死自己的 session）
  - ComposedErManager 按 entity 委托
  - ComposedErManager.create_resolver() 出一个 Resolver，一次 resolve 跨 engine 的树

这不是生产代码，只为验证代理机制 + 统一 Resolver 是否零摩擦。
非核心简化：两个 db 都建了全部表 schema，但只在各自 db 写各自数据 ——
spike 要验证的是 session 路由，不是 metadata 物理隔离。
"""

# 注意：不能用 `from __future__ import annotations` —— SQLModel 的
# Relationship 字段（list["Post"]）在延迟注解下会被当成 relationship
# 字符串参数解析失败（multi_app/models.py 也不用它）。

import asyncio
import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, Relationship, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx.loader.registry import ErManager
from nexusx.relationship import Relationship as NxRelationship
from nexusx.subset import DefineSubset


# ──────────────────────────────────────────────────────────
# 实体定义：blog 组（User/Post） + shop 组（Order/OrderItem）
# 两组分别落在不同 engine。User→Order 是跨库逻辑外键。
# ──────────────────────────────────────────────────────────

class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    # 同库 ORM 关系（blog session）
    posts: list["Post"] = Relationship(
        back_populates="author",
        sa_relationship_kwargs={"order_by": "Post.id"},
    )
    # 跨库关系稍后动态赋值（需要 Order 类已定义）


class Post(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="user.id")
    author: User = Relationship(back_populates="posts")


class Order(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    # 跨库逻辑外键 —— 指向 blog.User.id，但这里不建 SQL FK
    user_id: int
    total: float
    # 同库 ORM 关系（shop session）
    items: list["OrderItem"] = Relationship(
        back_populates="order",
        sa_relationship_kwargs={"order_by": "OrderItem.id"},
    )


class OrderItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="order.id")
    qty: int
    order: Order = Relationship(back_populates="items")


# 跨库 loader 的 shop session —— main() 里赋值
_shop_sf: async_sessionmaker | None = None


async def orders_by_user_id(user_ids: list[int]) -> list[list[Order]]:
    """跨库 batch loader：blog.User.id → shop.Order（用 shop session）。

    这就是「跨 engine 桥」—— loader 是用户函数，内部自由选用 session。
    """
    assert _shop_sf is not None
    async with _shop_sf() as session:
        result = await session.exec(select(Order).where(Order.user_id.in_(user_ids)))
        orders = list(result.all())
    by_user: dict[int, list[Order]] = {}
    for o in orders:
        by_user.setdefault(o.user_id, []).append(o)
    return [by_user.get(uid, []) for uid in user_ids]


# 动态赋跨库关系：User.orders 的 target 必须是真实类（不能字符串前向引用）
User.__relationships__ = [  # type: ignore[attr-defined]
    NxRelationship(
        fk="id",
        target=list[Order],
        name="orders",
        loader=orders_by_user_id,
        description="跨库：blog.User → shop.Order（shop session）",
    )
]


# ──────────────────────────────────────────────────────────
# ComposedErManager —— 按 entity 委托的总代理
# 实现 Resolver 对 registry 的全部 9 个访问点。
# ──────────────────────────────────────────────────────────

class ComposedErManager:
    """组合多个自洽 ErManager 的只读总代理，满足 LoaderRegistry 协议。

    核心是 _route：entity → 它所属的子 ErManager。所有按 entity 的查询
    委托过去；loader class 反向路由；clear_cache 聚合。
    """

    def __init__(self, members: list[ErManager]):
        self._members = members
        self._route: dict[type, ErManager] = {}
        # loader_cls → 拥有它的 member（反向路由，避免 get_loader 缓存污染）
        self._loader_owner: dict[type, ErManager] = {}
        for m in members:
            for cls in m.get_all_entities():
                self._route[cls] = m
            for _entity, rels in m.get_all_relationships().items():
                for rel_info in rels.values():
                    self._loader_owner[rel_info.loader] = m

    def _member_for(self, entity: type) -> ErManager | None:
        return self._route.get(entity)

    # — Resolver 依赖的查询接口（按 entity 路由）—

    def has_entity(self, entity: type) -> bool:
        return entity in self._route

    def get_relationships(self, entity):
        m = self._member_for(entity)
        return m.get_relationships(entity) if m else {}

    def get_relationship(self, entity, name):
        m = self._member_for(entity)
        return m.get_relationship(entity, name) if m else None

    def get_loader_for_entity(self, entity, rel_name, type_key=None):
        m = self._member_for(entity)
        return m.get_loader_for_entity(entity, rel_name, type_key) if m else None

    # — 按 name / 按 class 的兜底路由 —

    def get_loader_by_name(self, name, type_key=None):
        for m in self._members:
            loader = m.get_loader_by_name(name, type_key)
            if loader is not None:
                return loader
        return None

    def get_loader(self, loader_cls, type_key=None, force_split=False, params_key=None):
        owner = self._loader_owner.get(loader_cls)
        if owner is None:
            raise KeyError(f"loader_cls {loader_cls!r} 不属于任何成员 ErManager")
        return owner.get_loader(loader_cls, type_key, force_split, params_key)

    # — federation / 高级（spike 不碰，返回中性值）—

    def get_dto_loader(self, owner_dto, field_name=None):
        return None

    @property
    def _split_mode(self):
        return False

    @property
    def _fed_registry(self):
        return None

    # — 生命周期 / 缓存 —

    def clear_cache(self):
        for m in self._members:
            m.clear_cache()

    # — ER 图用（顺带验证组合体能喂 ErDiagramDotBuilder，虽非本 spike 重点）—

    def get_all_entities(self):
        return list(self._route.keys())

    def get_all_relationships(self):
        merged: dict = {}
        for m in self._members:
            merged.update(m.get_all_relationships())
        return merged

    # — 产出总代理 Resolver（照搬 ErManager.create_resolver 的 5 行）—

    def create_resolver(self):
        from nexusx.resolver import Resolver as _Resolver

        composed = self

        class BoundResolver(_Resolver):
            def __init__(self, context=None, loader_instances=None):
                super().__init__(
                    loader_registry=composed,
                    context=context,
                    loader_instances=loader_instances,
                )

        BoundResolver.__name__ = "Resolver"
        BoundResolver.__qualname__ = "Resolver"
        return BoundResolver


# ──────────────────────────────────────────────────────────
# DTO（DefineSubset）—— auto-load 会按 source entity 的关系名匹配字段
# ──────────────────────────────────────────────────────────

class PostDTO(DefineSubset):
    __subset__ = (Post, ("id", "title", "author_id"))


class OrderItemDTO(DefineSubset):
    __subset__ = (OrderItem, ("id", "qty"))


class OrderDTO(DefineSubset):
    __subset__ = (Order, ("id", "total", "user_id"))
    items: list[OrderItemDTO] = []  # auto-load → shop Order.items（shop session）


class UserDTO(DefineSubset):
    __subset__ = (User, ("id", "name"))
    posts: list[PostDTO] = []   # auto-load → blog User.posts（blog session）
    orders: list[OrderDTO] = []  # auto-load → 跨库 User.orders（shop session）


# ──────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────

async def main():
    global _shop_sf

    for f in ("spike_blog.db", "spike_shop.db"):
        if os.path.exists(f):
            os.remove(f)

    blog_engine = create_async_engine("sqlite+aiosqlite:///./spike_blog.db", echo=False)
    shop_engine = create_async_engine("sqlite+aiosqlite:///./spike_shop.db", echo=False)
    blog_sf = async_sessionmaker(blog_engine, class_=AsyncSession, expire_on_commit=False)
    shop_sf = async_sessionmaker(shop_engine, class_=AsyncSession, expire_on_commit=False)
    _shop_sf = shop_sf  # 供跨库 loader 使用

    # 建表（两组都在全局 metadata，两个 db 都建全部表；数据按库分离）
    async with blog_engine.begin() as c:
        await c.run_sync(SQLModel.metadata.create_all)
    async with shop_engine.begin() as c:
        await c.run_sync(SQLModel.metadata.create_all)

    # ── blog 库：2 user, 2 post ──
    async with blog_sf() as s:
        alice = User(name="Alice")
        bob = User(name="Bob")
        s.add(alice)
        s.add(bob)
        await s.commit()
        await s.refresh(alice)
        await s.refresh(bob)
        s.add(Post(title="P1", author_id=alice.id))
        s.add(Post(title="P2", author_id=alice.id))
        await s.commit()
        alice_id, bob_id = alice.id, bob.id

    # ── shop 库：Alice 2 单（100/200）+ Bob 1 单（50），Alice 第一单 2 个 item ──
    async with shop_sf() as s:
        o1 = Order(user_id=alice_id, total=100.0)
        o2 = Order(user_id=alice_id, total=200.0)
        o3 = Order(user_id=bob_id, total=50.0)
        s.add_all([o1, o2, o3])
        await s.commit()
        for o in (o1, o2, o3):
            await s.refresh(o)
        s.add(OrderItem(order_id=o1.id, qty=1))
        s.add(OrderItem(order_id=o1.id, qty=2))
        await s.commit()

    # ── 两个自洽 ErManager：loader 各自焊死自己的 session ──
    blog_er = ErManager(session_factory=blog_sf, entities=[User, Post])
    shop_er = ErManager(session_factory=shop_sf, entities=[Order, OrderItem])

    # ── 组合 ──
    composed = ComposedErManager([blog_er, shop_er])
    print("组合体路由表：")
    for cls, m in composed._route.items():
        print(f"  {cls.__name__:12} → {id(m):x}")

    # ── 总代理 Resolver ──
    ResolverCls = composed.create_resolver()
    resolver = ResolverCls()

    # root 数据从 blog 取（User 活在 blog 库）。只填 subset 标量字段 ——
    # 不能用 model_validate(orm)：pydantic 会碰 posts 字段触发 SQLAlchemy
    # detached lazy load。关系字段（posts/orders）留给 resolver auto-load 填。
    async with blog_sf() as s:
        result = await s.exec(select(User).order_by(User.id))
        root = [UserDTO(id=u.id, name=u.name) for u in result.all()]

    resolved = await resolver.resolve(root)

    # ── 断言：一次 resolve 跨了两个 engine ──
    print("\n=== resolve 结果 ===")
    for u in resolved:
        post_titles = [p.title for p in u.posts]
        order_totals = [o.total for o in u.orders]
        item_qtys = [it.qty for o in u.orders for it in o.items]
        print(
            f"{u.name}: posts={post_titles}  orders={order_totals}  "
            f"items(跨库钻取)={item_qtys}"
        )

    alice_dto = next(u for u in resolved if u.name == "Alice")
    bob_dto = next(u for u in resolved if u.name == "Bob")

    ok = True
    def check(cond, msg):
        nonlocal ok
        mark = "✅" if cond else "❌"
        print(f"  {mark} {msg}")
        ok = ok and cond

    print("\n=== 断言 ===")
    check([p.title for p in alice_dto.posts] == ["P1", "P2"], "Alice 同库 posts（blog session）= [P1, P2]")
    check([o.total for o in alice_dto.orders] == [100.0, 200.0], "Alice 跨库 orders（shop session）= [100, 200]")
    check([o.total for o in bob_dto.orders] == [50.0], "Bob 跨库 orders = [50]")
    check(
        [it.qty for o in alice_dto.orders for it in o.items] == [1, 2],
        "Alice orders.items 跨库二级钻取（shop session）= [1, 2]",
    )

    print(f"\n{'SPIKE 通过 ✅ —— 总代理 Resolver 跨 engine resolve 成立' if ok else 'SPIKE 失败 ❌'}")

    # ── 顺带验证原始诉求：ComposedErManager 喂现成 ER 图，跨 engine 实体同图 ──
    from nexusx.er_diagram import ErDiagram

    diagram = ErDiagram.from_er_manager(composed)
    mermaid = diagram.to_mermaid()
    print("\n=== ER 图（mermaid，直接来自 ComposedErManager）===")
    print(mermaid)
    names = {e.name for e in diagram.entities}
    rels = sorted({(r.source, r.target) for e in diagram.entities for r in e.relationships})
    print(f"图含实体: {sorted(names)}")
    print(f"图含关系: {rels}")
    er_ok = (
        {"User", "Post", "Order", "OrderItem"} <= names
        and ("User", "Order") in [(s, t) for s, t in rels]
    )
    print(
        f"{'✅ ER 图含 4 个跨 engine 实体 + 跨库 User→Order 边' if er_ok else '❌ ER 图缺失'}"
    )

    await blog_engine.dispose()
    await shop_engine.dispose()
    for f in ("spike_blog.db", "spike_shop.db"):
        if os.path.exists(f):
            os.remove(f)


if __name__ == "__main__":
    asyncio.run(main())
