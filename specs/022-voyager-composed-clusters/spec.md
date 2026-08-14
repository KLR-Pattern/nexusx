# Feature Specification: Voyager 的 ComposedErManager 分组与配色

**Feature Branch**: `022-voyager-composed-clusters`

**Created**: 2026-08-14

**Status**: Draft

**Input**: User description: "ComposedErManager 场景下 Voyager 的 member 分组与配色：ER 图（全局 + 邻域 subgraph）和 UseCase 页在多 ErManager 组合时按 member（service_name）分 cluster，member 可在 ErManager 上配置 color（opt-in，未配置默认白/不填充），cluster 支持背景色填充。归属优先级 fed_qn service > member(service_name) > Python module。复用 federation 的 module_color/federated_modules styling 机制（spec 019 research Unknown 4 遗留）。"

## 一句话

ComposedErManager 组合多个 ErManager 时，Voyager 的 ER 图和 UseCase 页按 member 分 cluster（标签 = member 的 `service_name`），member 可在 ErManager 上 opt-in 声明 `color` 让 cluster 带背景色填充；未声明 `service_name` 的 member 回落现状（按 Python module 分组），未声明 `color` 的 member 不填充（默认白）。补上 spec 019 research "Unknown 4" 明确推迟的跨 engine 分簇标注。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - ER 图按 member 分组 (Priority: P1)

开发者用 ComposedErManager 组合了两个 engine（如 blog + shop），打开 Voyager 的 ER 图。改动前，两个 member 的实体若定义在同一个 Python 模块（demo 现状即如此），会混在同一个 cluster 里无法区分；改动后，设了 `service_name` 的 member，其实体归入以该名字为标签的独立 cluster，跨 engine 关系边横跨两个 cluster，一眼可辨"哪些表属于哪个数据源"。

**Why this priority**: 分组是本特性的核心价值——不改任何行为，只是"看得出来"；没有分组，配色无从谈起。也是 spec 019 遗留缺口的主体。

**Independent Test**: 构造两个 member（各设 `service_name`，实体放同一 Python 模块），生成 ER 图 DOT，断言出现两个以 service_name 为标签的 cluster，且各 member 实体归属正确、跨边界边连接两 cluster。

**Acceptance Scenarios**:

1. **Given** ComposedErManager 含 member A（`service_name="blog"`，实体 User/Post）与 member B（`service_name="shop"`，实体 Order），两 member 实体定义在同一 Python 模块，**When** 生成 ER 图，**Then** 出现标签为 `blog` 与 `shop` 的两个 cluster，User/Post 在前者、Order 在后者。
2. **Given** 上述场景存在跨 engine 关系 User→Order，**When** 生成 ER 图，**Then** 该边两端分别落在 `blog` 与 `shop` cluster 中。
3. **Given** 单体 ErManager（非 Composed），**When** 生成 ER 图，**Then** 输出与改动前一致（按 Python module 分组，零回归）。

---

### User Story 2 - member 配色与 cluster 背景填充 (Priority: P2)

开发者为某 member 声明颜色（`ErManager(..., color="#E3F2FD")`），该 member 的 cluster 呈现背景色填充、边框着色，cluster 内实体的表头继承该色调；未声明颜色的 member cluster 不填充（白），仅分组。与 federation 的 `RemoteService(color=...)` opt-in 语义对偶：无自动调色板，颜色完全由用户声明。

**Why this priority**: 分组（US1）先解决"分开"，配色解决"一眼认出"。opt-in 保持与 federation 一致的克制，避免自动配色带来的不可预期。

**Independent Test**: 构造带 `color` 的 member 生成 ER 图，断言对应 cluster 出现 `fillcolor` 与 `pencolor`；构造不带 `color` 的 member，断言其 cluster 无 `fillcolor`（opt-in 断言，仿 `tests/test_federation_voyager.py` 模式）。

**Acceptance Scenarios**:

