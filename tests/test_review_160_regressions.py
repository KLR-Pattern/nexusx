"""Regression tests for issue #160 milestone M0 (7.0.0 review hotfixes).

Each test pins a behaviour the review found broken, exercised through the
public surface only (``GraphQLHandler.execute`` / ``ErManager.create_resolver``).
"""

from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Relationship, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx import GraphQLHandler, query

# ──────────────────────────────────────────────────────────
# BUG_1 fixtures — one O2M and one M2M paginated relationship
# ──────────────────────────────────────────────────────────


GET_ALL_CALLS: list[int] = []  # execution probe for BUG_3


class R160Base(SQLModel):
    pass


class R160AuthorTag(R160Base, table=True):
    __tablename__ = "r160_author_tag"

    author_id: int = Field(foreign_key="r160_author.id", primary_key=True)
    tag_id: int = Field(foreign_key="r160_tag.id", primary_key=True)


class R160Post(R160Base, table=True):
    __tablename__ = "r160_post"

    id: int | None = Field(default=None, primary_key=True)
    author_id: int = Field(foreign_key="r160_author.id")
    author: Optional["R160Author"] = Relationship(back_populates="posts")


class R160Tag(R160Base, table=True):
    __tablename__ = "r160_tag"

    id: int | None = Field(default=None, primary_key=True)
    authors: list["R160Author"] = Relationship(
        back_populates="tags", link_model=R160AuthorTag
    )


class R160Author(R160Base, table=True):
    __tablename__ = "r160_author"

    id: int | None = Field(default=None, primary_key=True)
    name: str = ""

    posts: list[R160Post] = Relationship(
        back_populates="author",
        sa_relationship_kwargs={"order_by": "R160Post.id"},
    )
    tags: list[R160Tag] = Relationship(
        back_populates="authors",
        link_model=R160AuthorTag,
        sa_relationship_kwargs={"order_by": "R160Tag.id"},
    )

    @query
    async def get_all(cls) -> list["R160Author"]:
        GET_ALL_CALLS.append(1)
        async with SESSION_FACTORY() as session:
            return list((await session.exec(select(cls))).all())


R160Base.model_rebuild()

engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
)
SESSION_FACTORY = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
handler = GraphQLHandler(base=R160Base, session_factory=SESSION_FACTORY)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _seed():
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    async with SESSION_FACTORY() as session:
        session.add(
            R160Author(
                id=1,
                name="a",
                posts=[R160Post(id=i, author_id=1) for i in (1, 2, 3)],
                tags=[R160Tag(id=i) for i in (1, 2, 3)],
            )
        )
        await session.commit()
    yield
    await engine.dispose()


def _page(result: dict, field: str) -> dict:
    return result["data"]["R160Author"]["get_all"][0][field]


# ──────────────────────────────────────────────────────────
# BUG_1 — limit=0 on a local paginated relationship
# ──────────────────────────────────────────────────────────


class TestLimitZeroHasMore:
    @pytest.mark.parametrize("field", ["posts", "tags"])
    async def test_limit_zero_is_an_empty_page_without_a_next_page(self, field: str):
        result = await handler.execute(
            "{ R160Author { get_all { id "
            f"{field}(limit: 0) {{ items {{ id }} pagination {{ has_more total_count }} }} "
            "} } }"
        )
        page = _page(result, field)
        assert page["items"] == []
        assert page["pagination"]["total_count"] == 3
        assert page["pagination"]["has_more"] is False


# ──────────────────────────────────────────────────────────
# BUG_2 fixtures — class-level Resolver caches vs. the registry
# ──────────────────────────────────────────────────────────

from pydantic import BaseModel  # noqa: E402

from nexusx import ErManager, Relationship  # noqa: E402


class R160Toy(BaseModel):
    id: int = 0
    child_id: int = 0


class R160Child(BaseModel):
    id: int = 0
    # ``toys`` is deliberately NOT a model field: it exists only as an
    # ErManager-registered relationship, which is the case the class-level
    # ``_traversable_fields_cache`` / ``should_traverse`` get wrong.


class R160Parent(BaseModel):
    id: int = 1
    children: list[R160Child] = []


async def _load_toys(keys: list[int]) -> list[list[R160Toy]]:
    return [[R160Toy(id=k * 100, child_id=k)] for k in keys]


def _no_session():  # pragma: no cover — never called; custom loaders own their I/O
    raise AssertionError("no database in this fixture")


# Registry A: R160Child has no relationships. Registry B: it has ``toys``.
# Constructed at import time in this order on purpose — the bug is order-dependent.
ER_A = ErManager(entities=[R160Parent, R160Child], session_factory=_no_session)
R160Child.__relationships__ = [
    Relationship(fk="id", target=list[R160Toy], name="toys", loader=_load_toys),
]
ER_B = ErManager(entities=[R160Parent, R160Child, R160Toy], session_factory=_no_session)


