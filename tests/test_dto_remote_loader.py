"""specs/016 T007 — DTO RemoteLoader: POST JSON 到 /nexusx/dto-batch + 对齐。

create_dto_remote_loader 生成 DataLoader，batch_load_fn POST {dto, join_key, keys}
到 member 的 /nexusx/dto-batch，member 返已 resolve 的 DTO 树 list[dict]，loader
按 join_key 分桶对齐到 mounter 物化的 DTO 类（model_validate 直收，不做 _orm_to_dto）。
"""

from __future__ import annotations

import pytest
from pydantic import create_model


class FakeTransport:
    """记录 POST body；返 canned {data: [...]} 响应。"""

    def __init__(self, data):
        self.data = data
        self.posts: list[tuple[str, dict]] = []

    async def post_json(self, url, body):
        self.posts.append((url, body))
        return {"data": self.data}


@pytest.mark.asyncio
async def test_dto_remote_loader_posts_json_and_aligns_to_many():
    from nexusx.federation.remote_loader import create_dto_remote_loader

    target_cls = create_model(
        "ReviewDTO",
        title=(str, None),
        rating=(int, None),
        product_id=(int, None),
        rating_double=(int, None),
    )
    # member 返的 resolved DTO 树（已 resolve rating_double）
    rows = [
        {"title": "Great", "rating": 5, "product_id": 10, "rating_double": 10},
        {"title": "Okay", "rating": 3, "product_id": 10, "rating_double": 6},
        {"title": "Meh", "rating": 2, "product_id": 20, "rating_double": 4},
    ]
    transport = FakeTransport(rows)

    loader_cls = create_dto_remote_loader(
        typename="ReviewDTO",
        join_key="product_id",
        endpoint="http://test/reviews",
        target_cls=target_cls,
        transport=transport,
        is_list=True,
    )
    result = await loader_cls().load_many([10, 20])

    # 对齐：key 10 → 2 条，key 20 → 1 条
    assert len(result) == 2
    assert isinstance(result[0], list)
    assert {r.title for r in result[0]} == {"Great", "Okay"}
    assert [r.title for r in result[1]] == ["Meh"]
    # member 已 resolve 的字段直收
    assert result[0][0].rating_double == 10

    # POST 到 dto-batch 端点，body 含 dto/join_key/keys
    assert len(transport.posts) == 1
    url, body = transport.posts[0]
    assert url.endswith("/nexusx/dto-batch")
    assert body == {"dto": "ReviewDTO", "join_key": "product_id", "keys": [10, 20]}


@pytest.mark.asyncio
async def test_dto_remote_loader_to_one():
    from nexusx.federation.remote_loader import create_dto_remote_loader

    target_cls = create_model("UDTO", name=(str, None), id=(int, None))
    rows = [{"name": "Alice", "id": 7}]
    transport = FakeTransport(rows)
    loader_cls = create_dto_remote_loader(
        typename="UDTO", join_key="id", endpoint="http://test/u",
        target_cls=target_cls, transport=transport, is_list=False,
    )
    result = await loader_cls().load_many([7, 999])
    assert result[0].name == "Alice"
    assert result[1] is None  # 缺 key → None


@pytest.mark.asyncio
async def test_dto_remote_loader_missing_key_returns_empty_list():
    from nexusx.federation.remote_loader import create_dto_remote_loader

    target_cls = create_model("R", title=(str, None), product_id=(int, None))
    transport = FakeTransport([])  # member 无数据
    loader_cls = create_dto_remote_loader(
        typename="R", join_key="product_id", endpoint="http://test/r",
        target_cls=target_cls, transport=transport, is_list=True,
    )
    result = await loader_cls().load_many([10])
    assert result == [[]]


@pytest.mark.asyncio
async def test_dto_remote_loader_rejects_bad_response_shape():
    from nexusx.federation.remote_loader import RemoteQueryError, create_dto_remote_loader

    target_cls = create_model("R", title=(str, None), product_id=(int, None))
    transport = FakeTransport("not-a-list")  # data 非 list
    loader_cls = create_dto_remote_loader(
        typename="R", join_key="product_id", endpoint="http://test/r",
        target_cls=target_cls, transport=transport, is_list=True,
    )
    with pytest.raises(RemoteQueryError):
        await loader_cls().load_many([10])


@pytest.mark.asyncio
async def test_dto_remote_loader_propagates_errors_envelope():
    """E: member 返 {'errors':[...]}（Resolver 失败透传）→ RemoteQueryError。

    对称 B（e2e member Resolver 失败）；这里在 loader 单测层直接喂 errors 包。
    """
    from nexusx.federation.remote_loader import RemoteQueryError, create_dto_remote_loader

    class _ErrorsTransport:
        async def post_json(self, url, body):
            return {"errors": [{"message": "discount service down"}]}

    target_cls = create_model("R", title=(str, None), product_id=(int, None))
    loader_cls = create_dto_remote_loader(
        typename="ReviewDTO", join_key="product_id", endpoint="http://test/r",
        target_cls=target_cls, transport=_ErrorsTransport(), is_list=True,
    )
    with pytest.raises(RemoteQueryError, match="discount service down"):
        await loader_cls().load_many([10])


@pytest.mark.asyncio
async def test_dto_remote_loader_rejects_non_dict_response():
    """E 续: resp 非 dict（传输异常）→ RemoteQueryError fail-fast。"""
    from nexusx.federation.remote_loader import RemoteQueryError, create_dto_remote_loader

    class _BadTransport:
        async def post_json(self, url, body):
            return ["unexpected"]  # 非 dict

    target_cls = create_model("R", title=(str, None), product_id=(int, None))
    loader_cls = create_dto_remote_loader(
        typename="R", join_key="product_id", endpoint="http://test/r",
        target_cls=target_cls, transport=_BadTransport(), is_list=True,
    )
    with pytest.raises(RemoteQueryError):
        await loader_cls().load_many([10])
