"""tests for 025 FK 关系条件过滤（Loader 识别 primaryjoin/secondaryjoin 额外条件）。

Fixture 实体族（specs/025-fk-loader-conditions/tasks.md T001）：
- CondUser / CondComment：O2M（eq / IS NULL / or_ / enum 形态）+ M2O（approver 过滤停用用户）
- CondProfile：反向一对一（O2M_SCALAR）条件
- CondArticle / CondReader / CondArticleReader：M2M（目标列 / link 表列条件，含 primaryjoin 侧声明）
- Bad* / OddPair* / Func*：非法声明组（US4 错误矩阵，测试内单独构造 ErManager）
- PR review 组：Mixed*（跨 target+link 两表 or_）/ Neq*（FK 对非等值）报错矩阵；
  Brf*（backref 传播）豁免行为，需建表走真实加载

声明面坑规避依据 contracts/declaration-surface.md §4：
Optional["X"] 注解、link_model 传 SQLModel 类、enum/secondaryjoin 引用 secondary 列用 lambda。
"""

import enum
from datetime import datetime, timezone
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy import and_, func, or_
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Relationship, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexusx.loader.pagination import PageArgs, PageLoadCommand

# ──────────────────────────────────────────────────────────
# 实体族
# ──────────────────────────────────────────────────────────


class CondBase(SQLModel):
    """Marker base for GraphQLHandler(base=...) discovery (conftest pattern)."""

    pass


class CondVisibility(str, enum.Enum):
    public = "public"
    private = "private"


class CondUser(CondBase, table=True):
    __tablename__ = "cond_user"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    status: str = Field(default="enabled")

    comments: list["CondComment"] = Relationship(
        back_populates="owner",
        sa_relationship_kwargs={
            "foreign_keys": "[CondComment.owner_id]",
            "order_by": "CondComment.id",
        },
    )
    # eq 条件（状态列软删除）
    active_comments: list["CondComment"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[CondComment.owner_id]",
            "primaryjoin": "and_(CondUser.id==CondComment.owner_id, CondComment.status=='active')",
            "viewonly": True,
            "order_by": "CondComment.id",
        },
    )
    # IS NULL 条件（时间戳软删除）
    live_comments: list["CondComment"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[CondComment.owner_id]",
            "primaryjoin": "and_(CondUser.id==CondComment.owner_id, CondComment.deleted_at==None)",
            "viewonly": True,
            "order_by": "CondComment.id",
        },
    )
    # or_ 组合整体条件
    notable_comments: list["CondComment"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[CondComment.owner_id]",
            "primaryjoin": lambda: and_(
                CondUser.id == CondComment.owner_id,
                or_(CondComment.status == "active", CondComment.pinned == True),  # noqa: E712
            ),
            "viewonly": True,
            "order_by": "CondComment.id",
        },
    )
    # enum 值条件（lambda 形式——字符串求值环境看不到 enum 类）
    public_comments: list["CondComment"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[CondComment.owner_id]",
            "primaryjoin": lambda: and_(
                CondUser.id == CondComment.owner_id,
                CondComment.visibility == CondVisibility.public,
            ),
            "viewonly": True,
            "order_by": "CondComment.id",
        },
    )
    # 多条件 AND（两条额外条件各自独立收集）
    fresh_comments: list["CondComment"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[CondComment.owner_id]",
            "primaryjoin": "and_(CondUser.id==CondComment.owner_id, "
            "CondComment.status=='active', CondComment.deleted_at==None)",
            "viewonly": True,
            "order_by": "CondComment.id",
        },
    )
    # 反向一对一（O2M_SCALAR）条件
    profile: Optional["CondProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "and_(CondUser.id==CondProfile.user_id, CondProfile.archived==False)",
            "uselist": False,
            "viewonly": True,
        },
    )


class CondComment(CondBase, table=True):
    __tablename__ = "cond_comment"
    id: int | None = Field(default=None, primary_key=True)
    body: str
    status: str = Field(default="active")
    pinned: bool = Field(default=False)
    deleted_at: datetime | None = Field(default=None)
    visibility: CondVisibility = Field(default=CondVisibility.public)
    owner_id: int = Field(foreign_key="cond_user.id")
    approver_id: int | None = Field(default=None, foreign_key="cond_user.id")

    owner: Optional["CondUser"] = Relationship(
        back_populates="comments",
        sa_relationship_kwargs={"foreign_keys": "CondComment.owner_id"},
    )
    # M2O 条件：过滤停用审批人
    approver: Optional["CondUser"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "and_(CondComment.approver_id==CondUser.id, CondUser.status=='enabled')",
            "foreign_keys": "CondComment.approver_id",
        },
    )


class CondProfile(CondBase, table=True):
    __tablename__ = "cond_profile"
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="cond_user.id", unique=True)
    archived: bool = Field(default=False)


# link 表实体（link_model 必须传 SQLModel 类——原生 Table 对象会在类构造期报错）
class CondArticleReader(CondBase, table=True):
    __tablename__ = "cond_article_reader"
    article_id: int = Field(foreign_key="cond_article.id", primary_key=True)
    reader_id: int = Field(foreign_key="cond_reader.id", primary_key=True)
    status: str = Field(default="active")


