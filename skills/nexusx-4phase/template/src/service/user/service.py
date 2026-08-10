"""User UseCaseService — user management."""
from nexusx import UseCaseService, mutation, query
from src.models import Resolver
from src.service.user.dtos import UserSummary
from src.service.user.methods import create_user as _create_user
from src.service.user.methods import list_users as _list_users


class UserService(UseCaseService):
    """User management."""

    @query
    async def list_users(cls) -> list[UserSummary]:
        """Get all users."""
        users = await _list_users()
        dtos = [UserSummary.model_validate(u) for u in users]
        return await Resolver().resolve(dtos)

    @mutation
    async def create_user(cls, name: str) -> UserSummary:
        """Create a new user."""
        user = await _create_user(name=name)
        dto = UserSummary.model_validate(user)
        return await Resolver().resolve(dto)
