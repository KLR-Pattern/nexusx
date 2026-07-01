"""User-related DTOs — UserSummary (单一来源，被 task / sprint 服务复用)."""
from nexusx import DefineSubset, SubsetConfig
from src.models import User


class UserSummary(DefineSubset):
    """User 实体的最小投影，含 id 与 name。

    作为单一来源被 task / sprint 服务引用（TaskSummary.owner、SprintSummary 间接通过 task），
    演示 nexusx 中 DTO 按需投影与跨 service 复用的模式。
    """

    __subset__ = SubsetConfig(kls=User, fields=["id", "name"])
