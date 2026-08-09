"""Federation demo — USERS service (leaf; mounted by reviews).

Run: uv run uvicorn demo.federation.users_app:app --port 8020

Hosts TWO levels: User ── UserConfig (local one-to-one). When a mounted service
asks for `author { config { theme } }`, users resolves UserConfig locally within
its own gql response — no extra cross-service hop.
"""

from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, Relationship, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from demo.federation._common import make_app
from nexusx import AutoQueryConfig, GraphQLHandler


class UsersBase(SQLModel):
    pass


class UserConfig(UsersBase, table=True):
    __tablename__ = "fed_demo_userconfig"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="fed_demo_user.id")
    theme: str


class User(UsersBase, table=True):
    __tablename__ = "fed_demo_user"
    __federation_keys__ = ["id"]
    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str
    config: UserConfig | None = Relationship(sa_relationship_kwargs={"uselist": False})


engine = create_async_engine(f"sqlite+aiosqlite:///{Path(__file__).parent / 'fed_users.db'}")
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with async_session() as s:
        if not (await s.exec(select(User))).first():
            s.add(User(id=1, name="Alice", email="alice@x.com"))
            s.add(User(id=2, name="Bob", email="bob@x.com"))
            s.add(UserConfig(id=1, user_id=1, theme="dark"))
            s.add(UserConfig(id=2, user_id=2, theme="light"))
            await s.commit()


handler = GraphQLHandler(
    base=UsersBase,
    session_factory=async_session,
    auto_query_config=AutoQueryConfig(),
    service_name="users",
)

app = make_app(handler, on_startup=init_db, title="Fed demo — users (leaf; User ── UserConfig)")
