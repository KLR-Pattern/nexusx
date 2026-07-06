"""Sprint domain — independent business methods."""
from sqlmodel import select

from src.db import async_session
from src.models import Sprint


async def list_sprints() -> list[Sprint]:
    """获取所有 Sprint。"""
    async with async_session() as session:
        result = await session.exec(select(Sprint))
        return list(result.all())


async def create_sprint(name: str) -> Sprint:
    """创建新 Sprint。"""
    async with async_session() as session:
        sprint = Sprint(name=name)
        session.add(sprint)
        await session.commit()
        await session.refresh(sprint)
        return sprint


async def get_sprint(sprint_id: int) -> Sprint | None:
    """获取单个 Sprint。"""
    async with async_session() as session:
        return await session.get(Sprint, sprint_id)
