from typing import Optional

from sqlmodel import Field, Relationship, SQLModel, select

from nexusx import query


class Project(SQLModel, table=True):
    __tablename__ = "core_api_project"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    description: str = ""

    sprints: list["Sprint"] = Relationship(back_populates="project")


class Sprint(SQLModel, table=True):
    __tablename__ = "core_api_sprint"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    project_id: int | None = Field(default=None, foreign_key="core_api_project.id")

    project: Optional["Project"] = Relationship(back_populates="sprints")
    tasks: list["Task"] = Relationship(
        back_populates="sprint",
        sa_relationship_kwargs={"order_by": "Task.id"},
    )

    @query
    async def get_sprints(cls, limit: int = 10) -> list["Sprint"]:
        from demo.core_api.database import async_session

        async with async_session() as session:
            result = await session.exec(select(cls).limit(limit))
            return list(result.all())
