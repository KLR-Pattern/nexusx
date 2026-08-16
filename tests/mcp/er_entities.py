"""Related entity pair for get_er_diagram tests.

Lives in its own module (without ``from __future__ import annotations``)
because SQLAlchemy resolves ``list["Entity"]`` relationship annotations at
mapper-configuration time and cannot handle them under deferred string
evaluation — see tests/mcp/test_simple_mcp.py.
"""

from sqlmodel import Field, Relationship, SQLModel

from nexusx import query


class SimpleMCPErBaseEntity(SQLModel):
    """Base class for ER-diagram mock entities."""

    __test__ = False


class SimpleMCPErTeam(SimpleMCPErBaseEntity, table=True):
    """Mock team entity with a one-to-many relationship."""

    __test__ = False
    __tablename__ = "simple_mcp_er_team"

    id: int | None = Field(default=None, primary_key=True)
    name: str

    heroes: list["SimpleMCPErHero"] = Relationship(back_populates="team")

    @query
    async def get_teams(cls) -> list["SimpleMCPErTeam"]:
        """Get all mock teams (metadata-only, no database)."""
        return []


class SimpleMCPErHero(SimpleMCPErBaseEntity, table=True):
    """Mock hero entity with a many-to-one relationship."""

    __test__ = False
    __tablename__ = "simple_mcp_er_hero"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    team_id: int | None = Field(default=None, foreign_key="simple_mcp_er_team.id")

    team: SimpleMCPErTeam | None = Relationship(back_populates="heroes")
