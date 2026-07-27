---

description: "Task list for nexusx 多服务联邦(federation)"
---

# Tasks: nexusx 多服务联邦(nexusx-to-nexusx Federation)

**Input**: Design documents from `/specs/012-federation/`(spec.md、plan.md、research.md、data-model.md、contracts/、quickstart.md)

**Prerequisites**: plan.md(required)、spec.md(required)、research.md、data-model.md、contracts/

**Tests**: plan.md 明确列出 6 个测试文件 + SC-001..007 可测,故纳入测试任务,故事内测试先写、先失败再实现。

**Organization**: 按 user story 组织(US1 单跳 / US2 多跳 / US5 schema 渲染 / US3 fail-fast / US4 Voyager 徽标),每故事可独立实现与测试。

## Format: `[ID] [P?] [Story] Description`

- **[P]**:可并行(不同文件、无未完成依赖)
- **[Story]**:所属 user story(US1/US2/US3/US4/US5);Setup/Foundational/Polish 不带 story 标签
- 描述含**精确文件路径**

## 关键设计锚点(执行时参照)

- **拓扑**:相对组合,无 router;`er.federate(services={...})` 挂载,入口服务 per-query 编排。
- **schema 源**:ER 图信息(非 SDL);远程关系带 `target_service`+`target_endpoint`,挂载方传递式拉取(visited-set 去环)。
- **取数**:RemoteLoader 向被挂服务 `/graphql` 发**一条 gql 嵌套查询**(以 `by_<key>_in` 为入口),被挂服务自解析组合子图;每服务一次批量。
- **物化**:init 期(async)`create_model`,物化类 `__name__` = 裸 typename;`FederatedTypeRegistry` 持规范身份。
- **渲染(FR-017)**:`SDLGenerator`/`IntrospectionGenerator` 关系字段来源从 `get_type_hints` 改为 `loader_registry.get_relationships`,实体来源改为 `get_all_entities()`,远程目标→裸名。
- **校验**:7 项 init 期 fail-fast。

---

## Phase 1: Setup(共享基础设施)

**Purpose**:子包骨架 + 可选依赖。

- [x] T001 Create federation subpackage skeleton in src/nexusx/federation/(__init__.py 公开导出占位 + 空模块 relationship.py / registry.py / remote_loader.py / manager.py / introspect.py / http.py / contract.py)
- [x] T002 [P] Add optional extra `[federation] = ["httpx"]` to pyproject.toml,并在 federation 模块入口对 httpx 做 lazy-import 守卫(缺失时 `er.federate(...)` 抛明确 ImportError)

---

## Phase 2: Foundational(阻塞性原语 + 核心机械)

**Purpose**:所有 user story 都依赖的纯新增原语与核心机械。

**⚠️ CRITICAL**:本阶段完成前不得开始任何 user story。

- [x] T003 [P] Implement `RemoteRelationship` dataclass + `"srv.typename"` parser(parse → `("srv","typename")`,非 Python 类型)in src/nexusx/federation/relationship.py
- [x] T004 [P] Add `target_service: str | None = None` field to `RelationshipInfo` in src/nexusx/loader/registry.py(默认 None,既有本地关系构造路径不变)
- [x] T005 [P] Extend `get_custom_relationships` to also return `RemoteRelationship` entries in src/nexusx/relationship.py(与 `Relationship` 混列校验)
- [x] T006 [P] Implement `AutoQueryConfig.batch_keys` policy + `_create_by_keys_in_query`(生成 `by_<key>_in` root,`where field.in_(values)`)in src/nexusx/standard_queries.py
- [x] T007 [P] Define ER fragment wire types(pydantic:`ERIntrospectionResponse`/`EntityFragment`/`RelDescriptor`/`FieldDescriptor`,含 `target_service`/`target_endpoint`/`batch_roots`)in src/nexusx/federation/contract.py
- [x] T008 [P] Implement injectable httpx transport wrapper(便于测试用 ASGITransport)in src/nexusx/federation/http.py
- [x] T009 Implement ER introspection member-side serializer(`ErManager.get_all_entities()`+`get_all_relationships()` → fragment,loader 不序列化,远程关系带 service+endpoint)+ expose `GET /nexusx/er-introspection` route in src/nexusx/federation/introspect.py(depends T007)
- [x] T010 Implement `FederatedTypeRegistry`(规范名↔物化类、`create_model` 物化、`model_rebuild` namespace)in src/nexusx/federation/registry.py(depends T003, T007)
- [x] T011 Implement `RemoteLoader` factory(从 FieldSelection 构造 gql 嵌套文档、以 `by_<key>_in` 入口、httpx POST、按 join key 分组对齐、反序列化进物化类)in src/nexusx/federation/remote_loader.py(depends T008, T010)

