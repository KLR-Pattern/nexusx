from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel, select

from nexusx import BatchPageConfig, OrderTerm, PageOrder, query

if TYPE_CHECKING:
    from .tasks import Task


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
    # specs/016 Paged: order profiles for the tasks relationship. A DTO field
    # `Annotated[list[TaskDTO], Paged(order="NEWEST")]` picks from these; the
    # page_loader (built from order_by above) executes the slice.
    __pagination_orders__ = {
        "tasks": BatchPageConfig(
            default_order="NEWEST",
            orders={
                "NEWEST": PageOrder([OrderTerm("id", "desc")]),
                "OLDEST": PageOrder([OrderTerm("id", "asc")]),
            },
        ),
    }

    @query
    async def get_sprints(cls, limit: int = 10) -> list["Sprint"]:
        from demo.core_api.database import async_session

        async with async_session() as session:
            result = await session.exec(select(cls).limit(limit))
            return list(result.all())
