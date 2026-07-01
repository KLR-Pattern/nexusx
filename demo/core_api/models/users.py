from typing import Optional

from sqlmodel import Field, Relationship, SQLModel, select

from nexusx import mutation, query


class User(SQLModel, table=True):
    __tablename__ = "core_api_user"

    id: int | None = Field(default=None, primary_key=True)
    name: str

    comments: list["Comment"] = Relationship(back_populates="author")

    @query
    async def get_users(cls, limit: int = 10) -> list["User"]:
        from demo.core_api.database import async_session

        async with async_session() as session:
            result = await session.exec(select(cls).limit(limit))
            return list(result.all())

    @mutation
    async def create_user(cls, name: str) -> "User":
        from demo.core_api.database import async_session

        async with async_session() as session:
            user = cls(name=name)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user
