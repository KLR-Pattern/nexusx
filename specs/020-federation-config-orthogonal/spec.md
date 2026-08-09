# Feature Specification: Federation 配置正交化

**Feature Branch**: `020-federation-config-orthogonal`

**Created**: 2026-08-09

**Status**: Draft

**Input**: User description: "Federation 配置正交化：把 member 侧联邦配置从 AutoQueryConfig 移到 entity，统一 order profile。"

## 背景与问题

nexusx federation 的 member 侧配置当前散落在多处（GraphQLHandler 参数、AutoQueryConfig 的 `batch_keys`/`batch_pages`、entity 的 `__pagination_orders__`、DTO 的 `SubsetConfig` federation_*），同一信息（join key、order profile）被 β（entity 关系联邦）和 γ（DTO 联邦）两条路径各声明一份，导致重复、易漂移、概念边界模糊（详见 note 15 federation 正交性分析）。

本 feature 把 member 侧联邦配置正交化：**联邦外键降为纯标记、order profile 统一不区分对内对外、配置集中到 entity、AutoQueryConfig 退化为执行者**。

## Clarifications

### Session 2026-08-09

- Q: mounter 侧 `join_remote` 是否纳入本 feature 的去重范围？ → A: **不纳入**（Option A）。mounter 与 member 是独立服务，`join_remote` 是 mounter 对 member 的跨服务契约（mounter 不该、也无法知道 member 的 `__federation_keys__` 内部声明；且 member 可能有多个外键，mounter 必须显式指明按哪个 join）。本 feature 只消除 **member 侧**的重复（`batch_keys` / `batch_pages` / `federation_join_key` → entity `__federation_keys__`）。
- Q: 旧配置（`batch_keys` / `batch_pages` / `federation_join_key`）的移除策略？ → A: **直接删**（Option A），无 deprecated 期、不保留兼容读法 / DeprecationWarning。federation 用户少，提供迁移文档（demo 为准），changelog 标 breaking。

## User Scenarios & Testing

> 「用户」= 使用 nexusx federation 的开发者。

### User Story 1 — 在 entity 上集中声明联邦能力（Priority: P1）

开发者定义一个 federation member（如 reviews 服务）时，在 entity 上一处声明它的全部联邦能力：哪些字段是联邦批量入口（`__federation_keys__`）、各分页维度怎么排序（`__pagination_orders__`）。不再到 AutoQueryConfig 里写 `batch_keys`/`batch_pages`，也不再在 DTO 上单独写 `federation_join_key` / `DTO.__pagination_orders__`。

**Why this priority**: 这是正交化的核心 —— 声明点从 4 处收敛到 entity 1 处，消除 join key / order profile 的重复声明。其余故事都建立在这个集中声明之上。

**Independent Test**: 给定一个 member entity，它通过 `__federation_keys__` + `__pagination_orders__` 声明联邦能力后，框架能据此生成 `by_<key>_in` 批量根、mounter 能成功联邦它，全程不读 `AutoQueryConfig.batch_keys/batch_pages`。

**Acceptance Scenarios**:

1. **Given** 一个 Review entity 带有 `__federation_keys__=["product_id"]` 和 `__pagination_orders__={"product_id": BatchPageConfig(...)}`, **When** 框架初始化该 member, **Then** 生成 `Review.by_product_id_in` 批量根（且 order 按 product_id 维度的 profile）。
2. **Given** 同样的 entity 声明, **When** mounter 通过 RemoteRelationship 联邦它, **Then** mounter 能批量 fetch 并按声明排序，行为与旧 `batch_keys`/`batch_pages` 配置等价。
3. **Given** member 用新声明（无 batch_keys/batch_pages）, **When** 跑三层联邦 demo（catalog→reviews→users）, **Then** 全部通过。

---

### User Story 2 — order profile 统一，不区分对内对外（Priority: P2）

