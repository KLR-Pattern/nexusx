# Tasks: DTO federation（UseCase 层 / γ 路径 federation）

**Input**: Design documents from `/specs/016-dto-tree-federation/`

**Organization**: 按 user story 组织（spec.md: US1 P1 / US2 P1 / US3 P2）。β 路径不动。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件，无未完成依赖）
- **[Story]**: 归属 user story（US1/US2/US3）；Foundational/Polish 无 story 标签

---

## Phase 1: Foundational（声明 + 数据结构 + 收集）

**Purpose**: public DTO 声明 + DTOFragment 数据结构 + ErManager 收集。**⚠️ 阻塞所有 story。**

- [X] T001 `SubsetConfig` 加 `federation_public: bool = False` + `federation_join_key: str | None = None` 字段；启动期校验（public=True → join_key 必填且 ∈ model_fields） in `src/nexusx/subset.py`
- [X] T002 [P] 定义 `DTOFragment`（对称 `EntityFragment`：name/base_entity/fields+类型/join_key/batch-root/remote_refs） in `src/nexusx/federation/contract.py`
- [X] T003 `ErManager` 启动期扫描 federation public DTO（显式 `dto_classes=` 参数，避免全局 `_subset_registry` 跨 member 污染），收集 public DTO 列表 in `src/nexusx/loader/registry.py`

**Checkpoint**: public DTO 可声明 + 收集，DTOFragment 数据结构就位。

---

## Phase 2: User Story 1 — member public DTO 自包含 + mounter γ 组合 (Priority: P1) 🎯 MVP

**Goal**: member public DTO 经 DTO batch root（跑 Resolver）+ 独立 introspection 端点暴露；mounter γ 物化 + RemoteLoader 取 DTO 树，组合成业务树。

**Independent Test**: 起 catalog + reviews（reviews 的 ReviewDTO public + 含 resolve_*），catalog UseCaseService RemoteRef reviews.ReviewDTO，查 composed_tree，断言返回 member 业务字段值。

- [ ] T004 [US1] member DTO batch root 生成（按 join_key 取实体 → 造 DTO 实例 → `er.create_resolver().resolve()` → 返 DTO 树），复用 standard_queries 的 batch root 框架 in `src/nexusx/standard_queries.py`
- [ ] T005 [P] [US1] 独立 DTO introspection 端点（序列化 public DTO → DTOFragment 列表，数据源 `_subset_registry` + `model_fields`；β ER introspection 不动） in `src/nexusx/federation/introspect.py`
- [ ] T006 [US1] mounter γ 物化 DTO RemoteRef（`compose_executor` 遇 DTOFragment → `create_model` 物化 DTO 类；跟实体物化同机制） in `src/nexusx/use_case/compose_executor.py`
- [ ] T007 [US1] RemoteLoader 取 DTO batch root（发 DTO batch root → member 返 DTO 树 → 按 join_key 对齐；复用 RemoteLoader 框架） in `src/nexusx/federation/remote_loader.py`
- [ ] T008 [US1] 端到端测试：member public DTO（subset + resolve_*）+ mounter γ 组合，断言 member 业务字段 + 自包含（含跨 service 出边解析） in `tests/test_dto_federation_e2e.py`

**Checkpoint**: γ 路径组合 member public DTO 端到端通（MVP）。

---

## Phase 3: User Story 2 — mounter 二次 resolve（member 值只读）(Priority: P1)

**Goal**: mounter 拿 member DTO 后 DefineSubset 选子集 + resolve_* 加字段，不改 member 业务值。

- [ ] T009 [US2] 测试：mounter DefineSubset member DTO + resolve_* 加字段（读 member 值算新字段），断言 member 值不被覆盖 in `tests/test_dto_federation_e2e.py`

**Checkpoint**: member 值只读契约生效（现有 Resolver/DefineSubset 纪律保证）。

---

## Phase 4: User Story 3 — join 复用（DTO FK 派生自实体）(Priority: P2)

**Goal**: DTO 的 FK 派生自实体（subset），RemoteLoader 按 FK batch join，复用 γ 机制。

- [ ] T010 [US3] 测试：DTO subset of 实体（含 FK），mounter 按 FK batch join member public DTO，机制同 RemoteLoader in `tests/test_dto_federation_e2e.py`

**Checkpoint**: join 复用（subset of ER 的红利）。

---

## Phase 5: Polish & Cross-Cutting

- [ ] T011 [P] 回归：β 路径（ER federation）不受影响（`test_federation_e2e` / `test_federation_pagination_e2e` / `test_federation_nested_local_pagination` 全绿）+ 012-014 + 5.0.1 零回归 in `tests/`
- [ ] T012 [P] demo 可选：federation demo 加 public DTO（如 reviews 的 ReviewDTO），演示 γ 路径组合 in `demo/federation/`
- [ ] T013 [P] 文档：技术文档已由 `specs/016/contracts/dto-federation.md` + `quickstart.md` 覆盖；`docs/advanced/` 用户教程作为后续

