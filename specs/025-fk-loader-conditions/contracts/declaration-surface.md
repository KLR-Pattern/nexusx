# Contract: 声明面（用户与 nexusx 的契约）

**日期**: 2026-09-30 | **特性**: 025 FK 关系条件过滤

本特性的对外契约是**声明面语法矩阵**与**错误契约**——nexusx 不新增任何自有 API，契约内容为"哪些 SQLAlchemy 原生声明会被识别、哪些会启动期拒绝"。

## 1. 支持的声明形式

### 一对多 / 多对一 / 反向一对一：primaryjoin

```python
class User(SQLModel, table=True):
    # 软删除过滤（状态列风格）
    active_comments: list["Comment"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "and_(User.id==Comment.owner_id, Comment.status=='active')",
            "viewonly": True,        # 可选：见 §3
            "order_by": "Comment.id",  # 可选：启用分页 loader（既有机制）
        },
    )
```

- 额外条件引用**目标实体**的列；可写多个（AND）；可用 `or_` / `not_` 组合（整体语义）；支持 `IS NULL`（`deleted_at==None`，时间戳软删除风格）。
- 多对一同构（如 `Comment.approver` 过滤停用用户；条件不满足 → 加载返回 `None`）。
- 多 FK 歧义时需按 SQLAlchemy 原生要求加 `foreign_keys`（非本特性新增要求）。

### 多对多：secondaryjoin（目标侧 + 关联表列）

```python
class Article(SQLModel, table=True):
    active_readers: list["Reader"] = Relationship(
        back_populates="articles",
        link_model=ArticleReader,          # 必须传 SQLModel link 类（§4 坑 1）
        sa_relationship_kwargs={
            "secondaryjoin": lambda: and_(
                Reader.id == ArticleReader.__table__.c.reader_id,
                Reader.status == "active",                     # 目标实体列
                ArticleReader.__table__.c.status == "active",  # 关联表列（关联有效性）
            ),
            "viewonly": True,
        },
    )
```

- secondaryjoin 引用 secondary 表列 / enum 值时**必须用 lambda**（字符串形式的求值命名空间只有实体类，见 §4 坑 3）。

## 2. 错误契约（启动期，ErManager 构造时）

| 声明形态 | 行为 |
|----------|------|
| 条件引用源实体（或合法集合外任何表）的列 | `ValueError`，信息含 `实体.关系`、被引用列、支持范围说明 |
| M2M 的 primaryjoin 侧带额外条件 | 同上（loader 查询不读源侧，物理不可执行） |
| FK 等值对之外的双列比较 | 同上 |
| 函数表达式 / 子查询参与条件 | 同上 |
| 无额外条件的纯 FK 关系 | 正常（存量行为零变化） |

错误风格与 ErManager 既有生成期校验一致（如 `__pagination_orders__` fail-fast）。

## 3. 语义契约

- **一处声明，全部消费路径生效**：entity GraphQL 嵌套、compose DTO 拼装、MCP、联邦 member 侧内嵌套（共享 loader 底座）；联邦 wire 契约不变。
- **分页口径**：窗口 / `total_count` / `has_more` 全部按过滤后集合（`total_count` ≠ 全量数）。
- **正交性**：条件属于关系不属于实体对——同对实体可并存多个条件各异的（或无条件的）关系，互不影响。
- **schema 形态不变**：SDL / introspection / ER 图不因条件变化。
- **viewonly 可选**：不要求（读路径行为无差异）；建议声明以表达写入侧语义（SQLAlchemy 惯例）。
- **M2O 条件不满足 → `None`；O2M 过滤后空集 → `[]`**。

## 4. 声明面已知坑（SQLAlchemy/SQLModel 原生约束，非 nexusx 行为）

1. `link_model` 必须传 SQLModel link **类**；传原生 `Table` 对象会在类构造时抛 `TypeError`。
2. 注解写 `Optional["X"]`；`"X | None"` 字符串注解 + `sa_relationship_kwargs` 组合解析失败。
3. primaryjoin/secondaryjoin **字符串形式**的求值环境只有实体类注册表：enum 类、Table 对象不可见 → 这些场景用 lambda 形式。
4. 类名含下划线在字符串声明解析时可能被 registry 分词拆散 → 同样以 lambda 规避。

## 5. 兼容性承诺

- 未声明额外条件的存量关系：加载结果、查询形态、错误行为**零变化**（FR-005）。
- 不新增公共 API、不改动既有 `__relationships__` 手写 loader 机制（并存，手写优先级照旧）。
- 发布为 minor 版本。
