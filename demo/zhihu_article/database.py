"""Database configuration and seed data for the order system demo."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from demo.zhihu_article.models import Customer, Order, OrderItem, Product, Review

engine = create_async_engine("sqlite+aiosqlite:///zhihu_demo.db", echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create tables and seed initial data."""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async with async_session() as session:
        existing = await session.exec(select(Customer))
        if existing.first():
            return

        # --- Customers ---
        customers = [
            Customer(name="张三", email="zhangsan@example.com", tier="gold"),
            Customer(name="李四", email="lisi@example.com", tier="regular"),
            Customer(name="王五", email="wangwu@example.com", tier="silver"),
        ]
        for c in customers:
            session.add(c)
        await session.commit()
        for c in customers:
            await session.refresh(c)

        # --- Products ---
        products = [
            Product(name="MacBook Pro 14", price=14999.0, category="electronics"),
            Product(name="iPhone 16 Pro", price=8999.0, category="electronics"),
            Product(name="AirPods Pro", price=1899.0, category="electronics"),
            Product(name="机械键盘", price=699.0, category="accessories"),
            Product(name="显示器支架", price=299.0, category="accessories"),
        ]
        for p in products:
            session.add(p)
        await session.commit()
        for p in products:
            await session.refresh(p)

        # --- Orders ---
        orders = [
            Order(
                customer_id=customers[0].id,
                status="pending",
                total_amount=16898.0,
                created_at="2024-01-15",
            ),
            Order(
                customer_id=customers[0].id,
                status="shipped",
                total_amount=8999.0,
                created_at="2024-01-10",
            ),
            Order(
                customer_id=customers[1].id,
                status="pending",
                total_amount=2598.0,
                created_at="2024-01-14",
            ),
            Order(
                customer_id=customers[2].id,
                status="shipped",
                total_amount=14999.0,
                created_at="2024-01-12",
            ),
            Order(
                customer_id=customers[2].id,
                status="cancelled",
                total_amount=699.0,
                created_at="2024-01-08",
            ),
        ]
        for o in orders:
            session.add(o)
        await session.commit()
        for o in orders:
            await session.refresh(o)

        # --- Order Items ---
        items_data = [
            (orders[0].id, products[0].id, 1, 14999.0),
            (orders[0].id, products[2].id, 1, 1899.0),
            (orders[1].id, products[1].id, 1, 8999.0),
            (orders[2].id, products[2].id, 1, 1899.0),
            (orders[2].id, products[3].id, 1, 699.0),
            (orders[3].id, products[0].id, 1, 14999.0),
            (orders[4].id, products[3].id, 1, 699.0),
        ]
        for order_id, product_id, quantity, unit_price in items_data:
            session.add(OrderItem(order_id=order_id, product_id=product_id, quantity=quantity, unit_price=unit_price))
        await session.commit()

        # --- Reviews (simulates external review service data) ---
        reviews = [
            Review(product_id=products[0].id, rating=5, comment="性能强劲，完全够用", reviewer_name="数码达人"),
            Review(product_id=products[0].id, rating=4, comment="续航可以再好一点", reviewer_name="极客用户"),
            Review(product_id=products[1].id, rating=5, comment="拍照效果惊艳", reviewer_name="摄影爱好者"),
            Review(product_id=products[2].id, rating=4, comment="降噪效果不错", reviewer_name="通勤党"),
            Review(product_id=products[2].id, rating=5, comment="佩戴舒适", reviewer_name="音乐迷"),
            Review(product_id=products[3].id, rating=3, comment="手感还行，轴体一般", reviewer_name="外设控"),
        ]
        for r in reviews:
            session.add(r)
        await session.commit()
