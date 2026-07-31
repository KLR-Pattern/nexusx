# Feature Specification: nexusx 联邦分页(Federation Pagination)

**Feature Branch**: `013-federation-pagination`

**Created**: 2026-07-31

**Status**: Draft

**Input**: User description: "为 federation 引入跨服务分页能力（首期 β path / gql executor 路径的 to-many 跨服务关系分页）。模型 offset/limit；范围 β 先行、γ 不做声明式分页；控制粒度'分页决定还给 field'（RemoteRelationship.sort_field 即开关）；member 零配置双 root；wire 为 batch 级标量 page_args + per-key 分页包 + join-key 对齐；核心难点在 member executor root 路径。"（设计经多轮逐层收敛，术语见 memory `project_federation_glossary`，方向决策见 `project_federation_pagination_direction`。）

## 模型概述(五条载重决定)

1. **模型:offset/limit,与本地分页同源。** 联邦分页复用本地分页的 `PageArgs`/`Pagination` 语义,不引入 Relay cursor——被挂载服务是单一数据源、单一排序,cursor 解决的"深分页稳定分页"问题在单源 member 下不存在。

2. **范围:首期只做 β path(gql executor)的 to-many 跨服务关系分页。** γ path(Resolver/DTO)首期不做声明式分页——分页是运行时参数,不属于 DTO 的声明式投影;γ 场景需要分页时由业务方法命令式复用同一套底层取数。

3. **控制粒度:分页决定还给 field。** 分页开关是 `RemoteRelationship.sort_field` 的有无——声明 `sort_field` 即该 to-many 关系分页(且按此排序),不声明即全量(与现状一致)。这与本地 `Relationship.order_by`(order_by 存在即分页、per-relationship、缺省则全量+警告)完全对称。不引入 member 能力配置层、不引入单独 `paginate` 布尔、不需要 federate 能力校验。

4. **member 零配置双 root。** 被挂载服务默认为每个 batch key 生成两个入口:`by_<key>_in`(全量,返回扁平列表,现状)与 `by_<key>_in_page`(分页,返回 per-key 分页包)。由挂载方的 field 声明决定调哪个,member 无需预声明分页能力。

5. **wire:batch 级标量 page_args + per-key 分页包 + join-key 对齐。** 分页参数(limit/offset/sort_field)是 batch 级标量(同一批所有 key 共享,由 GraphQL 字段 args 对所有 parent 统一保证);被挂载服务返回 per-key 分页包 `[{fk, items:[entity], pagination}]`;挂载方按 join key(不依赖返回顺序)对齐成每个 parent 的 `{items, pagination}`。

## Clarifications

### Session 2026-07-31

- Q: total_count 是否总是计算返回,还是可选(客户端 select 才算)? → A: 可选,对称本地分页——客户端在 `pagination { total_count }` 里显式 select 才算 COUNT OVER;否则 member 跳过 COUNT,只返 `has_more`(peek-by-1 本就免费)。
- Q: sort_field 是否支持排序方向? → A: 支持(ASC/DESC 可选),未指定方向时默认 ASC(SQL 标准,对齐本地窗口函数行为);member 据此 `ORDER BY`。
- Q: default_page_size/max_page_size 归属? → A: 对齐本地固定默认(default 20 / max 100),`RemoteRelationship` 不带 page size 字段;客户端需不同页大小就传 `limit`。

## 背景与动机

012-federation 让任意 nexusx 服务挂载其他 nexusx 服务,客户端一条查询透明跨服务取数。但跨服务 to-many 关系(如 `Product.reviews`)当前是**无上限全量取**——RemoteLoader 对被挂服务的 `by_<key>_in` 发一条 gql,把所有匹配行全拉回来。一个热门产品若有上万条评论,一次查询就能 OOM 或拖垮链路;且无法表达"只看前 5 条"。