**Checkpoint**:声明原语 + ER 端点 + 物化注册表 + RemoteLoader 就位,user story 可开始。

---

## Phase 3: User Story 1 — 单跳联邦取数(Priority: P1)🎯 MVP

**Goal**:catalog 挂 reviews,`{ product { reviews {...} } }` 返回正确嵌套结果,reviews 只被请求一次。

**Independent Test**(对应 SC-001/SC-003):catalog+reviews,查 N 个 product 的 reviews,断言结果正确 + reviews 服务恰好收到一条 gql 查询。

### Tests for User Story 1

- [x] T012 [P] [US1] Write test_federation_declaration.py:`RemoteRelationship` parse、`__relationships__` 识别(`get_custom_relationships` 返回)、`RelationshipInfo.target_service` 默认 None in tests/test_federation_declaration.py
- [x] T013 [P] [US1] Write test_federation_remote_loader.py(单跳):gql 文档构造、响应按 join key 对齐、缺失 key→None/[]、每 batch_load_fn 一条查询 in tests/test_federation_remote_loader.py

### Implementation for User Story 1

- [x] T014 [US1] Implement `federate()` orchestration core(单服务单跳:拉取一个服务 ER 片段 → 物化 → 注册 `RelationshipInfo`(target_service、fk_field=join_local、loader=RemoteLoader)→ 接入 ErManager)in src/nexusx/federation/manager.py(depends T009, T010, T011)
- [x] T015 [US1] Wire executor selection-aware loader channel + `target_service` routing:把 `FieldSelection` 传给远程 loader、按 `target_service≠None` 路由到 RemoteLoader in src/nexusx/execution/query_executor.py(depends T011)
- [x] T016 [US1] Add async `GraphQLHandler.federate(services=...)` 入口(lifespan 友好,物化后重建/刷新 SDL·Introspection·Executor 的实体来源)in src/nexusx/handler.py(depends T014)
- [x] T017 [US1] Write test_federation_e2e.py(单跳,catalog+reviews via httpx ASGITransport):SC-001(每服务一条)+ SC-003(N=1/N=100 调用次数均=1)+ 无过度取数 in tests/test_federation_e2e.py(depends T014–T016)

**Checkpoint**:US1 独立可测——单跳联邦端到端跑通,N+1 结构性不可能。

---

## Phase 4: User Story 2 — 多跳(跨服务)对客户端透明(Priority: P1)

**Goal**:`product { reviews { author { name } } }`(reviews/users 不同服务),客户端查询无前缀;catalog 对 reviews 一条查询(reviews 内部解析 author)。

**Independent Test**(SC-002):catalog+reviews(挂 users)+users,查多跳嵌套,断言无前缀 + catalog 对 reviews 一条 gql。

### Tests for User Story 2

- [x] T018 [P] [US2] Write test_federation_materialization.py:两遍物化、传递式 ER 拉取、跨远程引用 `model_rebuild` 解析、visited-set 去环 in tests/test_federation_materialization.py

### Implementation for User Story 2

- [x] T019 [US2] Extend `federate()`/`FederatedTypeRegistry`:传递式 ER 拉取(visited-set 去环)+ `RemoteEdge`(远程→远程边配置式声明,因不拥有远程类)in src/nexusx/federation/manager.py + src/nexusx/federation/registry.py(depends T014)
- [x] T020 [US2] Extend RemoteLoader:嵌套子选区整体转发(被挂服务自解析其组合子图,含其自身挂载的下游)in src/nexusx/federation/remote_loader.py(depends T011)
- [x] T021 [US2] Extend test_federation_e2e.py(多跳 catalog+reviews+users):SC-002(无前缀 + catalog 对 reviews 一条,author 由 reviews 内部解析)in tests/test_federation_e2e.py(depends T019, T020)