class CondArticle(CondBase, table=True):
    __tablename__ = "cond_article"
    id: int | None = Field(default=None, primary_key=True)
    title: str

    readers: list["CondReader"] = Relationship(
        back_populates="articles",
        link_model=CondArticleReader,
        # order_by 触发无条件 page_loader（悬空 link 口径测试用）
        sa_relationship_kwargs={"order_by": "CondReader.id"},
    )
    # M2M primaryjoin 侧 link 表列条件（PR review 放开：link/target 列条件
    # 无论声明在哪个 join 侧都可执行，loader 按引用列路由）
    declared_link_readers: list["CondReader"] = Relationship(
        back_populates="articles",
        link_model=CondArticleReader,
        sa_relationship_kwargs={
            "primaryjoin": lambda: and_(
                CondArticle.id == CondArticleReader.__table__.c.article_id,
                CondArticleReader.__table__.c.status == "active",
            ),
            "secondaryjoin": lambda: and_(
                CondReader.id == CondArticleReader.__table__.c.reader_id,
            ),
            "order_by": "CondReader.id",
            "viewonly": True,
        },
    )
    # M2M 目标侧条件
    active_readers: list["CondReader"] = Relationship(
        back_populates="articles",
        link_model=CondArticleReader,
        sa_relationship_kwargs={
            "secondaryjoin": lambda: and_(
                CondReader.id == CondArticleReader.__table__.c.reader_id,
                CondReader.status == "active",
            ),
            "order_by": "CondReader.id",  # 触发 M2M page_loader 生成（既有机制）
            "viewonly": True,
        },
    )
    # M2M link 表列条件（关联有效性）
    valid_readers: list["CondReader"] = Relationship(
        back_populates="articles",
        link_model=CondArticleReader,
        sa_relationship_kwargs={
            "secondaryjoin": lambda: and_(
                CondReader.id == CondArticleReader.__table__.c.reader_id,
                CondArticleReader.__table__.c.status == "active",
            ),
            "viewonly": True,
        },
    )


class CondReader(CondBase, table=True):
    __tablename__ = "cond_reader"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    status: str = Field(default="active")

    articles: list["CondArticle"] = Relationship(
        back_populates="readers", link_model=CondArticleReader
    )


# ── 非法声明组（US4 错误矩阵；测试内单独构造 ErManager，不进正常 fixture）──


class BadSourceUser(SQLModel, table=True):
    __tablename__ = "cond_bad_source_user"
    id: int | None = Field(default=None, primary_key=True)
    flag: str = Field(default="x")

    items: list["BadSourceItem"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "and_(BadSourceUser.id==BadSourceItem.owner_id, "
            "BadSourceUser.flag=='keep')",
            "viewonly": True,
        },
    )


class BadSourceItem(SQLModel, table=True):
    __tablename__ = "cond_bad_source_item"
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="cond_bad_source_user.id")


class BadM2MLink(SQLModel, table=True):
    __tablename__ = "cond_bad_m2m_link"
    owner_id: int = Field(foreign_key="cond_bad_m2m_owner.id", primary_key=True)
    item_id: int = Field(foreign_key="cond_bad_m2m_item.id", primary_key=True)


class BadM2MOwner(SQLModel, table=True):
    __tablename__ = "cond_bad_m2m_owner"
    id: int | None = Field(default=None, primary_key=True)
    flag: str = Field(default="x")

    items: list["BadM2MItem"] = Relationship(
        link_model=BadM2MLink,
        sa_relationship_kwargs={
            "primaryjoin": lambda: and_(
                BadM2MOwner.id == BadM2MLink.__table__.c.owner_id,
                BadM2MOwner.flag == "keep",
            ),
            "viewonly": True,
        },
    )


class BadM2MItem(SQLModel, table=True):
    __tablename__ = "cond_bad_m2m_item"
    id: int | None = Field(default=None, primary_key=True)

    owners: list["BadM2MOwner"] = Relationship(
        back_populates="items", link_model=BadM2MLink
    )


class OddPairA(SQLModel, table=True):
    __tablename__ = "cond_odd_pair_a"
    id: int | None = Field(default=None, primary_key=True)
    other_id: int = Field(default=0)

    items: list["OddPairB"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": lambda: and_(
                OddPairA.id == OddPairB.a_id,
                OddPairB.ref_id == OddPairA.other_id,
            ),
            "foreign_keys": "[OddPairB.a_id]",
            "viewonly": True,
        },
    )


class OddPairB(SQLModel, table=True):
    __tablename__ = "cond_odd_pair_b"
    id: int | None = Field(default=None, primary_key=True)
    a_id: int = Field(foreign_key="cond_odd_pair_a.id")
    ref_id: int = Field(default=0)


class FuncUser(SQLModel, table=True):
    __tablename__ = "cond_func_user"
    id: int | None = Field(default=None, primary_key=True)

    items: list["FuncItem"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": lambda: and_(
                FuncUser.id == FuncItem.owner_id,
                func.length(FuncItem.body) > 3,
            ),
            "viewonly": True,
        },
    )


