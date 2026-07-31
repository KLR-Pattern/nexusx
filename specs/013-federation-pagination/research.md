# Research: 联邦分页(Federation Pagination)

关联:[spec.md](./spec.md)、[plan.md](./plan.md)。本文记录 9 条关键技术决策的核实——决策、理由、被否备选。设计经多轮逐层收敛(模型 → 范围 → 控制粒度 → wire → 难点 → 护栏),每条均有明确结论。

## R1: 分页模型——offset/limit vs Relay cursor

- **Decision**:offset/limit,复用本地分页 `PageArgs`/`Pagination` 语义。
- **Rationale**:被挂载服务是单一数据源、单一排序,offset 天然可重建;cursor 解决的"多源/深分页稳定分页"问题在单源 member 下不存在。复用本地语义,挂载方/member/客户端零额外学习,本地窗口函数与序列化代码直接复用。
- **Alternatives**:Relay cursor(first/after + Connection/Edge/PageInfo)——否。需新定义 cursor 编解码、Connection 类型,与本地 offset 模型割裂、双轨维护;它解决的稳定性问题在本场景(单源 member)不存在,属过度设计。

## R2: 分页开关——sort_field 的有无 vs paginate 布尔

- **Decision**:`RemoteRelationship.sort_field` 的有无即分页开关(声明→分页+排序;不声明→全量)。
- **Rationale**:分页必须稳定排序——"有 sort 才能分页",故 sort 的存在是分页的天然前提,用其有无当开关语义自洽,免额外布尔。与本地 `Relationship.order_by`(order_by 存在即分页、per-relationship)完全对称,本地/联邦控制模型统一。分页是**关系的属性**,不是 entity 属性、不是全局开关。
- **Alternatives**:单独 `paginate=True` 布尔——否,冗余(paginate=True 仍须指定 sort,两字段耦合);全局 `enable_pagination`——否,本地经验表明 per-relationship 粒度才正确(混合共存:同 entity 的不同 to-many 可各自分页/全量)。

## R3: member 端——零配置双 root vs 能力配置层

- **Decision**:member 默认为每个 batch key 同时生成全量 root(`by_<key>_in`)与分页 root(`by_<key>_in_page`),零配置;"分页决定"完全落在挂载方 field 声明。
- **Rationale**:消除"member 能力声明 + federate 能力校验"一整层;member 总具备分页能力,不会出现"挂载方要分页但 member 没能力"的错配。代价仅是 member schema 每批量入口多一个 root(不被调用即不执行,无害)。
- **Alternatives**:`AutoQueryConfig.paginated_batch_keys` 让 member 显式声明分页能力——否,多一层配置 + 一类校验,且 member 无法预知谁会分页它;违反"分页决定还给 field"的收敛方向。

## R4: 核心难点——member executor root 路径改造

- **Decision**:让 member executor 的 root 执行路径认识分页 root 返回的 per-key 分页包,对 `items` 里的实体递归 BFS 解析子树、序列化 `{items, pagination}`;本质是把本地分页在"关系路径"(`_load_field_paginated` 的 `all_children.extend(items)` + `_serialize_relationship_value` 识别分页形状)已有的机制,推广到"root 路径"。
- **Rationale**:本地分页全部机制写在关系路径(被 executor 内部直接调用的 page_loader);联邦 member 分页发生在 root 路径(member 收到 `by_<key>_in_page` 这个 gql root 请求),而 root 路径目前 entity-only(假设 root 返回 entity/list),不认识分页包、不能对 items 递归。不改则分页只能取裸标量,无法承载真实查询(US2 不成立)。
- **Alternatives**:① mounter 端截断——否,数据已全量过网、total_count 失真,违背"分页在 member";② member root method 自己解析子树——否,root method 拿不到完整 selection(不知道客户端要 comments 的哪些字段)、重复实现 BFS;③ 让 root 返回扁平 list 由 mounter 重分组——否,丢 per-key 分页边界、LIMIT/OFFSET 无法 per-key。
- **风险与缓解**:动 executor 的 entity-centric 抽象,是整个特性风险最高处。缓解:(a) 仅当 root 返回分页包时走分治,非分页 root(`by_filter`/`by_id`/全量 `by_<key>_in`)零影响;(b) US1 最小切片(单 key + 标量 items,不递归)优先验证识别与对齐,再开 items 子树递归;(c) 专项单测覆盖 per-key 包识别、items 递归、pagination 透传。

