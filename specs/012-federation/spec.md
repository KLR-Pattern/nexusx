# Feature Specification: nexusx 多服务联邦(nexusx-to-nexusx Federation)

**Feature Branch**: `012-federation`

**Created**: 2026-07-26

**Status**: Draft

**Input**: User description: "在 nexus 中实现多服务组合的类似 graphql federation 的能力,服务提供方式类似一个接受 graphql 参数的 dataloader。多个 nexusx 服务可以组合在一起,每个 nexusx 服务都能挂载其他 nexusx 服务,没有集中 gateway,是相对组合;通过向其他服务发送 gql query 获取多级嵌套数据。"（设计逐轮收敛,本 spec 据此撰写。）

## 模型概述(两条载重决定)

1. **拓扑:相对组合,无 router。** 每个 nexusx 服务都能挂载其他 nexusx 服务(`er.federate(services={...})`);挂载是对称能力,任何服务既可挂载也可被挂载。不存在集中 gateway 或特权 router 角色。一条查询进入哪个服务,那个服务就是**这次查询**的编排者(per-query,非 per-topology)。挂载一个服务 = 挂载它的整个查询面(含它自己挂载的下游),因此**传递可达是 inherent 的**,无需把链路上每个服务都显式挂一遍。

2. **取数:gql 嵌套查询。** 挂载方要从被挂载服务取数据时,RemoteLoader 向该服务的 `graphql_query` 发送**一条 GraphQL 查询,请求多级嵌套子树**;被挂载服务用自己的 executor 一次性把自己那部分组合子图(本地 + 自身挂载)查完,返回成型的嵌套数据。挂载方只在**服务边界**拼接,不在单服务内部逐层 fetch——这保住了 nexusx"每服务一次批量"的核心身份,不在网络层制造 N+1。这就是用户最初的"接受 graphql 参数的 dataloader"。

## 背景与动机

nexusx 当前的 `ErManager` 把一个 SQLModel 库反射成 ER 图,`QueryExecutor` 用 BFS + DataLoader 按"每层一次批量取"解析嵌套查询,N+1 在结构上不可能。这是单体 nexusx 服务的核心能力。

当业务拆成多个 nexusx 服务(产品、评论、用户各一个进程,各有自己的库与 ER 图)时,客户端要一次拿到 `产品 { 评论 { 作者 } }` 跨三服务的数据,今天没有机制。本特性让任意 nexusx 服务能挂载其他 nexusx 服务,组合成一张(相对自身的)统一图:客户端像查单体一样发一条查询,入口服务把跨服务遍历编排成"对每个被挂载服务发一条 gql 嵌套查询"。每个被挂载服务仍用自己的批量引擎解析自己的子图——联邦不破坏 nexusx 的招牌,只在外层做边界拼接。

nexusx 已有的零件覆盖了大部分:每关系一个 DataLoader、custom relationship(`__relationships__`)、virtual entity、BFS query planner、ER 图结构化数据(`RelationshipInfo`)。净新增集中在:远程关系声明、远程类型物化、ER 内省与校验、RemoteLoader(gql 嵌套取数)、成员侧 `by_<key>_in` 入口、以及把 schema 渲染改成 registry 驱动。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 挂载一个服务,取其嵌套数据(Priority: P1)

作为一个把业务拆成多个 nexusx 服务的开发者,我希望在某个 nexusx 服务(例:catalog,本地有 `Product`)上挂载另一个 nexusx 服务(reviews,有 `Review`),并声明 `Product.reviews → reviews.Review`,这样客户端查 `{ product { reviews { title rating } } }` 时,catalog 自动向 reviews 发一条 gql 查询取回嵌套 reviews,我无需手写跨服务拼接。

**Why this priority**:联邦的最小可用切片。验证主链路——远程字段 = custom relationship + RemoteLoader(gql 嵌套取数)+ 物化 virtual target——端到端跑通,且保住 nexusx 招牌:对每个被挂载服务只发一条查询。