class FuncItem(SQLModel, table=True):
    __tablename__ = "cond_func_item"
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="cond_func_user.id")
    body: str = Field(default="")


# ── PR review 补充错误矩阵（构造期报错，不建表不进 fixture）──


class MixedLink(SQLModel, table=True):
    __tablename__ = "cond_mixed_link"
    owner_id: int = Field(foreign_key="cond_mixed_owner.id", primary_key=True)
    item_id: int = Field(foreign_key="cond_mixed_item.id", primary_key=True)
    status: str = Field(default="active")


class MixedOwner(SQLModel, table=True):
    __tablename__ = "cond_mixed_owner"
    id: int | None = Field(default=None, primary_key=True)

    items: list["MixedItem"] = Relationship(
        link_model=MixedLink,
        sa_relationship_kwargs={
            # 单一 or_ 同时引用 link 表列与 target 列 → 生成期 ValueError
            # （两步 M2M loader 无一条查询能承载，错挂一侧会笛卡尔积）
            "secondaryjoin": lambda: and_(
                MixedItem.id == MixedLink.__table__.c.item_id,
                or_(
                    MixedItem.status == "active",
                    MixedLink.__table__.c.status == "active",
                ),
            ),
            "viewonly": True,
        },
    )


class MixedItem(SQLModel, table=True):
    __tablename__ = "cond_mixed_item"
    id: int | None = Field(default=None, primary_key=True)
    status: str = Field(default="active")


class NeqUser(SQLModel, table=True):
    __tablename__ = "cond_neq_user"
    id: int | None = Field(default=None, primary_key=True)

    items: list["NeqItem"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[NeqItem.owner_id]",
            # FK 对上的 != 比较：签名撞 pair 不可静默当等值跳过 → 报错
            "primaryjoin": lambda: and_(
                NeqUser.id != NeqItem.owner_id, NeqItem.status == "keep"
            ),
            "viewonly": True,
        },
    )


class NeqItem(SQLModel, table=True):
    __tablename__ = "cond_neq_item"
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="cond_neq_user.id")
    status: str = Field(default="keep")


# ── PR review backref 豁免族（行为测试，需要建表）──


class BrfComment(SQLModel, table=True):
    __tablename__ = "cond_brf_comment"
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="cond_brf_user.id")
    status: str = Field(default="active")


class BrfUser(SQLModel, table=True):
    __tablename__ = "cond_brf_user"
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(default="")

    active_comments: list["BrfComment"] = Relationship(
        sa_relationship_kwargs={
            # backref 自动创建的反向关系会原样继承条件 primaryjoin；
            # 反向视角条件落在其 source 表 → 豁免提取（行为回到 master 的
            # 纯 FK 语义），不能在构造期崩
            "backref": "br_user_rel",
            "foreign_keys": "[BrfComment.owner_id]",
            "primaryjoin": lambda: and_(
                BrfUser.id == BrfComment.owner_id,
                BrfComment.status == "active",
            ),
            "order_by": "BrfComment.id",
            "viewonly": True,
        },
    )


# ──────────────────────────────────────────────────────────
# 测试基建（独立 engine，避免与 conftest 全局清场互相干扰）
# ──────────────────────────────────────────────────────────

_COND_ENTITIES = [
    CondUser, CondComment, CondProfile, CondArticle, CondReader, CondArticleReader,
]
_COND_TABLES = [e.__table__ for e in _COND_ENTITIES]

_cond_engine = None
_cond_session_factory = None


def _get_cond_engine():
    global _cond_engine
    if _cond_engine is None:
        _cond_engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False,
            poolclass=StaticPool,  # :memory: 单连接共享，跨 session 可见
        )
    return _cond_engine


