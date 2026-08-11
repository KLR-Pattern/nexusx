"""Task-related DTOs — TaskSummary with the shared UserSummary."""
from nexusx import DefineSubset, SubsetConfig
from src.models import Task
from src.service.user.dtos import UserSummary


class TaskSummary(DefineSubset):
    """Task DTO — owner is auto-loaded from Task.owner relationship."""

    __subset__ = SubsetConfig(kls=Task, fields=["id", "title", "done"])
    owner: UserSummary | None = None
