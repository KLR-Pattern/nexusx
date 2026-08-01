"""Federation order/direction (specs/014) — member unit + mounter e2e/schema tests.

Member side:
- ``_apply_direction`` (direction flip + nulls follow) and the single-column
  ``PageOrder`` constraint (unit).
- direction flip moves NULLs end↔start through the real window SQL (T015/US3).

Mounter side:
- caller-chosen ``order`` + ``direction`` flows end-to-end across the service
  boundary and the member sorts accordingly (T013/US1, SC-001/002/006).
- SDL and ``__schema`` expose the order enum (member profile names) + Direction
  consistently (T014/US2, SC-003).
"""

import os
import tempfile

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.applications import Starlette
from starlette.routing import Mount

from nexusx import AutoQueryConfig, GraphQLHandler
from nexusx.federation import RemoteRelationship, RemoteService
from nexusx.federation.http import GraphQLTransport
from nexusx.federation.introspect import build_federable_app
from nexusx.standard_queries import (
    BatchPageConfig,
    Direction,
    OrderTerm,
    PageOrder,
    _apply_direction,
    _resolve_page_orders,
    _ResolvedOrderTerm,
)

# ── _apply_direction: direction flip + nulls follow ──────────────────────


def test_apply_direction_none_keeps_profile_default():
    terms = (_ResolvedOrderTerm("rating", "desc", "last"),)
    assert _apply_direction(terms, None) == terms


def test_apply_direction_same_direction_no_flip():
    terms = (_ResolvedOrderTerm("rating", "desc", "last"),)
    assert _apply_direction(terms, Direction.DESC) == terms


def test_apply_direction_flip_also_flips_nulls():
    terms = (_ResolvedOrderTerm("rating", "desc", "last"),)
    flipped = _apply_direction(terms, Direction.ASC)
    assert flipped == (_ResolvedOrderTerm("rating", "asc", "first"),)


def test_apply_direction_nulls_none_stays_none_on_flip():
    # non-null column (e.g. PK tie-breaker) — nulls None stays None when flipped
    terms = (_ResolvedOrderTerm("id", "asc", None),)
    flipped = _apply_direction(terms, Direction.DESC)
    assert flipped == (_ResolvedOrderTerm("id", "desc", None),)


def test_apply_direction_accepts_string_value():
    # the GraphQL wire path may deliver a plain string rather than the Enum
    terms = (_ResolvedOrderTerm("rating", "desc", "last"),)
    assert _apply_direction(terms, "ASC") == (_ResolvedOrderTerm("rating", "asc", "first"),)


# ─_resolve_page_orders: single-column constraint ──────────────────────────


def test_resolve_page_orders_rejects_multicolumn_profile():
    class _MultiColEntity(SQLModel, table=True):
        __tablename__ = "nx14_multi_col"
        id: int | None = Field(default=None, primary_key=True)
        rating: int
        created_at: int

    config = BatchPageConfig(
        default_order="BAD",
        orders={
            "BAD": PageOrder(
                [OrderTerm("rating", "desc"), OrderTerm("created_at", "desc")]
            )
        },
    )
    with pytest.raises(ValueError, match="exactly one term"):
        _resolve_page_orders(_MultiColEntity, config)


# ── federation_order_enum_layout: mounter-side order-enum naming ──────────


def test_order_enum_layout_naming_and_direction():
    """A federation-paginated rel yields one ``{Target}Order`` enum (values =
    the member profile names) plus the shared ``Direction`` enum. specs/014."""
    from types import SimpleNamespace

    from nexusx.federation.contract import (
        BatchPageCapability,
        PageOrderDescriptor,
    )
    from nexusx.utils.pagination_schema import federation_order_enum_layout

    class _Review:
        pass

    class _Product:
        pass

    cap = BatchPageCapability(
        default_order="HIGHEST_RATING",
        orders=[
            PageOrderDescriptor(name="HIGHEST_RATING"),
            PageOrderDescriptor(name="NEWEST"),
        ],
    )
    rel = SimpleNamespace(target_entity=_Review, page_capability=cap)
    registry = SimpleNamespace(
        get_relationships=lambda e: {"reviews": rel} if e is _Product else {}
    )
    enums, field_name = federation_order_enum_layout(registry, [_Product])

    assert field_name[("_Product", "reviews")] == "_ReviewOrder"
    assert "_ReviewOrder" in enums and "Direction" in enums
    assert {v.value for v in enums["_ReviewOrder"]} == {"HIGHEST_RATING", "NEWEST"}