def get_cond_session_factory():
    global _cond_session_factory
    if _cond_session_factory is None:
        _cond_session_factory = async_sessionmaker(
            _get_cond_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _cond_session_factory


@pytest_asyncio.fixture
async def cond_db():
    """Create cond_* tables + seed canonical data, drop afterwards.

    Canonical dataset (US1/US2/US3 assertions reference these):
      alice (enabled): c1 active/public/not-pinned, c2 deleted, c3 active+deleted_at set
      bob   (disabled): approver of c2
      article a1: linked to r1 (active link + active reader),
                  r2 (deleted reader), r3 (inactive link, active reader)
    """
    engine = _get_cond_engine()
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: SQLModel.metadata.create_all(
                sync_conn, tables=_COND_TABLES
            )
        )

    sf = get_cond_session_factory()
    async with sf() as session:
        alice = CondUser(name="alice", status="enabled")
        bob = CondUser(name="bob", status="disabled")
        session.add_all([alice, bob])
        await session.commit()

        c1 = CondComment(
            body="c1", status="active", pinned=False, owner_id=alice.id,
            approver_id=alice.id, visibility=CondVisibility.public,
        )
        c2 = CondComment(
            body="c2", status="deleted", pinned=False, owner_id=alice.id,
            approver_id=bob.id, visibility=CondVisibility.public,
        )
        c3 = CondComment(
            body="c3", status="active", pinned=True, owner_id=alice.id,
            # aware datetime：SQLModel 0.0.45 起 naive datetime 写库报错
            # （UTCDateTime breaking change），aware 在新旧版本都合法
            deleted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            visibility=CondVisibility.private,
        )
        session.add_all([c1, c2, c3])

        p_live = CondProfile(user_id=alice.id, archived=False)
        session.add(p_live)

        a1 = CondArticle(title="a1")
        r1 = CondReader(name="r1", status="active")
        r2 = CondReader(name="r2", status="deleted")
        r3 = CondReader(name="r3", status="active")
        session.add_all([a1, r1, r2, r3])
        await session.commit()

        session.add_all([
            CondArticleReader(article_id=a1.id, reader_id=r1.id, status="active"),
            CondArticleReader(article_id=a1.id, reader_id=r2.id, status="active"),
            CondArticleReader(article_id=a1.id, reader_id=r3.id, status="revoked"),
        ])
        await session.commit()

        alice_id = alice.id
        bob_id = bob.id
        c2_id = c2.id
        article_id = a1.id

    yield {"alice_id": alice_id, "bob_id": bob_id, "c2_id": c2_id, "article_id": article_id}

    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: SQLModel.metadata.drop_all(
                sync_conn, tables=_COND_TABLES
            )
        )


def build_cond_manager():
    """ErManager over the cond entity family (real registry path)."""
    from nexusx import ErManager

    return ErManager(session_factory=get_cond_session_factory(), entities=list(_COND_ENTITIES))


def _rel_of(entity: type, name: str):
    """Mapper relationship handle for extractor unit tests."""
    from sqlalchemy import inspect as sa_inspect

    return sa_inspect(entity).relationships[name]


# ──────────────────────────────────────────────────────────
# T003: 提取器单元测试（直接调用 _extract_extra_filters）
# ──────────────────────────────────────────────────────────


class TestExtractExtraFilters:
    def _extract(self, entity, name, **kw):
        from nexusx.loader.registry import _extract_extra_filters

        rel = _rel_of(entity, name)
        target = rel.mapper.class_
        return _extract_extra_filters(rel, entity, target, **kw)

    def test_pure_fk_returns_none(self):
        assert self._extract(CondComment, "owner") is None

    def test_unconditioned_o2m_returns_none(self):
        assert self._extract(CondUser, "comments") is None

    def test_eq_condition_single_extra(self):
        extras = self._extract(CondUser, "active_comments")
        assert extras is not None and len(extras) == 1
        compiled = str(extras[0].compile(compile_kwargs={"literal_binds": True}))
        assert "status" in compiled and "active" in compiled

    def test_is_null_condition(self):
        extras = self._extract(CondUser, "live_comments")
        assert len(extras) == 1
        assert "IS NULL" in str(extras[0].compile())

    def test_multiple_and_conditions_collected_separately(self):
        extras = self._extract(CondUser, "fresh_comments")
        assert len(extras) == 2  # 两条额外条件各自独立，不粘连

    def test_or_combination_kept_whole(self):
        """or_ 必须整体为单一条件——拆散即 AND 语义破坏（research D1）。"""
        extras = self._extract(CondUser, "notable_comments")
        assert len(extras) == 1
        compiled = str(extras[0].compile(compile_kwargs={"literal_binds": True}))
        assert " OR " in compiled  # 组合语义保留

    def test_enum_value_condition(self):
        extras = self._extract(CondUser, "public_comments")
        assert len(extras) == 1

    def test_m2o_condition(self):
        extras = self._extract(CondComment, "approver")
        assert len(extras) == 1

    def test_m2m_secondaryjoin_target_condition(self):
        extras = self._extract(CondArticle, "active_readers", use_secondaryjoin=True)
        assert len(extras) == 1

    def test_m2m_secondaryjoin_link_table_condition(self):
        extras = self._extract(CondArticle, "valid_readers", use_secondaryjoin=True)
        assert len(extras) == 1  # link 表列条件合法（clarify Q3-B）


