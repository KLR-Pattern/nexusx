"""Task UseCaseService — task management with auto-loaded owner."""
from sqlmodel_nexus import UseCaseService, mutation, query
from src.models import Resolver
from src.service.task.dtos import TaskSummary
from src.service.task.methods import (
    create_task as _create_task,
    get_tasks_by_sprint as _get_tasks_by_sprint,
    list_tasks as _list_tasks,
)


class TaskService(UseCaseService):
    """Task management with auto-loaded owner."""

    @query
    async def list_tasks(cls) -> list[TaskSummary]:
        """Get all tasks with their owner (auto-loaded via DataLoader)."""
        tasks = await _list_tasks()
        dtos = [TaskSummary.model_validate(t) for t in tasks]
        return await Resolver().resolve(dtos)

    @query
    async def get_tasks_by_sprint(cls, sprint_id: int) -> list[TaskSummary]:
        """Get tasks for a specific sprint, with owner auto-loaded."""
        tasks = await _get_tasks_by_sprint(sprint_id=sprint_id)
        dtos = [TaskSummary.model_validate(t) for t in tasks]
        return await Resolver().resolve(dtos)

    @mutation
    async def create_task(cls, title: str, sprint_id: int, owner_id: int | None = None) -> TaskSummary:
        """Create a new task (reuses methods.py function)."""
        task = await _create_task(title=title, sprint_id=sprint_id, owner_id=owner_id)
        dto = TaskSummary.model_validate(task)
        return await Resolver().resolve(dto)
