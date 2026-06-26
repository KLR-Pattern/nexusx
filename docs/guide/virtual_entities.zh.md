# 虚拟实体（非 SQLModel 根）

绝大多数 NexusX 响应根都映射到一张数据库表——一个 SQLModel 实体，比如 `User` 或 `Order`。但有些根是从请求上下文、第三方 SDK 或外部服务组装出来的，背后没有表：

- **`CurrentUser`**——由 OIDC / JWT claims 组装
- **页面级 wrapper**——聚合多个服务的数据
- **第三方 SDK 类**（Stripe customer、OAuth profile），你并不拥有它
- **跨服务 DTO**——通过 HTTP 调用而非 DB 查询填充

对这类场景，NexusX 允许声明 **虚拟实体**：一个普通 `pydantic.BaseModel`，通过 `ErManager.add_virtual_entities()` 注册。注册后，该类可以参与解析、自定义关系、跨层数据流（ExposeAs / SendTo / Collector）以及 ER / Voyager 可视化——**不需要**继承 SQLModel、不需要 `__table__`、不涉及任何持久化。

## 何时使用虚拟实体

| 场景 | 用虚拟实体吗？ |
|------|----------------|
| 根本身就是 schema（如 `CurrentUser`） | **是——只用 `add_virtual_entities()`** |
| DTO 是某个外部 BaseModel schema 的 *子集*（如第三方 SDK 类） | **是——只用 BaseModel 作为 `DefineSubset.__subset__` 源** |
| 两者都是——根既是外部 schema 的子集 *又*有自己的关系 | **两个 API 一起用** |
| 根映射到一张 SQLModel 表 | **否——继续走 SQLModel 路径** |

两个 API（`add_virtual_entities()` 和 BaseModel 作为 DefineSubset 源）相互正交，按需选择。

## API：`ErManager.add_virtual_entities()`

```python
from pydantic import BaseModel
from nexusx import ErManager, Relationship, DefineSubset

class Agent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_oid: str
    name: str

class AgentDTO(DefineSubset):
    __subset__ = (Agent, ("id", "owner_oid", "name"))

async def load_agents_by_oid(keys: list[str]) -> list[list[AgentDTO]]:
    # 批量 loader——可以从 DB、缓存、外部 API 任意来源拉取
    ...

class CurrentUserRoot(BaseModel):
    oid: str
    name: str
    agents: list[AgentDTO] = []

    __relationships__ = [
        Relationship(
            fk="oid",
            target=list[AgentDTO],
            name="agents",
            loader=load_agents_by_oid,
        ),
    ]

# 装配
er = ErManager(entities=[Agent], session_factory=async_session)
er.add_virtual_entities([CurrentUserRoot])      # ← 注册虚拟根
resolver = er.create_resolver()

# 像普通根一样解析——行为与 SQLModel 根完全一致
root = CurrentUserRoot(oid="user-1", name="Alice")
result = await resolver.resolve(root)
assert {a.name for a in result.agents} == {"A1", "A2"}
```

### 方法契约

```python
er.add_virtual_entities(entities: list[type[BaseModel]]) -> None
```

必须在第一次 `er.create_resolver()` **之前**调用——之后注册表会被冻结。校验规则：

| 场景 | 结果 |
|------|------|
| `[A, B]`，A、B 是普通 BaseModel 且未注册过 | 两者都注册成功 |
| `[]`（空列表） | 空操作 |
| `[42]` 或 `[int]`（非类） | `TypeError("add_virtual_entities entries must be classes; ...")` |
| `[SomeRandomClass]`（不是 BaseModel） | `TypeError(f"{name} must be a subclass of pydantic.BaseModel")` |
| `[User]`，其中 `User(SQLModel, table=True)` | `TypeError(f"{name} is a SQLModel subclass; ...")`——SQLModel 应通过 `__init__` 的 `entities=` / `base=` 传入 |
| `[A, A]`（同次调用重复）或先 `[A]` 再 `[A]` | `ValueError(f"{name} is already registered")` |
| 在 `create_resolver()` 之后调用 | `RuntimeError("ErManager registry is frozen after first create_resolver() ...")` |

### 免费获得的能力

注册后，虚拟实体拥有 SQLModel 根的全部能力：

- **`Resolver().resolve(root)`**——完整树遍历，自动加载 `__relationships__`
- **`resolve_*` / `post_*` 方法**——包含 `post_default_handler` 终结器
- **ExposeAs / SendTo / Collector**——跨层数据流可以跨越 SQLModel / BaseModel 边界
- **自定义关系**——通过 `__relationships__` 声明，语法与 SQLModel 一致
- **ER 图 / Voyager 可视化**——实体作为 *虚拟节点* 出现，与表后端实体视觉区分（黄色填充、`«virtual»` 构造型、独立 `cluster_virtual` 簇）

### 你不会得到的

- **没有 `__table__`，没有 SQLAlchemy mapper**——该类 *不是* SQLModel 子类，会被需要 `__table__` 的原生 SQLAlchemy 查询构造器拒绝。这是有意设计；数据拉取请用 `resolve_*` 方法。
- **没有自动发现**——在调用 `er.add_virtual_entities([CurrentUserRoot])` *之前* 直接把 `CurrentUserRoot` 实例传给 `Resolver().resolve(...)` 会得到清晰错误，指向注册 API，而不是默默无效。
- **没有持久化**——虚拟实体是响应组装原语，没有 DB session，没有事务。

## API：BaseModel 作为 `DefineSubset.__subset__` 源

如果你的 DTO 是某个外部 BaseModel schema 的 *子集*（而不是它自己的 schema），使用拓宽后的 `DefineSubset` 源。SQLModel 不再必需：

