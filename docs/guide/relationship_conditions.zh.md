# 关系条件过滤

FK 自动生成的关联加载默认返回全部匹配行。软删除、归档、状态过滤这类"逻辑上只该看到一部分"的关系，用 SQLAlchemy 原生的 join 条件声明（`primaryjoin` / `secondaryjoin`）即可——nexusx 会识别声明中的额外条件并自动应用到该关系的全部加载路径（GraphQL 嵌套字段、compose DTO 拼装、MCP、联邦 member 侧），无需写任何加载代码，也不引入任何 nexusx 自有参数。

## 一对多 / 多对一：primaryjoin

```python
from typing import Optional
from sqlmodel import Field, Relationship, SQLModel

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str

    comments: list["Comment"] = Relationship(
        back_populates="owner",
        sa_relationship_kwargs={"foreign_keys": "[Comment.owner_id]"},
    )
    # 软删除过滤：只看未删除的评论
    active_comments: list["Comment"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[Comment.owner_id]",
            "primaryjoin": "and_(User.id==Comment.owner_id, Comment.status=='active')",
            "viewonly": True,        # 可选，见下文
            "order_by": "Comment.id",
        },
    )
```

这与手写 join 查询时的 `and_(FK 相等, 额外条件)` 完全同构。条件之间彼此独立：`comments` 照常返回全部行，`active_comments` 只返回满足条件的行。

多对一同构。条件不满足时返回 `None`（例如下面的 `approver` 指向停用用户）：

```python
class Comment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id")
    approver_id: Optional[int] = Field(default=None, foreign_key="user.id")

    owner: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "Comment.owner_id"}
    )
    approver: Optional["User"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "and_(Comment.approver_id==User.id, User.status=='enabled')",
            "foreign_keys": "Comment.approver_id",
        },
    )
```

## 支持的条件形态

| 形态 | 示例 |
|------|------|
| 列 = 常量（eq / ne / in 等） | `Comment.status == 'active'` |
| 空值判断（时间戳软删除风格） | `Comment.deleted_at == None`（生成 `IS NULL`） |
| 多条件 AND | 各条件独立声明，全部生效 |
| `or_` / `not_` 组合 | 整体生效，OR 不会被拆散改写 |
| 枚举值 | `Comment.visibility == Visibility.public`（需 lambda 声明，见下文坑清单） |

## 多对多：secondaryjoin

条件作用于**目标侧**（目标实体列）或**关联表自身列**（"这条关联记录本身有效"）：

```python
class ArticleReader(SQLModel, table=True):
    """link 表（link_model 必须传 SQLModel 类）。"""
    article_id: int = Field(foreign_key="article.id", primary_key=True)
    reader_id: int = Field(foreign_key="reader.id", primary_key=True)
    status: str = Field(default="active")

class Article(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    active_readers: list["Reader"] = Relationship(
        link_model=ArticleReader,
        sa_relationship_kwargs={
            "secondaryjoin": lambda: and_(
                Reader.id == ArticleReader.__table__.c.reader_id,
                Reader.status == "active",                      # 目标实体列
                ArticleReader.__table__.c.status == "active",   # 关联表列（关联有效性）
            ),
            "viewonly": True,
        },
    )
```

## 分页语义

声明了 `order_by` 的关系启用关联分页时，窗口、`total_count`、`has_more` 全部按**过滤后**的集合计算——`total_count` 是过滤后的数量，不是全量数。这对翻页器/进度条类界面是直接可用的口径。

## viewonly 是可选的

SQLAlchemy 允许带额外条件的 relationship 不声明 `viewonly`（2.0 起无警告），也允许与 `back_populates` 双向共存。nexusx 只走读路径，`viewonly` 声明与否对加载行为零差异——建议声明它来表达"此关系只读"的写入侧语义，但这是 SQLAlchemy 惯例而非 nexusx 要求。

## 不支持的形态（启动期报错）

以下声明会在 `ErManager` 构造时（应用启动）抛出 `ValueError`，信息含实体名、关系名与被引用列——不会静默忽略条件，也不会留到运行期才在具体查询上报错：

- 条件引用**目标实体（及关联表）之外**的列——例如一对多关系里引用了父实体的列。加载查询只读取目标侧数据，这类条件物理上不可执行。
- 多对多在 `primaryjoin` 侧（源↔关联表）声明额外条件——同样引用源实体列，不可执行；请把条件写到 `secondaryjoin`。
- FK 等值对之外的**双列比较**。
- 条件中包含函数表达式或子查询。

## 已知坑（SQLAlchemy / SQLModel 原生约束）

1. `link_model` 必须传 SQLModel link **类**；传原生 `Table` 对象会在类构造时报错。
2. 关系字段的注解写 `Optional["User"]`；`"User | None"` 字符串注解与 `sa_relationship_kwargs` 组合无法解析。
3. `primaryjoin` / `secondaryjoin` **字符串形式**的求值环境只有实体类名：枚举类、`Table` 对象不可见——这些场景改用 **lambda** 形式声明（见上文多对多示例）。
4. 同一张表存在多个指向同一目标的外键时，需按 SQLAlchemy 原生要求声明 `foreign_keys`。

## 与 GraphQL schema 的关系

条件是查询语义，不是 schema 语义：SDL、introspection 的形态不因条件变化（字段类型照常渲染），过滤后的空结果照常返回。联邦场景下条件在 member 侧加载时生效，对外 wire 契约不变。