## R5: page_args——batch 级标量 vs per-key

- **Decision**:`limit`/`offset`/`sort_field` 是 batch 级标量,同一次 batch 所有 key 共享同一组。
- **Rationale**:GraphQL 字段 args 对所有 parent 统一——同一 `reviews(limit:5)` 字段对所有 Product 都是 limit:5,故同一次 batch 必然共享。member 用 `PARTITION BY fk` + 统一 `LIMIT/OFFSET` 一次给所有 key 分页。与本地 `PageLoadCommand`(同 batch 共享 PageArgs)语义一致。
- **Alternatives**:per-key args 列表——否,GraphQL 不支持 per-instance 字段 args;不同分页参数的需求由挂载方 selection-based loader 隔离(012 既有 `generate_type_key_from_selection` + `force_split`)拆成不同 batch。

## R6: total_count——可选 vs 总返回

- **Decision**:`total_count` 仅在客户端 selection 显式请求时计算(对称本地 `pagination_selection`);不请求时 member 不算 `COUNT OVER`,只返 `has_more`。
- **Rationale**:`COUNT(*) OVER(PARTITION BY fk)` 在大表上贵;`has_more` 用 peek-by-1(取 limit+1 行)本就免费;对称本地分页的既有行为。
- **Alternatives**:① 总返回 total_count——否,每次分页都付 COUNT 成本;② 完全不支持——否,客户端常需总数(分页 UI)。

## R7: join-key 对齐——按 key vs 按顺序

- **Decision**:挂载方按 join key(不依赖返回顺序)把 per-key 分页包对齐到各 parent;UUID/Decimal join key 沿用 012 `_normalize_join_key` 的字符串化处理。
- **Rationale**:012 已踩坑(UUID/Decimal 跨 JSON 变字符串,`UUID("x") != "x"` 导致静默错配);分页包比扁平 list 多一层结构,对齐脆弱性放大,必须按 key 而非顺序。
- **Alternatives**:按返回顺序对齐——否,Apollo 官方把"entity 顺序错配=静默数据错"列为头号风险;nexusx 按 key 分桶天然规避。

## R8: γ path——不做声明式分页

- **Decision**:γ(Resolver/DTO)首期不做声明式分页;γ 场景需要分页时由业务方法签名带 limit/offset、命令式复用 β 建的同一套底层(member 分页 root + 分页 RemoteLoader)。
- **Rationale**:分页是运行时参数,塞进静态 DTO 投影会让 DTO 从"字段投影"变质为"带参数查询",破坏 DTO 投影的纯粹性;γ 是代码驱动,没有客户端 gql args,分页最自然的归宿是业务方法参数(命令式)。
- **Alternatives**:为 DTO 发明"带参数的投影声明语言"(如 `Page[list[ReviewDTO], limit=5]`)——否,设计成本高、破坏 DTO 抽象、与本地无对应物;β 与 γ 共享数据获取层已足够(只差意图表达:β=gql args 自动,γ=方法参数显式)。

## R9: 护栏——独立于分页协议,首期不做

- **Decision**:护栏(防全量 list 的 DoS,倾向 cost-based 拒绝)独立于分页协议,首期不做;未声明 `sort_field` 的远程关系本期仍全量取(沿用 012)。
- **Rationale**:分页协议(`{items, pagination}` + 翻页)是 opt-in 能力;护栏保护**所有** to-many(含未分页的),是另一层关切,不应绑定。Apollo 的 Demand Control(`@cost`/`@listSize` + 总成本上限拒绝)是其企业付费功能,nexusx 可后续做进开源核心(差异化)。
- **Alternatives**:① 首期含 size 截断护栏(max_page_size 硬切)——否,截断返回残缺数据(客户端不知情),cost-based 拒绝(返完整错误)更正确但需成本模型,超本期范围;② 默认开启分页协议护栏——否,改变返回形状、破坏兼容(参见 spec 关键设计决定 #7)。

---

**结论**:9 条决策全部收敛,无 NEEDS CLARIFICATION 残留。最高风险集中在 R4(member executor root 路径),实现须用 R4 的缓解策略(最小切片优先 + 专项单测 + 非分页 root 零影响隔离)。
