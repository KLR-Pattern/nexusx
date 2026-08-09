"""Member-side federation pagination configuration and SQL behavior."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import JSON
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx import (
    AutoQueryConfig,
    BatchPageConfig,
    GraphQLHandler,
    OrderTerm,
    PageOrder,
    add_standard_queries,
)
from nexusx.federation.contract import (
    EntityFragment,
    FieldDescriptor,
    RelDescriptor,
)
from nexusx.federation.introspect import serialize_er_introspection
from nexusx.federation.registry import FederatedTypeRegistry


async def _unused_session() -> Any:
    raise AssertionError("session should not be used")


class PageConfigBase(SQLModel):
    pass


class PageConfigItem(PageConfigBase, table=True):
    __tablename__ = "fed_page_config_item"
    id: int | None = Field(default=None, primary_key=True)
    product_id: int
    category: str
    rating: int | None = None


class PageConfigJson(PageConfigBase, table=True):
    __tablename__ = "fed_page_config_json"
    id: int | None = Field(default=None, primary_key=True)
    group_id: int
    payload: dict = Field(sa_type=JSON)


class PageOrderBase(SQLModel):
    pass


class PageOrderItem(PageOrderBase, table=True):
    __tablename__ = "fed_page_order_item"
    id: int | None = Field(default=None, primary_key=True)
    product_id: int
    rating: int | None = None


def _page_config(*terms: OrderTerm) -> BatchPageConfig:
    return BatchPageConfig(
        default_order="PRIMARY",
        orders={"PRIMARY": PageOrder(list(terms))},
    )


@pytest.fixture(autouse=True)
def _reset_federation_dunders():
    """每个测试后重置模块级 entity 的 federation dunder，防跨测试污染。"""
    yield
    for kls in (PageConfigItem, PageConfigJson, PageOrderItem):
        kls.__federation_keys__ = []
        kls.__pagination_orders__ = None


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (
            BatchPageConfig(
                default_order="MISSING",
                orders={"PRIMARY": PageOrder([OrderTerm("product_id")])},
            ),
            "default_order",
        ),
        (
            BatchPageConfig(
                default_order="lowercase",
                orders={"lowercase": PageOrder([OrderTerm("product_id")])},
            ),
            "enum-safe",
        ),
        (
            BatchPageConfig(
                default_order="PRIMARY",
                orders={"PRIMARY": PageOrder([])},
            ),
            "cannot be empty",
        ),
        (
            _page_config(OrderTerm("missing")),
            "not a SQL column",
        ),
        (
            _page_config(OrderTerm("product_id", "sideways")),  # type: ignore[arg-type]
            "direction",
        ),
        (
            _page_config(OrderTerm("rating")),
            "Nullable order field",
        ),
        (
            _page_config(OrderTerm(PageConfigItem.product_id + 1)),
            "column name",
        ),
    ],
)
def test_invalid_page_order_config_rejected(config, message):
    PageConfigItem.__federation_keys__ = ["product_id"]
    PageConfigItem.__pagination_orders__ = config
    with pytest.raises((TypeError, ValueError), match=message):
        add_standard_queries(
            [PageConfigItem],
            AutoQueryConfig(
                generate_by_id=False,
                generate_by_filter=False,
            ),
            _unused_session,
        )


def test_json_order_field_rejected():
    PageConfigJson.__federation_keys__ = ["group_id"]
    PageConfigJson.__pagination_orders__ = _page_config(OrderTerm("payload"))
    with pytest.raises(ValueError, match="unsupported column type"):
        add_standard_queries(
            [PageConfigJson],
            AutoQueryConfig(
                generate_by_id=False,
                generate_by_filter=False,
            ),
            _unused_session,
        )


def test_batch_keys_do_not_implicitly_generate_page_root():
    class FullOnlyBase(SQLModel):
        pass

    class FullOnly(FullOnlyBase, table=True):
        __tablename__ = "fed_page_config_full_only"
        __federation_keys__ = ["group_id"]
        id: int | None = Field(default=None, primary_key=True)
        group_id: int

    add_standard_queries(
        [FullOnly],
        AutoQueryConfig(
            generate_by_id=False,
            generate_by_filter=False,
        ),
        _unused_session,
    )
    assert hasattr(FullOnly, "by_group_id_in")
    assert not hasattr(FullOnly, "page_by_group_id_in")


def test_multi_key_schema_and_er_capabilities_are_unique_and_semantic():
    PageConfigItem.__federation_keys__ = ["product_id", "category"]
    # specs/020: single entity-level profile — product_id AND category (both in
    # __federation_keys__) share it; each gets its own page_by_<key>_in + a
    # per-field order enum, all backed by this one sort.
    PageConfigItem.__pagination_orders__ = BatchPageConfig(
        default_order="HIGHEST",
        orders={
            "HIGHEST": PageOrder(
                [OrderTerm("rating", "desc", "last")],
                description="Highest rating first",
            )
        },
    )
    handler = GraphQLHandler(
        base=PageConfigBase,
        session_factory=_unused_session,
        auto_query_config=AutoQueryConfig(
            generate_by_id=False,
            generate_by_filter=False,
        ),
        service_name="member",
    )

    sdl = handler.get_sdl()
    assert "type PageConfigItemProductIdPagePackage {" in sdl
    assert "type PageConfigItemCategoryPagePackage {" in sdl
    assert "enum PageConfigItemProductIdPageOrder {" in sdl
    assert "enum PageConfigItemCategoryPageOrder {" in sdl
    # The pagination root signature references Direction — its enum block must
    # be present too, or the SDL would name an undefined type. specs/014.
    assert "enum Direction {\n  ASC\n  DESC\n}" in sdl
    assert "page_by_product_id_in(" in sdl
    assert "page_by_category_in(" in sdl

    response = serialize_er_introspection(handler.er)
    fragment = next(e for e in response.entities if e.typename == "PageConfigItem")
    roots = {root.name: root for root in fragment.batch_roots}
    capability = roots["page_by_product_id_in"].page
    assert capability is not None
    assert capability.protocol == "offset-v1"
    assert capability.default_order == "HIGHEST"
    assert capability.orders[0].model_dump() == {
        "name": "HIGHEST",
        "description": "Highest rating first",
    }


def test_materialized_paginated_relationship_accepts_page_package():
    registry = FederatedTypeRegistry()
    registry.materialize(
        {
            "member.Parent": EntityFragment(
                typename="Parent",
                scalar_fields=[FieldDescriptor(name="id", type_name="int")],
                relationships=[
                    RelDescriptor(
                        name="children",
                        direction="ONETOMANY",
                        fk_field="id",
                        target_typename="Child",
                        is_list=True,
                        pagination=True,
                    )
                ],
            ),
            "member.Child": EntityFragment(
                typename="Child",
                scalar_fields=[FieldDescriptor(name="id", type_name="int")],
            ),
        }
    )
    parent_type = registry.get("member.Parent")
    parent = parent_type.model_validate(
        {
            "id": 1,
            "children": {
                "items": [{"id": 2}],
                "pagination": {"has_more": False},
            },
        }
    )
    assert parent.children["items"][0]["id"] == 2


@pytest.mark.asyncio
async def test_desc_nulls_last_and_pk_tie_breaker_are_stable():
    engine = create_async_engine("sqlite+aiosqlite://")
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(PageOrderItem.__table__.create, checkfirst=True)
    async with session_factory() as session:
        session.add_all(
            [
                PageOrderItem(id=1, product_id=9, rating=5),
                PageOrderItem(id=2, product_id=9, rating=5),
                PageOrderItem(id=3, product_id=9, rating=None),
                PageOrderItem(id=4, product_id=9, rating=3),
            ]
        )
        await session.commit()

    PageOrderItem.__federation_keys__ = ["product_id"]
    PageOrderItem.__pagination_orders__ = BatchPageConfig(
        default_order="HIGHEST",
        orders={
            "HIGHEST": PageOrder(
                [OrderTerm("rating", "desc", "last")]
            )
        },
    )
    handler = GraphQLHandler(
        base=PageOrderBase,
        session_factory=session_factory,
        auto_query_config=AutoQueryConfig(
            generate_by_id=False,
            generate_by_filter=False,
        ),
        service_name="member",
    )
    result = await handler.execute(
        "{ PageOrderItem { page_by_product_id_in("
        "product_id_list: [9], limit: 10, order: HIGHEST) { "
        "product_id items { id rating } pagination { has_more } } } }"
    )
    assert not result.get("errors"), result
    package = result["data"]["PageOrderItem"]["page_by_product_id_in"][0]
    assert [item["id"] for item in package["items"]] == [2, 1, 4, 3]
    assert package["pagination"] == {"has_more": False}

    key_only = await handler.execute(
        "{ PageOrderItem { page_by_product_id_in("
        "product_id_list: [9], limit: 1, order: HIGHEST) { product_id } } }"
    )
    assert key_only["data"]["PageOrderItem"]["page_by_product_id_in"] == [
        {"product_id": 9}
    ]
    await engine.dispose()