---

## Dependencies & Execution Order

- **Foundational (T001-T003)**: 阻塞所有 story
- **US1 (T004-T008)**: 依赖 Foundational；T004(member batch root) → T007(RemoteLoader 取) → T008(端到端)
- **US2 (T009)**: 依赖 US1（mounter 能取 DTO 后才测二次 resolve）
- **US3 (T010)**: 依赖 US1
- **Polish (T011-T013)**: 依赖所有 story

### MVP scope

Foundational + US1 = member public DTO 经 γ 组合端到端通。US2/US3 + Polish 增量。

---

## Notes

- β 路径（ER federation）全程不动——sdl_generator / SQLModel GraphQL 直查 / ER introspection 不碰
- member 值只读靠现有 Resolver/DefineSubset 纪律（resolve_* 加字段不覆盖、DefineSubset 选字段不改值）
- DTOFragment 收集可行性已验证（_subset_registry + model_fields，spec SC-004）
- member public DTO 自包含（member 自己挂载跨 service，Resolver 加工时解析出边）

---

## US1 实现续点（Foundational 后，2026-08-02）

**Foundational（T001-T003）已完成 @ commit `81c072e`，1379 测试零回归。**

### 实现偏离 spec 之处（已决策）

- **T003 用显式 `dto_classes=` 参数**（非 spec 字面的"扫描全局 `_subset_registry`"）。理由：同进程多 app（demo catalog+reviews+users、co-located 测试）下，全局扫描会让 member A 的 DTO introspection 漏出 member B 的 public DTO。`dto_classes=` 对称于 `entities=`，由 `GraphQLHandler` 透传。`ErManager.get_public_dtos()` 从 `dto_classes` 过滤 `__federation_public__=True`。
- **SubsetConfig 字段是 `kls`**（`src/nexusx/subset.py:420`），不是 contracts/quickstart/data-model 笔误的 `source=`。demo/测试用 `kls=Entity`。
- **DTO federation 元数据 stamp**：`SubsetMeta` 把 `__federation_public__` / `__federation_join_key__` stamp 到 DTO class（tuple 语法 DTO 默认 False），`get_public_dtos()` 读它。

### US1（T004-T008）4 个硬架构问题

1. **T004 DTO batch root 暴露**：DTO 不在 `entities`，`MethodScanner`（`src/nexusx/scanning.py`）扫的是 entity `@query` 方法 → GraphQL query root。DTO batch root（按 join_key 取实体 → 造 DTO → `er.create_resolver().resolve()` → 返 DTO 树）怎么进 query root？候选：挂 DTO class 上加 `@query` + 扩 MethodScanner 扫 `er.get_dto_classes()`，或独立注册路径。
2. **T006 federate 拉 DTO introspection + 物化**：`federation/manager.py` 的 `federate()` 现状拉 ER introspection 物化 entity。要加：拉 DTO introspection（DTOFragment 列表）→ `create_model` 物化 DTO 类。`RemoteRef reviews.ReviewDTO` 解析顺序：先查 DTO introspection（DTO），再查 ER introspection（entity）。
3. **T007 RemoteLoader 取 DTO 树**：`federation/remote_loader.py` 现状发实体 batch root（`by_<key>_in`）取实体再物化成 DTO。要改成发 DTO batch root 取**已 resolve 的 DTO 树**（member 返的），按 join_key 对齐到 mounter 物化的 DTO 类。
4. **mounter 物化 DTO ↔ RemoteRef 对齐**：`DTOFragment.name` → `create_model` → `reviews.ReviewDTO` 引用解析到物化类。

### US1 需读文件（fresh context 起手）

- `src/nexusx/scanning.py`（MethodScanner — T004 暴露机制）
- `src/nexusx/federation/manager.py`（federate — T006 物化）
- `src/nexusx/federation/remote_loader.py`（T007 取 DTO）
- `src/nexusx/federation/remote_ref.py`（RemoteRef/RemoteService — 引用解析）
- `src/nexusx/use_case/compose_executor.py`（γ 物化分派）

### demo 续点（T012）

- `demo/federation/reviews_app.py`：加 public `ReviewDTO`（`subset of Review` + `resolve_*`，`federation_public=True` + `federation_join_key="product_id"`）+ `GraphQLHandler(dto_classes=[ReviewDTO])`
- `demo/federation/catalog_app.py`：`ProductDTO.reviews: list[reviews.ReviewDTO]`（member public DTO，非现状的实体 RemoteRef）
- 参考：现状 catalog 的 `ReviewDTO`（line 170）是 mounter 端 subset of 远程**实体**；016 改成 member 端 public DTO，mounter 引用它