1. **Given** member A 声明 `service_name="blog"` 与 `color="#E3F2FD"`，**When** 生成 ER 图，**Then** `blog` cluster 带 `fillcolor="#E3F2FD"` 与同色边框，cluster 内节点表头继承该色。
2. **Given** member B 声明 `service_name="shop"` 但未声明 color，**When** 生成 ER 图，**Then** `shop` cluster 正常分组但无 `fillcolor`（默认白）。
3. **Given** 同一 member 同时声明 color 且后续 federate（叠加场景），**When** 生成 ER 图，**Then** federation 物化的 remote type 仍按远端 service 聚成 dashed cluster，member 本地实体仍按 member 聚成 rounded cluster，两者互不串扰、颜色各归各。

---

### User Story 3 - UseCase 页的 DTO 归属 (Priority: P3)

开发者把各 member 的 DTO 类注册进对应 ErManager（`dto_classes=...`），打开 Voyager 的 UseCase 页，命中的 DTO 节点归入所属 member 的 cluster（同样吃 member 颜色）；未注册进任何 member 的 DTO 维持按 Python module 分组。Route 节点（service 方法本身）不参与 member 归属——service 层不等于数据层。

**Why this priority**: UseCase 页是第二消费面，价值同 US1/US2 但受众更窄（DTO 图通常节点更少）；放在 ER 图验证之后做风险更低。

**Independent Test**: 构造 member + 注册 `dto_classes`，生成 UseCase 页 DOT，断言命中 DTO 的 cluster 为 member 名、颜色为 member 色；未注册 DTO 的 cluster 仍为 Python module。

**Acceptance Scenarios**:

1. **Given** member A（`service_name="blog"`, `color=...`, `dto_classes=[PostSummary]`），**When** 生成 UseCase 页图，**Then** `PostSummary` 节点落在 `blog` cluster 且应用其颜色。
2. **Given** 某 DTO 未注册进任何 member 的 `dto_classes`，**When** 生成 UseCase 页图，**Then** 该 DTO 按 Python module 分组（现状不回归）。
3. **Given** 某 DTO 是 federation 物化的 remote type，**When** 生成 UseCase 页图，**Then** 它按远端 service 聚簇（fed_qn 优先级高于 member 归属）。

---

### User Story 4 - 邻域 subgraph 继承分组与配色 (Priority: P4)

开发者在 ER 图选中某实体查看"Related Entities"邻域子图，子图中各实体依然带所属 member 的 cluster 归属与颜色——子图与全图 styling 一致，不会因为聚焦而丢失分组语义。

**Why this priority**: subgraph 与全图共享渲染路径，预期"自动获得"；单列 US 是为了把"不丢失"钉进验收，防实现时只顾全图路径。

**Independent Test**: 全图有 blog/shop 两 cluster 时，对 blog 侧某实体调用邻域子图（其邻居含 shop 实体），断言子图 DOT 仍含两个 cluster 且颜色正确。

**Acceptance Scenarios**:

1. **Given** 跨 engine 边 User(blog)→Order(shop) 且两 member 各有颜色，**When** 查看 User 的邻域子图，**Then** 子图含 `blog` 与 `shop` 两个带色 cluster，跨 engine 边保留。

### Edge Cases