开发者在 `__pagination_orders__` 里声明 order profile 时，不需要区分这个维度是「本地关系分页」（对内）还是「联邦批量分页」（对外）。同一个 BatchPageConfig 格式、同一个 `__pagination_orders__` 载体，框架靠 `__federation_keys__` 自动路由一个维度走本地 loader 还是联邦批量根。

**Why this priority**: 消除「本地分页配置 vs 联邦分页配置」两套概念，order 成为单一通用概念。是正交化的第二根支柱。

**Independent Test**: 一个 entity 同时有本地关系分页（如 comments）和联邦批量分页（如 product_id），两者 order profile 都在同一个 `__pagination_orders__` 里，框架分别正确路由。

**Acceptance Scenarios**:

1. **Given** Review.`__pagination_orders__` 同时含 `"comments"`（本地关系）和 `"product_id"`（在 `__federation_keys__` 里）, **When** 加载 Review.comments 和联邦批量 `Review.by_product_id_in`, **Then** 两者各自按自己的 order profile 排序，互不干扰。
2. **Given** 同一个 order profile 格式（BatchPageConfig）, **When** 用于本地关系和联邦批量, **Then** 无需任何「对内/对外」标记，框架自动路由正确。

---

### User Story 3 — γ DTO join key 归并到 entity（Priority: P3）

开发者做 γ（DTO 联邦）时，DTO 的 `federation_join_key` 不再单独在 SubsetConfig 里声明，而是复用源 entity 的 `__federation_keys__`。join key 单一来源（entity）。

**Why this priority**: 消除 join key 在 β（batch_keys）/γ（federation_join_key）的重复，统一到 entity。依赖 US1 的 `__federation_keys__`。

**Independent Test**: 一个 γ DTO（federation_public=True）的 join key 由其源 entity 的 `__federation_keys__` 决定，DTO 上不再写 federation_join_key。

**Acceptance Scenarios**:

1. **Given** ReviewDTO 的源 entity Review 声明 `__federation_keys__=["product_id"]`, **When** ReviewDTO 标记 federation_public=True, **Then** γ 联邦用 product_id 作为 join key，无需 DTO 上再声明 federation_join_key。
2. **Given** 旧的 `SubsetConfig(federation_join_key="product_id")` 用法, **When** 迁移到新模型, **Then** join key 只在 entity 上一处。

---

### Edge Cases

- **维度名重名**：`__pagination_orders__` 的 key 既是关系名又是字段名？约定：`__federation_keys__` 里的字段名优先识别为联邦维度；不在其中的走本地关系。框架按 `__federation_keys__` 路由。
- **旧配置处理**：旧的 `AutoQueryConfig(batch_keys=..., batch_pages=...)` 与 DTO `federation_join_key` 如何处理？federation 用户少，直接移除（breaking），提供迁移文档（以 demo 为准）。
- **纯本地 entity**：一个 entity 没有任何联邦能力？`__federation_keys__` 缺省为空，`__pagination_orders__` 只有本地关系维度，行为不变。
- **联邦外键不分页**：member 的某个联邦外键字段不需要分页（只 `by_<key>_in`，不 `page_by`）？`__pagination_orders__` 里该维度缺省 → 只生成 `by_<key>_in`（不分页根）。

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 支持 entity 上的 `__federation_keys__` 声明，标记哪些字段是联邦批量入口（纯标记，不携带排序配置）。
- **FR-002**: 系统 MUST 据 `__federation_keys__` 为每个标记字段生成 `by_<key>_in` 批量查询根（`WHERE key IN (values)`）。
- **FR-003**: 系统 MUST 据 `__federation_keys__` + `__pagination_orders__` 为带 order profile 的联邦外键生成 `page_by_<key>_in` 分页批量根。
- **FR-004**: `__pagination_orders__` MUST 作为统一的 order profile 载体，不区分维度是本地关系还是联邦外键；key 为维度名（关系名或字段名），值为 BatchPageConfig。
- **FR-005**: 系统 MUST 据 `__federation_keys__` 路由一个 `__pagination_orders__` 维度：在 `__federation_keys__` 里的字段 → 联邦批量根；不在的 → 本地关系 loader。
- **FR-006**: AutoQueryConfig MUST 移除 `batch_keys` / `batch_pages` 两个声明字段；改为读 entity 的 `__federation_keys__` + `__pagination_orders__` 生成对应根（声明在 entity，生成在 AutoQueryConfig）。**直接移除，不保留兼容读法 / DeprecationWarning**（breaking，见 Clarifications Q2）。
- **FR-007**: γ DTO 的 `federation_join_key` MUST 归并：join key 由源 entity 的 `__federation_keys__` 决定，DTO SubsetConfig 不再单独声明 join key。
- **FR-008**: 声明（entity）/ 执行（AutoQueryConfig 生成根）MUST 分离 —— entity 只声明能力，AutoQueryConfig 只读 entity 生成查询根，不承载联邦声明。
- **FR-009**: 迁移 MUST 覆盖 demo（reviews/catalog/users_app）、文档（docs/advanced/federation 双语）、测试（federation 相关），确保新声明模型一致。

