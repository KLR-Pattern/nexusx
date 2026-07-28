"""Composition: federation data → DefineSubset projection (+ computed fields).

Locks the pattern demonstrated by demo/federation/catalog_app.CatalogService:
a UseCase-side projection that queries the federated graph via handler.execute,
then shapes the result with a DefineSubset DTO sourced from the LOCAL entry
entity, with computed fields derived from the REMOTE data.
"""

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.applications import Starlette
from starlette.routing import Mount

from nexusx import AutoQueryConfig, DefineSubset, GraphQLHandler
from nexusx.federation import RemoteRelationship
from nexusx.federation.http import GraphQLTransport
from nexusx.federation.introspect import build_federable_app


class _UB(SQLModel):
    pass


class _RB(SQLModel):
    pass


class _CB(SQLModel):
    pass


class DSUser(_UB, table=True):
    __tablename__ = "fed_ds_user"
    id: int | None = Field(default=None, primary_key=True)
    name: str


class DSReview(_RB, table=True):
    __tablename__ = "fed_ds_review"
    id: int | None = Field(default=None, primary_key=True)
    product_id: int
    author_id: int
    title: str
    rating: int
    __relationships__ = [
        RemoteRelationship(
            name="author", target="users.DSUser",
            join_local="author_id", join_remote="id",
        ),
    ]


class DSProduct(_CB, table=True):
    __tablename__ = "fed_ds_product"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    __relationships__ = [
        RemoteRelationship(
            name="reviews", target="reviews.DSReview",
            join_local="id", join_remote="product_id", is_list=True,
        ),
    ]


class ProductSummary(DefineSubset):
    """DefineSubset over the LOCAL entry entity + remote-derived computed fields."""

    __subset__ = (DSProduct, ("id", "name"))
    review_count: int = 0
    avg_rating: float = 0.0
    top_reviewer: str | None = None


async def _project(handler: GraphQLHandler) -> list[ProductSummary]:
    """Mirror of CatalogService.product_summaries (federation → DefineSubset)."""
    res = await handler.execute(
        "{ DSProduct { by_filter { id name reviews { rating author { name } } } } }"
    )
    products = ((res.get("data") or {}).get("DSProduct") or {}).get("by_filter") or []
    out: list[ProductSummary] = []
    for p in products:
        reviews = p.get("reviews") or []
        ratings = [r["rating"] for r in reviews]
        reviewers = [r["author"]["name"] for r in reviews if r.get("author")]
        out.append(
            ProductSummary(
                id=p["id"],
                name=p["name"],
                review_count=len(reviews),
                avg_rating=round(sum(ratings) / len(ratings), 2) if ratings else 0.0,
                top_reviewer=(
                    max(set(reviewers), key=reviewers.count) if reviewers else None
                ),
            )
        )
    return out


