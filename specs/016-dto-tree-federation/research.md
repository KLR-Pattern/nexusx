# Research: DTO federation（UseCase 层）

**Feature**: specs/016-dto-tree-federation
**Date**: 2026-08-02

## 背景

spec + clarify 已定两条架构决策（见 spec.md `## Clarifications / Session 2026-08-02`）：
1. public 标记 = SubsetConfig federation 参数（声明式，跟 DTO 定义同处）
2. introspection = 独立 DTO introspection 端点（β ER introspection 不动）

本 research 解决 plan 级实现决策（spec 标"留 plan"或未明示的）。

## 决策

### D1: DTOFragment 序列化的具体字段

**决策**: DTOFragment 对称 EntityFragment，字段 = name / base_entity / fields(含类型) / join_key / batch_root / remote_refs。

**理由**: EntityFragment（012）已序列化实体形状（scalar_fields + relationships + batch_roots）。DTOFragment 对称——name(`__name__`) / base_entity(`_subset_registry[DTO]`) / fields+类型(`model_fields`) / join_key(SubsetConfig `federation_join_key`) / batch_root(生成的 DTO by_<key>_in) / remote_refs(`__relationships__`)。mounter 物化 DTOFragment 跟物化 EntityFragment 同机制（create_model）。

### D2: member DTO batch root 怎么生成

**决策**: 复用 standard_queries 的 batch root 生成框架，扩展一个"DTO batch root"——内部跑 er.create_resolver().resolve()。

**理由**: standard_queries 已生成 by_<key>_in（实体 batch root，SQL 直查）。DTO batch root 同结构（按 join_key 批量），但内部"取实体 → 造 DTO 实例 → er.create_resolver().resolve() → 返 DTO 树"。Resolver 是 ErManager 能力（er.create_resolver()），不经 UseCaseService。mounter 的 RemoteLoader 发 DTO batch root（跟发 by_<key>_in 对称），member 返 DTO 树。

### D3: mounter γ 路径怎么物化 + 取 DTO

**决策**: compose_executor（γ）扩展——遇到 RemoteRef 指向 DTOFragment（而非 EntityFragment）时，物化成 DTO 类（create_model from DTOFragment），RemoteLoader 发 DTO batch root 取数。

**理由**: γ 路径（UseCaseService + Resolver）已用 RemoteLoader 取远程实体（catalog composed_tree）。DTO 版区别：远程数据是 DTO 树（member Resolver 加工），不是实体。mounter 物化 DTO 类（from DTOFragment），RemoteLoader 发 DTO batch root（member 返 DTO 树）。Resolver 组合——DTO 树作为 mounter DTO 的 field 数据，mounter 可二次 resolve。

### D4: member DTO 自包含（跨 service 出边）怎么实现

**决策**: member public DTO 的 resolve_*（含跨 service RemoteRef，如 .author → users.UserDTO）在 member 端 Resolver 跑。member 自己是 federation mounter（挂载 users），er.create_resolver() 解析跨 service 出边。member DTO batch root 返自包含树。

**理由**: member 的 er.create_resolver() 已经能解析跨 service（012 传递式 federation）。DTO 的 resolve_* 跨 service 出边 = member 端 federation（member 挂载其他 service）。member DTO batch root 跑 Resolver 时，跨 service 出边被解析（member → users）。返自包含 DTO 树（含 author）。

### D5: SubsetConfig federation 参数的默认值

**决策**: `federation_public: bool = False`（默认非 public），`federation_join_key: str | None = None`（public=True 时必填）。

**理由**: 默认非 public（member 的 DTO 大多内部用，不暴露 federation）。public=True 时 federation_join_key 必填（federation 要 join key 取数）。SubsetConfig 加这两个字段，向后兼容（现有 SubsetConfig 不带 federation 参数 = 非 public）。

## 不需研究的项（已明确）

- **DTO 不进 ER diagram**: spec FR-009 已定。DTO introspection 独立端点（clarify Q2），ER introspection 不碰。
- **member 值只读**: spec FR-006 已定，现有 Resolver/DefineSubset 纪律保证。
- **β 不动**: spec FR-008 已定，SQLModel GraphQL 直查/SDL 不改。
- **收集可行性**: _subset_registry + model_fields，已验证（spec SC-004）。
