# Feature Specification: 可组合 ErManager（ComposedErManager）—— 同进程多 engine 组合

**Feature Branch**: `feat/composable-er-manager`

**Created**: 2026-08-07

**Status**: Draft（经多轮架构讨论 + spike 验证收敛，2026-08-07）

**建立在**: `specs/012-federation`（跨进程 federation，本特性的对偶）+ `specs/016-dto-tree-federation`（γ 路径）+ ErManager/Resolver 现有架构之上

**Input**: 需求经三次表述收敛——
1. 「ER diagram 配置中允许存在多 db engine」（可视化合并）
2. 「不仅是在图中拼装，还要在 resolver 后端真用上两个组件的关联，通过某个 DataLoader / relationship 定义互相的关联」（运行时跨 engine resolve）
3. 「ErManager 是不是也可以形成一种可组合的模式？」（给出解法核心）

**spike 验证**: `spike_composed_er.py`（resolve + ER 图双绿）

---

## 背景与动机

### 问题演化

用户的诉求在一次对话中逐步精确化：

| 阶段 | 表述 | 本质 |
|---|---|---|
| 1 | ER diagram 配置允许多 db engine | 可视化合并 |
| 2 | 还要在 resolver 后端跨 engine 关联（DataLoader/relationship） | 运行时跨库查询 |
| 3 | ErManager 可组合 | 解法思想 |

**最终目标：让多个数据库 engine 在 nexusx 里共存——不仅能画进一张 ER 图，还要能在后端真的跨 engine 关联查询。**

### 现状约束

nexusx 的核心数据结构 `ErManager` 锁死「一个 engine」：

```
ErManager(session_factory = 一个 engine, entities = 一组实体)
    └─ 所有 ORM 关系的 loader，在构造时被「焊死」到这个 session_factory
       create_one_to_many_loader(..., session_factory=这一个)
```

`ErManager.__init__` 的 `session_factory` 是单值，贯穿三处：root 查询、ORM 关系 loader、（federation 走 transport，不用 session）。

### 核心矛盾

若把两个 engine 的实体硬塞进同一个 ErManager（设 session = blog）：

```
resolve blog.User.posts   → ORM loader → blog session → ✅ Post 表在 blog.db
resolve shop.Order.items  → ORM loader → blog session → ❌ orderitem 表不在 blog.db
```

**被桥过去的 shop 实体，其自身 ORM 关系会查错库。** 这是「单 ErManager 塞多 engine」的根本障碍。

> 注：ER 图生成本身不碰 engine（纯读 SQLModel/SQLAlchemy 类元数据），所以「画图」这一层无障碍；障碍在 resolver 执行查询时的 session 归属。

---

## 关键边界：定位 = 「同进程 federation」

本特性与 `specs/012-federation`（跨进程 federation）是**同一组合抽象的两个实例**：

```
跨进程 federation（012，已有）:
   blog_er (进程1, :8001)      shop_er (进程2, :8002)
        \                          /
         \____ RemoteRelationship ____/   ← 跨边界关系，走 transport(HTTP)
                    mounter_er            ← 组合体（组合语义在 federation 层）

同进程组合（本特性 019）:
   blog_er (session A)          shop_er (session B)
        \                          /
         \____ 跨 manager 关系 ____/      ← 跨边界关系，走进程内直调
              ComposedErManager           ← 组合体（组合语义在 ErManager 层）
```

两者共享同一核心模式：**保持 member 自洽 + 只在边界外挂关系**。区别仅在边界关系走什么 transport（HTTP vs 进程内直调）。

这补齐了 nexusx 组合叙事的缺口：之前组合只在跨进程维度存在（federation），现在同进程多 engine 维度也有了。

---

## 模型概述

### 组合体结构

`ComposedErManager` 是一个**按 entity 委托的只读总代理**，满足 `LoaderRegistry` 协议：

```
ComposedErManager([blog_er, shop_er])
    │
    ├─ _route: dict[type, ErManager]        ← entity → 所属子 ErManager
    │     {User: blog_er, Post: blog_er,
    │      Order: shop_er, OrderItem: shop_er}
    │
    ├─ _loader_owner: dict[loader_cls, ErManager]  ← loader class 反向路由
    │
    └─ 对 Resolver 的每个访问点：
       has_entity / get_relationships / get_loader_for_entity  → 按 entity 委托
       get_loader_by_name                                      → 遍历成员
       get_loader(loader_cls)                                  → 反向路由
       clear_cache                                             → 聚合所有成员
       create_resolver                                         → 产出总代理 Resolver
```