**Checkpoint**:US1 + US2 均独立可测——多跳透明端到端。

---

## Phase 5: User Story 5 — 客户端能内省并渲染完整联邦 schema(Priority: P1)

**Goal**:SDL + `__schema` 内省含所有远程物化类型(裸名)与跨服务关系字段;渲染字段集 = executor 可解析字段集。

**Independent Test**(SC-007):联邦启动后 `get_sdl()` + `get_introspection_data()` 含 `Review`/`User`/`Product.reviews`/`Review.author`(裸名),与注册表字段集逐类型一致。

> 注:US1/US2 的**执行**不依赖本故事(executor 按 registry dispatch,不依赖 SDL 校验);本故事是"客户端能发现字段"的渲染层,与执行层独立。

### Tests for User Story 5

- [x] T022 [P] [US5] Write test_federation_schema_render.py:SDL + Introspection 含远程类型/字段(裸名);渲染字段集 = executor 经注册表可解析字段集(逐类型一致)in tests/test_federation_schema_render.py

### Implementation for User Story 5

- [x] T023 [US5] Make `SDLGenerator` registry-driven:`_generate_type` 关系字段来源从 `get_type_hints` 改为 `loader_registry.get_relationships`;`generate()` 实体来源改为 `get_all_entities()`;远程目标经 `FederatedTypeRegistry` 解析为裸名 in src/nexusx/sdl_generator.py(depends T010)
- [x] T024 [US5] Make `IntrospectionGenerator` registry-driven:`_build_entity_type` 同步改造(关系字段读注册表、实体读 `get_all_entities()`、远程目标裸名)in src/nexusx/introspection.py(depends T010)
- [x] T025 [US5] Wire materialized remote entities into SDL/Introspection entity source(物化后让两 generator 覆盖 `get_all_entities()`)in src/nexusx/handler.py(depends T016, T023, T024)

**Checkpoint**:客户端可经 SDL/`__schema` 发现完整联邦图;渲染与执行同源。

---

## Phase 6: User Story 3 — 启动期 fail-fast 校验(Priority: P2)

**Goal**:七类错配在入口服务启动期即拒绝,无一进入运行时。

**Independent Test**(SC-004):逐项构造七类错配,断言启动失败且报错定位到声明。

### Tests for User Story 3

- [x] T026 [P] [US3] Write test_federation_validation.py:七类 fail-fast(未知 srv / typename 缺失 / join 字段缺失或不兼容 / 缺 by_<key>_in root / 前缀重复 / 跨服务裸名重复 / 不可终止环)in tests/test_federation_validation.py

### Implementation for User Story 3

- [x] T027 [US3] Implement seven fail-fast checks in `federate()` in src/nexusx/federation/manager.py(depends T019):(a) srv 已注册 (b) typename 存在 (c) join_remote 字段存在且类型与 join_local 兼容 (d) by_<join_remote>_in root 存在 (e) 前缀唯一 (f) 跨服务裸名不重复 (g) 传递式拉取检出不可终止环

**Checkpoint**:联邦错配启动期全捕获。

---

## Phase 7: User Story 4 — Voyager 展示完整联邦图,远程节点标归属(Priority: P3)

**Goal**:Voyager/ER 图含所有远程物化实体(裸名),每个远程节点标归属服务。

**Independent Test**(SC-006):catalog+reviews+users 联邦,Voyager 图含三类节点 + 跨服务边,远程节点带归属标注。

### Implementation for User Story 4

- [x] T028 [US4] Add ownership badge/label(规范名 `srv.typename`,不揉进类型名)to remote nodes in ER diagram in src/nexusx/voyager/er_diagram_dot.py(+ 渲染层若有需要)

**Checkpoint**:联邦图可视化,归属可辨。

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**:跨故事收尾。

