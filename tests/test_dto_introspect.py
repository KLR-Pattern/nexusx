"""specs/016 T005 — 独立 DTO introspection 端点。

serialize_dto_introspection(er) 把 member 的 federation-public DTO 序列化成
DTOFragment 列表；build_federable_app 多挂一条 GET /nexusx/dto-introspection。
β 的 /nexusx/er-introspection 完全不动（零回归）。
"""

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx import AutoQueryConfig, DefineSubset, GraphQLHandler, SubsetConfig
from nexusx.federation.contract import DTOIntrospectionResponse
from nexusx.federation.http import GraphQLTransport
from nexusx.federation.introspect import (
    build_federable_app,
    fetch_dto_introspection,
    serialize_dto_introspection,
)


class _IBase(SQLModel):
    pass


class _Product(_IBase, table=True):
    __tablename__ = "dto_introspect_product"
    id: int | None = SQLField(default=None, primary_key=True)
    name: str


# public DTO（带 resolve_* 计算字段）
class _PubDTO(DefineSubset):
    __subset__ = SubsetConfig(
        kls=_Product,
        fields=("name",),
        federation_public=True,
        federation_join_key="id",
    )
    name_upper: str | None = None

    def resolve_name_upper(self) -> str:
        return (self.name or "").upper()


# 非 public DTO（member 内部用，不暴露）
class _InternalDTO(DefineSubset):
    __subset__ = (_Product, ("name",))


def test_serialize_dto_introspection_only_public():
    er = GraphQLHandler(
        base=_IBase,
        session_factory=lambda: None,
        auto_query_config=AutoQueryConfig(),
        service_name="catalog",
        dto_classes=[_PubDTO, _InternalDTO],
    )._er_manager

    resp = serialize_dto_introspection(er)
    assert isinstance(resp, DTOIntrospectionResponse)
    assert resp.service_name == "catalog"
    # 只有序列化 public DTO（_InternalDTO 不漏）
    names = {d.name for d in resp.dtos}
    assert names == {_PubDTO.__name__}

    frag = resp.dtos[0]
    assert frag.base_entity == "_Product"
    assert frag.join_key == "id"
    # scalar_fields 含 subset 字段 + resolve_* 计算字段
    field_names = {f.name for f in frag.scalar_fields}
    assert "name" in field_names
    assert "name_upper" in field_names  # resolve_* 计算字段
    # batch_root 命名对称 by_<join_key>_in
    assert frag.batch_root.name == "by_id_in"
    assert frag.batch_root.arg_name == "id_list"


@pytest.mark.asyncio
async def test_dto_introspection_endpoint_and_beta_zero_regression():
    """GET /nexusx/dto-introspection 返 public DTO；er-introspection 不变（β 零回归）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    handler = GraphQLHandler(
        base=_IBase,
        session_factory=sf,
        auto_query_config=AutoQueryConfig(),
        service_name="catalog",
        dto_classes=[_PubDTO],
    )
    app = build_federable_app(handler)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    try:
        # DTO introspection 端点
        resp = await fetch_dto_introspection(GraphQLTransport(client=client), "http://test")
        assert resp.service_name == "catalog"
        assert {d.name for d in resp.dtos} == {_PubDTO.__name__}

        # β er-introspection 仍可访问且不含 DTO（零回归）
        er_raw = await client.get("http://test/nexusx/er-introspection")
        er_payload = er_raw.json()
        assert er_payload["service_name"] == "catalog"
        entity_names = {e["typename"] for e in er_payload["entities"]}
        assert _PubDTO.__name__ not in entity_names  # DTO 不进 ER diagram
        assert "_Product" in entity_names
    finally:
        await client.aclose()
        await engine.dispose()


def test_serialize_dto_introspection_requires_service_name():
    """service_name 未设 → fail-fast（对称 serialize_er_introspection）。"""
    from nexusx import ErManager

    er = ErManager(entities=[_Product], session_factory=lambda: None)  # 无 service_name
    er._dto_classes = [_PubDTO]
    with pytest.raises(ValueError, match="service_name"):
        serialize_dto_introspection(er)
