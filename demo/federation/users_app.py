"""Federation demo — USERS service (leaf; mounted by reviews).

Run: uv run uvicorn demo.federation.users_app:app --port 8020
"""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from demo.federation._common import make_app
from nexusx import AutoQueryConfig, GraphQLHandler


class UsersBase(SQLModel):
    pass


class User(UsersBase, table=True):
    __tablename__ = "fed_demo_user"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str


engine = create_async_engine("sqlite+aiosqlite:///fed_users.db")
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with async_session() as s:
        if not (await s.exec(select(User))).first():
            s.add(User(name="Alice", email="alice@x.com"))
            s.add(User(name="Bob", email="bob@x.com"))
            await s.commit()


handler = GraphQLHandler(
    base=UsersBase,
    session_factory=async_session,
    auto_query_config=AutoQueryConfig(batch_keys={"User": ["id"]}),
    service_name="users",
)

app = make_app(handler, on_startup=init_db, title="Fed demo — users (leaf)")
