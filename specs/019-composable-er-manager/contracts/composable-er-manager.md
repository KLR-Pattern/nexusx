# Contract: 可组合 ErManager（ComposedErManager）public API

> Phase 1 产出。定义本特性对外暴露的 public API 契约 + Public API 兼容性承诺。nexusx 是已发布库（5.3.0），契约以「不 breaking」为硬约束。

## 1. 新增 public API（阶段 1，纯 additive）

### `ComposedErManager`

```python
from nexusx import ComposedErManager          # 顶层导出
from nexusx.loader import ComposedErManager   # 包内导出

ComposedErManager(
    members: list[ErManager],
    *,
    cross_relationships: list[Relationship] | None = None,
    service_name: str | None = None,
)
```

**契约**：
- `members`：各自自洽的子 `ErManager`（单 engine）。不可空、构造后不可变（FR-016）。
- `cross_relationships`：跨 engine 边界关系（`Relationship`，loader 用户闭包）。组合体持有为叠加层（DD-02）。
- `service_name`：组合体作为 federation member 被消费时的统一 service 名（可选，独立使用时不需）。
- **满足 `LoaderRegistry` Protocol**，可作 `Resolver(loader_registry=...)`、`ErDiagram.from_er_manager(...)`、`GraphQLHandler(er_manager=...)`（阶段 2）的输入。

**抛错**（fail-fast，构造期）：
- 实体 `full_class_name` 冲突 → `ValueError`
- 跨边界关系 source/target 不在任一 member → `ValueError`
- `members` 为空 → `ValueError`

### `LoaderRegistry` Protocol

```python
from nexusx.loader import LoaderRegistry   # 导出（runtime_checkable Protocol）
```

Resolver / ER 图 对 registry 的查询接口契约。`ErManager` 天然满足。详见 [data-model.md §1](../data-model.md)。

### 跨边界 `Relationship` 用法（复用，0 新 API）

```python
from nexusx import Relationship

async def orders_by_user_id(user_ids: list[int]) -> list[list[Order]]:
    async with shop_session() as s:           # 用户闭包，用目标 engine 的 session
        ...
    return [...]

composed = ComposedErManager(
    members=[blog_er, shop_er],
    cross_relationships=[
        Relationship(fk="id", target=list[Order], name="orders", loader=orders_by_user_id),
    ],
)
```

## 2. 总代理 Resolver 契约

```python
Resolver = composed.create_resolver()        # 返回一个 Resolver 子类
resolver = Resolver(context={...})           # 每请求一个实例
await resolver.resolve([user_dto, ...])      # 一次调用，跨 engine + 跨 service 透明
```

**契约**：
- `create_resolver()` 产出的 Resolver，`loader_registry` = 组合体本身。
- resolve 跨 engine 实体树时，关系解析按 entity 委托到对的子 member（loader 已绑对 session）。
- 跨边界关系（叠加层）由组合体自持有的 loader 解析。
- **Resolver 本体 0 改动**（spike 实证）——契约复用既有 `Resolver` 全部能力（auto-load、分页、federation dispatch）。

## 3. 与既有组件的交互契约（0 改动组件）

| 既有组件 | 交互 | 改动 |
|---|---|---|
| `Resolver.__init__(loader_registry: Any)` | 直接接受组合体 | 0（已 `Any`） |
| `ErDiagram.from_er_manager(er)` | 鸭子类型吃组合体 | 0（调 `get_all_entities`/`get_all_relationships`） |
| `ErDiagramDotBuilder(er_manager)` | 鸭子类型吃组合体 | 0（多读 `_fed_registry`） |
| `ErManager` | 被组合（作为 member） | 0 |

## 4. 阶段 2 契约：GraphQLHandler / Application 注入（非 breaking）

### `GraphQLHandler`（阶段 2）

```python
# 现有路径（保留，0 变化）
GraphQLHandler(base=BlogBase, session_factory=blog_sf, ...)

# 新增注入路径（additive 可选参数）
GraphQLHandler(er_manager=composed, entities=[User, Post, Order, OrderItem], ...)
```

**契约**：
- `er_manager=` 与 `base=` 互斥（二者都给 → `ValueError`）。
- 注入路径：跳过 `EntityDiscovery(base)` + 自造 ErManager；`QueryExecutor(loader_registry=composed)` → `composed.create_resolver()` 做关系解析（跨 engine，0 改动 resolve 链路）。
- `MethodScanner.scan(entities)` 扫描合并实体集；SDL 从合并 entities 产出。
- `handler.er` 类型注解放宽 `-> ErManager` 为 `-> LoaderRegistry`（运行时 0 影响）。

**语义边界**（文档化，非 breaking）：注入路径下 `handler.er` 返回组合体，其管理接口（`add_virtual_entities`/`initialize`/`federate`）不可用——这些操作在子 ErManager 上做。现有 `base=` 路径行为完全不变。

### `Application`（阶段 2）

```python
Application(name="...", er_manager=composed, entities=[...], description="...")
# 与 base=/url=/engine=/session_factory= 互斥
```

内部把 `er_manager` 透传给 `GraphQLHandler`。现有 `base=` + 连接参数路径保留。

## 5. federation 叠加契约（FR-017）

- 子 `ErManager` 可各自声明 `RemoteRelationship` 并 `initialize()` → federate 物化进各自 `_registry`/`_fed_registry`。
- 组合体通过委托 + `_fed_registry` 聚合视图看到物化的 remote type；resolver dispatch 透明。
- **federate/initialize 不在 ComposedErManager 上调用**（FR-013）——组合体不实现，调用即报错。
- ComposedErManager 作 federation member 被消费：`service_name`（组合体级）+ `get_public_dtos`/`get_dto_classes`（聚合）+ `get_all_entities` 正确暴露。

## 6. Public API 兼容性承诺

| 类别 | API | 影响 | breaking? |
|---|---|---|---|
| **0 改动** | `ErManager` `Resolver` `ErDiagram` `ErDiagramDotBuilder` `Relationship` 及 `__all__` 其余 | 无 | — |
| **纯新增** | `ComposedErManager` `LoaderRegistry` | 加入 `__all__` | 否（additive） |
| **阶段 2 小改** | `GraphQLHandler.__init__`（+可选 `er_manager=`）`GraphQLHandler.er`（注解放宽）`Application.__init__`（+可选 `er_manager=`） | 注入分支 + 注解 | 否（可选参数 + 注解放宽 + 文档化语义边界） |

**硬承诺**：阶段 1 完全 additive，现有 public API 零改动。阶段 2 不移除/重命名/改语义任何现有 public API，仅增加可选参数与放宽注解。符合 nexusx「公共接口默认不 breaking」纪律。