本地 nexusx 早有成熟的 offset/limit 分页(`PageArgs`/`PageLoadCommand`/`page_loader` + 窗口函数 per-key 分页),但那只作用于"该服务当查询入口时的本地关系"。跨服务关系走的是 RemoteLoader(发 gql),不经过本地 page_loader,所以本地分页能力到不了联邦。

本特性把本地分页的能力延伸到跨服务边界:被挂载服务暴露一个分页版 batch root,挂载方的 RemoteLoader 像使用本地 page_loader 一样使用它。核心约束:分页必须发生在数据所在的被挂载服务(member)——挂载方截断无意义(数据已全量过网且 total_count 失真)。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 跨服务 to-many 关系分页(最小可用)(Priority: P1)

作为一个把业务拆成多服务的开发者,我希望对一条跨服务 to-many 关系(如 `Product.reviews → reviews.Review`)开启分页:在声明上给定排序字段,客户端查询时带 `limit`/`offset`,只取一页数据并附分页元数据(`has_more`/`total_count`),而非全量拉回。

**Why this priority**:联邦分页的最小可用切片。验证主链路——member 分页 root + RemoteLoader 分页取数 + 挂载方对齐 + 返回 `{items, pagination}`——端到端跑通,且保住 012 招牌:对每个被挂服务仍只发一条 gql。

**Independent Test**:起 catalog(本地 `Product`) + reviews(`Review` + `by_product_id_in`),声明 `RemoteRelationship(..., sort_field="created_at")`,查 `{ product { reviews(limit:5, offset:0) { items { title } pagination { has_more total_count } } } }`,断言:只返回排序后的前 5 条、`has_more`/`total_count` 正确、reviews 服务只收到一条 gql。

**Acceptance Scenarios**:

1. **Given** reviews 有 42 条某产品的 Review,**When** 查 `reviews(limit:5, offset:0)` 按 `created_at` 排序,**Then** 返回前 5 条,`pagination.has_more = true`,`pagination.total_count = 42`。
2. **Given** 同上,**When** 查 `reviews(limit:5, offset:40)`,**Then** 返回最后 2 条,`has_more = false`,`total_count = 42`。
3. **Given** 分页查询涉及 N 个产品,**When** 执行,**Then** reviews 服务只收到**一条** gql 查询(分页 root 携带全部 N 个 key + 共享的 limit/offset/sort_field)。

---

### User Story 2 - 分页关系的 items 带嵌套子树(Priority: P1)

作为一个开发者,我希望分页的远程关系的 `items` 里能正常解析其下子关系——如分页取 `reviews` 后,每条 review 的 `comments`(reviews 本地关系)甚至 `comments.author`(再跨服务到 users)都能在同一页结果里正确返回,member 一次 gql 把分页 + 子树都解析完。

**Why this priority**:这是分页与 012 的"子树批发"协调的关键,也是整个特性风险最高的部分——它要求被挂载服务的 executor 在分页 root 返回的"per-key 分页包"上,对 `items` 里的实体递归解析子树。若不做,分页只能取裸标量,无法承载真实业务查询。

**Independent Test**:reviews 有 `Review.comments`(本地),查 `reviews(limit:5) { items { title comments { text } } }`,断言:每个分页 review 的 comments 正确解析、分页元数据不受子树影响、仍只发一条 gql。

**Acceptance Scenarios**:

1. **Given** reviews 的 `Review.comments` 是本地 to-many 关系,**When** 查分页 reviews 含 `items { comments { text } }`,**Then** 返回的前 5 条 review 各自带其 comments,结构正确。
2. **Given** `Comment.author` 进一步跨服务到 users(reviews 挂 users),**When** 查分页 reviews 含 `items { comments { author { name } } }`,**Then** author 正确解析(reviews 内部向 users 发其自己的 gql),分页仍只针对 reviews 这一层。

---

### User Story 3 - 多 parent 批量分页 + join key 对齐(Priority: P1)

作为一个开发者,我希望一次查询里多个 parent(如多个 `Product`)的同一分页关系,在一条 batch 里被 per-key 分页,且结果按 join key 正确对齐到各自的 parent——包括 join key 是 UUID/Decimal 这类跨 JSON 会变字符串的类型。

