"""User domain — independent business methods."""
from sqlmodel import select

from src.db import async_session
from src.models import User


async def list_users() -> list[User]:
    """获取所有用户。"""
    async with async_session() as session:
        result = await session.exec(select(User))
        return list(result.all())


async def create_user(name: str) -> User:
    """创建新用户。"""
    async with async_session() as session:
        user = User(name=name)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user