# ──────────────────────────────────────────────────────────
# T005/T006: US1 一对多加载行为（ErManager 真实路径）
# 数据集（cond_db fixture）：alice 名下
#   c1: active / public / not pinned / deleted_at=None
#   c2: deleted / public / not pinned / deleted_at=None
#   c3: active / private / pinned / deleted_at=2026-01-01
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestOneToManyConditions:
    async def test_eq_condition_filters_soft_deleted(self, cond_db):
        mgr = build_cond_manager()
        rows = await _load(
            mgr._registry[CondUser]["active_comments"].loader, cond_db["alice_id"]
        )
        assert sorted(r.body for r in rows) == ["c1", "c3"]  # c2(deleted) 被滤

    async def test_unconditioned_relationship_unchanged(self, cond_db):
        """对照正交：无条件关系照常返回全部（FR-005）。"""
        mgr = build_cond_manager()
        rows = await _load(
            mgr._registry[CondUser]["comments"].loader, cond_db["alice_id"]
        )
        assert sorted(r.body for r in rows) == ["c1", "c2", "c3"]

    async def test_multiple_and_conditions_all_apply(self, cond_db):
        """多条件 AND 全生效：active 且未标记删除时间 → 仅 c1。"""
        mgr = build_cond_manager()
        rows = await _load(
            mgr._registry[CondUser]["fresh_comments"].loader, cond_db["alice_id"]
        )
        assert [r.body for r in rows] == ["c1"]

    async def test_filtered_empty_set_returns_empty_list(self, cond_db):
        """过滤后空集返回 []（非 None）——用一个无匹配的 key 驱动。"""
        mgr = build_cond_manager()
        rows = await _load(
            mgr._registry[CondUser]["active_comments"].loader, 99999
        )
        assert rows == []

    async def test_viewonly_irrelevant_to_read_path(self, cond_db):
        """active_comments 声明了 viewonly，与未声明的加载行为一致（FR-007）。"""
        mgr = build_cond_manager()
        info = mgr._registry[CondUser]["active_comments"]
        assert info.loader is not None
        rows = await _load(info.loader, cond_db["alice_id"])
        assert len(rows) == 2


@pytest.mark.asyncio
class TestConditionForms:
    async def test_is_null_form(self, cond_db):
        """时间戳软删除风格：deleted_at IS NULL → c1、c2（c3 有删除时间）。"""
        mgr = build_cond_manager()
        rows = await _load(
            mgr._registry[CondUser]["live_comments"].loader, cond_db["alice_id"]
        )
        assert sorted(r.body for r in rows) == ["c1", "c2"]

    async def test_enum_value_form(self, cond_db):
        """enum 值条件（lambda 声明）→ 仅 public 的 c1、c2。"""
        mgr = build_cond_manager()
        rows = await _load(
            mgr._registry[CondUser]["public_comments"].loader, cond_db["alice_id"]
        )
        assert sorted(r.body for r in rows) == ["c1", "c2"]

    async def test_or_combination_semantics(self, cond_db):
        """or_ 整体语义：status=='active' OR pinned → c1(active)、c3(active+pinned)；

        若被错误拆散为 AND，则只剩 c1（c2 既非 active 也未 pinned 排除不受影响，
        但 c3 会因 pinned=False 的 AND 分支被错误滤掉）——本用例守住 OR 不拆散。
        """
        mgr = build_cond_manager()
        rows = await _load(
            mgr._registry[CondUser]["notable_comments"].loader, cond_db["alice_id"]
        )
        assert sorted(r.body for r in rows) == ["c1", "c3"]


# ──────────────────────────────────────────────────────────
# T008: US2 标量方向（M2O 条件不满足 → None；O2M_SCALAR 同语义）
# c1.approver=alice(enabled)、c2.approver=bob(disabled)
# alice 名下 profile: archived=False（命中条件）
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestScalarConditions:
    async def test_m2o_condition_met_returns_target(self, cond_db):
        mgr = build_cond_manager()
        approver = await _load(
            mgr._registry[CondComment]["approver"].loader, cond_db["alice_id"]
        )
        assert approver is not None and approver.name == "alice"

    async def test_m2o_condition_unmet_returns_none(self, cond_db):
        """c2 的 approver 指向停用 bob → None（不抛错、不返回停用用户）。"""
        mgr = build_cond_manager()
        approver = await _load(
            mgr._registry[CondComment]["approver"].loader, cond_db["bob_id"]
        )
        assert approver is None

    async def test_m2o_unconditioned_owner_unaffected(self, cond_db):
        """同实体无条件 owner 照常（方向正交）：c2 的 owner 是 alice
        （owner loader 按 User.id 查、无条件——approver 的停用过滤不影响它，
        即使 alice 与 bob 都作为 key 批量查询）。"""
        mgr = build_cond_manager()
        owners = await mgr._registry[CondComment]["owner"].loader().load_many(
            [cond_db["alice_id"], cond_db["bob_id"]]
        )
        assert [o.name if o else None for o in owners] == ["alice", "bob"]

    async def test_o2m_scalar_condition(self, cond_db):
        """反向一对一（O2M_SCALAR）：条件命中（archived=False）返回 profile。

        （archived=True 命中 → None 的对照由条件语义保证：条件不满足即
        无行匹配，loader 返回 None——与 M2O 同一工厂路径。）
        """
        mgr = build_cond_manager()
        profile = await _load(
            mgr._registry[CondUser]["profile"].loader, cond_db["alice_id"]
        )
        assert profile is not None and profile.archived is False


