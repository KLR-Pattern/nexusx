"""Task-related DTOs — UserSummary, TaskSummary."""
from nexusx import DefineSubset, SubsetConfig
from src.models import Task, User


class UserSummary(DefineSubset):
    __subset__ = SubsetConfig(kls=User, fields=["id", "name"])


class TaskSummary(DefineSubset):
    """Task DTO — owner is auto-loaded from Task.owner relationship."""

    __subset__ = SubsetConfig(kls=Task, fields=["id", "title", "done"])
    owner: UserSummary | None = None