- [x] T029 [P] Export federation public API(`RemoteRelationship`、`RemoteEdge`、`federate`、`by_<key>_in` 经 `AutoQueryConfig`)in src/nexusx/__init__.py
- [x] T030 Run `ruff check` + `mypy --strict` on src/nexusx + tests;修复所有告警
- [x] T031 Run full regression `pytest -q`:SC-005(未启用 federate 时既有 nexusx 全量测试零回归)
- [x] T032 [P] Run quickstart.md validation(V1–V7:启动/单跳/多跳透明/无过度取数/schema 渲染/fail-fast/单体零回归)
- [x] T033 [P] Docs:add federation guide to docs/ + README 一段说明(同构 nexusx 联邦,非通用 gateway)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup(Phase 1)**:无依赖,立即开始。
- **Foundational(Phase 2)**:依赖 Setup;**阻塞所有 user story**。
- **User Stories(Phase 3+)**:均依赖 Foundational 完成。
- **Polish(Phase 8)**:依赖所有纳入的 user story 完成。

### User Story Dependencies

- **US1(P1, MVP)**:Foundational 完成后即可开始;不依赖其他故事。
- **US2(P1)**:依赖 US1 的 `federate()` 核心(T014);在 US1 之上扩展传递式拉取与远程→远程边。
- **US5(P1)**:依赖 Foundational(`FederatedTypeRegistry` T010)与 US1 的 handler.federate(T016,物化后重建);与执行层(US1/US2)渲染/执行正交、可并行推进。
- **US3(P2)**:依赖 US2 的 `federate()` 扩展(T019,含传递式拉取,校验 g 项依赖它)。
- **US4(P3)**:依赖物化完成(US1);独立小改。

### Within Each User Story

- 测试先写、先失败再实现(TDD)。
- 声明/数据原语 → 服务/编排 → 集成 → 端到端测试。
- 故事完成后在 checkpoint 独立验证,再进入下一优先级。

### Parallel Opportunities

- Setup/Foundational 中所有 `[P]` 任务(T002–T008)可并行。
- 各故事的 `[P]` 测试任务可与同故事其他 `[P] 任务并行。
- US1(执行)与 US5(渲染)在 Foundational 后可由不同人并行推进(渲染/执行正交)。
- Polish 的 `[P]` 任务(T029/T032/T033)可并行。

---

## Parallel Example: Foundational

```bash
# 这些 [P] 任务互不依赖、不同文件,可并行:
Task: "T003 RemoteRelationship in src/nexusx/federation/relationship.py"
Task: "T004 target_service in src/nexusx/loader/registry.py"
Task: "T005 get_custom_relationships in src/nexusx/relationship.py"
Task: "T006 by_<key>_in in src/nexusx/standard_queries.py"
Task: "T007 ER fragment wire types in src/nexusx/federation/contract.py"
Task: "T008 httpx transport in src/nexusx/federation/http.py"
# 之后顺序:T009(introspect)→ T010(registry)→ T011(remote_loader)
```

---

## Implementation Strategy

### MVP First(US1 Only)

1. Phase 1 Setup + Phase 2 Foundational(关键阻塞)。
2. Phase 3 US1(单跳端到端)。
3. **STOP and VALIDATE**:SC-001/SC-003(每服务一条 gql、N+1 结构性不可能)。
4. 可演示:catalog 挂 reviews 取嵌套 reviews。

### Incremental Delivery

1. Setup + Foundational → 原语与机械就位。
2. + US1 → 单跳 MVP(可演示)。
3. + US2 → 多跳透明(可演示)。
4. + US5 → 客户端可内省完整 schema。
5. + US3 → 错配启动期全捕获。
6. + US4 → Voyager 联邦图。
7. Polish → 全量回归 + 文档。

### Parallel Team Strategy

- Foundational 完成后:US1(执行)与 US5(渲染)可并行;US2/US3 依赖 US1 串行;US4 独立小改可穿插。

---

## Notes

- `[P]` = 不同文件、无未完成依赖。
- `[Story]` 标签映射到 spec.md 的 user story,便于追溯。
- 每 user story 独立可完成、可测试。
- 测试先写、先失败再实现。
- 每个任务或逻辑分组后 commit。
- 在任一 checkpoint 可停下独立验证该故事。
- 避免:模糊任务、同文件冲突、破坏独立性的跨故事依赖。
- FR-017(US5,SDL+Introspection registry 化)与 research R4(handler async federate)是 plan 钉牢的两项头号技术风险,实现时优先验证。
