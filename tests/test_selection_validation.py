"""Pre-execution selection validation in QueryExecutor.

Unknown fields in a selection must surface as GraphQL-style validation
errors ("Cannot query field ... on type ...") BEFORE execution, instead of
being silently dropped at serialization (which produced empty-object rows
and ``success: true`` — poison for AI-agent self-correction).

Exemptions: ``__typename``, and the federation machine-facing
``by_<key>_in`` batch roots whose selections are built by mounters' remote
loaders (DTO-side computed fields are dropped by design there).
"""

import json

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Relationship, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx import AutoQueryConfig, BatchPageConfig, GraphQLHandler, OrderTerm, PageOrder


class SelectionValBase(SQLModel):
    """Base class for selection-validation test entities."""

    pass


class SelectionValTeam(SelectionValBase, table=True):
    __tablename__ = "selection_val_team"

    id: int | None = Field(default=None, primary_key=True)
    name: str

    # Expose a federation batch root (by_id_in) to guard its validation
    # exemption, plus a pagination root (page_by_id_in) to guard package
    # validation: {id, items, pagination} on SelectionValTeamIdPagePackage.
    __federation_keys__ = ("id",)
    __pagination_orders__ = BatchPageConfig(
        default_order="PRIMARY",
        orders={"PRIMARY": PageOrder([OrderTerm("id")])},
    )

    heroes: list["SelectionValHero"] = Relationship(back_populates="team")


class SelectionValHero(SelectionValBase, table=True):
    __tablename__ = "selection_val_hero"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    team_id: int | None = Field(default=None, foreign_key="selection_val_team.id")

    team: SelectionValTeam | None = Relationship(back_populates="heroes")


engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
)
session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)
handler = GraphQLHandler(
    base=SelectionValBase,
    session_factory=session_factory,
    auto_query_config=AutoQueryConfig(),
)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _seed():
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    async with session_factory() as session:
        team = SelectionValTeam(id=1, name="Avengers")
        session.add(team)
        await session.flush()
        session.add(SelectionValHero(id=1, name="Spider-Man", team_id=1))
        await session.commit()
    yield
    await engine.dispose()


def _messages(result: dict) -> str:
    return json.dumps(result.get("errors", []))


@pytest.mark.asyncio
async def test_unknown_field_reports_validation_error():
    """A misspelled field errors instead of silently returning empty rows."""
    result = await handler.execute(
        "{ SelectionValTeam { by_filter { nmae } } }"
    )

    assert result.get("data", {}).get("SelectionValTeam", {}).get("by_filter") is None
    assert "Cannot query field 'nmae' on type 'SelectionValTeam'" in _messages(result)


@pytest.mark.asyncio
async def test_unknown_nested_field_names_target_type():
    """An unknown field inside a relationship names the TARGET entity type."""
    result = await handler.execute(
        "{ SelectionValTeam { by_filter { heroes { nmae } } } }"
    )

    assert (
        "Cannot query field 'nmae' on type 'SelectionValHero'" in _messages(result)
    )


@pytest.mark.asyncio
async def test_fk_column_remains_queryable():
    """FK columns are queryable (pre-existing behavior) even though the SDL
    omits them — validation must match executability, not the SDL."""
    result = await handler.execute(
        "{ SelectionValHero { by_id(id: 1) { id team_id } } }"
    )

    assert not result.get("errors")
    assert result["data"]["SelectionValHero"]["by_id"]["team_id"] == 1


@pytest.mark.asyncio
async def test_typename_is_allowed():
    """__typename must not be rejected (GraphQL meta field)."""
    result = await handler.execute(
        "{ SelectionValTeam { by_filter { __typename } } }"
    )

    assert not result.get("errors")


@pytest.mark.asyncio
async def test_valid_queries_unaffected():
    """A fully valid nested selection still resolves relationships."""
    result = await handler.execute(
        "{ SelectionValTeam { by_filter { name heroes { name } } } }"
    )

    assert not result.get("errors")
    team = result["data"]["SelectionValTeam"]["by_filter"][0]
    assert team == {"name": "Avengers", "heroes": [{"name": "Spider-Man"}]}


@pytest.mark.asyncio
async def test_sibling_method_still_executes():
    """A bad selection skips only its own method; siblings still run."""
    result = await handler.execute(
        "{ SelectionValTeam { by_filter { name } by_id(id: 1) { nmae } } }"
    )

    assert "Cannot query field 'nmae' on type 'SelectionValTeam'" in _messages(result)
    by_filter = result["data"]["SelectionValTeam"]["by_filter"]
    assert by_filter == [{"name": "Avengers"}]


@pytest.mark.asyncio
async def test_items_on_non_paginated_relationship_errors():
    """``items``/``pagination`` are package keys of paginated relationships
    only (is_active_paginated_relationship) — on a plain relationship they
    are unknown fields, matching the SDL's plain ``[Hero!]!`` rendering."""
    result = await handler.execute(
        "{ SelectionValTeam { by_filter { heroes { items { name } } } } }"
    )

    assert "Cannot query field 'items' on type 'SelectionValHero'" in _messages(
        result
    )


@pytest.mark.asyncio
async def test_federation_batch_root_is_exempt():
    """by_<key>_in batch roots take mounter-built selections that include
    DTO-side computed fields the entity never serves — validation is
    skipped there (silent drop by design, mounter recomputes)."""
    result = await handler.execute(
        "{ SelectionValTeam { by_id_in(id_list: [1]) { label } } }"
    )

    assert not result.get("errors"), result


@pytest.mark.asyncio
async def test_pagination_root_package_selection_is_valid():
    """The full three-key package {fk, items, pagination} validates and runs."""
    result = await handler.execute(
        "{ SelectionValTeam { page_by_id_in(id_list: [1], order: PRIMARY) { "
        "id items { name } pagination { has_more } } } }"
    )

    assert not result.get("errors"), result
    packages = result["data"]["SelectionValTeam"]["page_by_id_in"]
    assert packages[0]["items"][0]["name"] == "Avengers"


@pytest.mark.asyncio
async def test_pagination_root_unknown_key_names_package_type():
    """An unknown key on a pagination root errors naming the PagePackage
    wrapper type — not the entity type (which would point the agent at the
    wrong place)."""
    result = await handler.execute(
        "{ SelectionValTeam { page_by_id_in(id_list: [1]) { itemz { id } } } }"
    )

    assert (
        "Cannot query field 'itemz' on type 'SelectionValTeamIdPagePackage'"
        in _messages(result)
    )