- member 未设 `service_name` 时怎么办？→ 回落现状：该 member 的实体按 Python `__module__` 分组。不强制命名（非 breaking），demo/文档引导设置。
- member 的 `service_name` 与本地 Python module 名前缀碰撞（如 service_name=`blog` 而存在模块 `blogging.models`）时，module 颜色前缀匹配可能误命中 → 实现须保证 member 分组的颜色只作用于以 service_name 为根的 cluster（精确归属，非模糊前缀）；该碰撞场景进测试。
- 多个 member 设了相同 `service_name` 怎么办？→ 不合并（各自成 cluster 会因 DOT cluster id 同名而崩）→ 实现须在聚合时对重名报错或附加可区分后缀（plan 阶段定，倾向 fail-fast 报错，提示 service_name 需唯一）。
- member 声明了 `color` 但没声明 `service_name` 怎么办？→ color 无处安放，聚合时忽略该 color 并保持现状分组（不报错；文档说明 color 依赖 service_name 生效）。
- `color` 值非法（如拼错的十六进制）→ 不做值校验，透传给 graphviz（graphviz 自身容错渲染）；文档建议用 `#RRGGBB` 浅色。
- 所有 member 都未设 `service_name` → 整图回落现状 Python module 分组，行为与改动前完全一致。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `ErManager` MUST 支持在构造时声明可选颜色（`color`），默认不声明；颜色仅作为可视化元信息，不影响任何查询/加载行为。
- **FR-002**: ComposedErManager MUST 向 Voyager 消费面暴露 member 分组信息：设了 `service_name` 的 member，其实体（及注册进 `dto_classes` 的 DTO）可归属到该 member；未设的不参与。
- **FR-003**: ER 图节点归属优先级 MUST 为：federation 物化类型的 owning service > member 的 `service_name` > Python `__module__`（现状）。
- **FR-004**: 设了颜色的 member，其 cluster MUST 同时呈现背景填充（fillcolor）与边框色（pencolor），且 cluster 内节点表头继承该色；未设颜色的 member cluster MUST NOT 出现背景填充（默认白）。
- **FR-005**: UseCase 页的 DTO 节点归属 MUST 遵循与 FR-003 相同的优先级（member 判定依据为 `dto_classes` 注册关系）；Route 节点 MUST 维持按 Python module 分组，不参与 member 归属。
- **FR-006**: federation 远端 service cluster 的 dashed 边界语义 MUST 保持不变；member 本地 cluster 使用 rounded 样式，与远端服务边界在视觉上可区分。
- **FR-007**: 邻域子图（Related Entities）MUST 继承与全图一致的 member 分组与配色。
- **FR-008**: 非 Composed 场景（单体 ErManager，无论是否设 color）MUST 与改动前行为一致；本特性 MUST NOT 构成 breaking change。
- **FR-009**: member 分组名（`service_name`）在 ComposedErManager 内 MUST 唯一，重名 MUST 在构造期 fail-fast 报错。

### Key Entities

- **member 分组信息**: entity/DTO 类 → 所属 member（`service_name`、`color`）的只读映射，由 ComposedErManager 聚合各 member 提供；单体 ErManager 不提供（消费面探测不到即回落现状）。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 双 member demo（blog/shop）的 ER 图中，member 实体 100% 归入以各自 service_name 为标签的 cluster，跨 engine 边两端 cluster 不同。
- **SC-002**: 颜色严格 opt-in：声明 color 的 member cluster 含 fillcolor；未声明的 DOT 输出中不出现 fillcolor（可自动断言）。
- **SC-003**: 全量既有测试零回归（含 federation voyager、composed er manager、voyager 各 spec 套件）。
- **SC-004**: 单体 ErManager 场景 ER 图输出与改动前语义一致（实现中顺带修正 cluster 模板既有挤行 bug，属性行空白规范化；节点/边/cluster/颜色不变，见 contracts §5 已记录偏离）。

## Assumptions

- 颜色为合法 graphviz 颜色字符串（推荐 `#RRGGBB` 浅色），库不做值校验、不提供自动调色板（对齐 federation 的 opt-in 克制）。
- mermaid 路径（`ErDiagram.to_mermaid`）不在本特性范围内：mermaid erDiagram 语法无分组/填色概念。
- `service_name` 复用既有字段（federation 语义），不新增同义的 `name` 参数；未设 service_name 的 member 不参与分组。
- Route 节点（UseCaseService 方法）不参与 member 归属：service 层组织方式与数据源归属是两个正交维度。
- UseCase 页 DTO 归属以 `dto_classes` 注册为准：未注册进任何 member 的 DTO 无法（也不应被猜测）归属。
