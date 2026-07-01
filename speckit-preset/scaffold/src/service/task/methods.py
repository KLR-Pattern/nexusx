"""Task domain — independent business methods."""
from sqlmodel import select

from src.db import async_session
from src.models import Task


async def list_tasks() -> list[Task]:
    """获取所有任务。"""
    async with async_session() as session:
        result = await session.exec(select(Task))
        return list(result.all())


async def get_tasks_by_sprint(sprint_id: int) -> list[Task]:
    """获取指定 Sprint 下的所有任务。"""
    async with async_session() as session:
        result = await session.exec(
            select(Task).where(Task.sprint_id == sprint_id)
        )
        return list(result.all())


async def create_task(title: str, sprint_id: int, owner_id: int | None = None) -> Task:
    """在指定 Sprint 中创建新任务。"""
    async with async_session() as session:
        task = Task(title=title, sprint_id=sprint_id, owner_id=owner_id)
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task
