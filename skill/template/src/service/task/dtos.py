"""Task-related DTOs — TaskSummary (UserSummary 引用自 user/dtos.py 单一来源)."""
from nexusx import DefineSubset, SubsetConfig
from src.models import Task
from src.service.user.dtos import UserSummary


class TaskSummary(DefineSubset):
    """Task DTO — owner is auto-loaded from Task.owner relationship."""

    __subset__ = SubsetConfig(kls=Task, fields=["id", "title", "done"])
    owner: UserSummary | None = None
