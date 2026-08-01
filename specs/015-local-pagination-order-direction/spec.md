# Feature Specification: 本地分页 order/direction

**Feature Branch**: `015-local-pagination-order-direction`

**Created**: 2026-08-01

**Status**: Draft

**建立在**: `specs/014-federation-order-direction` 之上

**Input**: User description: "让 member 本地分页（enable_pagination 开启的本地 list 关系，如 Review.comments）支持查询期 order/direction 选择，达到与 federation 分页（specs/013/014）同等的灵活度。"

## 背景与动机

014 把 federation 分页的 order/direction 选择权下放到查询期：member 定义 order profile 集合，查询者经 GraphQL 参数选 profile + 翻 direction。但这个能力**只在 federation 跨服务分页（`RemoteRelationship(pagination=True)`）那层有**。

本地分页（`enable_pagination=True` 开启的本地 list 关系，如 `Review.comments`）走的是另一套 loader，排序固定（`Relationship.order_by` → 单字段 `sort_field`），查询者只能传 `limit/offset`，既不能选 order、也不能翻 direction。

问题：同一条本地一对多关系（如评论列表），有时要"最新"、有时要"最赞"、有时要升序——目前只能改 `order_by` 重新部署，或 member 为每种排序声明多个关系。这与 federation 分页的灵活度不对等。

本特性把 **federation 分页已有的排序内核抽成 federation 与本地分页共享的 core**，让本地 page_loader 接上去，使本地分页关系也支持查询期 order/direction。

## 模型概述（两条决策）

1. **排序内核统一为 shared core。** 把 federation 已有的排序数据结构（`PageOrder`/`OrderTerm`）、排序构建（`_build_order_expressions`）、方向翻转（`_apply_direction`，含 nulls 跟随）、schema 渲染（order enum + direction）抽成 federation 与本地分页共同调用的内核。federation 分页与本地分页成为这个内核的两个应用，而非两套并行机制。

2. **本地关系声明 order profile 集合。** 本地 list 关系扩展声明 order profile 集合 + default profile；查询者经 GraphQL 参数选 profile + direction。未配 profile 的本地关系维持现状（固定 `order_by`），向后兼容。

## Clarifications

### Session 2026-08-01

- Q: 本地分页关系的 order profile 集合在哪里声明？ → A: 扩展 `Relationship` 加 `page_orders`/`default_page_order` 字段（与现有 `order_by` 同处声明）。
- Q: profile 与 order_by 同时存在怎么处理？ → A: profile 优先；未配 profile 时 `order_by` 作为固定排序兜底（向后兼容）。
- Q: shared core 抽取后 federation 声明与本地声明是否统一？ → A: 底层共享（`PageOrder`/`OrderTerm` + `_build_order_expressions`/`_apply_direction`/渲染），容器分开（`BatchPageConfig` 给 federation root，本地关系用类级声明）。

### Session 2026-08-02（实现期修正）

- Q(实现期发现): 原"扩展 `Relationship.page_orders`"方案实测不可行——本地分页用的是 SQLModel **ORM** `Relationship`（`from sqlmodel import Relationship`，参数固定，`page_orders` kwarg 报 `TypeError`），不是可扩展的 nexusx custom `Relationship`。 → A: 改为**类级 `__pagination_orders__: dict[str, BatchPageConfig]`**（key = ORM relation 名），声明在实体类上，ErManager 启动期读取、按 relation 名关联 ORM relationship。**FR-001 与"关键设计决定 2"据此修正，以本条为准。**

## User Scenarios & Testing *(mandatory)*

### User Story 1 — 查询者为本地分页关系挑 order profile + direction (Priority: P1)

作为一个查 nexusx 服务的客户端开发者，我希望对本地分页关系（如 `Review.comments`）传 `order` 和 `direction`，这样同一条关系能拿到不同排序（最新/最赞/升序/降序），不用 member 改 `order_by` 重新部署。

