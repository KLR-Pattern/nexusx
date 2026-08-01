# Feature Specification: Federation 分页 order/direction 开放给查询者

**Feature Branch**: `feat/federation-order-direction`

**Created**: 2026-08-01

**Status**: Draft

**建立在**: `specs/013-federation-pagination` 之上

**Input**: User description: "把 federation 远程 to-many 分页关系的 order 选择权从「挂载方部署期静态绑定」改为「查询期由查询者经 GraphQL 参数决定」，并开放排序方向（升序/降序）给查询者。"

## 背景与动机

013 实现了 federation 远程 to-many 分页：member 定义 order profile（语义排序），mounter 在 `RemoteRelationship` 上**静态选一个** order（部署期），业务客户端只能传 `limit`/`offset`，既不能选 order、也不能翻转方向。

问题：order 在部署期写死，查询者无法按场景挑排序或翻方向。同一条 `reviews` 关系，有时要"最高评分"、有时要"最新"、有时要升序——目前只能让 member 定义多个关系，或改部署重新 federate。

本特性把 **order profile 的选择权下放到查询期**：mounter 把 member 暴露的 profile 集合渲染成 GraphQL 参数 enum，查询者查时挑 profile + direction（升序/降序）。索引控制权仍在 member（查询者只能在 member 批准的 profile 集合里选名字、翻方向，不能传任意 sort field）。

## 模型概述

两条决策：

1. **order 由查询者挑（方案乙）**：member 定义 order profile 集合 → ER introspection 传 mounter → mounter 渲染成 schema 的 `order` 参数 enum → 查询者 GraphQL 查询时挑 `order` + `direction` → mounter 透传给 member 的 `page_by_<key>_in` → member 按选择排序。
2. **只开放方向，不开放 field**：查询者可翻 direction（ASC/DESC），但 sort field 仍封闭（member 控制索引）。每个 profile 单列排序，让 direction 翻转语义干净。

目标查询形态：

```graphql
{
  Product {
    by_filter {
      reviews(limit: 5, offset: 0, order: HIGHEST_RATING, direction: DESC) {
        items { title rating }
        pagination { has_more total_count }
      }
    }
  }
}
```

## User Scenarios & Testing *(mandatory)*

### User Story 1 — 查询者挑 order profile + direction（Priority: P1）

作为一个查 federation 入口服务的客户端开发者，我希望在 GraphQL 查询里给分页关系传 `order` 和 `direction`，这样同一条查询路径能拿到不同排序的结果（最高评分 / 最新 / 升序 / 降序），不用 member 预定义多个关系、不用改部署。

**Why this priority**：本特性的核心增量——把 order 选择权从部署期搬到查询期。验证主链路：查询参数 → mounter 透传 → member 按选择排序 → 正确结果返回。

**Independent Test**：起 catalog（挂 reviews，reviews 暴露 `HIGHEST_RATING`/`NEWEST` 两个 profile）+ reviews + users，分别查 `reviews(order: HIGHEST_RATING, direction: DESC)` 和 `reviews(order: NEWEST, direction: ASC)`，断言两次结果排序不同且各自正确。

**Acceptance Scenarios**:

1. **Given** reviews 暴露 `HIGHEST_RATING` profile，**When** 查询者传 `order: HIGHEST_RATING, direction: DESC`，**Then** 返回 items 按 HIGHEST_RATING 的列 desc 排序。
2. **Given** 同一关系，**When** 传 `direction: ASC`，**Then** items 按该列 asc 排序（与 DESC 严格相反）。
3. **Given** 同一关系，**When** 传 `order: NEWEST`，**Then** items 按 NEWEST profile 排序（与 HIGHEST_RATING 不同）。

---

### User Story 2 — mounter 把 member 的 profile 集合渲染成 schema enum（Priority: P1）

作为一个 federation 入口服务的开发者，我希望挂载一个分页关系后，我的 GraphQL schema 自动给该关系加上 `order`（enum，值=member 的 profile 名）+ `direction`（ASC/DESC）参数，客户端能从 schema 发现这些选项——无需我手写 enum。