def test_order_enum_layout_disambiguates_same_target_different_orders():
    """Two federation-paginated rels on ONE target with DIFFERENT order sets
    must render under distinct enum names — otherwise the SDL would define two
    enums with the same name and different values. specs/014."""
    from types import SimpleNamespace

    from nexusx.federation.contract import (
        BatchPageCapability,
        PageOrderDescriptor,
    )
    from nexusx.utils.pagination_schema import federation_order_enum_layout

    class _Review:
        pass

    class _Product:
        pass

    def _cap(*names):
        return BatchPageCapability(
            default_order=names[0],
            orders=[PageOrderDescriptor(name=n) for n in names],
        )

    rel_reviews = SimpleNamespace(
        target_entity=_Review, page_capability=_cap("HIGHEST_RATING", "NEWEST")
    )
    rel_by_user = SimpleNamespace(
        target_entity=_Review, page_capability=_cap("USER_RATING")
    )
    registry = SimpleNamespace(
        get_relationships=lambda e: (
            {"reviews": rel_reviews, "by_user": rel_by_user} if e is _Product else {}
        )
    )
    enums, field_name = federation_order_enum_layout(registry, [_Product])

    # First rel keeps the plain {Target}Order name; the second (same target,
    # different orders) is disambiguated with the relationship name.
    assert field_name[("_Product", "reviews")] == "_ReviewOrder"
    assert field_name[("_Product", "by_user")] == "_ReviewByUserOrder"
    assert {v.value for v in enums["_ReviewOrder"]} == {"HIGHEST_RATING", "NEWEST"}
    assert {v.value for v in enums["_ReviewByUserOrder"]} == {"USER_RATING"}


def test_order_enum_layout_dedupes_same_target_same_orders():
    """Two rels sharing a target AND order set share ONE enum (no duplicate)."""
    from types import SimpleNamespace

    from nexusx.federation.contract import (
        BatchPageCapability,
        PageOrderDescriptor,
    )
    from nexusx.utils.pagination_schema import federation_order_enum_layout

    class _Review:
        pass

    class _Product:
        pass

    cap = BatchPageCapability(
        default_order="NEWEST",
        orders=[PageOrderDescriptor(name="NEWEST")],
    )
    registry = SimpleNamespace(
        get_relationships=lambda e: (
            {"reviews": SimpleNamespace(target_entity=_Review, page_capability=cap),
             "also_reviews": SimpleNamespace(target_entity=_Review, page_capability=cap)}
            if e is _Product else {}
        )
    )
    enums, field_name = federation_order_enum_layout(registry, [_Product])

    assert field_name[("_Product", "reviews")] == "_ReviewOrder"
    assert field_name[("_Product", "also_reviews")] == "_ReviewOrder"
    assert sum(1 for n in enums if n == "_ReviewOrder") == 1  # rendered once



# ── US3 (T015): direction flip moves NULLs (member SQL, window+outer) ─────


@pytest.mark.asyncio
async def test_direction_flip_moves_nulls_member_side():
    """direction ASC flips a ``desc + nulls_last`` profile: NULLs go end → start.
    The flipped terms feed BOTH the window inner and the outer ORDER BY, so the
    NULL position stays consistent with the row order. Member-side via
    ``page_by_<key>_in``. specs/014 US3 / SC-001."""

    class _NullsBase(SQLModel):
        pass

    class _NullsItem(_NullsBase, table=True):
        __tablename__ = "nx14_nulls_item"
        id: int | None = Field(default=None, primary_key=True)
        group_id: int
        rating: int | None = None

    engine = create_async_engine("sqlite+aiosqlite://")
    sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(_NullsItem.__table__.create, checkfirst=True)
    async with sf() as s:
        s.add_all([
            _NullsItem(id=1, group_id=9, rating=5),
            _NullsItem(id=2, group_id=9, rating=None),
            _NullsItem(id=3, group_id=9, rating=3),
            _NullsItem(id=4, group_id=9, rating=None),
            _NullsItem(id=5, group_id=9, rating=4),
        ])
        await s.commit()

    handler = GraphQLHandler(
        base=_NullsBase, session_factory=sf,
        auto_query_config=AutoQueryConfig(
            generate_by_id=False, generate_by_filter=False,
            batch_pages={"_NullsItem": {"group_id": BatchPageConfig(
                default_order="RATING",
                orders={"RATING": PageOrder([OrderTerm("rating", "desc", "last")])},
            )}},
        ),
        service_name="member",
    )
    try:
        # DESC = profile default (rating desc, nulls_last) → NULLs at the end;
        # PK tie-breaker follows the desc direction → among NULLs, id 4 before 2.
        desc = await handler.execute(
            "{ _NullsItem { page_by_group_id_in(group_id_list: [9], limit: 10, "
            "order: RATING, direction: DESC) { items { id rating } } } }"
        )
        assert not desc.get("errors"), desc
        desc_items = desc["data"]["_NullsItem"]["page_by_group_id_in"][0]["items"]
        assert [it["rating"] for it in desc_items] == [5, 4, 3, None, None]
        assert [it["id"] for it in desc_items if it["rating"] is None] == [4, 2]

        # ASC flips → rating asc, nulls_first → NULLs at the start; PK tie-breaker
        # flips to asc → among NULLs, id 2 before 4.
        asc = await handler.execute(
            "{ _NullsItem { page_by_group_id_in(group_id_list: [9], limit: 10, "
            "order: RATING, direction: ASC) { items { id rating } } } }"
        )
        assert not asc.get("errors"), asc
        asc_items = asc["data"]["_NullsItem"]["page_by_group_id_in"][0]["items"]
        assert [it["rating"] for it in asc_items] == [None, None, 3, 4, 5]
        assert [it["id"] for it in asc_items if it["rating"] is None] == [2, 4]
    finally:
        await engine.dispose()