### 为什么成立（地基）

Resolver 的 dispatch **天然是「按 entity 路由」的**（nexusx 现有设计，无心插柳地成为组合地基）：

```python
# resolver.py 中所有 loader 获取，都是「先定实体，再取 loader」
source_entity = self._resolve_source(type(node))
loader = self._registry.get_loader_for_entity(source_entity, loader_name, ...)
rel_info = self._registry.get_relationship(parent_entity, field_name)
```

因此组合体只需「收到 entity → 查路由表 → 委托给子 ErManager」。**子 ErManager 完全自洽，单 session 不变；组合体不重建任何 loader，只委托。** 这直接绕开「改 ErManager 内部支持多 session」（触核心不变量）的高代价方案。

### 跨边界关系：复用现成 `Relationship`

跨 engine 的桥（如 blog.User → shop.Order）**不造新概念**，复用 `nexusx.relationship.Relationship`：

```python
User.__relationships__ = [
    Relationship(
        fk="id", target=list[Order], name="orders",
        loader=orders_by_user_id,   # 用户 async 函数，内部用 shop session
    )
]
```

`Relationship.loader` 是用户提供的 async batch 函数，内部自由选用 session——这正是「跨 engine 桥」的现成原料。组合体把这条关系（由 blog_er 在 `__init__` 时通过 `_build_custom_relationship_info` 注册）纳入自己的关系图。

### 两条暴露路径的分叉

组合难度高度依赖于走哪条 GraphQL 暴露路径：

```
UseCase 路径（service method 入口）:
  service method (自己拿 session) → Resolver(loader_registry=ComposedErManager)
  → 完全不碰 GraphQLHandler / schema
  → 组合 = ComposedErManager 一处改动              【零框架改动】

entity-first 路径（@query 装饰器入口）:
  GraphQLHandler(base=单个) 内部自造 ErManager    ← 锁死单 base
  → 组合需额外工作（仅 handler 注入, 关系解析 0 改动）  【小改动】
```

---

## Clarifications

### Session 2026-08-07（架构讨论 + spike 验证）

- **Q: 多 engine 是「跨库 SQL join」吗？**
  A: 不是。跨库 SQL join 物理上做不到。本特性是**应用层 DataLoader 批量关联**（N+1 batch fetch），跨库实体分别在自己的 engine 查询，在应用层组合。

- **Q: 多个 ErManager 是否意味着用户要选哪个 Resolver？**
  A: 不需要。`ComposedErManager.create_resolver()` 产出一个**总代理 Resolver**，它的 `loader_registry` 就是组合体本身，跨 engine resolve 对用户透明。

- **Q: 被桥过去的实体的自身 ORM 关系能正常钻取吗？**
  A: 能（spike 已验证二级钻取）。因为该实体在它自己的子 ErManager 里，ORM 关系 loader 早就焊对了 session。这是组合体相比「单 ErManager 硬塞」的核心优势。

- **Q: 为什么不走 federation 的 InProcessTransport 统一？**
  A: 那是更远的终局（见「中长期演进」）。当前先做独立的 ComposedErManager，避免在框架里吸收「多 engine member 编排」语义（违反组合优先于吸收的纪律）。

- **Q: 跨 engine 关系应该在哪声明？**
  A: **组合体级集中声明**（`ComposedErManager` 构造时传入），而非源实体的 `__relationships__`。理由：让每个 ErManager 对跨边界关联**无感**，单独使用时纯粹——组合层知识不泄漏进成员层（组合优于吸收）。代价：组合体从「纯代理」升级为「代理 + 叠加层」，需自己持有跨边界关系及其 loader，`get_relationships` 时与委托自子 member 的本地关系合并返回。

- **Q: 跨 engine 组合是否支持写操作与事务一致性？**
  A: **不支持**。本特性只管「读关联」（resolve/auto-load）；写操作各自落在独立 engine 上，**不提供跨 engine 事务**。跨库分布式事务（两阶段提交）复杂度极高，与本特性「application-layer DataLoader 批量关联」的定位冲突；跨库写一致性应由业务在应用层处理（saga 等），不进框架。

