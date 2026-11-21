# Quickstart: 025 FK 关系条件过滤

**日期**: 2026-09-30 | **前提**: 已安装含本特性的 nexusx（≥ 发布版本）

## 验证目标

证明端到端生效：在 relationship 上声明原生 join 额外条件后，**不写任何加载代码**，关联加载（含分页计数）自动过滤。

## 场景 1：一对多软删除过滤（核心场景）

```python
import asyncio

from sqlmodel import Field, Relationship, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


class User(SQLModel, table=True):
    __tablename__ = "qs_user"
    id: int | None = Field(default=None, primary_key=True)
    name: str

    comments: list["Comment"] = Relationship(
        back_populates="owner",
        sa_relationship_kwargs={"foreign_keys": "[Comment.owner_id]"},
    )
    active_comments: list["Comment"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[Comment.owner_id]",
            "primaryjoin": "and_(User.id==Comment.owner_id, Comment.status=='active')",
            "viewonly": True,
            "order_by": "Comment.id",
        },
    )


class Comment(SQLModel, table=True):
    __tablename__ = "qs_comment"
    id: int | None = Field(default=None, primary_key=True)
    body: str
    status: str = Field(default="active")
    owner_id: int = Field(foreign_key="qs_user.id")
    owner: User | None = Relationship(
        back_populates="comments",
        sa_relationship_kwargs={"foreign_keys": "Comment.owner_id"},
    )
```

建库造数（alice 名下 2 条 active + 1 条 deleted）后：

```python
from nexusx import ErManager
from nexusx.loader.pagination import PageArgs, PageLoadCommand

sf = async_sessionmaker(create_async_engine("sqlite+aiosqlite:///qs.db"),
                        class_=AsyncSession, expire_on_commit=False)
mgr = ErManager(session_factory=sf, entities=[User, Comment])

async def demo(alice_id: int):
    rows = await mgr._registry[User]["active_comments"].loader().load(alice_id)
    assert sorted(r.body for r in rows) == ["c1", "c3"]        # deleted 被滤

    all_rows = await mgr._registry[User]["comments"].loader().load(alice_id)
    assert len(all_rows) == 3                                   # 对照关系不受影响

    pkg = await mgr._registry[User]["active_comments"].page_loader().load(
        PageLoadCommand(fk_value=alice_id, page_args=PageArgs(limit=1))
    )
    assert [i.body for i in pkg.items] == ["c1"]
    assert pkg.pagination.total_count == 2                      # 过滤后口径
    assert pkg.pagination.has_more is True

asyncio.run(demo(alice_id))
```

**预期**：三个断言全部通过——软删除零泄漏、无条件关系零变化、分页三要素按过滤后集合。

## 场景 2：多对一条件过滤（目标不可见 → None）

`Comment.approver` 声明 `"primaryjoin": "and_(Comment.approver_id==User.id, User.status=='enabled')"` 后，加载指向停用用户的 approver 得到 `None`（不抛错）。

## 场景 3：多对多目标侧 + 关联表条件

`secondaryjoin` 用 lambda 声明（含 `Reader.status == "active"` 与 link 表列条件，见 [contracts/declaration-surface.md](./contracts/declaration-surface.md) §1），加载只返回满足双重条件的读者。

## 场景 4：非法声明诚实失败

条件引用源实体列（如一对多关系里写 `User.flag=='keep'`）：

```python
try:
    ErManager(session_factory=sf, entities=[BadUser, BadItem])
    raise AssertionError("未报错")
except ValueError as e:
    assert "BadUser.items" in str(e)      # 错误可定位到关系
```

## GraphQL 端到端（可选）

对场景 1 的 schema 查询嵌套字段：

```graphql
query { users { name activeComments { body } comments { body } } }
```

**预期**：`activeComments` 只含 active、`comments` 含全部；SDL 形态与无条件时一致（不因条件出现新字段/参数）。

## 已知坑速查

lambda 声明场景（enum 值 / secondaryjoin 引用 link 表列）、`Optional["X"]` 注解形式、`link_model` 传 SQLModel 类——详见 [contracts/declaration-surface.md](./contracts/declaration-surface.md) §4。