**Why this priority**：方案乙的机制核心——跨服务 enum 共享。没有这条，查询者无 enum 可挑，US1 不成立。

**Independent Test**：挂载 reviews（暴露 HIGHEST_RATING/NEWEST）后取 mounter 的 SDL + `__schema` 内省，断言 `reviews` 字段有 `order` 参数（enum 含两个 profile 名，默认 = member 的 default_order）和 `direction` 参数（ASC/DESC）。

**Acceptance Scenarios**:

1. **Given** reviews 暴露 {HIGHEST_RATING, NEWEST}，**When** federate 后取 mounter SDL，**Then** `reviews` 字段签名含 `order: <XxxOrder>`（enum 值 = 两个 profile 名）。
2. **Given** 同上，**Then** `reviews` 字段含 `direction: Direction`（enum: ASC, DESC）。
3. **Given** member 的 default_order=NEWEST，**Then** mounter 的 `order` 参数默认值 = NEWEST。
4. **Given** `__schema` 内省，**Then** 它与 SDL 暴露一致的 order/direction 参数（两条渲染路径同源）。

---

### User Story 3 — direction 翻转时 nulls 跟随（Priority: P2）

作为一个查询者，我希望传 direction 翻转排序时，NULL 的位置语义正确（desc 时 NULL 在末尾，翻成 asc 时 NULL 在开头），不出现 NULL 位置错乱。

**Why this priority**：direction 翻转的正确性细节。NULL 排序跨方言易错，必须定义清楚。

**Independent Test**：member 定义一个 nullable 列的 profile（desc + nulls_last），分别查 desc 与 asc，断言 NULL 在 desc 时末尾、asc 时开头。

**Acceptance Scenarios**:

1. **Given** profile `RATING`（rating desc, nulls_last），**When** direction=DESC，**Then** NULL rating 在末尾。
2. **Given** 同上，**When** direction=ASC（翻转），**Then** rating asc 且 NULL 在开头（nulls 跟随翻转：nulls_last → nulls_first）。

---

### Edge Cases

- **order 参数缺省**：查询者不传 order → 用 member 的 `default_order`。
- **direction 参数缺省**：不传 direction → 用 profile 定义的默认方向。
- **member 暴露的 profile 集合为空**：federate 启动期 fail-fast（mounter 无 enum 可渲染）。
- **查询者传 member 未暴露的 order 名**：GraphQL enum 校验拒绝（值不匹配），不进 member。
- **PageOrder 含多列**：member 启动期校验拒绝（本期只支持单列）。
- **`RemoteRelationship.order` 旧字段**：废弃；声明它不再生效（order 由查询参数决定），启动期给出 deprecation 提示。
- **同一查询对不同分页关系传不同 order/direction**：各自独立解析，互不影响。
- **RemoteLoader 透传缺省**：order/direction 经 selection.arguments 传 member，缺省时 member 用 default。

## Requirements *(mandatory)*

### Functional Requirements

#### member 侧

- **FR-001**：member 的 `page_by_<key>_in` root MUST 新增 `direction` 参数（取值 ASC|DESC），与既有 `order`/`limit`/`offset` 并列。
- **FR-002**：member MUST 按 `direction` 翻转所选 profile 的排序项——`direction` 覆盖 profile 项的默认方向，且 `nulls` 跟随翻转（`desc + nulls_last` ↔ `asc + nulls_first`）；窗口函数内层与外层 MUST 用翻转后完全一致的 order expressions。
- **FR-003**：member 的 `PageOrder` MUST 限定单列（恰好一个 `OrderTerm`）；多列 profile 在 member 启动期校验阶段拒绝。
- **FR-004**：member 的 ER introspection MUST 暴露 order profile 集合（名 + 描述）与 `default_order`，供 mounter 渲染 enum（沿用 013 的 `BatchPageCapability`，不暴露物理列/方向/nulls）。

#### mounter 侧（关系元数据 + schema）