**Why this priority**:DataLoader 的批量是 nexusx 的招牌;分页必须保留它(per-key 窗口函数一次 SQL 给所有 parent 分页),且对齐必须不依赖返回顺序(012 已为 UUID/Decimal join key 踩过坑,分页包多一层结构,对齐脆弱性放大)。

**Independent Test**:N 个 Product(含 UUID 主键)查各自的 `reviews(limit:5)`,断言:每个 Product 拿到自己的前 5 条、对齐正确(UUID 不因字符串化而错配)、总查询仍是一条 gql。

**Acceptance Scenarios**:

1. **Given** 3 个 Product(id 分别 1/2/3),各有不同数量 reviews,**When** 一次查它们的 `reviews(limit:5)`,**Then** 每个 Product 拿到各自按 key 分页的结果,互不错配。
2. **Given** join key 为 UUID,**When** 同上查询,**Then** 返回的 per-key 分页包按 UUID 正确对齐到 parent(不因 UUID 在 JSON 里变字符串而失配)。

---

### User Story 4 - field 级声明 + member 零配置 + 现状零回归(Priority: P2)

作为一个开发者,我希望分页声明挂在 `RemoteRelationship.sort_field`(与本地 `Relationship.order_by` 对称),被挂载服务无需任何分页相关配置(默认生成双 root);而**没有**声明 `sort_field` 的跨服务关系,行为与 012 完全一致(全量取)。

**Why this priority**:控制模型的简洁性与向后兼容。分页是纯粹的叠加能力——不声明零变化、既有联邦测试零回归;声明方式与本地分页一致,降低学习成本。

**Independent Test**:同一联邦里,一条远程关系声明 `sort_field`(分页)、另一条不声明(全量),断言:前者返回 `{items, pagination}`,后者返回扁平列表;既有 012 测试全部通过。

**Acceptance Scenarios**:

1. **Given** 远程关系 R1 声明 `sort_field="created_at"`、R2 不声明,**When** 同时查两者,**Then** R1 返回 `{items, pagination}` 分页结构,R2 返回扁平列表(全量)。
2. **Given** 012 既有联邦测试套件,**When** 合并本特性后运行,**Then** 全部通过(未声明分页的远程关系行为不变)。

---

### User Story 5 - 启动期 fail-fast 校验(Priority: P2)

作为开发者,我希望分页相关的错配在入口服务启动期即明确报错,不留到运行时——例如:在 to-one 关系上声明分页、`sort_field` 不是被挂服务该类型的合法字段等。

**Why this priority**:延续 012 的 fail-fast 纪律。联邦的跨进程隐式契约靠启动期校验保证;分页新增一类声明(`sort_field`),其错配同样应启动期检出。

**Independent Test**:分别构造分页相关错配,启动入口服务,断言每类都抛明确错误并退出。

**Acceptance Scenarios**:

1. **Given** 在 to-one 远程关系(target 为裸 `RemoteRef`,非 `list[...]`)上声明 `sort_field`,**When** 启动,**Then** 失败,指明分页仅适用于 to-many。
2. **Given** 声明的 `sort_field` 不是被挂服务该类型的标量字段,**When** 启动,**Then** 失败,指明非法排序字段。

---

### Edge Cases

- **offset 超出总数**:返回空 `items` + `has_more=false` + `total_count` 仍为真实总数。
- **parent 在该关系下无匹配 children**:`items=[]`、`total_count=0`、`has_more=false`(不报错)。
- **最后一页不满 `limit`**:返回剩余条数,`has_more=false`。
- **join key 为 UUID/Decimal**:对齐按 join key 字面值匹配,不因 JSON 字符串化失配(沿用 012 的 `_normalize_join_key`)。
- **客户端不传 `limit`**:声明了 `sort_field` 的关系字段类型固定为分页形状,用 `default_page_size`(对齐本地默认 20)。
- **客户端不请求 `total_count`**:member 不执行 COUNT OVER,`pagination` 只含 `has_more`(省大表成本,对称本地 `pagination_selection`)。
- **to-one 关系声明分页**:启动期 fail-fast(US5)。
- **嵌套分页**(分页关系下还有分页关系,如分页 reviews 里每条 review 的 comments 也分页):本期支持 member 内部的本地嵌套分页(被挂服务自己 executor 的既有能力);跨服务嵌套(分页 reviews 下的远程 author)在本期范围内(US2 场景 2),深层组合的代价待 plan 评估。
- **被挂服务运行期变更排序字段**:本期不热感知,重启入口服务重新 init(同 012 假设)。