**Why this priority**: 本特性的核心增量——把 order 选择权从部署期搬到查询期，对本地分页。验证主链路：查询参数 → executor 透传 → 本地 page_loader 按 profile + direction 排序 → 正确结果。

**Independent Test**: 起 member（开 `enable_pagination`，`Review.comments` 配 `NEWEST`/`MOST_LIKED` 两个 profile），分别查 `comments(order: MOST_LIKED, direction: DESC)` 和 `comments(order: NEWEST, direction: ASC)`，断言两次结果排序不同且各自正确。

**Acceptance Scenarios**:

1. **Given** `Review.comments` 配 `MOST_LIKED` profile，**When** 查询者传 `order: MOST_LIKED, direction: DESC`，**Then** items 按 `MOST_LIKED` 的列 desc 排序。
2. **Given** 同关系，**When** `direction: ASC`，**Then** items 按该列 asc（与 DESC 严格相反）。
3. **Given** 同关系，**When** `order: NEWEST`，**Then** items 按 `NEWEST` profile 排（与 `MOST_LIKED` 不同）。

---

### User Story 2 — member 开发者声明本地关系的 order profile 集合 (Priority: P1)

作为一个 member 开发者，我希望在声明本地一对多关系时配一组命名的 order profile，框架自动把 profile 集合渲染成 GraphQL `order` enum + `direction` 参数，客户端从 schema 能发现这些选项——无需手写 enum。

**Why this priority**: 机制核心——profile 集合 → schema enum。没有这条，查询者无 enum 可挑。

**Independent Test**: `Review.comments` 配 `{NEWEST, MOST_LIKED}` 后取 SDL + `__schema` 内省，断言 `comments` 字段有 `order` 参数（enum 含两个 profile 名，默认 = default profile）和 `direction` 参数（ASC/DESC）。

**Acceptance Scenarios**:

1. **Given** `Review.comments` 暴露 `{NEWEST, MOST_LIKED}`，**When** 取 SDL，**Then** `comments` 字段签名含 `order: <XxxOrder>`（enum 值 = 两个 profile 名）。
2. **Given** 同上，**Then** `comments` 字段含 `direction: Direction`（ASC, DESC）。
3. **Given** `default_profile=NEWEST`，**Then** `order` 参数默认值 = NEWEST。
4. **Given** `__schema` 内省，**Then** 与 SDL 暴露一致（两条渲染路径同源）。

---

### User Story 3 — direction 翻转时 nulls 跟随 (Priority: P2)

作为一个查询者，我希望传 direction 翻转排序时 NULL 位置语义正确（desc 时 NULL 在末尾，asc 时在开头），不出现 NULL 错乱。沿用 014 语义。

**Why this priority**: direction 翻转的正确性细节。NULL 排序跨方言易错。

**Independent Test**: member 定义一个 nullable 列的 profile（desc + nulls_last），分别查 desc 与 asc，断言 NULL 在 desc 末尾、asc 开头。

**Acceptance Scenarios**:

1. **Given** profile `RATING`（rating desc, nulls_last），**When** `direction=DESC`，**Then** NULL rating 在末尾。
2. **Given** 同上，**When** `direction=ASC`，**Then** rating asc 且 NULL 在开头（nulls_last → nulls_first）。

---

### Edge Cases

- **order 参数缺省**: 查询者不传 `order` → 用 member 的 default profile。
- **direction 参数缺省**: 不传 `direction` → 用 profile 定义的默认方向。
- **member 暴露的 profile 集合为空**: 启动期 fail-fast（无 enum 可渲染）。
- **查询者传未暴露的 order 名**: GraphQL enum 校验拒绝，不进 loader。
- **没配 profile 的本地分页关系**: 维持现状（固定 `order_by`，`comments(limit, offset)` 无 order/direction 参数），向后兼容。
- **本地分页关系既配 profile 又有 order_by**: profile 优先接管排序；`order_by` 仅在未配 profile 时作为固定排序兜底（向后兼容，FR-003）。
- **federation 分页 × 本地分页 order 同时存在**: 外层 `RemoteRelationship` 的 order/direction 与内层本地关系的 order/direction 各自独立解析（5.0.1 已让两者能叠加；本特性让内层也有 order/direction）。

