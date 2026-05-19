"""Sprint UseCaseService — sprint management with task statistics."""
from sqlmodel_nexus import UseCaseService, mutation, query
from src.models import Resolver
from src.service.sprint.dtos import SprintSummary
from src.service.sprint.methods import (
    create_sprint as _create_sprint,
    get_sprint as _get_sprint,
    list_sprints as _list_sprints,
)


class SprintService(UseCaseService):
    """Sprint management with task statistics."""

    @query
    async def list_sprints(cls) -> list[SprintSummary]:
        """Get all sprints with task counts and contributor names."""
        sprints = await _list_sprints()
        dtos = [SprintSummary.model_validate(s) for s in sprints]
        return await Resolver().resolve(dtos)

    @query
    async def get_sprint(cls, sprint_id: int) -> SprintSummary | None:
        """Get a single sprint by ID."""
        sprint = await _get_sprint(sprint_id=sprint_id)
        if not sprint:
            return None
        dto = SprintSummary.model_validate(sprint)
        return await Resolver().resolve(dto)

    @mutation
    async def create_sprint(cls, name: str) -> SprintSummary:
        """Create a new sprint (reuses methods.py function)."""
        sprint = await _create_sprint(name=name)
        dto = SprintSummary.model_validate(sprint)
        return await Resolver().resolve(dto)