- **FR-005**：mounter MUST 在分页关系的元数据里携带 member 的 page capability（profile 集合 + default_order），供 schema 渲染使用。
- **FR-006**：mounter 的 GraphQL schema（SDL 与 `__schema` 内省两条路径）MUST 为 federation 分页关系字段渲染 `order` 参数（enum，值 = member profile 名集合）与 `direction` 参数（enum: ASC|DESC）；`order` 的默认值 = member 的 `default_order`。
- **FR-007**：mounter 的 `direction` enum MUST 是 mounter 自有的全局类型（ASC/DESC），在 schema 里渲染一次。

#### mounter 侧（取数透传）

- **FR-008**：mounter 的 RemoteLoader MUST 从查询的 selection.arguments 读取 `order` 与 `direction`，并透传进发给 member 的 `page_by_<key>_in` gql；不再在 federate 时静态烘焙（bake）order。
- **FR-009**：mounter MUST 废弃 `RemoteRelationship.order` 静态字段——order 的唯一来源是查询参数（缺省时 member 用 default_order）。
- **FR-010**：federate 校验 MUST 放宽：`pagination=True` 不再强制声明 `order`；改为校验 member 暴露的 `page_capability.orders` 非空（否则启动期 fail-fast）。

#### 边界

- **FR-011**：本期 MUST 仅支持 β 路径（GraphQL 直查 mounter）。γ 路径（Resolver/UseCase 业务代码组装）选 order 明确不在本期范围。
- **FR-012**：sort field MUST 保持封闭——查询者不能传任意 sort field，只能在 member 批准的 profile 集合里选名字 + 翻方向。索引控制权仍在 member。

### Key Entities *(include if feature involves data)*

- **order profile**：member 定义的一个语义排序（单列：一个 field + 默认 direction + nulls），有唯一的 enum-safe 大写名。查询者按名字引用。
- **direction**：查询者传的排序方向（ASC/DESC），覆盖 profile 的默认方向；翻转时 nulls 跟随。
- **page capability**：member 经 ER introspection 暴露的分页能力（profile 集合 + default_order），是 mounter 渲染 order enum 的唯一数据源。
- **RemoteRelationship**：挂载方的跨服务分页关系声明；`order` 字段废弃，分页关系的 order 改由查询参数决定。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**：同一分页关系，查询者传 `direction: DESC` 与 `direction: ASC`，返回 items 的排序严格相反（含 NULL 位置正确）。
- **SC-002**：查询者传不同 `order` profile，返回 items 按各 profile 的列排序，结果不同且正确。
- **SC-003**：mounter 的 SDL 与 `__schema` 内省都暴露 `order`（enum 值 = member profile 名集合）+ `direction`（ASC/DESC）参数，两者字段集一致。
- **SC-004**：`RemoteRelationship.order` 字段废弃后，移除所有静态 order 绑定，order 的唯一来源是 GraphQL 查询参数（缺省走 member default）。
- **SC-005**：member 定义多列 PageOrder 在启动期被拒绝（单列约束生效）。
- **SC-006**：每次遍历对每个被挂服务仍只发**一条** GraphQL 请求（order/direction 透传不破坏 federation 每服务一次批量的招牌）。
- **SC-007**：单体 nexusx（未启用 federation）零回归；既有 federation 非分页路径不受影响。

## Assumptions

- 假设本期只覆盖 β 路径（GraphQL 直查）；γ 路径（Resolver/UseCase）选 order 留待后续。
- 假设每个 order profile 恰好一个 OrderTerm（单列排序）；多列复合排序不支持。
- 假设 sort field 不开放给查询者（索引控制权留 member）；要更多排序就由 member 多暴露 profile。
- 假设 federation 为新功能、无外部向后兼容包袱：`RemoteRelationship.order` 是 API 删除，不需 deprecation 迁移期。
- 假设 member 是可信的（它暴露的 profile 集合已经过其索引把关）；mounter 不二次校验物理列。
- 假设查询者传的 order/direction 经 GraphQL enum 校验（不合法值在 schema 层拒绝，不进 member）。
- 假设 direction 缺省时用 profile 的默认方向；order 缺省时用 member 的 default_order。