# ──────────────────────────────────────────────────────────
# T011: US3 分页语义（过滤后口径：窗口/total_count/has_more 一致）
# active_comments 过滤后剩 c1、c3（按 id 排序）
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestPaginationSemantics:
    async def test_page_window_count_consistent(self, cond_db):
        mgr = build_cond_manager()
        pl = mgr._registry[CondUser]["active_comments"].page_loader
        pkg = await pl().load(
            PageLoadCommand(fk_value=cond_db["alice_id"], page_args=PageArgs(limit=1))
        )
        # 先过滤后分页：窗口=c1、total=2（非全量 3）、has_more=True
        assert [i.body for i in pkg.items] == ["c1"]
        assert pkg.pagination.total_count == 2
        assert pkg.pagination.has_more is True

    async def test_second_page(self, cond_db):
        mgr = build_cond_manager()
        pl = mgr._registry[CondUser]["active_comments"].page_loader
        pkg = await pl().load(
            PageLoadCommand(
                fk_value=cond_db["alice_id"],
                page_args=PageArgs(limit=1, offset=1),
            )
        )
        assert [i.body for i in pkg.items] == ["c3"]
        assert pkg.pagination.total_count == 2
        assert pkg.pagination.has_more is False

    async def test_offset_beyond_total_returns_empty_page_with_count(self, cond_db):
        """空页不丢 total_count（count fallback 生效）。"""
        mgr = build_cond_manager()
        pl = mgr._registry[CondUser]["active_comments"].page_loader
        pkg = await pl().load(
            PageLoadCommand(
                fk_value=cond_db["alice_id"],
                page_args=PageArgs(limit=1, offset=10),
            )
        )
        assert pkg.items == []
        assert pkg.pagination.total_count == 2

    async def test_fully_filtered_parent_keeps_zero_count(self, cond_db):
        """父实体过滤后空集：total=0 且键不丢（与不存在的父实体混合批量）。"""
        mgr = build_cond_manager()
        pl = mgr._registry[CondUser]["active_comments"].page_loader
        pkgs = await pl().load_many([
            PageLoadCommand(fk_value=99999, page_args=PageArgs(limit=1)),
            PageLoadCommand(fk_value=cond_db["alice_id"], page_args=PageArgs(limit=1)),
        ])
        assert pkgs[0].pagination.total_count == 0
        assert pkgs[1].pagination.total_count == 2


# ──────────────────────────────────────────────────────────
# T012: US3 M2M（目标列条件 / link 表列条件 / 对照 / 分页路径）
# a1 链接：r1(active 读者, active link)、r2(deleted 读者, active link)、
#          r3(active 读者, revoked link)
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestManyToManyConditions:
    async def test_m2m_target_side_condition(self, cond_db):
        """目标侧条件 Reader.status=='active' → r1、r3（r2 被滤）。"""
        mgr = build_cond_manager()
        readers = await _load(
            mgr._registry[CondArticle]["active_readers"].loader,
            cond_db["article_id"],
        )
        assert sorted(r.name for r in readers) == ["r1", "r3"]

    async def test_m2m_link_table_condition(self, cond_db):
        """link 表列条件（关联有效性）status=='active' → r1、r2（r3 关联失效）。"""
        mgr = build_cond_manager()
        readers = await _load(
            mgr._registry[CondArticle]["valid_readers"].loader,
            cond_db["article_id"],
        )
        assert sorted(r.name for r in readers) == ["r1", "r2"]

    async def test_m2m_unconditioned_control(self, cond_db):
        """对照无条件 M2M 照常返回全部三位读者。"""
        mgr = build_cond_manager()
        readers = await _load(
            mgr._registry[CondArticle]["readers"].loader, cond_db["article_id"]
        )
        assert sorted(r.name for r in readers) == ["r1", "r2", "r3"]

    async def test_m2m_primaryjoin_link_table_condition(self, cond_db):
        """primaryjoin 侧 link 表列条件（PR review 放开）：与 secondaryjoin
        侧声明等价 —— r1、r2（r3 关联失效），reader 自身 status 不参与。"""
        mgr = build_cond_manager()
        readers = await _load(
            mgr._registry[CondArticle]["declared_link_readers"].loader,
            cond_db["article_id"],
        )
        assert sorted(r.name for r in readers) == ["r1", "r2"]

    async def test_m2m_paginated_path_with_condition(self, cond_db):
        """分页 M2M 路径带条件：active_readers(过滤后 r1、r3) 分页口径一致。"""
        mgr = build_cond_manager()
        pl = mgr._registry[CondArticle]["active_readers"].page_loader
        assert pl is not None  # active_readers 声明了 order_by → page_loader 存在
        pkg = await pl().load(
            PageLoadCommand(
                fk_value=cond_db["article_id"], page_args=PageArgs(limit=1)
            )
        )
        assert [r.name for r in pkg.items] == ["r1"]
        assert pkg.pagination.total_count == 2  # 过滤后计数，非全量 3
        assert pkg.pagination.has_more is True


# ──────────────────────────────────────────────────────────
# PR review: backref 豁免 + 悬空 link 计数口径
# ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def brf_db():
    """Create brf_* tables + seed: u1 with one active + one deleted comment."""
    engine = _get_cond_engine()
    tables = [BrfUser.__table__, BrfComment.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=tables))

    sf = get_cond_session_factory()
    async with sf() as session:
        u1 = BrfUser(name="u1")
        session.add(u1)
        await session.commit()
        c_active = BrfComment(owner_id=u1.id, status="active")
        c_deleted = BrfComment(owner_id=u1.id, status="deleted")
        session.add_all([c_active, c_deleted])
        await session.commit()
        ids = (u1.id, c_active.id, c_deleted.id)

    yield {
        "user_id": ids[0], "active_id": ids[1], "deleted_id": ids[2]
    }

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: SQLModel.metadata.drop_all(c, tables=tables))