## Requirements *(mandatory)*

### Functional Requirements

#### 声明（member 侧）

- **FR-001**（本地关系 order profile 声明）: 系统 MUST 通过扩展 `Relationship`（加 `page_orders: dict[str, PageOrder]` + `default_page_order: str` 字段）让本地 list 关系声明 order profile 集合 + default profile，复用 `PageOrder`/`OrderTerm`（与 federation 分页同源）；声明与现有 `order_by` 同处。
- **FR-002**（profile 校验）: member 启动期 MUST 校验每个 profile：名是 enum-safe 大写且唯一；含 `OrderTerm`（field 是普通 SQL column、非 JSON/BLOB）；direction ∈ {asc, desc}；nullable 字段 MUST 显式 `nulls`；default profile 在集合内。沿用 013/014 的校验。
- **FR-003**（向后兼容）: 未声明 profile 的本地分页关系 MUST 维持现状（固定 `sort_field`，`comments(limit, offset)` 无 order/direction 参数）。

#### schema 渲染

- **FR-004**（渲染 order enum + direction）: 声明了 profile 的本地分页关系，其字段 MUST 渲染为 `comments(limit, offset, order: <Enum>, direction: Direction)`，`order` enum 值 = profile 名集合、默认 = default profile；`direction` enum = {ASC, DESC}。SDL 与 `__schema` 内省两条路径同源。
- **FR-005**（复用 federation 渲染）: 上述渲染 MUST 复用 federation 分页已有的 order enum + direction 渲染逻辑（shared core），而非新写一套。

#### 执行（page_loader）

- **FR-006**（profile + direction 驱动排序）: 本地 page_loader MUST 按查询者选的 profile + direction 构建排序表达式（复用 `_build_order_expressions` + `_apply_direction`），而非固定 `sort_field`。
- **FR-007**（nulls 跟随翻转）: direction 翻转时 nulls MUST 跟随（desc+nulls_last ↔ asc+nulls_first），沿用 014；窗口内层与外层 order 表达式一致。
- **FR-008**（稳定 tie-breaker）: 未含的主键列 MUST 按确定性方向追加为稳定 tie-breaker（沿用 013/014）。
- **FR-009**（per-query 参数透传）: executor MUST 从查询 `selection.arguments` 读取 `order`/`direction`，透传给本地 page_loader（同一 batch 内 order/direction 相同）。

#### 边界

- **FR-010**（单列约束沿用）: 本期 profile 单列排序约束沿用 014（多列 profile 启动期拒绝）。
- **FR-011**（federation × 本地叠加）: 本特性 MUST 与 5.0.1 的 federation items 子树本地分页叠加兼容：内层本地分页关系的 order/direction 不破坏外层 federation 分页。

### Key Entities

- **order profile**: member 定义的一个语义排序（单列：一个 field + 默认 direction + nulls），唯一 enum-safe 大写名。查询者按名引用。复用 `PageOrder`/`OrderTerm`。
- **direction**: 查询者传的排序方向（ASC/DESC），覆盖 profile 默认方向；翻转时 nulls 跟随。复用 `Direction` enum。
- **本地 page_loader**: 改造成按 profile + direction 排序（而非固定 `sort_field`）的 per-parent 分页 loader。
- **shared core**: 抽出的共享排序内核（`PageOrder`/`OrderTerm`/`_build_order_expressions`/`_apply_direction`/渲染），federation 分页与本地分页共同调用。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 同一本地分页关系，查询者传 `direction: DESC` 与 `direction: ASC`，返回 items 排序严格相反（含 NULL 位置正确）。
- **SC-002**: 查询者传不同 `order` profile，返回 items 按各 profile 列排序，结果不同且正确。
- **SC-003**: member 的 SDL 与 `__schema` 内省都暴露 `order`（enum = profile 名集合）+ `direction`（ASC/DESC），两者字段集一致。
- **SC-004**: 未配 profile 的本地分页关系行为不变（向后兼容，既有本地分页测试零回归）。
- **SC-005**: federation 分页（`Product.reviews`）的 order/direction 不受影响（既有 federation 测试零回归）；外层 federation 分页 × 内层本地 order/direction 能叠加。
- **SC-006**: shared core 抽取后，federation 分页与本地分页的排序逻辑同源（无重复实现）。