# ── US1 (T013) + US2 (T014): mounter end-to-end + schema discovery ───────
#
# One federated fixture: catalog mounts reviews; reviews exposes TWO order
# profiles (HIGHEST_RATING = rating desc, NEWEST = created_at desc) on data
# where the two orders are anti-correlated, so a caller-chosen order/direction
# produces visibly different results.

_reviews = RemoteService("reviews", url="http://test/reviews")


class ODCatalogBase(SQLModel):
    pass


class ODReviewsBase(SQLModel):
    pass


class ODReview(ODReviewsBase, table=True):
    __tablename__ = "nx14_od_review"
    id: int | None = Field(default=None, primary_key=True)
    product_id: int
    title: str
    rating: int
    created_at: int


class ODProduct(ODCatalogBase, table=True):
    __tablename__ = "nx14_od_product"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    __relationships__ = [
        RemoteRelationship(
            fk="id", target=list[_reviews.ODReview],
            name="reviews", join_remote="product_id",
            pagination=True,
        ),
    ]


def _od_engine():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return create_async_engine(f"sqlite+aiosqlite:///{path}")


_cat_engine = _od_engine()
_rev_engine = _od_engine()
_cat_sf = async_sessionmaker(_cat_engine, class_=AsyncSession, expire_on_commit=False)
_rev_sf = async_sessionmaker(_rev_engine, class_=AsyncSession, expire_on_commit=False)
_od_seeded = False


async def _od_ensure_seed():
    global _od_seeded
    if _od_seeded:
        return
    async with _cat_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with _rev_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with _cat_sf() as s:
        s.add(ODProduct(id=1, name="P1"))
        await s.commit()
    async with _rev_sf() as s:
        # rating and created_at are anti-correlated so the two profiles diverge.
        #   title: A   B   C
        #   rating: 5   4   3     → HIGHEST_RATING desc = A B C
        #   created_at: 10 30 20  → NEWEST desc = B C A ; NEWEST asc = A C B
        s.add(ODReview(id=1, product_id=1, title="A", rating=5, created_at=10))
        s.add(ODReview(id=2, product_id=1, title="B", rating=4, created_at=30))
        s.add(ODReview(id=3, product_id=1, title="C", rating=3, created_at=20))
        await s.commit()
    _od_seeded = True


class _CountingTransport(GraphQLTransport):
    def __init__(self, client):
        super().__init__(client=client)
        self.gql_calls = 0

    async def post_json(self, url, body):
        if "/graphql" in url:
            self.gql_calls += 1
        return await super().post_json(url, body)


@pytest.fixture
async def od_federation():
    await _od_ensure_seed()
    reviews_handler = GraphQLHandler(
        base=ODReviewsBase, session_factory=_rev_sf,
        auto_query_config=AutoQueryConfig(
            batch_keys={"ODReview": ["product_id"]},
            batch_pages={
                "ODReview": {
                    "product_id": BatchPageConfig(
                        default_order="HIGHEST_RATING",
                        orders={
                            "HIGHEST_RATING": PageOrder(
                                [OrderTerm("rating", "desc")],
                                description="Highest rating first",
                            ),
                            "NEWEST": PageOrder(
                                [OrderTerm("created_at", "desc")],
                                description="Newest first",
                            ),
                        },
                    )
                }
            },
        ),
        service_name="reviews",
    )
    reviews_app = build_federable_app(reviews_handler)
    catalog_handler = GraphQLHandler(
        base=ODCatalogBase, session_factory=_cat_sf,
        auto_query_config=AutoQueryConfig(), service_name="catalog",
    )
    composite = Starlette(routes=[Mount("/reviews", app=reviews_app)])
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=composite), base_url="http://test",
    )
    transport = _CountingTransport(client=client)
    await catalog_handler.er.initialize(transport=transport)
    yield catalog_handler, transport
    await client.aclose()