```python
from oauth_sdk import OAuthClaims   # 第三方 BaseModel，有 28 个字段

class AuthSummaryDTO(DefineSubset):
    __subset__ = (OAuthClaims, ("sub", "email", "name"))
    # AuthSummaryDTO 只有 OAuthClaims 28 个字段中的 3 个

# 直接从 kwargs 构造——不需要 ORM 行
dto = AuthSummaryDTO(sub="user-1", email="a@x.com", name="Alice")
```

如果 BaseModel 源 *也* 有 `__relationships__`，且你希望自动加载能命中它们，再额外用 `add_virtual_entities()` 注册一次：

```python
class CurrentUser(BaseModel):
    oid: str
    name: str
    tenant_id: str       # 加上你 auth context 里的另外 20 个字段

    __relationships__ = [
        Relationship(fk="oid", target=list[AgentDTO], name="agents", loader=load_agents_by_oid),
    ]

class CurrentUserDTO(DefineSubset):
    __subset__ = (CurrentUser, ("oid", "name"))   # CurrentUser schema 的子集
    agents: list[AgentDTO] = []                    # 通过源的关系自动加载

er = ErManager(entities=[Agent], session_factory=async_session)
er.add_virtual_entities([CurrentUser])             # ← 让自动加载能找到源
resolver = er.create_resolver()

dto = CurrentUserDTO(oid="user-1", name="Alice")
result = await resolver.resolve(dto)
assert {a.name for a in result.agents} == {"A1", "A2"}
```

如果不对源调用 `add_virtual_entities()`，schema 子集化仍然有效（DTO 的 `__subset_fields__` 会被填充），但自动加载 *不会* 触发——源在注册表里不可见。

## 迁移：替换 `_subset_registry` hack

在这个特性之前，项目通过直接改 NexusX 内部状态来绕过限制：

```python
# ❌ 旧 hack——脆弱、未文档化、版本升级容易崩
from nexusx.subset import _subset_registry
_subset_registry[CurrentUserRootDTO] = CurrentUserRoot
```

用官方 API 替换。正确姿势取决于 hack 在做什么：

### 情况 A——把 BaseModel 注册为"虚拟源"，以获得自动加载 / ER 可见性

```python
# ✅ 官方：add_virtual_entities + DefineSubset 拓宽
class CurrentUserRootDTO(DefineSubset):
    __subset__ = (CurrentUserRoot, ("oid", "name"))
    # ... resolve_*、post_*、源或 DTO 上的 __relationships__ ...

er = ErManager(entities=[...], session_factory=async_session)
er.add_virtual_entities([CurrentUserRoot])
```

### 情况 B——根本身就是 schema（不需要子集化）

```python
# ✅ 官方：普通 BaseModel + add_virtual_entities
class CurrentUserRoot(BaseModel):
    oid: str
    name: str
    __relationships__ = [...]

er = ErManager(entities=[...], session_factory=async_session)
er.add_virtual_entities([CurrentUserRoot])
```

迁移是 **机械的**（可搜索替换）：

1. 找到每一行 `_subset_registry[X] = Y`。
2. 如果 `Y` 有 `__relationships__`，或你希望它在 ER 图中可见：在 `ErManager(...)` 之后加 `er.add_virtual_entities([Y])`。
3. 如果 `X` 是 `Y` schema 的子集：声明 `class X(DefineSubset): __subset__ = (Y, ("field", "names"))`。
4. 如果 `X` *就是* `Y`（根是它自己的 schema）：把 `X` 改成普通 `BaseModel`，然后 `er.add_virtual_entities([X])`。
5. 删除 `_subset_registry` 改动。

不需要重写 DTO 层级。`ErManager.__init__` 签名不变。

## ER / Voyager 可视化

混合 SQLModel 实体与虚拟实体的项目可以无异常地生成 ER 图，虚拟实体视觉上与真实表后端实体区分：

| 方面 | SQLModel 实体 | 虚拟实体 |
|------|---------------|----------|
| 头部填充 | 主题主色（青绿） | 浅黄（`#FFF9C4`） |
| 标签 | `{ClassName}` | `«virtual»\n{ClassName}` |
| 簇 | 按模块路径分组 | `cluster_virtual`（虚线边框） |
| 边 | 正常绘制 | 正常绘制（无特殊处理） |

```python
from nexusx import ErDiagram
from nexusx.voyager.er_diagram_dot import ErDiagramDotBuilder

er = ErManager(entities=[Agent], session_factory=async_session)
er.add_virtual_entities([CurrentUserRoot])

# 数据 API——查看实体与关系
diagram = ErDiagram.from_er_manager(er)
for e in diagram.entities:
    print(f"{e.name} (virtual={e.is_virtual}): {[r.name for r in e.relationships]}")

# DOT 渲染——输出 Voyager 兼容的 graphviz
builder = ErDiagramDotBuilder(er)
builder.analysis()
print(builder.render_dot())
```

## 约束

- **`ErManager.__init__` 至少需要一个 SQLModel 实体**（通过 `base=` 或 `entities=`）。零 SQLModel 的项目不在范围内——也没有 loader 值得管理。
- **`add_virtual_entities()` 必须在第一次 `create_resolver()` 之前调用**。之后注册表冻结；ErManager 按设计是一次性的（实体注册只在启动时发生一次）。
- **虚拟根上的自定义关系必须显式声明**，通过 `__relationships__`。AutoLoad 的"字段名匹配 ORM 关系名"隐式路径仍要求真实 SQLModel 源——虚拟根没有 ORM 元数据可读。