**Independent Test**:起 catalog(本地 `Product`)+ reviews(`Review` + `by_product_id_in` root + ER 内省端点),声明 `RemoteRelationship(target="reviews.Review", join_local="id", join_remote="product_id")`,查多个 Product 的 reviews,断言:结果正确、reviews 服务**只被请求一次**(一条 gql 查询)。

**Acceptance Scenarios**:

1. **Given** catalog 本地有 `Product(id, name)`,reviews 有 `Review(id, product_id, title, rating)` 且暴露 ER 内省端点与 `by_product_id_in` root,**When** catalog 启动并 `er.federate(services={"reviews": <url>})`,**Then** 启动成功,`reviews.Review` 物化为 virtual 实体并注册,无报错。
2. **Given** 上述联邦,**When** 客户端查 `{ product { id reviews { title rating } } }` 取 N 个产品,**Then** 返回正确嵌套结果;reviews 服务**只收到一条** gql 查询(携带全部 N 个 `product_id`),而非 N 条。
3. **Given** 同一联邦,**When** 客户端只查 `{ product { id name } }`(不触碰 reviews),**Then** reviews 服务**完全不被调用**。

---

### User Story 2 - 多跳(跨多服务)对客户端透明(Priority: P1)

作为一个开发者,我希望查询能连续跨越多个服务(如 `product { reviews { author { name } } }`,reviews 与 users 是不同服务),且对客户端与查单体无异——客户端不知道 reviews、author 分布在不同服务。

**Why this priority**:多跳是联邦相对"单外部数据源挂载"的核心增量;透明性是联邦成立前提。挂载 reviews 即可达 reviews 自己挂载的 users(reviews 的查询面已含),故 catalog 只需挂 reviews 即可触达 author——传递可达 inherent。

**Independent Test**:起 catalog + reviews(挂 users) + users,声明 `Product.reviews → reviews.Review`;reviews 侧自行声明 `Review.author → users.User`。查 `product { reviews { author { name } } }`,断言:结果正确、客户端查询无服务前缀、catalog 对 reviews 只发一条 gql 查询(该查询的嵌套选区含 `author`,reviews 内部解析 author)。

**Acceptance Scenarios**:

1. **Given** catalog 挂 reviews;reviews 挂 users 并声明 `Review.author → users.User`,**When** 客户端经 catalog 查 `{ product { reviews { author { name } } } }`,**Then** 返回完整嵌套结果;catalog 对 reviews 发**一条** gql 查询,选区含 `reviews { ... author { name } }`,reviews 自行解析 author(必要时 reviews 内部向 users 发其自己的 gql 查询)。
2. **Given** 同一查询,**When** 检查客户端 GraphQL 文档与对外 schema,**Then** 只有裸类型名(`Product`/`Review`/`User`),不含 `reviews.`/`users.` 前缀。
3. **Given** router 不拥有 `Review` 类(远程物化),**When** 需在远程类型 `Review` 上挂出边(`author`),**Then** 该边在拥有 `Review` 的那一侧(reviews)声明(远程→远程边配置式声明,不要求 co-location 到不拥有的类)。

---

### User Story 3 - 启动期 fail-fast 校验(含成环)(Priority: P2)

作为开发者/运维,我希望所有联邦错配(引用不存在的服务/类型、join 字段对不上、前缀冲突、跨服务同名类型、挂载图成环)在**入口服务启动时**即明确报错拒绝,不留到运行时。

**Why this priority**:联邦引入跨进程隐式契约。init 期物化天然支持启动期校验;相对组合下挂载图可能成环(A 挂 B、B 挂 A),必须检出以免传递式 ER 拉取无限递归。

**Independent Test**:分别构造六类错配(未知 srv / typename 缺失 / join 字段缺失或类型不兼容 / 缺 `by_<key>_in` root / 前缀重复 / 跨服务裸名重复 / 挂载成环),启动入口服务,断言每类都抛明确错误并退出。

**Acceptance Scenarios**:

