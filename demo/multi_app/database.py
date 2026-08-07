"""Database configuration for multi-app demo.

This module provides separate database sessions for Blog and Shop applications.
Each application uses its own SQLite database file.
"""

from contextlib import asynccontextmanager

from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from .models import BlogBaseEntity, Order, OrderItem, Post, Product, ShopBaseEntity, User

# Blog application database
BLOG_DATABASE_URL = f"sqlite+aiosqlite:///{Path(__file__).parent / 'blog.db'}"
blog_engine = create_async_engine(BLOG_DATABASE_URL, echo=False)
blog_async_session = async_sessionmaker(
    blog_engine, class_=AsyncSession, expire_on_commit=False
)

# Shop application database
SHOP_DATABASE_URL = f"sqlite+aiosqlite:///{Path(__file__).parent / 'shop.db'}"
shop_engine = create_async_engine(SHOP_DATABASE_URL, echo=False)
shop_async_session = async_sessionmaker(
    shop_engine, class_=AsyncSession, expire_on_commit=False
)


@asynccontextmanager
async def get_blog_session():
    """Get database session for Blog application."""
    async with blog_async_session() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def get_shop_session():
    """Get database session for Shop application."""
    async with shop_async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_databases():
    """Initialize both databases and create tables."""
    # Create Blog database tables
    async with blog_engine.begin() as conn:
        await conn.run_sync(BlogBaseEntity.metadata.create_all)

    # Create Shop database tables
    async with shop_engine.begin() as conn:
        await conn.run_sync(ShopBaseEntity.metadata.create_all)

    # Add some initial data
    await add_sample_data()


async def add_sample_data():
    """Add sample data to both databases."""
    # Add Blog sample data
    async with get_blog_session() as session:
        # Check if users already exist
        result = await session.exec(select(User).limit(1))
        if result.first() is None:
            # Add users
            user1 = User(name="Alice", email="alice@example.com")
            user2 = User(name="Bob", email="bob@example.com")
            session.add(user1)
            session.add(user2)
            await session.commit()
            await session.refresh(user1)
            await session.refresh(user2)

            # Add posts
            post1 = Post(
                title="First Post", content="Hello World!", author_id=user1.id
            )
            post2 = Post(
                title="GraphQL is Great", content="Let's talk about GraphQL", author_id=user1.id
            )
            post3 = Post(title="SQLModel Tips", content="Best practices", author_id=user2.id)
            session.add(post1)
            session.add(post2)
            session.add(post3)
            await session.commit()

    # Add Shop sample data
    async with get_shop_session() as session:
        # Check if products already exist
        result = await session.exec(select(Product).limit(1))
        if result.first() is None:
            # Add products
            product1 = Product(name="Laptop", price=999.99, stock=10)
            product2 = Product(name="Mouse", price=29.99, stock=50)
            product3 = Product(name="Keyboard", price=79.99, stock=30)
            session.add(product1)
            session.add(product2)
            session.add(product3)
            await session.commit()
            await session.refresh(product1)
            await session.refresh(product2)
            await session.refresh(product3)

            # Add orders
            order1 = Order(customer_name="Alice")
            order2 = Order(customer_name="Bob")
            session.add(order1)
            session.add(order2)
            await session.commit()
            await session.refresh(order1)
            await session.refresh(order2)

            # Add order items
            item1 = OrderItem(
                order_id=order1.id, product_id=product1.id, quantity=1, unit_price=product1.price
            )
            item2 = OrderItem(
                order_id=order1.id, product_id=product2.id, quantity=2, unit_price=product2.price
            )
            item3 = OrderItem(
                order_id=order2.id, product_id=product3.id, quantity=1, unit_price=product3.price
            )
            session.add(item1)
            session.add(item2)
            session.add(item3)

            # Update order totals
            order1.total_amount = product1.price * 1 + product2.price * 2
            order2.total_amount = product3.price * 1

            # Update product stock
            product1.stock -= 1
            product2.stock -= 2
            product3.stock -= 1

            await session.commit()