@pytest.mark.asyncio
class TestBackrefReverseRelationship:
    async def test_backref_reverse_exempts_extraction(self, brf_db, caplog):
        """backref 反向：构造期不崩（豁免提取）+ warning；正向条件照常生效；
        反向保持 master 纯 FK 语义（deleted 评论也解析出 owner）。"""
        import logging as _logging

        from nexusx import ErManager

        with caplog.at_level(_logging.WARNING, logger="nexusx.loader.registry"):
            mgr = ErManager(
                session_factory=get_cond_session_factory(),
                entities=[BrfUser, BrfComment],
            )
        assert any(
            "BrfComment.br_user_rel" in r.message and "backref" in r.message
            for r in caplog.records
        )

        # 正向：声明过条件 → 只剩 active（master 上没有条件机制，这是新能力）
        rows = await _load(
            mgr._registry[BrfUser]["active_comments"].loader, brf_db["user_id"]
        )
        assert [c.status for c in rows] == ["active"]

        # 反向：backref 自动创建、未写条件 → 纯 FK 解析（key=owner_id），
        # 行为同 master —— deleted 评论同样解析出 owner
        owner = await _load(
            mgr._registry[BrfComment]["br_user_rel"].loader, brf_db["user_id"]
        )
        assert owner is not None and owner.id == brf_db["user_id"]


@pytest.mark.asyncio
class TestDanglingLinkCountCaliber:
    """悬空 link 行（target 已物理删除，SQLite 不强制 FK）下的 count 口径。

    无条件关系的回退计数保持 master 口径（link 行计数、含悬空 —— FR-005
    存量零变化）；target 列条件关系的回退计数按门控 join target，与窗口
    口径一致（悬空排除）。窗口口径（join target）在两侧都不含悬空行。
    """

    async def _seed_dangling(self, article_id: int):
        sf = get_cond_session_factory()
        async with sf() as session:
            session.add(CondArticleReader(article_id=article_id, reader_id=999))
            await session.commit()

    async def test_unconditioned_fallback_keeps_master_caliber(self, cond_db):
        await self._seed_dangling(cond_db["article_id"])
        mgr = build_cond_manager()
        pl = mgr._registry[CondArticle]["readers"].page_loader
        assert pl is not None  # readers 声明了 order_by → page_loader 存在
        # 窗口内：join target → 悬空行不进窗口
        pkg = await pl().load(
            PageLoadCommand(
                fk_value=cond_db["article_id"], page_args=PageArgs(limit=5)
            )
        )
        assert pkg.pagination.total_count == 3
        # offset 超界 → 回退计数（无条件不 join）→ 含悬空的 link 行数（master 口径）
        pkg2 = await pl().load(
            PageLoadCommand(
                fk_value=cond_db["article_id"],
                page_args=PageArgs(offset=10, limit=5),
            )
        )
        assert pkg2.items == []
        assert pkg2.pagination.total_count == 4

    async def test_conditioned_fallback_joins_target_consistently(self, cond_db):
        await self._seed_dangling(cond_db["article_id"])
        mgr = build_cond_manager()
        pl = mgr._registry[CondArticle]["active_readers"].page_loader
        # 窗口内：target 列条件过滤后 r1、r3
        pkg = await pl().load(
            PageLoadCommand(
                fk_value=cond_db["article_id"], page_args=PageArgs(limit=5)
            )
        )
        assert pkg.pagination.total_count == 2
        # offset 超界 → 门控开启 join target：悬空排除，与窗口口径一致
        pkg2 = await pl().load(
            PageLoadCommand(
                fk_value=cond_db["article_id"],
                page_args=PageArgs(offset=10, limit=5),
            )
        )
        assert pkg2.items == []
        assert pkg2.pagination.total_count == 2


# ──────────────────────────────────────────────────────────
# T013: US4 非法声明诚实失败（ErManager 构造期 ValueError，信息可定位）
# ──────────────────────────────────────────────────────────