- **Q: ComposedErManager 构造后，成员集合是否可变？**
  A: **不可变**。成员 + 跨边界关系在 `__init__` 一次性确定，之后冻结（与 ErManager 的 frozen 语义一致）。构造时一次性完成所有校验（重名检测、loader 反向映射、跨边界关系叠加），不提供 `add_member` / `add_cross_rel`。

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — 同进程多 engine，UseCase 路径跨库 resolve (Priority: P1)

**场景**：一个进程内有 blog（SQLite）和 shop（PostgreSQL）两个 engine。blog.User 需通过跨库关系 resolve 出 shop.Order，并继续钻取 Order.items。

**spike 已验证**（`spike_composed_er.py`）：

```
Given blog_er(session=blog, entities=[User, Post])
  And shop_er(session=shop, entities=[Order, OrderItem])
  And User.__relationships__ 声明跨库 orders (loader 用 shop session)
  And ComposedErManager([blog_er, shop_er])
When resolver = composed.create_resolver()(context=...)
  And await resolver.resolve([UserDTO, ...])
Then UserDTO.posts  == blog 的 Post 列表           (blog session)
And  UserDTO.orders == shop 的 Order 列表           (shop session, 跨 engine)
And  UserDTO.orders[*].items == shop 的 OrderItem   (shop session, 二级钻取)
```

### User Story 2 — 跨 engine ER 图合并 (Priority: P1)

**场景**：用户最初诉求——一张 ER 图同时展示多个 engine 的实体及跨库关系。

**spike 已验证**：

```
Given ComposedErManager([blog_er, shop_er])
When ErDiagram.from_er_manager(composed).to_mermaid()
Then 图含 User, Post, Order, OrderItem 四个跨 engine 实体
And  图含跨库边 User ||--o{ Order : orders
And  图含同库边 User ||--o{ Post, Order ||--o{ OrderItem
```

ER 图生成层（`ErDiagram` / `ErDiagramDotBuilder`）**零改动**——它们只调 `get_all_entities()` / `get_all_relationships()` / `_fed_registry`，组合体已实现。

### User Story 3 — entity-first GraphQL 多 engine schema (Priority: P2)

**场景**：走 `@query` 装饰器路径的项目，希望一个 GraphQL schema 同时暴露两个 engine 的查询入口。

**关键认知（决定工作量）**：entity-first 的关系解析层**不需要额外工作**——`QueryExecutor` 通过 `loader_registry.create_resolver()` 拿 Resolver（`query_executor.py:398`），与 UseCase 路径调用 `er.create_resolver()` 是同一方法。换上 ComposedErManager 后，entity-first 的关系解析自动跨 engine；root @query 的 session 也由方法体自带（不依赖 handler）。**真正要改的只有 `GraphQLHandler` 自造 ErManager 那一处构造。**

```
Given GraphQLHandler 支持注入 er_manager + entities
When handler = GraphQLHandler(er_manager=composed, entities=[User,Post,Order,OrderItem])
Then handler.get_sdl() 同时含 UserQuery 和 OrderQuery
And  handler.execute("{ User { ... } Order { ... } }") 跨 engine 正常
```

### User Story 4 — 跨边界关系声明 (Priority: P2)

**场景**：用户声明两个 engine 实体之间的关联，并让它同时出现在 resolve 链路和 ER 图中。

```
Given User(blog) 与 Order(shop) 通过 user_id 逻辑外键关联
When 在 User.__relationships__ 声明 Relationship(target=list[Order], loader=...)
Then resolver 能跨库 resolve User.orders
And  ER 图画出 User → Order 边
And  该关系标注「跨 engine」来源（便于 ER 图分簇/标注）
```

### User Story 5 — federation × ComposedErManager 叠加：完整测试覆盖 (Priority: P1)

**场景**：ComposedErManager 与 federation（012/016）叠加时的组合性边界。组合 × 组合最易藏边界 bug（spec 起草期间曾误判 mounter 冲突），须完整集成测试覆盖。

**测试矩阵**（每条须有集成测试）：

- **A. member 端组合**（ComposedErManager 当 federation member 被消费）：
  - A1 member 内部跨 engine 关系，mounter 拉取的子树含 member 跨 engine 数据
  - A2 member ER/DTO introspection 反映所有子 member 实体 + 统一 service_name
- **B. mounter 端组合**（子 member 各自 federate）：
  - B1 一个子 member federate 远程 → 物化 type 经组合体委托可见 + resolve 通
  - B2 多个子 member 各自 federate 不同远程 service → 组合体聚合
  - B3 resolve 同时跨 engine（进程内）+ 跨 service（federation）混合路径
