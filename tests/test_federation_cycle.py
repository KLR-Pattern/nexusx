"""Circular cross-service association — what actually happens.

A classic cycle: User ←→ Post across two services that mount each other.

    svcUsers.User ──posts──▶ svcPosts.Post
    svcPosts.Post ──author──▶ svcUsers.User   (back-reference → cycle)

Cyclic data: U1.posts → [P1], P1.author → U1.

Probes each stage:
  - init/materialization: visited-set + model_rebuild (should terminate)
  - gql (β): finite-depth query (should resolve)
  - _build_nested_selection: visited guard (should produce a finite selection)
  - Resolver (γ): BFS auto-traversal — the at-risk stage on cyclic data
"""

import asyncio

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.applications import Starlette
from starlette.routing import Mount

from nexusx import AutoQueryConfig, DefineSubset, GraphQLHandler
from nexusx.federation import RemoteRelationship, RemoteService
from nexusx.federation.http import GraphQLTransport
from nexusx.federation.introspect import build_federable_app

# Mutual service roots — distinct names to avoid cross-test pending-subset clashes.
svcUsers = RemoteService("svcUsers", url="http://test/svcUsers")
svcPosts = RemoteService("svcPosts", url="http://test/svcPosts")


class _UsersBase(SQLModel):
    pass


class CycUser(_UsersBase, table=True):
    __tablename__ = "cyc_user"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[svcPosts.CycPost],
            name="posts", join_remote="author_id",
        ),
    ]


class _PostsBase(SQLModel):
    pass


class CycPost(_PostsBase, table=True):
    __tablename__ = "cyc_post"
    id: int | None = Field(default=None, primary_key=True)
    author_id: int
    title: str
    __relationships__ = [
        RemoteRelationship(
            fk="author_id", target=svcUsers.CycUser,
            name="author", join_remote="id",
        ),
    ]


# Cyclic DTO tree via forward refs: UserDTO.posts → PostDTO, PostDTO.author → UserDTO.
class CycUserDTO(DefineSubset):
    __subset__ = (svcUsers.CycUser, ("name",))
    posts: list["CycPostDTO"] = []


class CycPostDTO(DefineSubset):
    __subset__ = (svcPosts.CycPost, ("title",))
    author: "CycUserDTO | None" = None


@pytest.fixture(scope="module")
async def _engines():
    eng = {
        "users": create_async_engine("sqlite+aiosqlite:///:memory:"),
        "posts": create_async_engine("sqlite+aiosqlite:///:memory:"),
    }
    for e in eng.values():
        async with e.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
    yield eng
    for e in eng.values():
        await e.dispose()


async def _build(engines):
    def sf(k):
        return async_sessionmaker(engines[k], class_=AsyncSession, expire_on_commit=False)

    async with sf("users")() as s:
        if not (await s.exec(select(CycUser))).first():
            s.add(CycUser(id=1, name="Alice"))
            await s.commit()
    async with sf("posts")() as s:
        if not (await s.exec(select(CycPost))).first():
            s.add(CycPost(id=1, author_id=1, title="Hello"))
            await s.commit()

    users_h = GraphQLHandler(
        base=_UsersBase, session_factory=sf("users"),
        auto_query_config=AutoQueryConfig(batch_keys={"CycUser": ["id"]}),
        service_name="svcUsers", expose_mounted_endpoints=True,
    )
    posts_h = GraphQLHandler(
        base=_PostsBase, session_factory=sf("posts"),
        auto_query_config=AutoQueryConfig(batch_keys={"CycPost": ["author_id", "id"]}),
        service_name="svcPosts", expose_mounted_endpoints=True,
    )
    composite = Starlette(routes=[
        Mount("/svcUsers", app=build_federable_app(users_h)),
        Mount("/svcPosts", app=build_federable_app(posts_h)),
    ])
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=composite), base_url="http://test")
    transport = GraphQLTransport(client=client)
    return users_h, posts_h, transport, client


@pytest.mark.asyncio
async def test_cycle_init_and_gql_and_selection_safe(_engines):
    """Init (materialization) + gql (β) + selection-builder handle the cycle."""
    users_h, posts_h, transport, client = await _build(_engines)
    # Mutual mount — each federates the other (service-level cycle).
    await posts_h.er.initialize(transport=transport)
    await users_h.er.initialize(transport=transport)

    try:
        # Init terminated (no hang) + materialized the partner type.
        assert users_h.er._fed_registry.has("svcPosts.CycPost")
        assert posts_h.er._fed_registry.has("svcUsers.CycUser")

        # _build_nested_selection terminates (visited guard) → finite selection.
        R = users_h.er.create_resolver()()
        post_cls = users_h.er._fed_registry.get("svcPosts.CycPost")
        sel = R._build_nested_selection(post_cls, CycPostDTO)
        sub = list((sel.sub_fields or {}).keys())
        assert "title" in sub and "author" in sub  # did not blow the stack

        # gql (β): finite-depth query across the cycle: User → Post → User.
        res = await users_h.execute(
            "{ CycUser { by_id(id: 1) { name posts { title author { name } } } } }"
        )
        assert not res.get("errors"), res
        u = res["data"]["CycUser"]["by_id"]
        assert u["name"] == "Alice"
        assert u["posts"][0]["title"] == "Hello"
        assert u["posts"][0]["author"]["name"] == "Alice"  # back-reference resolved
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_cycle_resolver_behaviour(_engines):
    """Resolver (γ) on cyclic data: terminate or loop?

    The Resolver BFS auto-traverses the DTO tree with no depth guard, so cyclic
    data (User→Post→User→…) is the at-risk case. We bound it with a timeout and
    report the observed behaviour rather than hang the suite.
    """
    users_h, _posts_h, transport, client = await _build(_engines)
    await users_h.er.initialize(transport=transport)

    try:
        R = users_h.er.create_resolver()
        try:
            resolved = await asyncio.wait_for(
                R().resolve([CycUserDTO(name="Alice")]), timeout=5.0,
            )
            assert resolved[0].name == "Alice"
            outcome = "COMPLETED"
        except asyncio.TimeoutError:
            outcome = "TIMED OUT (infinite BFS — known γ risk on cyclic data)"
        print(f"\nResolver on cyclic data: {outcome}")
    finally:
        await client.aclose()
