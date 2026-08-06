# Feature Specification: DTO federation（UseCase 层 / γ 路径 federation）

**Feature Branch**: `016-dto-tree-federation`

**Created**: 2026-08-02

**Status**: Draft（经多轮架构讨论收敛，2026-08-02 定稿）

**建立在**: `specs/012-federation`（ER federation）+ `specs/004-non-sqlmodel-roots`（virtual entity）+ `specs/013/014`（分页）+ 5.0.1（member 本地分页透传 federation items 子树）之上

**Input**: "γ 路径（UseCaseService）的 federation：member 暴露 public DTO（subset of 实体 + Resolver 加工，自包含业务树），mounter UseCaseService 关联 member public DTO，Resolver 组合。β 路径（ER federation）不动。"

## 背景与动机

nexusx 有两条 GraphQL 路径：
- **β**（SQLModel GraphQL 直查）：组合实体，mounter executor traverse（ER federation, 012）
- **γ**（UseCase GraphQL / UseCaseService）：组合 DTO，Resolver 组装业务树（3.0）

ER federation（012）跨服务组合**实体**（裸数据）。但业务逻辑（折扣/库存/聚合）在 Resolver 里，不在裸实体——现状 γ（catalog `composed_tree`, 5.0.1）在 **mounter 侧** Resolver 加工远程实体，业务没跟数据 owner。

本特性：**γ 路径的跨服务 federation——member 暴露 public DTO（UseCase 层，subset of 实体 + Resolver 加工，自包含业务树），mounter 的 UseCaseService 关联 member public DTO，Resolver 组合成业务树。** 业务封装在 member（图→树），mounter 拿业务结果。**β 路径（ER federation）完全不动。**

## 关键边界：两条路径分层 + virtual entity vs DTO

```
β (ER federation, 012, 不动):     关联 ER diagram 成员
  ├─ SQLModel 实体(Review)          ✓
  ├─ virtual entity(004, ER 成员)   ✓
  └─ DTO                            ✗ (不进 ER diagram)

γ (DTO federation, 新):            UseCase 层关联 member public DTO
  └─ ProductDTO.reviews → reviews.ReviewDTO  ✓ (UseCase 层)
```

- **ER diagram 只收真正 entity**（SQLModel + virtual entity）。DTO 不进 ER diagram。
- **DTO（DefineSubset）住 UseCase 层**。`subset of 实体` 是**派生关系**（`__subset__`），不是 ER 成员。
- **virtual entity（004，ER 成员）vs DTO（UseCase 层）**——都是 pydantic，但归属不同层，不混淆。

## 模型概述

```
member 侧:
  ① public DTO = DefineSubset(subset of 实体): 骨架字段(派生自实体, 含 FK) + 计算字段(resolve_*)
     ↑ 自包含业务树: member Resolver 加工(图→树), 含跨 service 出边(.author → users.UserDTO)
       member 自己也是 federation mounter(reviews 挂 users), Resolver 加工时跨 service 解析
  ② member 标记 public DTO: register_federation_dto(ReviewDTO, join_key="product_id")
     (非 public DTO 是 member 内部用, 不暴露)
  ③ member DTO batch root(按 join_key 取数): 取实体 → 造 DTO → er.create_resolver().resolve()
     返完整 DTO 业务树(含跨 service 解析); 不经 UseCaseService, 直接 ErManager Resolver

mounter 侧(γ 路径, 复用现有 UseCaseService + Resolver + RemoteLoader):
  ④ mounter UseCaseService(root) 的 DTO 引用 member public DTO:
       ProductDTO.reviews: list[reviews.ReviewDTO]  (RemoteRef member public DTO)
  ⑤ Resolver 组合: resolve_reviews 用 RemoteLoader 取 reviews.ReviewDTO(member batch root 返 DTO 树)
  ⑥ mounter 可二次 resolve: 在 member DTO 上加字段/选子集/重组, member 业务字段值只读契约

β 路径(ER federation): 完全不动, 继续关联实体+virtual entity
```

## Clarifications

### Session 2026-08-02

- Q: member 的 public DTO 怎么标记（可被 federation 引用 + join_key）？ → A: 在 `SubsetConfig`（`__subset__`）里加 federation 配置参数（`federation_public=True` + `federation_join_key="..."`）——跟 DTO 定义同处，声明式，复用 SubsetConfig 结构，不加新顶层机制。
- Q: member 怎么暴露 DTOFragment 给 mounter？ → A: 独立 DTO introspection 端点（β 的 ER introspection 完全不动，跟"两条路径分层"一致——β 用 ER introspection，γ 用 DTO introspection）。

## User Scenarios & Testing *(mandatory)*

### User Story 1 — member public DTO 自包含，mounter UseCaseService 组合 (Priority: P1)