1. **Given** 声明引用 `target="reviews.Review"` 但挂载 registry 无 `reviews`,**When** 启动,**Then** 失败,错误指明未注册前缀 `reviews` 及出错声明。
2. **Given** `reviews` 已挂但其 ER 片段不含 `Review`,或 `Review` 不含 `join_remote`,或类型与本地 `join_local` 不兼容,**When** 启动,**Then** 失败,指明缺哪个类型/字段或类型不匹配。
3. **Given** reviews 未暴露按 `join_remote` 的 `by_<key>_in` root,**When** 启动,**Then** 失败,指明缺哪个 root。
4. **Given** 两个被挂服务自声明同名(前缀冲突),**When** 启动,**Then** 失败,列出冲突服务。
5. **Given** 两个不同服务暴露同名类型,**When** 启动,**Then** 失败,指出跨服务裸名重复。
6. **Given** 挂载图成环(A 挂 B、B 挂 A),**When** 启动并传递式拉取 ER 片段,**Then** 检出环并 fail-fast,不无限递归。

---

### User Story 4 - Voyager 展示完整联邦图,远程节点标注归属(Priority: P3)

作为开发者/架构师,我希望入口服务的 Voyager/ER 图画出联邦后的**完整图**(含所有远程物化实体,裸名显示),并在每个远程节点标注归属服务。

**Why this priority**:联邦超两三个服务后拓扑复杂,无图难维护。Voyager 已是自文档化手段,扩展到联邦图是自然延伸。优先级低于前三条(不影响取数正确性)。

**Independent Test**:建立 catalog + reviews + users 联邦,打开 catalog 的 Voyager,断言:图中出现所有本地与远程实体(裸名)、远程节点带归属标注、跨服务边正常。

**Acceptance Scenarios**:

1. **Given** catalog + reviews + users 联邦已启动,**When** 打开 Voyager,**Then** 图含 `Product`、`Review`、`User`(裸名),`Product→Review`、`Review→User` 跨服务边可见。
2. **Given** 同一图,**When** 查看 `Review` 节点,**Then** 标注归属 `reviews`(规范名 `reviews.Review` 作标签/徽标,不把前缀揉进类型名)。

---

### User Story 5 - 客户端能内省并渲染完整联邦 schema(Priority: P1)

作为客户端/前端开发者,我希望入口服务暴露的 GraphQL schema(SDL 与 `__schema` 内省)含**完整**联邦图——本地类型、远程物化类型(裸名)、跨服务关系字段(如 `Product.reviews`、`Review.author`)——这样客户端/GraphiQL 能发现并直接查询。

**Why this priority**:"对客户端透明"的硬前提。schema 里看不到字段/类型,客户端无法构造查询。执行靠 registry 驱动的 BFS,渲染靠 registry 驱动的 schema 生成,两条路径须一致覆盖联邦类型与关系。现状 schema 生成是 type-hint 驱动、不读 `__relationships__`,故须显式立项。

**Independent Test**:联邦启动后取 SDL 与 `__schema` 内省,断言出现 `type Review { ... }`、`type User { ... }`、`Product.reviews`、`Review.author`,全为裸名。

**Acceptance Scenarios**:

1. **Given** catalog + reviews + users 联邦已启动,**When** 取 SDL,**Then** SDL 含 `type Review`、`type User`、`Product.reviews`、`Review.author`,类型名均为裸名。
2. **Given** 同一联邦,**When** 经 `__schema` 内省查 `Product`/`Review` 字段,**Then** 分别含 `reviews`(→`Review`)、`author`(→`User`)。
3. **Given** SDL 与执行,**When** 对比 SDL 字段集与 executor 经注册表可解析字段集,**Then** 逐类型完全一致(渲染与执行同源)。

---

### Edge Cases

