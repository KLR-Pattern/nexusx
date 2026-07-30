from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    # Forward-only: Task lives in .tasks; resolved by SQLAlchemy's registry at
    # mapper-configure time (the package __init__ imports every model).
    from .tasks import Task


class Tag(SQLModel, table=True):
    __tablename__ = "core_api_tag"

    id: int | None = Field(default=None, primary_key=True)
    name: str


class TaskLabel(SQLModel, table=True):
    __tablename__ = "core_api_task_label"

    task_id: int = Field(foreign_key="core_api_task.id", primary_key=True)
    label_id: int = Field(foreign_key="core_api_label.id", primary_key=True)


class Label(SQLModel, table=True):
    __tablename__ = "core_api_label"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    color: str = "#999999"

    tasks: list["Task"] = Relationship(back_populates="labels", link_model=TaskLabel)