### Key Entities

- **`__federation_keys__`**（entity 级，新增）：联邦外键标记 —— 声明哪些字段是联邦批量入口（如 `["product_id"]`）。纯标记，不携带排序。框架据此生成 `by_<key>_in` 根，并据此路由 order 维度。
- **`__pagination_orders__`**（entity 级，已存在、语义扩展）：统一 order profile —— key 为维度名（关系名 or 联邦外键字段名），值为 BatchPageConfig。不再区分对内对外。
- **BatchPageConfig**（已存在）：order profile 载体 —— `default_order` + `orders{名字: PageOrder}`。本地关系和联邦批量共用同一格式。
- **AutoQueryConfig**（已存在、职责退化）：从「联邦声明载体」退化为「读 entity 生成 by_/page_by 根的执行者」。移除 batch_keys/batch_pages。

## Success Criteria

### Measurable Outcomes

- **SC-001**: federation member **侧**的 join key（如 product_id）声明点从 3 处（`batch_keys` / `batch_pages` / `federation_join_key`）降到 entity 上 1 处（`__federation_keys__`）。mounter 侧 `join_remote` 保留（跨服务契约，不在此去重范围）。
- **SC-002**: 同一个 order profile（如 HIGHEST_RATING）只声明一份（旧：β batch_pages 一份 + γ DTO.`__pagination_orders__` 一份；新：`__pagination_orders__` 一份）。
- **SC-003**: federation member 的联邦能力配置全部集中在 entity（GraphQLHandler 参数 / AutoQueryConfig / DTO 不再承载联邦 join key 或 order 声明）。
- **SC-004**: 三层联邦 demo（catalog→reviews→users）在新声明模型下行为与旧模型等价（功能零回归）。
- **SC-005**: AutoQueryConfig 的职责回归「自动查询生成开关」（default_limit / generate_by_id / generate_by_filter），不再含联邦声明字段。

## Assumptions

- federation 当前用户少，breaking 改动可接受：直接移除 `AutoQueryConfig.batch_keys/batch_pages` 和 DTO `federation_join_key`，不保留长 deprecated 期（提供迁移文档，以 demo 为准）。
- β（entity 关系联邦）和 γ（DTO 联邦）共享新的 entity 声明底座（`__federation_keys__` + `__pagination_orders__`）；两者内部调度路径（remote_loader / dto_remote_loader）可仍分开，但用户侧声明统一。
- **mounter 侧 `join_remote` 不在本 feature 的「去重」范围**：mounter 与 member 是不同服务，`RemoteRelationship(join_remote=...)` 是 mounter 对 member 的契约（mounter 不知道 member entity 的 `__federation_keys__`，必须显式告诉框架按 member 的哪个字段 join）。本 feature 聚焦 member 侧去重 + order 统一。
- 现有 federation 公共 API（RemoteService / RemoteRef / RemoteRelationship）的声明模型保持不变（正交性分析已确认这部分设计良好）。
