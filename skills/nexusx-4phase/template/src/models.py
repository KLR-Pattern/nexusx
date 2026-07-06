"""Phase 1→2: SQLModel entity definitions.

Phase 1: Pure entity fields + Relationship declarations (no methods).
Phase 2: Method mounting from service/<domain>/methods.py via mount_method().

Entity graph:
    Sprint ──1:N──→ Task ──N:1──→ User
"""
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel

from src.db import async_session


class BaseEntity(SQLModel):
    """All entities inherit from this base class for shared metadata discovery."""


class User(BaseEntity, table=True):
    """系统用户，可以是任务的创建者或负责人。"""

    id: int | None = Field(default=None, primary_key=True, description="用户唯一标识")
    name: str = Field(description="用户显示名称")

    # ORM relationships (noload: use explicit queries or Resolver DataLoader)
    tasks: list["Task"] = Relationship(
        back_populates="owner",
        sa_relationship_kwargs={"lazy": "noload"},
    )


class Sprint(BaseEntity, table=True):
    """迭代周期，包含一批待完成的任务。"""

    id: int | None = Field(default=None, primary_key=True, description="Sprint 唯一标识")
    name: str = Field(description="Sprint 名称，如 'Sprint 1'")

    # ORM relationships (noload)
    tasks: list["Task"] = Relationship(
        back_populates="sprint",
        sa_relationship_kwargs={"lazy": "noload", "order_by": "Task.id"},
    )


class Task(BaseEntity, table=True):
    """具体的工作项，属于某个 Sprint，由某个 User 负责。"""

    id: int | None = Field(default=None, primary_key=True, description="任务唯一标识")
    title: str = Field(description="任务标题")
    done: bool = Field(default=False, description="是否已完成")

    sprint_id: int = Field(foreign_key="sprint.id", description="所属 Sprint ID")
    owner_id: int | None = Field(
        default=None,
        foreign_key="user.id",
        description="负责人 ID，可为空表示未分配",
    )

    # ORM relationships (noload)
    sprint: Optional["Sprint"] = Relationship(
        back_populates="tasks",
        sa_relationship_kwargs={"lazy": "noload"},
    )
    owner: Optional["User"] = Relationship(sa_relationship_kwargs={"lazy": "noload"})


# ── Method mounting (Phase 2) ─────────────────────────────────────────


def mount_method():
    """挂载 service methods 到 entity classes。需在外部显式调用。"""
    import functools

    from nexusx import mutation, query
    from src.service.sprint.methods import create_sprint, list_sprints
    from src.service.task.methods import create_task, get_tasks_by_sprint, list_tasks
    from src.service.user.methods import create_user, list_users

    def _mount(entity, fn, decorator):
        @functools.wraps(fn)
        async def wrapper(cls, *args, **kwargs):
            return await fn(*args, **kwargs)
        setattr(entity, fn.__name__, decorator(wrapper))

    _mount(User, list_users, query)
    _mount(User, create_user, mutation)
    _mount(Sprint, list_sprints, query)
    _mount(Sprint, create_sprint, mutation)
    _mount(Task, list_tasks, query)
    _mount(Task, get_tasks_by_sprint, query)
    _mount(Task, create_task, mutation)


# ── ErManager + Resolver (Phase 3) ──────────────────────────────────────

from nexusx import ErManager  # noqa: E402

er = ErManager(
    entities=[User, Sprint, Task],
    session_factory=async_session,
)
Resolver = er.create_resolver()
