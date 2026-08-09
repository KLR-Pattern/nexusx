"""specs/016 — γ 失败路径覆盖（C/D/E）。

C: _wire_dto_remote_loaders fail-fast —— mounter 引用 member 未暴露的 DTO → 启动期 raise。
D: dto_batch_endpoint unknown DTO → errors 包（mounter 收到可包成 RemoteQueryError）。
E（在 test_dto_remote_loader.py）: DTO RemoteLoader resp.errors → RemoteQueryError。
"""

import httpx
import pytest
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from nexusx import DefineSubset, GraphQLHandler, SubsetConfig
from nexusx.federation import RemoteService
from nexusx.federation.contract import BatchRoot, DTOFragment, FieldDescriptor
from nexusx.federation.introspect import build_federable_app
from nexusx.federation.manager import FederationError, _wire_dto_remote_loaders
from nexusx.federation.registry import FederatedTypeRegistry

rev_svc = RemoteService("reviews", url="http://test/reviews")


class _WireBase(SQLModel):
    pass


class _WireProduct(_WireBase, table=True):
    __tablename__ = "dto_wire_product"
    __federation_keys__ = ["id"]
    id: int | None = SQLField(default=None, primary_key=True)
    name: str


class _MounterRef(DefineSubset):
    """mounter DTO 引用 reviews.NobodyDTO（member 未暴露）→ wiring 期应 fail-fast。"""

    __subset__ = (_WireProduct, ("id", "name"))
    ref: list[rev_svc.NobodyDTO] = SQLField(default_factory=list)


class _PublicWireDTO(DefineSubset):
    __subset__ = SubsetConfig(
        kls=_WireProduct,
        fields=("id", "name"),
        federation_public=True,
    )


def test_wire_dto_loaders_failfast_unknown_dto():
    """C: mounter 引用 member 未暴露的 public DTO → FederationError（启动期）。

    reviews 服务已 mount（endpoints 含 reviews），但只暴露 ReviewDTO；
    mounter 的 _MounterRef.ref 指向 reviews.NobodyDTO → has() False → raise。
    """
    from nexusx import ErManager

    reg = FederatedTypeRegistry()
    # member 暴露 ReviewDTO（让 has('reviews.ReviewDTO') True，reviews 服务算 mounted）
    reg.materialize_dtos({
        "reviews.ReviewDTO": DTOFragment(
            name="ReviewDTO",
            base_entity="Review",
            scalar_fields=[FieldDescriptor(name="title", type_name="str")],
            join_key="product_id",
            batch_root=BatchRoot(name="by_product_id_in", arg_name="product_id_list"),
        )
    })

    er = ErManager(entities=[_WireProduct], session_factory=lambda: None, service_name="catalog")
    er._dto_classes = [_MounterRef]

    with pytest.raises(FederationError, match="no such public DTO"):
        _wire_dto_remote_loaders(
            er, reg, dto_fragments={}, endpoints={"reviews": "http://test/reviews"},
            transport=None,
        )


@pytest.mark.asyncio
async def test_dto_batch_endpoint_unknown_dto_returns_errors():
    """D: POST 一个 member 没有的 DTO 名 → {'errors':[...]}（不是 500）。

    mounter 端 DTO RemoteLoader 见 resp.errors 包成 RemoteQueryError。
    unknown-DTO 分支在查 DB 前就返回，所以无需真 DB。
    """
    handler = GraphQLHandler(
        base=_WireBase, session_factory=lambda: None, service_name="reviews",
        # 无 public DTO —— _dto_batch_roots 为空
    )
    app = build_federable_app(handler)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    try:
        resp = await client.post(
            "http://test/nexusx/dto-batch",
            json={"dto": "Nonexistent", "join_key": "id", "keys": [1]},
        )
        payload = resp.json()
        assert "errors" in payload
        assert any("Nonexistent" in e.get("message", "") for e in payload["errors"])
        assert "data" not in payload
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_dto_batch_endpoint_rejects_join_key_mismatch():
    handler = GraphQLHandler(
        base=_WireBase,
        session_factory=lambda: None,
        service_name="reviews",
        dto_classes=[_PublicWireDTO],
    )
    app = build_federable_app(handler)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )
    try:
        resp = await client.post(
            "http://test/nexusx/dto-batch",
            json={"dto": "_PublicWireDTO", "join_key": "wrong", "keys": [1]},
        )
        payload = resp.json()
        assert "errors" in payload
        assert "uses join_key 'id'" in payload["errors"][0]["message"]
    finally:
        await client.aclose()
