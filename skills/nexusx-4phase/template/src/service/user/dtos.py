"""User-related DTOs — UserSummary."""
from nexusx import DefineSubset, SubsetConfig
from src.models import User


class UserSummary(DefineSubset):
    """User DTO."""

    __subset__ = SubsetConfig(kls=User, fields=["id", "name"])
