"""specs/016 T004 — member DTO batch root 生成器。

add_dto_batch_roots(er_manager) 为每个 federation-public DTO 注册一个
``by_<join_key>_in(values) -> list[dict]`` 函数到 ``er_manager._dto_batch_roots``。
内部：按 join_key 取实体 → 造 DTO 实例 → ``er.create_resolver().resolve()``
→ ``model_dump(mode="json")``。返已 resolve 的 DTO 树（含 resolve_* 计算字段）。
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx import DefineSubset, ErManager, SubsetConfig
from nexusx.standard_queries import add_dto_batch_roots


class _BRBase(SQLModel):
    pass


class _Review(_BRBase, table=True):
    __tablename__ = "dto_br_review"
    id: int | None = SQLField(default=None, primary_key=True)
    product_id: int
    title: str
    rating: int


class _ReviewDTO(DefineSubset):
    __subset__ = SubsetConfig(
        kls=_Review,
        fields=("title", "rating", "product_id"),
        federation_public=True,
        federation_join_key="product_id",
    )
    # 计算字段（member Resolver 加工）
    rating_double: int | None = None

    def resolve_rating_double(self) -> int:
        return self.rating * 2


@pytest.mark.asyncio
async def test_dto_batch_root_resolves_and_aligns():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sf() as s:
        s.add(_Review(id=1, product_id=10, title="Great", rating=5))
        s.add(_Review(id=2, product_id=10, title="Okay", rating=3))
        s.add(_Review(id=3, product_id=20, title="Meh", rating=2))
        await s.commit()

    er = ErManager(entities=[_Review], session_factory=sf, service_name="reviews")
    er._dto_classes = [_ReviewDTO]  # member 把 public DTO 传给 ErManager
    add_dto_batch_roots(er)

    # _dto_batch_roots 注册了 _ReviewDTO 的 batch root（key = DTO __name__）
    assert _ReviewDTO.__name__ in er._dto_batch_roots
    by_fn, join_key = er._dto_batch_roots[_ReviewDTO.__name__]
    assert join_key == "product_id"

    rows = await by_fn([10, 20])
    # 返 list[dict]，含 resolve_* 计算字段
    assert len(rows) == 3
    by_pid = {}
    for r in rows:
        by_pid.setdefault(r["product_id"], []).append(r)
    # product_id=10 → 2 条（对齐）
    assert len(by_pid[10]) == 2
    assert {r["title"] for r in by_pid[10]} == {"Great", "Okay"}
    # resolve_* 计算字段被 member Resolver 加工
    great = next(r for r in rows if r["title"] == "Great")
    assert great["rating_double"] == 10  # 5 * 2
    okay = next(r for r in rows if r["title"] == "Okay")
    assert okay["rating_double"] == 6  # 3 * 2

    await engine.dispose()


@pytest.mark.asyncio
async def test_dto_batch_root_empty_keys_returns_empty():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    er = ErManager(entities=[_Review], session_factory=sf, service_name="reviews")
    er._dto_classes = [_ReviewDTO]
    add_dto_batch_roots(er)
    by_fn, _ = er._dto_batch_roots[_ReviewDTO.__name__]
    assert await by_fn([]) == []
    await engine.dispose()


def test_add_dto_batch_roots_skips_non_public():
    """非 public DTO（无 federation_public）不生成 batch root。"""

    class _InternalDTO(DefineSubset):
        __subset__ = (_Review, ("title",))

    er = ErManager(entities=[_Review], session_factory=lambda: None, service_name="reviews")
    er._dto_classes = [_InternalDTO]
    add_dto_batch_roots(er)
    assert er._dto_batch_roots == {}


def test_public_dto_join_key_validated_at_class_creation():
    """join_key 不在 DTO subset 字段里 → metaclass 期 fail-fast（先于 add_dto_batch_roots）。"""
    import pytest as _pytest

    with _pytest.raises(ValueError, match="federation_join_key"):

        class _BadDTO(DefineSubset):
            __subset__ = SubsetConfig(
                kls=_Review,
                fields=("title", "rating", "product_id"),
                federation_public=True,
                federation_join_key="nonexistent",
            )


def test_add_dto_batch_roots_rejects_unsupported_join_key_type():
    """Decimal 等 _SUPPORTED_JOIN_TYPES 外的 join key → member 启动期 fail-fast。

    对称 β 的 _check_join_contract：DTO federation 走 JSON wire，非支持类型的
    join key 会静默落空（Decimal 响应侧被 model_dump 转成 str、lookup 侧未归一化，
    永远对不上桶）。member 端 add_dto_batch_roots 拿得到 base_entity 列类型，
    是最早的 fail-fast 点。
    """
    from decimal import Decimal

    class _DecReview(_BRBase, table=True):
        __tablename__ = "dto_br_decimal"
        id: int | None = SQLField(default=None, primary_key=True)
        amount: Decimal | None = SQLField(default=None)

    class _DecDTO(DefineSubset):
        __subset__ = SubsetConfig(
            kls=_DecReview,
            fields=("amount",),
            federation_public=True,
            federation_join_key="amount",
        )

    er = ErManager(
        entities=[_DecReview], session_factory=lambda: None, service_name="reviews",
    )
    er._dto_classes = [_DecDTO]
    with pytest.raises(ValueError, match="unsupported type"):
        add_dto_batch_roots(er)


def test_add_dto_batch_roots_accepts_uuid_join_key():
    """UUID join key 是 _SUPPORTED_JOIN_TYPES 成员 → 放行（配合 wire 归一化可用）。

    UUID 是最常见的 PK 类型之一；任务 1 的 wire 归一化让它能跨 JSON 往返，
    本测试确认类型校验不会误拒它。
    """
    from uuid import UUID

    class _UuidReview(_BRBase, table=True):
        __tablename__ = "dto_br_uuid"
        id: UUID | None = SQLField(default=None, primary_key=True)
        owner_id: UUID | None = SQLField(default=None)

    class _UuidDTO(DefineSubset):
        __subset__ = SubsetConfig(
            kls=_UuidReview,
            fields=("owner_id",),
            federation_public=True,
            federation_join_key="owner_id",
        )

    er = ErManager(
        entities=[_UuidReview], session_factory=lambda: None, service_name="reviews",
    )
    er._dto_classes = [_UuidDTO]
    add_dto_batch_roots(er)  # 不抛
    assert _UuidDTO.__name__ in er._dto_batch_roots