## 关键设计决定与取舍论证

1. **为什么统一 shared core 而非分叉两套。** federation 分页（013/014）已实现一套完整的"按 profile + direction 排序分页"逻辑。本地分页若另起一套，等于重复实现 + 长期双份维护 + 语义漂移风险。统一为 shared core，federation 与本地分页都调，013/014 成为 shared core 的首个应用。

2. **为什么本地关系声明载体选扩展 Relationship。** federation 分页用 `AutoQueryConfig.batch_pages` → `BatchPageConfig`（按 entity + batch key 索引），因为 federation 分页是 member 的 batch root。本地分页关系是实体上的关系字段，不是 root，挂不到 `batch_pages`，需要关系级别的声明。扩展 `Relationship` 加 `page_orders`/`default_page_order`——与现有 `order_by` 同处，profile 是关系属性、配置集中、心智一致，`order_by` → `page_orders` 是自然升级路径。

3. **为什么 DataLoader 的 per-query 参数这样处理。** 本地 page_loader 是按 parent key batch 的 DataLoader，但 order/direction 是整个 selection 的参数（同一 batch 内所有 parent 共享同一 order/direction）。复用 federation 的 selection 注入机制（loader 实例上挂当前 selection），或直接把 order/direction 塞进 cmd。两者皆可，plan 阶段选。

4. **为什么保留 sort_field 兜底。** 现有本地分页关系用 `Relationship.order_by` → `sort_field`。强制改成 profile 会破坏向后兼容。保留：没配 profile 的用 `sort_field`（现状），配了 profile 的用 profile。两条路径在 page_loader 内分叉，但排序构建都走 shared core。

5. **为什么单列约束本期沿用。** 014 把 `PageOrder` 限定单列。shared core 抽取时若顺带放开多列，federation 分页也会受影响（破坏 014 范围）。本期保持单列，多列留后续。

6. **为什么 shared core 底层共享但容器分开。** federation 分页（batch root，按 entity+field 索引，member 暴露给 mounter）与本地分页（关系字段，member 内部）的索引模型和生命周期不同，强行统一容器会扭曲一方。共享"排序内核"（`PageOrder`/`OrderTerm` + 构建/翻转/渲染），分开"声明容器"（`BatchPageConfig` vs `Relationship.page_orders`）——既 DRY 又贴合各自场景。

## Assumptions

- 假设本特性只覆盖本地分页（`enable_pagination` 的 list 关系）；federation 分页的 order/direction 已由 013/014 提供，本特性是把它下沉/统一，不改 federation 行为。
- 假设本地分页关系声明 profile 是 member 的部署期决定（profile 集合在关系定义时确定），查询者只在 member 批准的集合里选。
- 假设 sort field 不开放给查询者（索引控制权留 member）；要更多排序由 member 多暴露 profile，沿用 014。
- 假设 nulls 翻转语义、单列约束、稳定 tie-breaker 沿用 014（shared core 已实现）。
- 假设 profile 声明载体的具体形式（扩展 `Relationship` vs 新建容器）在 plan 阶段定；spec 阶段只约束"复用 `PageOrder`/`OrderTerm` + 关系级别声明"。
- 假设本期不改变 federation 分页行为；federation items 子树内本地分页的 order/direction 叠加由 5.0.1 保证，本特性让内层本地分页也有 order/direction。