- **被挂载服务运行期间新增字段**:本期不热感知,入口服务重启重新 init。
- **被挂载服务启动期不可达**:入口服务启动 fail-fast。
- **join key 为复合键(多字段)**:本期不支持,校验拒绝。
- **挂载图成环**:传递式 ER 拉取检出即 fail-fast(US3 场景 6)。
- **同一规范类型被多条 edge 引用**:`FederatedTypeRegistry` 去重,只 `create_model` 一次。
- **gql 嵌套查询返回的行与 keys 不对齐**(DataLoader 要求位置对应):RemoteLoader 按 join key 分组对齐,缺失映射为 `None`(to-one)/ `[]`(to-many)。
- **客户端选中远程实体不存在的字段**:按现有 GraphQL 字段不存在语义报错。
- **远程 to-many 关系分页**:本期不强制远程分页(`by_<key>_in` 返回扁平列表);远程分页为后续。
- **嵌套深度极大**:被挂载服务解析自身子图仍是一次批量查询(其引擎的 N+1-proof 保证);跨服务深度由入口服务的 BFS 按服务边界推进,每跨一个服务一条 gql 查询。

## Requirements *(mandatory)*

### Functional Requirements

#### 声明与寻址

- **FR-001**(声明 API):系统 MUST 提供新的 `RemoteRelationship` 数据类,与现有 `Relationship` 并列声明于 `__relationships__`,携带 `name`、`target`、`join_local`、`join_remote`,且**不内联 loader**(由框架组合时生成)。现有 `Relationship`(target 为类、loader 必填)语义不变。
- **FR-002**(标记字符串寻址):`RemoteRelationship.target` MUST 取形如 `"<srv>.<typename>"` 的字符串,框架扫描时 parse 为 `("srv","typename")`。该字符串 MUST 仅作声明标记,不参与 Pydantic forward-ref 解析。
- **FR-003**(服务前缀 + 每服务挂载 registry):每个 nexusx 服务 MUST 暴露自声明的稳定 `name` 作为命名前缀(类比 MCP multi-app 的 `app_name`)。一个挂载方 MUST 维护**自己的** `name → endpoint` 挂载 registry(`er.federate(services={...})`)。前缀 MUST 仅作内部路由/校验/消歧;对外 schema 不含前缀。
- **FR-004**(远程→远程边声明):系统 MUST 支持在远程(物化)类型上声明出边;因挂载方不拥有远程类,这类边 MUST 在拥有该类型的服务侧以配置式声明。

#### 组合数据源(schema)

- **FR-005**(ER 内省为 schema 源,含远程引用):组合数据源 MUST 是 ER 图信息(实体标量字段 + `RelationshipInfo`),由成员经 **ER 内省端点**暴露。其中远程关系 MUST 声明其目标服务 + 端点,使挂载方能**传递式**发现并拉取可达子图的片段(visited-set 去环)。系统 MUST NOT 以 GraphQL SDL 为组合数据源。

#### 初始化与物化

- **FR-006**(init 期物化,非运行时懒加载):挂载方 MUST 在初始化阶段(冻结 `ErManager` 之前)完成:传递式拉取可达 ER 片段、校验、物化,再冻结。冻结后注册表 MUST NOT 变更。MUST NOT 采用运行时按需懒加载远程类型形状。
- **FR-007**(两遍物化):pass1 按声明边 + 片段中远程引用做 BFS(visited-set 去环),拉全可达片段;pass2 拓扑排序后 `create_model` 物化,用"裸名→物化类"namespace 执行 `model_rebuild` 解跨远程引用。
- **FR-008**(物化类型裸名):物化类的 `__name__` MUST 等于裸 `typename`(不加前缀、不驼峰)。规范身份 `"<srv>.<typename>"` MUST 由独立模块 `FederatedTypeRegistry` 维护,用于内部寻址,不进入 `__name__`。
- **FR-009**(RelationshipInfo 扩展):`RelationshipInfo` MUST 增加 `target_service: str | None`(本地为 `None`,远程为归属前缀)。executor 据此把远程关系路由到 RemoteLoader。
- **FR-019**(物化类型出边注册):物化的远程类型 MUST 把其自身关系(来自 ER 片段 + 在其上声明的远程出边)注册为 `RelationshipInfo`,使 executor 的 BFS 能从该类型继续向下一跳,也使 schema 渲染覆盖这些字段。