@pytest.mark.asyncio
async def test_definesubset_projection_over_federated_data():
    engines = {k: create_async_engine("sqlite+aiosqlite:///:memory:") for k in ("u", "r", "c")}
    try:
        for e in engines.values():
            async with e.begin() as conn:
                await conn.run_sync(SQLModel.metadata.create_all)

        def sf(k):
            return async_sessionmaker(engines[k], class_=AsyncSession, expire_on_commit=False)

        async with sf("u")() as s:
            s.add(DSUser(id=1, name="Alice"))
            s.add(DSUser(id=2, name="Bob"))
            await s.commit()
        async with sf("r")() as s:
            s.add(DSReview(id=1, product_id=1, author_id=1, title="Great", rating=5))
            s.add(DSReview(id=2, product_id=1, author_id=2, title="Okay", rating=3))
            s.add(DSReview(id=3, product_id=2, author_id=1, title="Mediocre", rating=2))
            await s.commit()
        async with sf("c")() as s:
            s.add(DSProduct(id=1, name="Widget"))
            s.add(DSProduct(id=2, name="Gadget"))
            await s.commit()

        uh = GraphQLHandler(
            base=_UB, session_factory=sf("u"),
            auto_query_config=AutoQueryConfig(batch_keys={"DSUser": ["id"]}),
            service_name="users",
        )
        rh = GraphQLHandler(
            base=_RB, session_factory=sf("r"),
            auto_query_config=AutoQueryConfig(batch_keys={"DSReview": ["product_id", "author_id"]}),
            service_name="reviews",
        )
        ch = GraphQLHandler(
            base=_CB, session_factory=sf("c"),
            auto_query_config=AutoQueryConfig(), service_name="catalog",
        )

        composite = Starlette(routes=[
            Mount("/users", app=build_federable_app(uh)),
            Mount("/reviews", app=build_federable_app(rh)),
        ])
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=composite), base_url="http://test")
        transport = GraphQLTransport(client=client)
        await rh.federate({"users": "http://test/users"}, transport=transport)
        await ch.federate({"reviews": "http://test/reviews"}, transport=transport)

        summaries = await _project(ch)

        by_name = {s.name: s for s in summaries}
        # Widget: 2 reviews (5, 3) across Alice + Bob.
        assert by_name["Widget"].review_count == 2
        assert by_name["Widget"].avg_rating == 4.0
        assert by_name["Widget"].top_reviewer in {"Alice", "Bob"}
        # Gadget: 1 review (2) by Alice.
        assert by_name["Gadget"].review_count == 1
        assert by_name["Gadget"].avg_rating == 2.0
        assert by_name["Gadget"].top_reviewer == "Alice"
        # DefineSubset sourced from the LOCAL entity (not a remote/dynamic type).
        assert ProductSummary.__nexusx_subset_source__ is DSProduct

        # ── DefineSubset a REMOTE type (reviews.DSReview) ──────────────────
        # The materialized remote class only exists post-federate, so the DTO is
        # built dynamically from the FederatedTypeRegistry, not at module load.
        from pydantic import ConfigDict

        fed_review = ch._er_manager._fed_registry.get("reviews.DSReview")
        assert fed_review is not None
        ReviewSummary = type(
            "ReviewSummary",
            (DefineSubset,),
            {
                "__subset__": (fed_review, ("title", "rating")),
                "model_config": ConfigDict(extra="ignore"),
                "__module__": __name__,
            },
        )
        assert list(ReviewSummary.model_fields) == ["title", "rating"]
        assert ReviewSummary.__nexusx_subset_source__ is fed_review  # subset of the REMOTE type
        # Project the federated reviews (selecting only the subset's fields).
        res2 = await ch.execute(
            "{ DSProduct { by_filter { reviews { title rating } } } }"
        )
        sample = res2["data"]["DSProduct"]["by_filter"][0]["reviews"][0]
        projected = ReviewSummary.model_validate(sample).model_dump()
        assert projected == {"title": sample["title"], "rating": sample["rating"]}

        # ── Cross-service data composition (join local + reviews + users) ────
        # A composed view is NOT a single-source DefineSubset — it flattens the
        # federated nested result (Product → Review → User) into rows that each
        # carry fields from all three services.
        class _ProductReviewView(BaseModel):
            product_name: str
            title: str
            rating: int
            author_name: str | None = None

        res3 = await ch.execute(
            "{ DSProduct { by_filter { name reviews { title rating author { name } } } } }"
        )
        composed = [
            _ProductReviewView(
                product_name=p["name"],
                title=r["title"],
                rating=r["rating"],
                author_name=(r.get("author") or {}).get("name"),
            )
            for p in ((res3.get("data") or {}).get("DSProduct") or {}).get("by_filter") or []
            for r in p.get("reviews") or []
        ]
        # 3 reviews total: Widget(Great/Alice, Okay/Bob) + Gadget(Mediocre/Alice).
        assert len(composed) == 3
        widget = [c for c in composed if c.product_name == "Widget"]
        assert {c.title for c in widget} == {"Great", "Okay"}
        assert {c.author_name for c in widget} == {"Alice", "Bob"}
        assert [c.title for c in composed if c.product_name == "Gadget"] == ["Mediocre"]
    finally:
        await client.aclose()
        for e in engines.values():
            await e.dispose()
