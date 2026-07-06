"""Sprint-related DTOs — SprintSummary with derived fields."""
from nexusx import DefineSubset, SubsetConfig
from src.models import Sprint
from src.service.task.dtos import TaskSummary


class SprintSummary(DefineSubset):
    """Sprint DTO with derived fields computed after tasks are loaded."""

    __subset__ = SubsetConfig(kls=Sprint, fields=["id", "name"])
    tasks: list[TaskSummary] = []
    task_count: int = 0
    contributor_names: list[str] = []

    def post_task_count(self):
        return len(self.tasks)

    def post_contributor_names(self):
        return sorted({t.owner.name for t in self.tasks if t.owner})