## Requirements *(mandatory)*

### Functional Requirements

#### 声明与控制(field 级)

- **FR-001**(sort_field 即分页开关):`RemoteRelationship` MUST 增加可选 `sort_field`(携带可选排序方向,默认 ASC)。声明 `sort_field` 的 to-many 远程关系 MUST 走分页(按该字段 + 方向排序 + 返回分页形状);未声明的 MUST 保持 012 的全量取行为。语义 MUST 与本地 `Relationship.order_by`(order_by 存在即分页)对称。`RemoteRelationship` 仅新增 `sort_field` 一个分页字段;`default_page_size`/`max_page_size` 复用本地固定默认(20/100),不暴露 per-relationship 覆盖(对齐本地)。
- **FR-002**(仅 to-many):`sort_field` MUST 仅对 to-many(`target=list[...]`)远程关系有效;在 to-one 上声明 MUST 启动期 fail-fast。
- **FR-003**(member 零配置双 root):被挂服务 MUST 默认为每个 batch key 同时生成 `by_<key>_in`(全量)与 `by_<key>_in_page`(分页)两个入口 root,无需额外配置;挂载方据远端声明决定调哪个。

#### wire 契约

- **FR-004**(分页 root 签名):member 的分页 root MUST 形如 `by_<key>_in_page(<key>_list, limit, offset, sort_field)`,其中 `limit`/`offset`/`sort_field` 为 batch 级标量(同一批所有 key 共享同一组分页参数)。`sort_field` MUST 携带排序方向(或附独立方向参数),member 据此 `ORDER BY`;未声明方向时默认 ASC。
- **FR-005**(per-key 分页包返回):member 分页 root MUST 返回 per-key 分页包列表 `[{fk, items:[entity], pagination:{has_more, total_count?}}]`,每个包对应一个输入 key。`total_count` MUST 仅在客户端 selection 显式请求时计算(对称本地 `pagination_selection`);未请求时 member MUST NOT 执行 COUNT OVER,只返 `has_more`(peek-by-1 本就免费)。
- **FR-006**(join-key 对齐):挂载方 RemoteLoader MUST 按 join key(不依赖返回顺序)把 per-key 分页包对齐到各 parent,缺失映射为 `{items:[], pagination:{has_more:false, total_count:0}}`。

#### member 端执行(核心能力)

- **FR-007**(member executor 支持分页 root 返回):被挂服务的 executor MUST 能执行分页 root——认识其返回的 per-key 分页包,对每个包的 `items` 里的实体递归解析子树(本地关系 + 进一步跨服务 hop),并把 `pagination` 元数据原样透传。MUST NOT 要求分页 root 的 `items` 只能是裸标量。
- **FR-008**(per-key 窗口函数分页):member 分页 root MUST 用按 join key 分区(`PARTITION BY fk`)、按 `sort_field` 排序的窗口函数,一次查询给所有输入 key 各自分页;`has_more` 用 peek-by-1(取 limit+1 行判定),`total_count` 用分区计数。

#### mounter 端执行