#### 取数(gql 嵌套查询)

- **FR-010**(gql 嵌套取数):RemoteLoader MUST 通过向被挂载服务的 `graphql_query` 发送**一条 GraphQL 查询、请求多级嵌套子树**来取数;被挂载服务 MUST 自行解析其组合子图(本地 + 自身挂载)并返回成型嵌套数据。挂载方 MUST 只在服务边界拼接,MUST NOT 对同一被挂载服务在其内部子图上逐层发多次 flat 请求(避免网络层 N+1,保住每服务一次批量的身份)。
- **FR-011**(gql 查询入口与对齐):RemoteLoader 构造的 gql 查询 MUST 以被挂载服务的 `by_<key>_in`(按 `join_remote` 批量)为入口,携带本层收集的 join key;返回结果 MUST 按 join key 分组对齐到 DataLoader 的位置契约(缺失映射为 `None`/`[]`)。
- **FR-012**(成员 `by_<key>_in` root):`AutoQueryConfig` MUST 能为指定字段生成 `by_<key>_in` 批量查询 root(语义 `where field.in_(values)`),作为 gql 嵌套查询的入口,供 RemoteLoader 使用。

#### 校验(全部 fail-fast,init 期)

- **FR-013**(启动期校验):挂载方初始化时 MUST 对每条 `RemoteRelationship`/远程边逐项校验,任一失败即拒绝启动:(a) `srv` 在挂载 registry 中;(b) 该服务暴露该 `typename`;(c) `join_remote` 字段存在且类型与本地 `join_local` 兼容;(d) 该服务暴露按 `join_remote` 的 `by_<key>_in` root;(e) 任意两个被挂服务 `name` 不重复;(f) 任意两个不同服务不暴露同名裸类型;(g) 传递式 ER 拉取检出挂载图成环即拒绝。

#### 透明性 / 渲染 / 角色

- **FR-014**(多跳透明):系统 MUST 支持跨任意多服务边界的连续遍历,对外 schema 与客户端查询 MUST 仅含裸类型名。
- **FR-015**(挂载对称,无 router):挂载 MUST 是每个 nexusx 服务对称具备的能力;系统 MUST NOT 引入特权 router/gateway 角色。查询的编排 MUST 由其入口服务承担(per-query)。被挂载服务为本特性所需的新增面 MUST 限定为:暴露自声明 `name`、ER 内省端点、`by_<key>_in` root(均通用能力,非联邦专属耦合)。
- **FR-016**(Voyager 联邦图):Voyager/ER 图 MUST 在联邦启动后渲染完整联邦图(含所有本地与远程物化实体,远程节点裸名),并以规范名/归属标注每个远程节点的所属服务(作标签/徽标,不揉进类型名)。
- **FR-017**(schema 生成 registry 驱动):SQLModel GraphQL 面的 schema 生成(SDL 与 `__schema` 内省)MUST 以 `ErManager` 注册表为关系字段来源,覆盖所有注册实体(含 virtual/物化远程类型),并把每条注册关系(含 `RemoteRelationship`)渲染为 GraphQL 字段。MUST NOT 仅依赖 Python type hints(`get_type_hints`)发现关系字段。
- **FR-018**(远程目标解析裸名):schema 生成渲染远程关系字段时,MUST 经 `FederatedTypeRegistry` 把 `"srv.typename"` 解析为物化类裸 `__name__` 作 GraphQL 类型名。

### Key Entities *(include if feature involves data)*