class TestCrossRegistryCache:
    async def test_second_registry_still_sees_relationships_after_first_resolved(self):
        """A registry-scoped cache must not be keyed by class alone (#160 BUG_2).

        Resolving through A first used to freeze ``R160Child.should_traverse
        = False`` and ``R160Parent.traversable = []`` in process-level caches;
        a later resolve through B — where ``R160Child`` *does* have a
        relationship — then skipped the subtree and ``toys`` stayed empty.
        """
        await ER_A.create_resolver()().resolve([R160Parent(id=1, children=[R160Child(id=1)])])

        out = await ER_B.create_resolver()().resolve(
            [R160Parent(id=2, children=[R160Child(id=2)])]
        )
        assert out[0].children[0].toys == [R160Toy(id=200, child_id=2)]


# ──────────────────────────────────────────────────────────
# BUG_3 — pagination intent is validated before execution
# ──────────────────────────────────────────────────────────

class TestPaginationIntentValidation:
    async def test_paginated_field_without_limit_or_fetch_all_is_rejected_before_execution(self):
        """SDL advertises limit/offset/fetchAll as optional, but volume intent is
        mandatory (2026-11 contract). The mismatch must surface as a pre-execution
        validation error with a machine-readable code — not as a RESOLVER_ERROR
        raised from inside the loader after the user's method already ran."""
        GET_ALL_CALLS.clear()
        result = await handler.execute(
            "{ R160Author { get_all { id posts { items { id } } } } }"
        )
        errors = result["errors"]
        assert len(errors) == 1
        assert errors[0]["extensions"]["code"] == "PAGINATION_INTENT_REQUIRED"
        assert errors[0]["path"] == ["R160Author", "get_all", "posts"]
        assert "posts" in errors[0]["message"]
        assert "limit" in errors[0]["message"] and "fetchAll" in errors[0]["message"]
        # Same shape as the existing unknown-field validation path: the method key is
        # not populated at all.
        assert result["data"]["R160Author"].get("get_all") is None
        assert GET_ALL_CALLS == []  # never reached the user's method

    async def test_explicit_limit_or_fetch_all_pass_validation(self):
        GET_ALL_CALLS.clear()
        ok_limit = await handler.execute(
            "{ R160Author { get_all { id posts(limit: 1) { items { id } } } } }"
        )
        ok_fetch_all = await handler.execute(
            "{ R160Author { get_all { id posts(fetchAll: true) { items { id } } } } }"
        )
        assert "errors" not in ok_limit and "errors" not in ok_fetch_all
        assert len(_page(ok_fetch_all, "posts")["items"]) == 3
        assert GET_ALL_CALLS == [1, 1]


# ──────────────────────────────────────────────────────────
# SIG_15 — every error path carries extensions.code
# ──────────────────────────────────────────────────────────


class TestGenericErrorCode:
    async def test_unhandled_errors_carry_a_machine_readable_code(self):
        """ALIAS_CONFLICT / RESOLVER_ERROR / SKIPPED_PRIOR_FAILURE /
        BARE_GROUP_FIELD / PAGINATION_INTENT_REQUIRED all carry a code; the
        top-level catch-all must too, so agents can branch on it."""
        result = await handler.execute("{ R160Author { get_all { id")
        assert result["errors"][0]["extensions"]["code"] == "INTERNAL_ERROR"
        assert result["errors"][0]["message"]


# ──────────────────────────────────────────────────────────
# M1 small items: SIG_3 export, SIG_9 deprecation, API_3_7 warning
# ──────────────────────────────────────────────────────────


import nexusx  # noqa: E402
import nexusx.use_case as use_case_pkg  # noqa: E402
from nexusx.use_case.business import UseCaseService  # noqa: E402


class TestM1SmallItems:
    def test_create_use_case_router_is_exported_from_use_case_package(self):
        assert use_case_pkg.create_use_case_router is nexusx.create_use_case_router

    def test_one_argument_get_dto_loader_warns(self):
        er = ErManager(entities=[R160Parent], session_factory=_no_session)
        with pytest.warns(DeprecationWarning, match="get_dto_loader"):
            assert er.get_dto_loader("anything") is None

    def test_sync_query_method_on_service_warns_instead_of_vanishing(self, caplog):
        class SyncService(UseCaseService):
            @query
            def not_async(cls) -> str:  # type: ignore[misc] — deliberately sync
                return "x"

        assert "not_async" not in SyncService.__use_case_methods__
        assert any("not async" in r.message for r in caplog.records), caplog.records