- **FR-009**(β path 分页分流):挂载方 executor 在解析远程 to-many 关系时,MUST 检测该关系是否声明了 `sort_field`(分页),据此分流到分页 RemoteLoader 或全量 RemoteLoader。
- **FR-010**(page_args 透传):挂载方 MUST 把从客户端 gql 解析得到的 `limit`/`offset`(及声明的 `sort_field`)作为 batch 级标量透传给分页 RemoteLoader,再经 wire 传给 member。
- **FR-011**(分页与子树批发协调):分页发生在跨服务边界关系;其下子树(被挂服务的本地关系、进一步跨服务 hop)MUST 在同一次 member gql 的 `items` 内由被挂服务解析,不破坏 012 的"每服务一次批量"。

#### 校验(fail-fast,init 期)

- **FR-012**(分页相关启动校验):挂载方初始化时 MUST 对声明了 `sort_field` 的远程关系校验:(a) 关系是 to-many;(b) `sort_field` 是被挂服务该类型的合法标量字段。任一失败即拒绝启动。

#### 透明性 / 渲染

- **FR-013**(分页字段 schema 形状):声明了 `sort_field` 的远程 to-many 关系,其对外 GraphQL schema 形状 MUST 为分页结果类型(`{items:[...], pagination:{has_more, total_count}}`),与本地分页关系的渲染一致,使客户端能发现并查询。

### Key Entities *(include if feature involves data)*

- **分页远程关系**:声明了 `sort_field` 的 to-many `RemoteRelationship`,对客户端表现为 `{items, pagination}` 形状字段。
- **member 分页 root(`by_<key>_in_page`)**:被挂服务默认生成的分页批量入口,接收 keys + batch 级分页参数,返回 per-key 分页包。
- **per-key 分页包**:member 分页 root 的返回单位 `{fk, items:[entity], pagination}`,供挂载方按 join key 对齐。
- **分页 RemoteLoader**:挂载方侧消费分页 root 的 DataLoader,把 keys + page_args 转成一条分页 gql,按 join key 对齐成各 parent 的 `{items, pagination}`。
- **batch 级 page_args**:`limit`/`offset`/`sort_field` 三个标量,同一次 batch 内所有 key 共享(由 GraphQL 字段 args 对所有 parent 统一保证)。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**(分页正确性):声明 `sort_field` 的远程 to-many 关系,`limit`/`offset` 分页返回的条数、顺序、`has_more`、`total_count` 全部正确(含 offset 越界、最后不满页、空页)。
- **SC-002**(每服务一次批量不破):分页查询下,被挂服务仍只收到**一条** gql(分页 root 携带全部 keys + 共享分页参数),不在网络层产生逐层 N+1。
- **SC-003**(join-key 对齐正确):多 parent 批量分页的结果按 join key 正确对齐到各 parent,UUID/Decimal 等 join key 不因跨 JSON 字符串化而错配。
- **SC-004**(现状零回归):未声明 `sort_field` 的远程关系行为与 012 完全一致;既有 012 联邦测试套件合并后全部通过;单体 nexusx 全量测试零回归。
- **SC-005**(分页 + 子树):分页关系的 `items` 内的本地/跨服务子关系正确解析,分页元数据不受子树影响。
- **SC-006**(fail-fast):to-one 声明分页、`sort_field` 非法等错配在启动期检出并拒绝,无一例进入运行时。

## 关键设计决定与取舍论证

1. **为什么是 offset/limit,不用 Relay cursor。** 被挂载服务是单一数据源、单一排序,offset 天然可重建;cursor 解决的"多源/深分页稳定分页"问题在单源 member 下不存在。复用本地 `PageArgs`/`Pagination` 语义,挂载方、被挂方、客户端零额外学习成本,且本地分页的窗口函数/序列化代码直接复用。

2. **为什么分页开关是 `sort_field` 的有无(field 级)。** 分页必须稳定排序——"有 sort 才能分页",故 sort 的存在是分页的天然前提,用它的有无当开关语义自洽,且不需要额外布尔。这与本地 `Relationship.order_by`(order_by 存在即分页、per-relationship)完全对称,本地/联邦控制模型统一。分页是**关系的属性**,不是 entity 的属性、不是全局开关——一个 entity 的三个 to-many 关系可各自独立决定分不分页。