- **联邦服务(federating service)**:任意开了 `er.federate(...)` 的 nexusx 服务,承担进入它的查询的编排。无特权 router。
- **被挂载服务(mounted service)**:被某联邦服务挂载的 nexusx 服务,暴露自声明 `name`、ER 内省端点、`by_<key>_in` root。任何服务可同时是联邦服务与被挂载服务。
- **`RemoteRelationship`**:新增声明数据类,表达跨服务关系,携带 `target="<srv>.<typename>"`、`join_local`、`join_remote`,不内联 loader。
- **`"<srv>.<typename>"` 规范名**:远程类型内部规范身份,仅用于路由/校验/消歧,不进对外 schema。
- **`FederatedTypeRegistry`**:新增模块,维护"规范名 ↔ 物化类",负责两遍物化与跨远程引用解析;内部按类对象建键,不依赖 `__name__` 唯一性。
- **`RemoteLoader`**:新增 DataLoader,把一组 join key + 嵌套选区转成**一条对被挂载服务 `graphql_query` 的 gql 查询**,返回按 key 对齐的成型嵌套数据。
- **`RelationshipInfo`(+`target_service`)**:既有关系元数据,新增 `target_service` 区分本地/远程并供 executor 路由。
- **ER 片段(ER fragment)**:成员经 ER 内省端点返回的结构化数据(类型的标量字段 + `RelationshipInfo`,远程关系带目标服务+端点),是组合、校验与传递式发现的输入单位。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**(单跳):catalog(本地 `Product`)挂 reviews 联邦下,查 `{ product { reviews { title rating } } }` 对 N 个产品返回正确嵌套结果,且 reviews 服务**恰好收到一条** gql 查询(携带全部 N 个 `product_id`)。
- **SC-002**(多跳透明):`product { reviews { author { name } } }`(reviews/users 不同服务)返回正确嵌套结果;客户端文档与对外 schema 不含服务前缀;catalog 对 reviews 只发一条 gql 查询(reviews 内部自行解析 author)。
- **SC-003**(每服务一次批量):对一次查询中涉及的每个被挂载服务,RemoteLoader 恰好发**一条** gql 嵌套查询;被挂载服务内部用自身引擎一次批量解析其子图(不在网络层产生逐层 N+1)。
- **SC-004**(启动期 fail-fast):七类错配(未知 srv / typename 缺失 / join 字段缺失或不兼容 / 缺 `by_<key>_in` root / 前缀重复 / 跨服务裸名重复 / 挂载成环)各自在入口服务启动期检出并拒绝,无一例进入运行时。
- **SC-005**(单体零回归):联邦特性合并后,既有单体 nexusx 全量测试零回归(未启用 `federate` 时本地查询/SDL/Voyager 不变)。
- **SC-006**(联邦图可视化):Voyager 渲染的联邦图含所有本地与远程物化实体(远程裸名),每个远程节点带归属标注,跨服务边正确。
- **SC-007**(完整 schema 渲染):SDL 与 `__schema` 内省均含所有远程物化类型(裸名)及全部跨服务关系字段;SDL 字段集与 executor 经注册表可解析字段集逐类型一致。

## 关键设计决定与取舍论证

1. **为什么组合数据源是 ER 图信息,而非 GraphQL SDL。** SDL 是 ER 图的有损投影:输出序列化主动剔除 FK 字段(`_filter_output`),且 SDL 不携带方向/基数/分页元数据。联邦最需要的 join key(FK)与基数恰是 SDL 丢失的。ER 内省直接给出 `RelationshipInfo.fk_field`/`direction`/`is_list`,join key 确定且可校验,并与 Voyager/executor 同源,不引入第二套真相。

2. **为什么远程类型用"标记字符串"而非 Python 类型。** `"<srv>.<typename>"` 含点号,非合法 Python 标识符;若做成可解析类型注解,Pydantic forward-ref、`model_rebuild`、mypy 每层都跟它打架。降格为框架扫描时 parse 的声明标记(不参与类型解析),绕开 80% 的"魔改";物化在 init 期用 `create_model` 现场生成真实类。