member（reviews）标记 ReviewDTO public（subset of Review + resolve_total + 跨 service `.author → users.UserDTO`）。member batch root 按 product_id 返**完整 ReviewDTO 树**（Resolver 加工 + 跨 service）。mounter（catalog）UseCaseService 的 `ProductDTO.reviews → reviews.ReviewDTO`，Resolver 组合，拿到 member 业务树。

**Why this priority**: 核心切片——证明 γ 路径能跨服务组合 member public DTO（自包含业务树）。

**Independent Test**: 起 catalog + reviews（reviews 挂 users），catalog `CatalogService.composed_tree` 查 `ProductDTO.reviews`，断言返回 reviews.ReviewDTO（含 member 算的 total + 跨 service 已解析的 author）。

**Acceptance Scenarios**:
1. **Given** member 标记 ReviewDTO public + join_key，**When** mounter UseCaseService RemoteRef reviews.ReviewDTO，**Then** 返回 member 业务字段（member Resolver 算的）。
2. **Given** member DTO 含跨 service 出边（`.author → users.UserDTO`），**When** member Resolver 加工，**Then** author 跨 service 解析，返自包含树。
3. **Given** reviews Resolver 过程含复杂业务，**When** catalog 查 ReviewDTO，**Then** catalog 不感知 reviews 图→树过程，只接 DTO 树。

---

### User Story 2 — mounter 二次 resolve（member 值只读）(Priority: P1)

mounter 拿 reviews.ReviewDTO 后 DefineSubset 选子集 + resolve_* 加 tax，不改 member 业务值。

**Acceptance Scenarios**:
1. **Given** mounter DefineSubset ReviewDTO（选 title+total），**When** 查，**Then** 只返选字段（不改值）。
2. **Given** mounter resolve_* 加 tax（读 total），**When** 查，**Then** tax 是 mounter 算的，total 仍是 member 原值（不覆盖）。

---

### User Story 3 — join 复用（DTO FK 派生自实体）(Priority: P2)

DTO subset of 实体，FK 派生，RemoteLoader 按 FK batch 取数（γ 机制复用）。

**Acceptance Scenarios**:
1. **Given** ReviewDTO subset of Review（含 product_id），**When** mounter 按 product_id batch join reviews.ReviewDTO，**Then** 机制同 RemoteLoader（γ），不为 DTO 设计新 join。

---

### Edge Cases

- **member public DTO 含跨 service 出边**: ReviewDTO.author → users.UserDTO。member 端 Resolver 加工时解析（member 挂载 users），返自包含树。
- **member Resolver 失败**: member 加工 DTO 业务计算失败 → DTO batch root 返错误，mounter 透传（`RemoteQueryError`）。
- **public vs 非 public DTO**: 非 public DTO 是 member 内部用，不暴露 federation。只有 public 可被 mounter γ 引用。
- **DTO 深嵌套**: member DTO 树多层，mounter 递归（Resolver 嵌套）。

## Requirements *(mandatory)*

### member 侧

- **FR-001**（public DTO = DefineSubset subset of 实体）: 可 federation 的 DTO MUST 是 `DefineSubset`（subset of ER 实体）——骨架字段（派生自实体含 FK）+ 计算字段（`resolve_*`）。非 public DTO 是 member 内部，不暴露。
- **FR-002**（member public 标记 = SubsetConfig federation 参数）: member MUST 在 `SubsetConfig`（`__subset__`）里声明 federation 参数（`federation_public=True` + `federation_join_key`）标记 public DTO。只有 `federation_public` 的 DTO 暴露给 γ 引用。声明跟 DTO 定义同处（声明式，复用 SubsetConfig，不加新顶层机制）。
- **FR-003**（member DTO batch root 跑 Resolver）: member DTO batch root（按 join_key）MUST 跑 `er.create_resolver().resolve()` 返 DTO 业务树。不经 UseCaseService。
- **FR-004**（member DTO 自包含，含跨 service）: member public DTO 的跨 service 出边（`.author → users.UserDTO`）MUST 在 member 端 Resolver 加工时解析（member 自己是 federation mounter，挂载其他 service）。返自包含业务树。

### mounter 侧（γ）

- **FR-005**（UseCaseService 关联 member public DTO）: mounter UseCaseService 的 DTO MUST 能引用 member public DTO（`RemoteRef reviews.ReviewDTO`），用 RemoteLoader 取（member batch root 返 DTO 树）。
- **FR-006**（member 值只读契约）: mounter 二次 resolve MUST NOT 改 member 业务字段值。沿用现有 Resolver/DefineSubset 纪律（`resolve_*` 加字段不覆盖、`DefineSubset` 选字段不改值）。
- **FR-007**（join 复用）: DTO 的 FK 派生自实体（subset），RemoteLoader 按 FK batch 取数，复用 γ 路径 RemoteLoader 机制。

### 边界

