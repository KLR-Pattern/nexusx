"""Database setup for the ComposedErManager demo.

Two SQLite engines (blog + shop) in one process, each with its own session
factory. The ComposedErManager (``app.py``) combines their ErManagers so a
single query resolves across both engines, in-process — no HTTP bridge.
"""

from contextlib import asynccontextmanager

from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from .models import CmBlogBase, CmOrder, CmOrderItem, CmPost, CmShopBase, CmUser

blog_engine = create_async_engine(f"sqlite+aiosqlite:///{Path(__file__).parent / 'cm_blog.db'}", echo=False)
blog_async_session = async_sessionmaker(
    blog_engine, class_=AsyncSession, expire_on_commit=False
)

shop_engine = create_async_engine(f"sqlite+aiosqlite:///{Path(__file__).parent / 'cm_shop.db'}", echo=False)
shop_async_session = async_sessionmaker(
    shop_engine, class_=AsyncSession, expire_on_commit=False
)


@asynccontextmanager
async def get_blog_session():
    async with blog_async_session() as s:
        yield s


@asynccontextmanager
async def get_shop_session():
    async with shop_async_session() as s:
        yield s


async def init_databases() -> None:
    """Create tables in both engines and seed sample data (idempotent)."""
    async with blog_engine.begin() as c:
        await c.run_sync(CmBlogBase.metadata.create_all)
    async with shop_engine.begin() as c:
        await c.run_sync(CmShopBase.metadata.create_all)
    await _add_sample_data()


async def _add_sample_data() -> None:
    # Blog: Alice/Bob + a couple of Alice's posts.
    async with get_blog_session() as s:
        if (await s.exec(select(CmUser).limit(1))).first() is None:
            alice = CmUser(name="Alice", email="alice@example.com")
            bob = CmUser(name="Bob", email="bob@example.com")
            s.add(alice)
            s.add(bob)
            await s.commit()
            await s.refresh(alice)
            await s.refresh(bob)
            s.add(CmPost(title="First post", content="hello", author_id=alice.id))
            s.add(CmPost(title="Second post", content="world", author_id=alice.id))
            await s.commit()

    # Resolve user ids so the shop orders can link to them by logical FK.
    async with get_blog_session() as s:
        alice = (await s.exec(select(CmUser).where(CmUser.name == "Alice"))).first()
        bob = (await s.exec(select(CmUser).where(CmUser.name == "Bob"))).first()
        alice_id, bob_id = alice.id, bob.id

    # Shop: orders linked to blog users by user_id, plus items on Alice's first order.
    async with get_shop_session() as s:
        if (await s.exec(select(CmOrder).limit(1))).first() is None:
            o1 = CmOrder(user_id=alice_id, total=99.9)
            o2 = CmOrder(user_id=alice_id, total=19.9)
            o3 = CmOrder(user_id=bob_id, total=5.0)
            s.add_all([o1, o2, o3])
            await s.commit()
            for o in (o1, o2, o3):
                await s.refresh(o)
            s.add(CmOrderItem(order_id=o1.id, qty=1))
            s.add(CmOrderItem(order_id=o1.id, qty=2))
            await s.commit()