3. **为什么物化类 `__name__` 保持裸名。** `ErManager._registry` 是 `dict[type,...]`,按类对象而非 `__name__` 建键——两个不同服务物化的 `Review` 是不同类对象,内部不撞键,mangle 解决的是不存在的问题。`__name__` 外泄处(对外 SDL/dispatch),mangle 也救不了:两服务 `Review` mangle 后 strip 回去仍都叫 `Review`,一份 schema 里非法——重名是 GraphQL 硬约束,只能 fail-fast。规范身份由 `FederatedTypeRegistry` 持有即可。

4. **为什么在初始化期物化,而非运行时懒加载。** init 期物化让校验可启动期 fail-fast、`ErManager` 冻结不变量不被破坏(物化在冻结前)、Voyager 启动后即完整、无需 stale/TTL。代价:被挂服务运行期加字段需重启入口服务重新 init(见假设)。

5. **为什么是相对组合、无 router。** 把"router"设为特权角色违背 nexusx 的对称性(每个实体可关联任意实体 → 推广到跨服务应同样对称)。挂载是每个 nexusx 服务都有的能力;编排由查询入口服务 per-query 承担;无集中 gateway。挂载一个服务即挂载其整个查询面(含其下游),传递可达 inherent——这正是"相对组合":每个服务组合相对自身的视图。

6. **为什么取数走 gql 嵌套查询,而非 flat 逐层。** flat 逐层会把**单服务自己的本地子图**也切成多次请求(如 reviews 自有 `评论→评论作者→...` 几层,flat 会让挂载方对 reviews 发多次逐层请求),在网络边界重新制造 N+1,砸掉 nexusx"每服务一次批量"的招牌。gql 嵌套查询让**每个被挂载服务用自己的 executor 一次性批量解析自身组合子图**,挂载方只在服务边界拼接——既保住批量身份,又拿到 chunk-coalescing 的好处(每服务子图一次查完)。这也是用户最初"接受 graphql 参数的 dataloader"的准确实现。注:组合/渲染用的 schema 源仍是 ER(决定 1),gql 查询只是取数执行路径,二者同源于被挂服务的 `ErManager`,不构成第二套真相。

7. **为什么 schema 生成必须 registry 驱动。** 现状 `sdl_generator._generate_type` 经 `get_type_hints` 发现关系字段,而 `__relationships__` 的 custom/remote 关系不是类型注解——若不改,远程关系字段(`reviews`/`author`)与物化远程类型进不了对外 schema,客户端无法查询,US2/US5 不成立。executor 本就 registry 驱动,渲染侧须向执行侧对齐,使"渲染"与"执行"同源。这是本特性相对现有代码最关键的非平凡改动,plan 阶段须单列。

## Assumptions

- 假设所有被挂载服务都是 nexusx 服务,且 ER 内省端点与 gql 查询接口协议在挂载方与被挂方间一致(同版本或兼容)。
- 假设挂载方启动期可同步访问所有可达被挂服务的 ER 内省端点;任一不可达 → 启动 fail-fast。
- 假设联邦 MVP 仅支持对远程实体的**读取**;远程写入/mutation 不在本期。
- 假设跨服务 join 为**单字段**(复合键不支持,校验拒绝);join key 类型兼容性按类型名相等或已知兼容映射判定。
- 假设跨服务**无裸类型名重复**(否则 fail-fast);多数部署靠命名约定满足。
- 假设被挂服务自声明 `name` 在部署内唯一(前缀唯一性由 FR-013 校验保证)。
- 假设物化的远程类型字段来自 ER 片段,无用户自定义 validator/serializer。
- 假设被挂服务运行期间新增/变更字段本期不热感知,需重启入口服务重新 init。
- 假设本期 RemoteLoader 构造的 gql 嵌套查询针对被挂服务的 SQLModel GraphQL 面(`graphql_query`),不走 UseCase GraphQL 面。
- 假设鉴权/多租户透传不在本期(联邦运行于内部可信网络)。
- 假设本期不处理远程 to-many 关系的分页(`by_<key>_in` 返回扁平列表)。
