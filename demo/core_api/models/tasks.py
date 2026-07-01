from typing import Optional

from sqlmodel import Field, Relationship, SQLModel, select

from nexusx import Relationship as CustomRelationship
from nexusx import mutation, query

from .metadata import Tag, TaskLabel


class Comment(SQLModel, table=True):
    __tablename__ = "core_api_comment"

    id: int | None = Field(default=None, primary_key=True)
    content: str
    task_id: int = Field(foreign_key="core_api_task.id")
    author_id: int = Field(foreign_key="core_api_user.id")

    task: Optional["Task"] = Relationship(back_populates="comments")
    author: Optional["User"] = Relationship(back_populates="comments")


async def _tags_by_task_loader(task_ids: list[int]) -> list[list[Tag]]:
    from sqlmodel import select
    from demo.core_api.database import async_session

    async with async_session() as session:
        all_tags = (await session.exec(select(Tag))).all()

    return [list(all_tags) for _ in task_ids]


class Task(SQLModel, table=True):
    __tablename__ = "core_api_task"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    done: bool = False
    sprint_id: int = Field(foreign_key="core_api_sprint.id")
    owner_id: int | None = Field(default=None, foreign_key="core_api_user.id")

    sprint: Optional["Sprint"] = Relationship(back_populates="tasks")
    owner: Optional["User"] = Relationship()
    comments: list["Comment"] = Relationship(back_populates="task")
    labels: list["Label"] = Relationship(back_populates="tasks", link_model=TaskLabel)

    __relationships__ = [
        CustomRelationship(
            fk="id",
            target=list[Tag],
            name="tags",
            loader=_tags_by_task_loader,
            description="Task tags (loaded via custom loader, not ORM)",
        )
    ]

    @query
    async def get_tasks(cls, limit: int = 10) -> list["Task"]:
        from demo.core_api.database import async_session

        async with async_session() as session:
            result = await session.exec(select(cls).limit(limit))
            return list(result.all())

    @mutation
    async def create_task(cls, title: str, sprint_id: int, owner_id: int | None = None) -> "Task":
        from demo.core_api.database import async_session

        async with async_session() as session:
            task = cls(title=title, sprint_id=sprint_id, owner_id=owner_id)
            session.add(task)
            await session.commit()
            await session.refresh(task)
            return task
