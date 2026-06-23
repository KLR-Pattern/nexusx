"""Database engine + session factory (no model imports).

This module is safe to import from both models.py and database.py.
"""
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

engine = create_async_engine("sqlite+aiosqlite://", echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