- **C. federation 状态聚合**：ComposedErManager `_fed_registry` 正确聚合子 member（remote type 判断、ER 图 styling）
- **D. 约束**：ComposedErManager `initialize`/`federate` 明确报错（FR-013）；子 member `initialize` 成功、组合体委托看到物化结果
- **E. 回归**：现有 federation 测试（012/013/014/016）+ ComposedErManager 基础测试零回归

### Edge Cases

- **EC1 实体重名**：两个 engine 的实体若落在同一 module 路径且同名，`full_class_name`（`module.ClassName`）会冲突。组合体应去重校验/告警。一般不同 app 的 module 不同，需验证。
- **EC2 clear_cache 时序**：`Resolver.resolve()` 开头调 `registry.clear_cache()`。组合体的 `clear_cache` 必须聚合所有成员，否则跨成员的 loader 缓存不一致。
- **EC3 get_loader 反向路由缺失**：若某 `loader_cls` 不属于任何成员（异常情况），`get_loader` 应清晰报错而非静默创建。
- **EC4 auto_query_config 标准查询**：`add_standard_queries` 用 handler 的 `session_factory` 生成 by_id/by_filter。多 engine 下各 base 的标准查询须保留各自 session 归属（见「边界」）。
- **EC5 federation 叠加**：ComposedErManager 与 federation（012/016）**正交可叠加**。federation 的 mutating 操作（federate/initialize）落子 ErManager，组合体只查询委托；子 member 可各自声明 RemoteRelationship 并 federate，物化进各自 `_registry`，组合体委托可见 + `_fed_registry` 聚合。组合 × 组合最易藏边界 bug（spec 起草期间曾误判 mounter 冲突），须完整测试覆盖（见 US5 矩阵）。
- **EC6 root DTO 构造**：root DTO 不能用 `model_validate(orm_instance)`（pydantic 会碰 ORM relationship 字段触发 detached lazy load）。只能填 subset 标量字段，关系留给 auto-load。（spike 暴露，resolver 内部 `_orm_to_dto` 已正确处理。）

---

## Requirements *(mandatory)*

### Functional Requirements

#### ComposedErManager 核心协议（阶段 1，P1）

- **FR-001** 实现 `LoaderRegistry` 协议的全部 Resolver 访问点：`has_entity` / `get_relationships` / `get_relationship` / `get_loader_for_entity` / `get_loader_by_name` / `get_loader` / `get_dto_loader` / `clear_cache` / `_split_mode` / `_fed_registry`。
- **FR-002** 按 entity 委托：维护 `entity → member` 路由表，`has_entity` / `get_relationships` / `get_loader_for_entity` 按 entity 路由到对应子 ErManager。
- **FR-003** loader class 反向路由：维护 `loader_cls → member` 映射（从各成员的 `get_all_relationships()` 收集），`get_loader(loader_cls)` 精确路由，避免缓存污染。
- **FR-004** `clear_cache` 聚合所有成员。
- **FR-005** `create_resolver()` 产出总代理 Resolver：照搬 `ErManager.create_resolver` 的 5 行，把组合体自身作为 `loader_registry` 注入。Resolver 本体零改动。
- **FR-006** ER 图兼容：实现 `get_all_entities` / `get_all_relationships`（合并所有成员），`_fed_registry` 返回中性值（None），使现成 `ErDiagram.from_er_manager` / `ErDiagramDotBuilder` 零改动可用。

#### 跨边界关系（阶段 1，P1）

- **FR-007** 跨 engine 关系复用 `nexusx.relationship.Relationship` 抽象（loader 为用户 async batch 函数，内部选用目标 engine 的 session），不引入全新的关系类型。**声明位置见 FR-008（组合体层，非源实体）。**
- **FR-008** 跨边界关系在 `ComposedErManager` 构造时**集中传入**，不声明在源实体的 `__relationships__` 上。子 ErManager 对跨边界关联完全无感，单独使用时纯粹。组合体持有这些跨边界 `RelationshipInfo`（叠加层），`get_relationships` 时与委托自子 member 的本地关系合并返回。

#### entity-first 组合（阶段 2，P2）

