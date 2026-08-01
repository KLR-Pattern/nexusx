# Design Decisions

**特性**:`specs/014-federation-order-direction` | **日期**:2026-08-01 | **Spec**:[spec.md](./spec.md)

本文记录把 order 选择权下放到查询期、开放 direction 的关键决策。每条以 **Decision / Rationale / Alternatives** 呈现。所有决策已与用户 4 轮讨论确认，零待澄清。

---

## D1. order 选择权下放到查询期（方案乙）

**Decision**:order profile 由查询者在 GraphQL 查询参数里挑（`reviews(order: ..., direction: ...)`），mounter 把 member 暴露的 profile 集合渲染成 schema 的 order enum 并透传给 member；`RemoteRelationship.order` 部署期静态字段废弃。

**Rationale**:013 把 order 在部署期写死（`RemoteRelationship.order`），同一条关系只能给一种排序，无法适应多变查询场景（最高评分 / 最新 / 升序）。下放查询期让一条路径出多排序，且 order 仍是 member 批准的封闭集合（不是任意 field），索引控制权不丢。

**Alternatives**:
- 维持 013 部署期静态选（方案甲）+ 只开放 direction —— 放弃「查询期挑 profile」的灵活性，否决。
- 开放任意 sort field —— 客户端可 order by 无索引列，member 索引失控，否决（见 D2）。

---

## D2. 开放方向，不开放 field

**Decision**:查询者可传 `direction`(ASC/DESC) 翻转排序，但 sort field 封闭（只能在 member profile 集合里选名字）。

**Rationale**:B-tree 索引天然双向，翻转方向通常仍走索引，风险低；而开放任意 field = 客户端能 order by 无索引列 → 窗口函数 + 全表排序，member 被打慢。索引控制权是 013 的核心不变量，本特性不破坏它。要更多排序由 member 多暴露 profile。

**Alternatives**:
- 同时开放 field + direction —— 索引失控，否决。
- direction 也封闭（纯静态）—— 放弃灵活性，否决。

---

## D3. 单列 profile

**Decision**:`PageOrder` 限定恰好一个 `OrderTerm`（单列排序）；多列复合 profile 在 member 启动期校验拒绝。

**Rationale**:direction 翻转在单列下语义干净（翻那一个 term 的方向 + nulls）。多列复合排序的「全翻 / 部分翻」有歧义（如 `[rating desc, created_at desc]` 翻成 `[rating asc, created_at ?]`?）。单列消除歧义。要复杂排序由 member 多暴露单列 profile。

**Alternatives**:
- 允许多列 + 定义「全翻」语义 —— 啰嗦且反直觉（用户通常只想翻主列），否决。
- 允许多列 + 逐 term 显式 direction —— 复杂度重回 013 早期被否的方案，否决。

---

## D4. direction 翻转 nulls 跟随

**Decision**:查询者传 direction 覆盖 profile 默认方向时，nulls 跟随翻转：`desc + nulls_last` ↔ `asc + nulls_first`。

**Rationale**:「翻转」的直觉是「完全相反」。NULL 位置跨方言易错（SQLite/Postgres/MySQL 默认不同），013 强制 nullable 列声明 nulls 就是为了消除方言差异；翻转时同步翻 nulls 保持这一不变量。翻转后的 terms 同时用于 window 内层与 outer（沿用 013 的稳定排序约束）。

**Alternatives**:
- nulls 不变（desc+nulls_last 翻成 asc+nulls_last）—— 「方向翻了但 NULL 没翻」语义混乱，否决。
- member 逐 profile 显式定义翻后 nulls —— 最灵活但最啰嗦，单列场景没必要，否决。

---

## D5. 只做 β 路径

**Decision**:本期仅支持 β 路径（GraphQL 直查 mounter，executor 遇分页关系走 RemoteLoader）。γ 路径（Resolver/UseCase 业务代码组装）选 order 不在本期。

**Rationale**:β 是 federation 的主路径（嵌套 gql 查询），覆盖绝大多数用例。γ 路径选 order 需要 Resolver 侧另设入口，会膨胀本期范围。先做 β 验证主链路，γ 留后续。

**Alternatives**:
- β + γ 同期做 —— 范围失控，否决。

---

## D6. RemoteRelationship.order 直接删除（不 deprecate）

**Decision**:`RemoteRelationship.order` 字段作 API 删除，不保留 deprecation 迁移期。

**Rationale**:federation 是新功能（013 刚落、未广泛使用），无外部兼容包袱。order 改由查询参数决定后，静态字段与查询参数会双源冲突，必须删。用户明确「完整新功能、没有向后兼容需要」。

**Alternatives**:
- 保留 order 作「默认 fallback」—— 双源语义含糊（查询参数覆盖？还是静态优先？），且 federation 无兼容需求，否决。

---

## D7. 跨服务 enum 一致性靠 orders 集合（单一数据源）

**Decision**:mounter 渲染的 order enum 值 = member `BatchPageCapability.orders` 的名集合（同一份 wire 数据）；enum 类型名由 mounter 自定。gql 传值不传名，mounter 与 member 的 enum 名不必一致。

**Rationale**:`BatchPageCapability.orders`（013 已有）已经是 profile 名集合的唯一来源。mounter 据此渲染 enum，值天然与 member 一致（都源自同一 wire）。enum 名是 mounter schema 内部标识，不影响值传递。无需在 contract 加新字段。

**Alternatives**:
- contract 加 `order_enum_name` 让 mounter 复用 member 的 enum 名 —— 没必要（值一致就够），否决。

---

## 研究结论

七条决策全部落地，无阻塞性未知。主要技术风险：
- **direction 翻转的 window/outer 一致性**（D4）—— 沿用 013 的「内层与 outer 同 terms」约束，翻转在 `_build_order_expressions` 之前对 terms 一次性完成，天然一致。
- **跨服务 enum 一致性**（D7）—— 单一数据源（orders），值层面一致。

其余（member direction 参数、RemoteLoader 去 bake、RelationshipInfo.page_capability、SDL 渲染）为常规新增/接线，路径明确。