def _review_titles(res):
    pkg = res["data"]["ODProduct"]["by_id"]["reviews"]
    return [it["title"] for it in pkg["items"]]


@pytest.mark.asyncio
async def test_us1_order_and_direction_chosen_by_caller(od_federation):
    """US1 / SC-002: same relationship, different ``order`` → different results,
    each correct. specs/014."""
    catalog_handler, _ = od_federation
    highest = await catalog_handler.execute(
        "{ ODProduct { by_id(id: 1) { reviews(limit: 5, order: HIGHEST_RATING, "
        "direction: DESC) { items { title } } } } }"
    )
    assert not highest.get("errors"), highest
    assert _review_titles(highest) == ["A", "B", "C"]  # rating desc

    newest_desc = await catalog_handler.execute(
        "{ ODProduct { by_id(id: 1) { reviews(limit: 5, order: NEWEST, "
        "direction: DESC) { items { title } } } } }"
    )
    assert not newest_desc.get("errors"), newest_desc
    assert _review_titles(newest_desc) == ["B", "C", "A"]  # created_at desc


@pytest.mark.asyncio
async def test_us1_direction_asc_flips_the_profile(od_federation):
    """US1 / SC-001: ``direction: ASC`` flips NEWEST (created_at desc) → asc,
    the strict reverse of DESC. specs/014."""
    catalog_handler, _ = od_federation
    asc = await catalog_handler.execute(
        "{ ODProduct { by_id(id: 1) { reviews(limit: 5, order: NEWEST, "
        "direction: ASC) { items { title } } } } }"
    )
    assert not asc.get("errors"), asc
    assert _review_titles(asc) == ["A", "C", "B"]  # created_at asc (flipped)


@pytest.mark.asyncio
async def test_us1_one_gql_per_traversal(od_federation):
    """SC-006: order/direction passthrough does not break the one-gql-per-service
    invariant."""
    catalog_handler, transport = od_federation
    await catalog_handler.execute(
        "{ ODProduct { by_id(id: 1) { reviews(limit: 5, order: NEWEST, "
        "direction: ASC) { items { title } } } } }"
    )
    assert transport.gql_calls == 1


@pytest.mark.asyncio
async def test_us2_sdl_exposes_order_enum_and_direction(od_federation):
    """US2 / SC-003: mounter SDL renders ``order`` (enum = both member profile
    names, default = default_order) + ``direction`` (ASC|DESC). specs/014."""
    catalog_handler, _ = od_federation
    sdl = catalog_handler.get_sdl()
    assert (
        "reviews(limit: Int, offset: Int = 0, "
        "order: ODReviewOrder = HIGHEST_RATING, direction: Direction): ODReviewResult!"
    ) in sdl
    # order enum carries BOTH member profile names.
    assert "enum ODReviewOrder {\n  HIGHEST_RATING\n  NEWEST\n}" in sdl
    assert "enum Direction {\n  ASC\n  DESC\n}" in sdl


@pytest.mark.asyncio
async def test_us2_introspection_matches_sdl(od_federation):
    """US2 / SC-003: ``__schema`` exposes the same order/direction args as SDL
    (two paths, one source), with the member default_order as default."""
    catalog_handler, _ = od_federation
    intro = catalog_handler.get_introspection_data()
    types = {t["name"]: t for t in intro["types"]}
    assert {v["name"] for v in types["ODReviewOrder"]["enumValues"]} == {
        "HIGHEST_RATING",
        "NEWEST",
    }
    product = types["ODProduct"]
    reviews_field = next(f for f in product["fields"] if f["name"] == "reviews")
    arg_by_name = {a["name"]: a for a in reviews_field["args"]}
    assert {"limit", "offset", "order", "direction"} <= set(arg_by_name)
    order_arg = arg_by_name["order"]
    # Drill the (nullable ENUM) type wrapper to its name.
    order_type = order_arg["type"]
    while order_type.get("ofType"):
        order_type = order_type["ofType"]
    assert order_type["name"] == "ODReviewOrder"
    assert order_arg["defaultValue"] == "HIGHEST_RATING"
    direction_type = arg_by_name["direction"]["type"]
    while direction_type.get("ofType"):
        direction_type = direction_type["ofType"]
    assert direction_type["name"] == "Direction"