- **FR-009**（唯一构造改动）`GraphQLHandler.__init__` 增加注入分支：接受预构造的 `er_manager`（ComposedErManager）+ 合并的 `entities` 列表，绕过内部 `EntityDiscovery(base)` + 自造 ErManager。现有 `base=` 路径保留，非 breaking。注入后 `QueryExecutor(loader_registry=composed)` 自动生效。
- **FR-010**（关系解析 0 改动）entity-first 关系解析无需额外工作：`QueryExecutor._get_entity_resolver` 调 `loader_registry.create_resolver()`（`query_executor.py:398`），换 ComposedErManager 后自动得到总代理 Resolver，跨 engine 关系解析与 UseCase 路径同机制。root @query 的 session 由方法体自带，亦无需改动。
- **FR-011**（SDL/方法扫描）注入路径下，`MethodScanner.scan(entities)` 扫描合并实体集，产出合并的 query_methods / mutation_methods；SDL/Introspection 从合并 entities 自动产出合并 schema（现有 `for entity in self.entities` 收集逻辑天然支持）。

#### 边界

- **FR-012** auto_query_config 多 engine：标准查询（by_id/by_filter）须按 base 归属使用各自 session_factory。阶段 2 明确处理或文档标为「多 engine 下推荐手写 @query」。
- **FR-013** ComposedErManager 不实现 ErManager 的「管理接口」（`add_virtual_entities` / `federate` / `initialize`）——它是查询/组合代理（外加跨边界关系叠加层），不修改子 member 状态。管理操作在各子 ErManager 上进行。
- **FR-014** 实体重名校验：组合体构造时检测 `full_class_name` 冲突并明确报错。
- **FR-015**（out-of-scope）跨 engine 写操作与事务一致性不在本特性范围。本特性只提供读关联（resolve/auto-load）；写操作各自独立 engine，跨库写一致性由业务在应用层处理（saga 等）。
- **FR-016** 不可变性：成员集合与跨边界关系在 `ComposedErManager.__init__` 一次性确定，之后冻结（与 ErManager frozen 语义一致）。构造时完成重名检测、loader 反向映射、跨边界关系叠加；不提供 `add_member` / `add_cross_rel`。
- **FR-017** federation 正交：ComposedErManager 不实现 `federate`/`initialize`（FR-013）；子 ErManager 可各自声明 `RemoteRelationship` 并 federate，物化进各自 `_registry`，组合体委托可见 + `_fed_registry` 聚合。federation mutating 操作只落子 ErManager，不落组合体。

### Key Entities

| 组件 | 职责 | 阶段 |
|---|---|---|
| `ComposedErManager` | 按 entity 委托的总代理，实现 LoaderRegistry 协议 | 1 |
| `ComposedErManager.create_resolver` | 产出总代理 Resolver | 1 |
| 跨边界 `Relationship` | 复用现有，loader 内部路由 session | 1 |
| `GraphQLHandler` 注入分支 | 接受预构造 er_manager + 合并 entities | 2 |
| `LoaderRegistry` Protocol（可选） | 把 Resolver 依赖的查询接口正式抽象为 Protocol | 1/2 |

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-1** spike 的 4 个 resolve 断言全绿（同库 posts、跨库 orders、跨库二级钻取 items）。
- **SC-2** spike 的 ER 图断言全绿（4 实体同图 + 跨库边）。
- **SC-3** UseCase 路径产品化后，现有测试套件零回归（全量 pass）。
- **SC-4** ComposedErManager 实现 LoaderRegistry 全部 9 个访问点，Resolver 本体零改动。
- **SC-5**（阶段 2）entity-first 多 engine schema 生成 + 执行通过，现有 `base=` 单 base 路径行为不变。
- **SC-6** federation × ComposedErManager 叠加测试矩阵（US5 的 A–E）全绿；现有 federation 测试（012/013/014/016）与 ComposedErManager 基础测试零回归。

### 量化「轻」

spike 实证：
- `ComposedErManager` 代理逻辑 ~80 行（含注释）
- `create_resolver` 照搬 5 行
- Resolver 本体（~2000 行 BFS/auto-load/分页）**0 改动**
- ER 图生成层 **0 改动**

---

## 关键设计决定与取舍论证

### DD-01 代理 vs 合并视图 → 选代理

**决定**：ComposedErManager 按 entity 委托，不合并子 ErManager 的内部 `_registry`。

**理由**：合并视图会把子 ErManager 的 `_registry`（含 federation 状态、loader 实例缓存）摊进一个新 dict，破坏封装、状态难合并。代理保持每个子 ErManager 自洽，组合体只读委托。