class TestIllegalDeclarations:
    def _build(self, entities):
        from nexusx import ErManager

        return ErManager(
            session_factory=get_cond_session_factory(), entities=entities
        )

    def test_o2m_condition_referencing_source_column(self):
        with pytest.raises(ValueError) as ei:
            self._build([BadSourceUser, BadSourceItem])
        msg = str(ei.value)
        assert "BadSourceUser.items" in msg
        assert "flag" in msg  # 被引用列可定位
        assert "target" in msg  # 支持范围说明

    def test_m2m_primaryjoin_side_condition_rejected(self):
        """M2M primaryjoin 侧条件引用 source 列 → 报错不静默（D4）。
        PR review 起 link/target 列条件在 primaryjoin 侧合法（按引用列路由），
        非法的只剩 source 列引用——本用例正是。"""
        with pytest.raises(ValueError) as ei:
            self._build([BadM2MOwner, BadM2MItem])
        msg = str(ei.value)
        assert "BadM2MOwner.items" in msg
        assert "primaryjoin" in msg

    def test_mixed_table_condition_rejected(self):
        """单一条件跨 target+link 两表（or_ 混合）→ 报错：两步 M2M loader
        无一条查询能承载，错挂一侧会笛卡尔积静默错数据（PR review repro：
        非分页返回多余行、分页正确，两 loader 结果分叉）。"""
        with pytest.raises(ValueError) as ei:
            self._build([MixedOwner, MixedItem, MixedLink])
        msg = str(ei.value)
        assert "MixedOwner.items" in msg
        assert "spans" in msg
        assert "separately" in msg

    def test_non_equality_fk_pair_rejected(self):
        """FK 对上的 != 比较 → 报错：loader 是等值 IN 查询，非等值声明若
        静默跳过即"声明不等于、返回恰好相反的集合"（PR review repro 实证）。"""
        with pytest.raises(ValueError) as ei:
            self._build([NeqUser, NeqItem])
        msg = str(ei.value)
        assert "NeqUser.items" in msg
        assert "Non-equality" in msg

    def test_non_fk_column_pair_rejected(self):
        """双列非 FK 比较：SQLAlchemy 将其推导为第二对 join pair，被既有的
        复合 FK 防御拦截（NotImplementedError）；提取器的 sig 不匹配防御
        （ValueError）覆盖其余非预期形态——两者都是启动期诚实失败。"""
        with pytest.raises((ValueError, NotImplementedError)) as ei:
            self._build([OddPairA, OddPairB])
        assert "OddPairA.items" in str(ei.value)

    def test_function_expression_rejected(self):
        with pytest.raises(ValueError) as ei:
            self._build([FuncUser, FuncItem])
        msg = str(ei.value)
        assert "FuncUser.items" in msg
        assert "function" in msg

    def test_legal_and_pure_fk_construct_fine(self):
        """对照：合法条件组与纯 FK 组正常构造（不因校验误伤）。"""
        mgr = self._build(list(_COND_ENTITIES))
        assert set(mgr._registry[CondUser]) >= {
            "comments", "active_comments", "profile",
        }


# ──────────────────────────────────────────────────────────
# T014: FR-008 schema 形态不变（条件是查询语义，不是 schema 语义）
# ──────────────────────────────────────────────────────────


class TestSchemaShapeUnchanged:
    def _sdl(self) -> str:
        from nexusx.sdl_generator import SDLGenerator

        g = SDLGenerator(
            list(_COND_ENTITIES), query_description=None, mutation_description=None
        )
        return g.generate(
            include_mutations=False, loader_registry=None, enable_pagination=False
        )

    def test_condition_field_types_match_unconditioned(self):
        sdl = self._sdl()
        # 带条件关系与无条件关系类型完全一致，无特殊标记
        assert "comments: [CondComment!]!" in sdl
        assert "active_comments: [CondComment!]!" in sdl
        assert "live_comments: [CondComment!]!" in sdl
        assert "profile: CondProfile" in sdl

    def test_condition_literals_do_not_leak_into_sdl(self):
        sdl = self._sdl()
        assert "'active'" not in sdl  # 条件值不进 schema
        assert "IS NULL" not in sdl.upper().replace(":", "")


# ──────────────────────────────────────────────────────────
# T015: FR-009 全路径冒烟（GraphQL 端到端嵌套查询走条件 loader）
# ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGraphQLEndToEnd:
    async def test_nested_field_query_applies_condition(self, cond_db):
        """GraphQL 嵌套查询端到端：active_comments 过滤、comments 对照。

        GraphQL 视图 → field tree → LoaderRegistry 是 entity GraphQL 路径；
        compose DTO 拼装与 MCP 经由同一 loader registry（全量回归覆盖其
        既有链路），联邦 wire 契约不经 primaryjoin（提取只发生在本地
        loader 生成期），故此处以 GraphQL 端到端作为全路径代表实证。
        """
        from nexusx import AutoQueryConfig, GraphQLHandler, add_standard_queries

        sf = get_cond_session_factory()
        cfg = AutoQueryConfig(default_limit=20)
        add_standard_queries([CondUser, CondComment], cfg, sf)  # 幂等（hasattr 守护）
        handler = GraphQLHandler(
            base=CondBase, session_factory=sf, auto_query_config=cfg
        )
        result = await handler.execute(
            "{ CondUser { by_id(id: %d) { name"
            " active_comments { body } comments { body } } } }"
            % cond_db["alice_id"]
        )
        assert not result.get("errors"), result
        node = result["data"]["CondUser"]["by_id"]
        assert node["name"] == "alice"
        assert sorted(c["body"] for c in node["active_comments"]) == ["c1", "c3"]
        assert sorted(c["body"] for c in node["comments"]) == ["c1", "c2", "c3"]


async def _load(loader_cls, key):
    """Instantiate a loader class once and load a single key."""
    return await loader_cls().load(key)