3. **为什么 member 零配置双 root,不引入能力配置层。** 让被挂服务默认生成全量 + 分页两个 root,使"分页决定"完全落在挂载方的 field 声明上。这消除了"member 能力声明 + federate 能力校验"一整层,且不会出现"挂载方要分页但 member 没能力"的错配(member 总有能力)。代价:member schema 每个批量入口多一个分页 root(无害,不被调用即不执行)。

4. **为什么 γ path 首期不做声明式分页。** γ 是 DTO 驱动(代码组装),没有客户端 gql args;分页是运行时参数,塞进静态 DTO 投影会让 DTO 从"字段投影"变质成"带参数查询"。γ 场景需要分页时,由业务方法签名带 limit/offset、命令式复用 β 建的同一套底层(member 分页 root + 分页 RemoteLoader)。DTO 投影抽象保持纯粹。

5. **为什么 page_args 是 batch 级标量,不是 per-key。** GraphQL 字段 args 对所有 parent 统一——同一 `reviews(limit:5)` 字段对所有 Product 都是 limit:5,故同一次 batch 所有 key 共享同一组分页参数,member 用 `PARTITION BY fk` + 统一 `LIMIT/OFFSET` 一次给所有 key 分页。不同分页参数的需求由挂载方的 selection-based loader 隔离(012 既有机制)拆成不同 batch。

6. **为什么难点在被挂服务的 executor root 路径。** 本地分页的全部机制(取分页包 → items 进 BFS 递归 → 序列化识别分页形状)都写在 executor 的"关系路径"上(被 executor 内部直接调用的 page_loader);而联邦 member 分页发生在"root 路径"(member 收到的是 `by_<key>_in_page` 这个 gql root 请求),root 路径目前只认"root 返回 entity/list",不认识分页包、不能对 `items` 递归。难点不是发明新机制,是把关系路径已有的分页递归推广到 root 路径——这动了 executor 的 entity-centric 抽象,是整个特性风险最高处,plan 阶段须单列且优先用最小切片验证。

7. **为什么护栏独立于分页协议,且首期不做。** 分页协议(`{items, pagination}` + 翻页)是 opt-in 的能力;护栏(防全量 list 的 DoS)是另一层,不应绑定。未声明 `sort_field` 的远程关系本期仍全量取(沿用 012),护栏(参考 Apollo Demand Control 的 cost-based 拒绝,优于 size 截断——拒绝返完整错误优于截断返残缺数据)作为后续独立特性。两者解耦:护栏保护所有 to-many(含未分页的),分页协议提供翻页能力。

## Assumptions

- 假设联邦基础(012-federation)已实现并可工作;本特性建立在其 RemoteLoader / RemoteRelationship / ER 内省 / 物化类型之上。
- 假设分页模型为 offset/limit(与本地分页同源);Relay cursor 不在本期。
- 假设首期只做 β path(gql executor)的 to-many 跨服务关系分页;γ path(Resolver/DTO)声明式分页不在本期(业务方法命令式复用底层)。
- 假设被挂服务为 nexusx 服务,默认生成双 root(全量 + 分页),无需额外配置。
- 假设声明了 `sort_field` 的远程关系字段类型固定为分页形状(`{items, pagination}`);客户端不传 `limit` 时用 `default_page_size`(对齐本地默认 20),`max_page_size` 固定 100 作硬上限(对齐本地);`RemoteRelationship` 不暴露 page size 字段。
- 假设护栏(防全量 list 的 DoS,倾向 cost-based 拒绝)为后续独立特性,不在本期;未声明分页的远程关系本期仍全量取。
- 假设跨服务 join 为单字段(沿用 012);join key 类型兼容性(含 UUID/Decimal 字符串化对齐)沿用 012 既有处理。
- 假设被挂服务运行期变更排序字段本期不热感知,需重启入口服务重新 init(同 012)。
- 假设鉴权/多租户透传不在本期(沿用 012,联邦运行于内部可信网络)。