**代价**：少数「按 class 查」的路径（`get_loader(loader_cls)`）需反向映射，但绝大多数热路径已走「按 entity」API。

### DD-02 跨边界关系：复用 Relationship 抽象 + 组合体层声明 → 选复用 + 组合体注入

**决定**：跨 engine 关系用 `Relationship(loader=用户函数)`，不引入新关系类型；**声明位置在组合体层**（`ComposedErManager` 构造时传入），而非源实体的 `__relationships__`。

**理由**：
- 复用 `Relationship`：`Relationship.loader` 本就是为「非 ORM、用户 loader 驱动的关系」设计，跨 engine 只是「loader 内部换 session」，零新概念。
- 组合体层声明：让每个 ErManager 对跨边界关联**无感**，单独使用时纯粹——组合层知识不泄漏进成员层（组合优于吸收）。若声明在源实体上，`blog_er` 单独跑时 `User` 身上会悬着指向 `Order` 的无意义关系。

**代价**：ComposedErManager 从「纯只读委托代理」升级为「代理 + 叠加层」——需自己持有跨边界关系及其 loader，`get_relationships` 时合并返回。DD-01（不合并子 member 的 `_registry`）依然成立。

**注**：spike（`spike_composed_er.py`）为快速验证，把跨边界关系写在 `User.__relationships__` 上（源实体级）；产品化改为组合体层注入。

### DD-03 LoaderRegistry Protocol 抽象 → 选抽象（阶段 1/2）

**决定**：把 Resolver 依赖的「查询接口」从 ErManager 具体类抽离为正式 Protocol。

**理由**：`registry.py` 已有 `LoaderRegistry = ErManager` 别名，「registry」概念本就比「ErManager 具体类」宽。Protocol 把 Resolver 的依赖面显式列出，ComposedErManager 逐个实现不会漏。正交切分：查询接口（组合体实现）vs 管理接口（仅 ErManager）。

### DD-04 不走 federation transport 统一（暂） → 选独立实现

**决定**：当前做独立的 ComposedErManager，不通过给 federation 塞 `InProcessTransport` 来实现。

**理由**：transport 统一是更远的终局（见「中长期演进」）。当前独立实现更直接、风险更低，且不违反「组合优先于吸收」（避免框架吸收「多 engine member 编排」语义）。federation 的语义是「每个 member 独立 schema/service」，进程内套这层过重。

### DD-05 阶段化交付 → UseCase 先行

**决定**：阶段 1 只做 ComposedErManager + UseCase 路径 + ER 图（零框架改动即可用）；阶段 2 才碰 GraphQLHandler。

**理由**：spike 证明 UseCase 路径 + ER 图零摩擦，可立即交付价值；entity-first 组合经确认也是小工作量（关系解析复用 `create_resolver`，真正要改的只有 `GraphQLHandler` 的 er_manager 注入口），分开降低风险。

---

## 中长期演进与开放点（不锁死，留 plan/future）

- **Transport 统一**：若将来 federation 的 `FederationTransport` Protocol 塞一个 `InProcessTransport`（不发 HTTP，直接调另一个 ErManager），则「跨进程 federation」与「同进程组合」可统一为同一组合机制的两个 transport。当前不追求，但保留这条演进路径。
- **GraphQLHandler 组合的更深形态**：阶段 2 的「注入分支」是最小改动；更彻底的是 `ComposedGraphQLHandler`（组合多个 handler 的 schema）。视阶段 2 实际反馈决定。
- **ER 图跨 engine 分簇标注**：复用 federation 的 `module_color` / `federated_modules` 分簇机制，让跨 engine 实体按 engine/app 分框上色。spike 未验证此增强，留作可选。
- **双向跨边界关系**：当前跨边界关系单向声明（User→Order）。双向（Order→User）是否需要组合体级声明，视需求。

---

## Assumptions

- 跨 engine 关联是**应用层 DataLoader 批量关联**，非跨库 SQL join。
- 子 ErManager 各自自洽：单 session_factory、loader 已正确绑定各自 engine。
- UseCase 路径的 service method 自带 session 获取（不依赖 handler 的 session_factory 做 root 查询）。
- ER 图生成层与 engine 解耦（纯读元数据），组合不涉及 ER 图层改动。
- spike（`spike_composed_er.py`）的验证结果可信，作为阶段 1 可行性的实证基础。
