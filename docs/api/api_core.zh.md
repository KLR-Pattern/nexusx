# Core API 参考

ErManager、Resolver、DefineSubset、Loader 的完整 API 参考。

## ErManager

使用 `ErManager` 管理实体关系——发现实体、注册关系、创建 Resolver。

```python
from nexusx import ErManager

er = ErManager(
    base=SQLModel,                    # SQLModel 基类（与 entities 互斥）
    entities=None,                    # 显式实体列表（与 base 互斥）
    session_factory=async_session,    # 异步 session 工厂
)
```

!!! warning
    `base` 和 `entities` 互斥，不能同时传递这两个参数。

### 方法

| 方法 | 说明 |
|------|------|
| `create_resolver()` | 返回绑定了实体图的 Resolver 类 |
| `get_diagram()` | 返回 ErDiagram 实例 |
| `add_virtual_entities(entities)` | 将普通 BaseModel 子类注册为虚拟实体（见下文） |

### add_virtual_entities

将普通 `pydantic.BaseModel` 子类注册为**虚拟实体**——非 SQLModel 根，可与 SQLModel 实体一起参与解析、自定义关系和 ER 可视化。典型场景：从 OIDC claims 组装的 `CurrentUser`、聚合多服务的页面 wrapper、第三方 SDK DTO。

```python
from pydantic import BaseModel
from nexusx import ErManager, Relationship

class CurrentUserRoot(BaseModel):
    oid: str
    name: str
    agents: list[AgentDTO] = []

    __relationships__ = [
        Relationship(fk="oid", target=list[AgentDTO],
                     name="agents", loader=load_agents_by_oid),
    ]

er = ErManager(entities=[Agent], session_factory=async_session)
er.add_virtual_entities([CurrentUserRoot])          # ← 必须在 create_resolver() 之前
Resolver = er.create_resolver()
```

必须在第一次 `create_resolver()` **之前**调用——之后注册表会冻结。

| 输入 | 结果 |
|------|------|
| `[A, B]`（普通 BaseModel，未注册过） | 两者都注册 |
| `[]`（空列表） | 无操作 |
| `[42]` 或 `[int]`（非类） | `TypeError` |
| `[SomeRandomClass]`（不是 BaseModel） | `TypeError` |
| `[User]`（其中 `User(SQLModel, table=True)`） | `TypeError`——SQLModel 必须通过 `__init__` 的 `entities=` / `base=` 传入 |
| `[A, A]`（同次或跨次重复） | `ValueError` |
| 在 `create_resolver()` 之后调用 | `RuntimeError`（"registry is frozen"） |

使用模式、ER 可视化规则、以及从 `_subset_registry` hack 的迁移，详见 [虚拟实体指南](../guide/virtual_entities.zh.md)。

## Resolver

`Resolver` 由 `ErManager.create_resolver()` 返回。使用它来解析 DTO 树。

```python
Resolver = er.create_resolver()

result = await Resolver().resolve(dtos)
```

### Resolver 构造器参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `context` | `dict` | 全局上下文，可通过 `ancestor_context` 访问 |
| `loader_params` | `dict` | DataLoader 额外参数 |
| `debug` | `bool` | 启用调试日志 |

### Resolver.resolve

```python
result = await Resolver().resolve(dtos)
```

参数 `dtos` 可以是单个 DTO 实例或 DTO 列表。返回解析后的同一对象（就地修改）。

### 执行顺序

1. 执行所有 `resolve_*` 方法（加载关系数据）
2. 遍历已有的对象字段
3. 执行所有 `post_*` 方法（计算派生字段）
4. 收集 SendTo 值到祖先的 Collector

## DefineSubset

使用 `DefineSubset` 作为 DTO 基类——从 SQLModel 实体生成 Pydantic 模型。

```python
from nexusx import DefineSubset

class UserDTO(DefineSubset):
    __subset__ = (User, ("id", "name"))
```

!!! tip
    将 `DefineSubset` 理解为"从实体中选取字段的声明"——你告诉框架需要哪些字段，框架负责生成对应的 Pydantic 模型。

### __subset__ 语法

接受元组 `(Entity, ('field1', 'field2'))` 或 `SubsetConfig` 对象。

### 规则

- FK 字段自动从序列化输出隐藏（`exclude=True`），但内部仍可用
- 关系字段声明在类体中（非 `__subset__`），类型必须是 DTO 类型

!!! warning
    禁止直接使用 SQLModel 实体作为字段类型。例如 `author: User | None` 会导致 TypeError。必须使用 DTO 类型：`author: UserDTO | None`。

!!! tip
    `__subset__` 的源可以是任意 `BaseModel` 子类，不只是 `SQLModel`。这让你可以直接对外部 schema（OAuth claims、第三方 SDK 类）做子集化，背后不需要 ORM 表。源是普通 BaseModel 时不会触发 `_orm_to_dto` 转换——用户直接构造 DTO 实例。详见 [虚拟实体指南](../guide/virtual_entities.zh.md)。

## SubsetConfig

使用 `SubsetConfig` 进行声明式 DTO 配置（`__subset__` 的替代形式）：

```python
from nexusx import SubsetConfig

class UserDTO(DefineSubset):
    __subset__ = SubsetConfig(entity=User, fields=("id", "name"))
```

## Loader

在 `resolve_*` 方法中使用 `Loader` 声明 DataLoader 依赖。

```python
from nexusx import Loader

# DataLoader 类
def resolve_tags(self, loader=Loader(TagLoader)):
    return loader.load(self.id)

# 异步批量函数
async def load_users(user_ids):
    ...
def resolve_owner(self, loader=Loader(load_users)):
    return loader.load(self.owner_id)
```

!!! warning
    Loader 依赖名必须匹配关系名。例如 `Loader('author')` 要求 ErManager 中有名为 `author` 的关系。

## build_dto_select

使用 `build_dto_select` 构建从 SQL 数据库查询 DTO 所需字段的 SELECT 语句：

```python
from nexusx import build_dto_select

stmt = build_dto_select(SprintSummary)
stmt = build_dto_select(SprintSummary, where=Sprint.id == sprint_id)
```

> **注意：** 当 ORM 关系使用 `lazy="noload"` 时（ErManager + Resolver 的推荐模式），此函数的收益有限，因为裁剪仅限于标量列。可以用 `select(Entity)` + `DTO.model_validate(entity)` 实现相同效果。仅在 DTO 从宽表中选取少量标量列时，列裁剪才有实际价值。