- **FR-008**（β 不动）: 本特性 MUST NOT 改 β 路径（ER federation, SQLModel GraphQL 直查）。β 继续关联实体+virtual entity。
- **FR-009**（DTO 不进 ER diagram）: DTO MUST NOT 进 ER diagram。ER diagram 只实体 + virtual entity（004）。DTO 住 UseCase 层。
- **FR-010**（零回归）: 012-014 + 5.0.1 行为不变。

### Key Entities

- **public DTO**: `DefineSubset`（subset of 实体 + `resolve_*`），member 标记 public（可 federation）。UseCase 层，自包含业务树。
- **DTOFragment**: DTO introspection 序列化（γ 物化远程 DTO 用）。数据源 `_subset_registry` + `model_fields`。
- **DTO batch root**: member 按 join_key 返 DTO 树的入口（跑 Resolver）。

## Success Criteria *(mandatory)*

- **SC-001**: member public DTO（自包含业务树）能被 mounter UseCaseService（γ）组合，返回 member 业务字段 + 跨 service 解析。
- **SC-002**: mounter 二次 resolve 不改 member 值（member 只读契约）。
- **SC-003**: β 路径（ER federation）不变；DTO 不进 ER diagram。
- **SC-004**: DTOFragment 从 DefineSubset 收集可行（`_subset_registry` + `model_fields`，已验证）。
- **SC-005**: 012-014 + 5.0.1 零回归。

## 关键设计决定与取舍论证

1. **为什么 γ 路径（不 β）。** DTO 是 UseCase 层（业务），β 是 ER 层（数据）。DTO federation 是业务的跨服务组合，走 γ（UseCaseService + Resolver）。β 继续数据（实体）。两条路径分层，不交叉——避免 DTO 污染 β 的数据组合。

2. **为什么 DTO 不进 ER diagram（只实体+virtual）。** ER diagram 是数据层（实体关系）。DTO 是业务层（UseCase）。混进 ER 污染数据层。virtual entity（004）是 ER 成员（数据形状），DTO（DefineSubset）是 UseCase 层（业务）——都是 pydantic 但归属不同层，不混淆。`subset of 实体` 是 DTO 的派生关系（`__subset__`），不是 ER 成员身份。

3. **为什么 public 标记。** member 的 DTO 可能很多（内部用），只暴露 public（可 federation）的。public = 可被其他 service 引用。控制暴露面，非 public DTO 不进 federation。

4. **为什么 member DTO 自包含（member 跨 service federation）。** member public DTO 含跨 service 出边（`.author → users.UserDTO`），member 自己是 federation mounter 挂载 users，Resolver 加工时解析。返自包含业务树，mounter 拿完整树，不用拼 author。业务在 member 端组装完整——这是"业务跟 owner"的体现。

5. **为什么 member batch root 跑 er.create_resolver（不经 UseCaseService）。** `er.create_resolver()` 是 ErManager 能力，UseCaseService 内部也是用它。DTO federation 直接用，跳过 UseCaseService 壳。Resolver 本就独立于 UseCaseService。

6. **为什么 member 值只读。** member 业务字段（折扣）是 member 算的，mounter 改它破坏业务正确性。现有 Resolver/DefineSubset 纪律（`resolve_*` 加字段不覆盖、`DefineSubset` 选字段不改值）直接保证边界，不是新规则。

7. **为什么 DTOFragment 从 `_subset_registry` + `model_fields`。** 实测 `DefineSubset.__subset__` 被 pydantic `__getattr__` 拦截（metaclass 消费后没保留）。`_subset_registry[DTO]` 提供等价 base_entity 映射，`model_fields` 一次性给出全部字段+类型（骨架+PK+计算，pydantic 已合并）。可行性已验证。

## 中长期演进与开放点（不锁死，留 plan/future）

DTO 的"管理"是中长期会演进的问题，本 spec 只定最小可工作集，以下点明确**不锁死**：

- **DTO 注册时机/生命周期**: 启动期静态声明 vs 运行期动态注册？member DTO 变更 mounter 怎么感知？——假设启动期静态 + 重启 re-init（沿用 012），动态/热感知留后续。
- **DTO 版本/兼容**: member DTO 演进（字段变更）对 mounter 的影响——留后续（trusted-network 假设）。
- **DTO batch root 形态**: 复用 standard_queries 生成 vs 独立——留 plan。

## Assumptions

- 假设 member 已有 UseCase Resolver（3.0+）+ DefineSubset（3.2+），本特性复用。
- 假设 DTO 计算字段在类上有 annotation（resolve_* 纪律），`model_fields` 含类型——已验证。
- 假设 join key 是 DTO 标量字段（派生自实体 FK），单字段（复合键后续）。
- 假设本期只读（DTO federation 是查询，不含跨 service mutation）。
- 假设 member public DTO 自包含（member 自己挂载跨 service，Resolver 加工时解析）。
