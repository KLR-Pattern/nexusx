"""Database seed data.

Phase 1: create_all + mock seed (供团队讨论数据样本).
"""
from sqlmodel import SQLModel, select

from src.db import async_session, engine
from src.models import Sprint, Task, User


async def init_db() -> None:
    """Create tables and seed mock data."""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async with async_session() as session:
        existing = await session.exec(select(User))
        if existing.first():
            return

        users = [User(name="Alice"), User(name="Bob"), User(name="Charlie")]
        for u in users:
            session.add(u)
        await session.commit()
        for u in users:
            await session.refresh(u)

        sprints = [Sprint(name="Sprint 1"), Sprint(name="Sprint 2")]
        for s in sprints:
            session.add(s)
        await session.commit()
        for s in sprints:
            await session.refresh(s)

        tasks_data = [
            ("Setup CI/CD", sprints[0].id, users[0].id, True),
            ("Design schema", sprints[0].id, users[1].id, True),
            ("Build API", sprints[0].id, users[0].id, False),
            ("Write tests", sprints[1].id, users[2].id, False),
            ("Deploy", sprints[1].id, users[1].id, False),
        ]
        for title, sprint_id, owner_id, done in tasks_data:
            session.add(Task(title=title, sprint_id=sprint_id, owner_id=owner_id, done=done))
        await session.commit()
