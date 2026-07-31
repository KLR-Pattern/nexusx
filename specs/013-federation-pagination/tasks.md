---

description: "Task list for nexusx 联邦分页(federation pagination)"
---

# Tasks: nexusx 联邦分页(Federation Pagination)

**Input**: Design documents from `/specs/013-federation-pagination/`(spec.md、plan.md、research.md、data-model.md、contracts/、quickstart.md)

**Prerequisites**: plan.md(required)、spec.md(required)、research.md、data-model.md、contracts/

**Tests**: plan.md 列出 5 个测试文件 + SC-001..006 可测,故纳入测试任务,故事内测试先写、先失败再实现(TDD)。

**Organization**: 按 user story 组织(US1 基础分页 / US2 items 子树递归 / US3 UUID·Decimal 对齐 / US4 渲染+零回归 / US5 fail-fast),每故事可独立实现与测试。核心难点(research R4:member executor root 路径)拆为 US1 v1(标量 items)+ US2(items 递归)两步隔离推进。

## Format: `[ID] [P?] [Story] Description`

- **[P]**:可并行(不同文件、无未完成依赖)
- **[Story]**:所属 user story(US1/US2/US3/US4/US5);Foundational/Polish 不带 story 标签
- 描述含**精确文件路径**

## 关键设计锚点(执行时参照)

- **控制粒度**:`RemoteRelationship.sort_field` 即分页开关(有→分页+排序,无→全量,对齐本地 `Relationship.order_by`);member 默认为每 batch key 生成全量 `by_<key>_in` + 分页 `by_<key>_in_page` 双 root,零配置。
- **wire**:分页 root `by_<key>_in_page(<key>_list, limit, offset, sort_field)`,page_args 是 batch 级标量;返回 per-key 分页包 `[{fk, items, pagination}]`;挂载方按 join key 对齐(不依赖顺序)。
- **核心难点(R4/FR-007)**:member executor 的 root 执行路径目前 entity-only,要让它认识分页 root 返回的 per-key 分页包、对 `items` 递归 BFS——把本地分页在"关系路径"(`_load_field_paginated` 的 `all_children.extend(items)` + `_serialize_relationship_value`)已有的机制搬到"root 路径"。隔离:仅 root 返回分页包时走分治,非分页 root(`by_filter`/`by_id`/全量 `by_<key>_in`)零影响。
- **total_count 可选(R6)**:仅客户端 selection 请求时算 COUNT OVER;否则只返 `has_more`。
- **零回归(US4/SC-004)**:未声明 `sort_field` 的远程关系走 012 全量路径,行为逐字节不变;既有 012 联邦 + 单体 nexusx 测试零回归。
- **本期不做**:γ path 声明式分页、护栏(cost-based 拒绝)——均 spec 显式排除。

---

## Phase 1: Foundational(阻塞性原语)

**Purpose**:所有 user story 都依赖的声明原语 + 内省暴露。本特性**不新增子包/依赖**(扩展 012 `federation/` + 既有 `standard_queries`/`executor`),无独立 Setup,声明原语直接归此阶段。

**⚠️ CRITICAL**:本阶段完成前不得开始任何 user story。

- [x] T001 [P] Add optional `sort_field: str | None = None` field to `RemoteRelationship`(携带可选排序方向,默认 ASC)in src/nexusx/federation/relationship.py
- [x] T002 [P] Extend `BatchRoot` with `paginated: bool = False` + `sort_field: str | None = None` in src/nexusx/federation/contract.py
- [x] T003 [P] Serialize paginated batch root in ER introspection(`BatchRoot.paginated`/`sort_field` 进 `batch_roots`,供挂载方识别 member 分页能力)in src/nexusx/federation/introspect.py(depends T002)

**Checkpoint**:分页声明字段 + 内省暴露就位,user story 可开始。

---

## Phase 2: User Story 1 — 跨服务 to-many 关系分页(基础,P1)🎯 MVP

**Goal**:声明 `sort_field` 的远程 to-many 关系,客户端传 `limit`/`offset`,member 返回 per-key 分页包,挂载方对齐成 `{items, pagination}`;每被挂服务仍一条 gql。

**Independent Test**(SC-001/SC-002):catalog+reviews,查分页 reviews(标量 items,int join key),断言条数/顺序/`has_more`/`total_count` 正确 + reviews 恰好收到一条分页 gql。

> **最小切片**:本故事先做"标量 items、不递归子树"(单/多 key int)。items 子树递归是 US2(下一个故事)。如此隔离 member root 路径的核心难点。

### Tests for User Story 1

- [ ] T004 [P] [US1] Write test_federation_pagination_decl.py:`RemoteRelationship.sort_field` 声明、`is_list` 派生、未声明→全量语义 in tests/test_federation_pagination_decl.py
- [x] T005 [P] [US1] Write test_federation_pagination_loader.py(int key):分页 gql 文档构造(`by_<key>_in_page` + batch 级 limit/offset/sort_field)、per-key 包按 join key 对齐成 `{items,pagination}`、`total_count` 可选、缺失 key→空包 in tests/test_federation_pagination_loader.py
- [ ] T006 [P] [US1] Write test_federation_pagination_root.py(member 侧):分页 root 返回 per-key 包识别、items(标量)序列化、`pagination` 透传、非分页 root 零影响 in tests/test_federation_pagination_root.py

### Implementation for User Story 1

- [x] T007 [US1] Implement `_create_by_keys_in_page_query`(默认每 batch key 生成 `by_<key>_in_page`;窗口函数 `PARTITION BY <key> ORDER BY <sort_field> <dir>` + peek-by-1 `has_more` + 可选 `COUNT(*) OVER` `total_count`)in src/nexusx/standard_queries.py(depends T002)
- [x] T008 [US1] **member executor root 路径识别分页包 v1**(`_execute_entity_group`:root 返回分页包→序列化 `{items,pagination}`;非分页 root 走原路径零影响)in src/nexusx/execution/query_executor.py(**核心难点 v1**,depends T007)
- [x] T009 [US1] Implement 分页 RemoteLoader(`build_gql_query` 分页变体 + page_args 从注入的 FieldSelection.arguments 作 batch 级标量透传 + per-key 包按 join key 对齐成 `{items,pagination}`)in src/nexusx/federation/remote_loader.py(depends T007)
- [x] T010 [US1] Wire mounter:`_wire_remote_relationship` 据 `RemoteRelationship.sort_field` 把分页 RemoteLoader 挂到 `RelationshipInfo.page_loader`(`sort_field` 透传)in src/nexusx/federation/manager.py(depends T001, T009)
- [x] T011 [US1] Wire mounter β path 分页分流:`_load_field_batch` is_remote 分支检测 `sort_field`→分页 RemoteLoader + `fetch_remote_subtree` 增 `page_args` 透传 in src/nexusx/execution/query_executor.py(depends T009, T010)
- [ ] T012 [US1] Write test_federation_pagination_e2e.py(catalog+reviews,int key,标量 items,via httpx ASGITransport):SC-001(分页正确)+ SC-002(每服务一条 gql)in tests/test_federation_pagination_e2e.py(depends T008–T011)

**Checkpoint**:US1 MVP 独立可测——基础分页端到端跑通,member root 路径识别验证通过(最高风险点的第一半)。

---

## Phase 3: User Story 2 — 分页关系的 items 带嵌套子树(P1)⚠️ 最高风险

**Goal**:分页远程关系的 `items` 内的子关系(本地 comments + 跨服务 author)由 member 一次 gql 解析返回;分页元数据不受子树影响。

**Independent Test**(SC-005):reviews 有 `Review.comments`(本地)+ `Comment.author`(跨 users),查分页 reviews 含 `items { comments { author } }`,断言子树正确 + 分页正确 + 仍一条 gql。

> 这是 research R4 的核心难点第二半:把 US1 的 root 路径识别扩展为对 `items` 递归。依赖 US1 的 root 路径骨架(T008)。

### Tests for User Story 2

- [ ] T013 [P] [US2] Extend test_federation_pagination_root.py:分页包 `items` 内实体递归解析子树(comments)+ `pagination` 不受子树影响 in tests/test_federation_pagination_root.py

### Implementation for User Story 2

- [ ] T014 [US2] **member executor root 路径对 items 递归**(把分页包 `items` 里的 entity extend 进 BFS 下一层,解析其本地关系 + 进一步跨服务 hop;复用本地分页 `_load_field_paginated` 的 `all_children.extend(items)` 模式)in src/nexusx/execution/query_executor.py(**核心难点 v2**,depends T008)
- [ ] T015 [US2] Extend test_federation_pagination_e2e.py(分页 reviews 含 comments + 跨服务 author):SC-005 in tests/test_federation_pagination_e2e.py(depends T014)

**Checkpoint**:US1+US2 均独立可测——分页 + 嵌套子树端到端(核心难点全通过)。

---

## Phase 4: User Story 3 — 多 parent 批量 + UUID/Decimal join key 对齐(P1)

**Goal**:多 parent 的分页关系在一条 batch 里 per-key 分页,UUID/Decimal 等 join key 不因跨 JSON 字符串化错配。

**Independent Test**(SC-003):N 个 Product(含 UUID 主键)查各自分页 reviews,断言每个 parent 拿到自己的页 + UUID 对齐正确。

### Tests for User Story 3

- [ ] T016 [P] [US3] Extend test_federation_pagination_loader.py:UUID/Decimal join key 的 per-key 包对齐(不因 JSON 字符串化错配)in tests/test_federation_pagination_loader.py

### Implementation for User Story 3

- [ ] T017 [US3] Apply `_normalize_join_key` to 分页 RemoteLoader 的 per-key 包对齐(UUID/Decimal 桶匹配)in src/nexusx/federation/remote_loader.py(depends T009)
- [ ] T018 [US3] Extend e2e(多 parent UUID 主键分页)in tests/test_federation_pagination_e2e.py(depends T017)

**Checkpoint**:US3 独立可测——UUID/Decimal 对齐正确(SC-003)。

---

## Phase 5: User Story 4 — field 声明 + member 零配置 + 现状零回归(P2)

**Goal**:声明 `sort_field` 的远程关系渲染为 `{items, pagination}`;未声明的扁平 list(012 行为);既有 012 联邦 + 单体零回归。

**Independent Test**(SC-004):同联邦 R1 声明 sort_field(分页)、R2 不声明(全量),SDL/Introspection 与实际返回形状一致;012 测试套件全过。

### Tests for User Story 4

- [ ] T019 [P] [US4] Write test_federation_pagination_render.py:声明 `sort_field` 的远程关系在 SDL/`__schema` 渲染为 `{items,pagination}`;未声明仍扁平 in tests/test_federation_pagination_render.py
- [ ] T020 [P] [US4] Add 零回归断言:既有 `tests/test_federation_*.py`(012 套件)+ 单体 nexusx 全量测试在本特性下仍通过(回归门)in tests/

### Implementation for User Story 4

- [ ] T021 [US4] Render 分页字段 in SDL(声明 `sort_field` 的远程 to-many 关系→`{items:[...], pagination:{has_more,total_count}}`)in src/nexusx/sdl_generator.py(depends T010)
- [ ] T022 [US4] Render 分页字段 in Introspection(`__schema` 同步)in src/nexusx/introspection.py(depends T010)
- [ ] T023 [US4] 混合回归 e2e:同联邦内分页 + 全量关系共存,行为分流正确 in tests/test_federation_pagination_e2e.py(depends T021, T022)

**Checkpoint**:US4 独立可测——渲染分页形状 + 既有零回归(SC-004)。

---

## Phase 6: User Story 5 — 启动期 fail-fast 校验(P2)

**Goal**:分页错配(to-one 声明分页、`sort_field` 非 member 合法字段)在入口服务启动期即拒绝。

**Independent Test**(SC-006):构造两类错配,断言启动失败且报错定位到声明。

### Tests for User Story 5

- [ ] T024 [P] [US5] Extend test_federation_pagination_decl.py:to-one 声明 `sort_field` 拒、`sort_field` 非合法标量字段拒 in tests/test_federation_pagination_decl.py

### Implementation for User Story 5

- [ ] T025 [US5] Add 分页 fail-fast checks in `federate()`/wiring:(a) 声明 `sort_field` 的关系是 to-many(FR-002);(b) `sort_field` 是被挂服务该类型的合法标量字段(FR-012b)。任一失败拒绝启动 in src/nexusx/federation/manager.py(depends T001, T003)

**Checkpoint**:US5 独立可测——分页错配启动期全捕获(SC-006)。

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**:跨故事收尾。

- [ ] T026 [P] Run `ruff check` + `mypy --strict` on src/nexusx + tests;修复所有告警
- [ ] T027 Run full regression `pytest -q`:SC-004(未声明 `sort_field` 时 012 联邦 + 单体 nexusx 全量测试零回归)
- [ ] T028 [P] Run quickstart.md validation(场景 1–5:基础分页 / items 子树 / UUID 对齐 / 零回归 / fail-fast)
- [ ] T029 [P] Docs:`docs/advanced/federation.md` 增分页章节(中英)+ `demo/federation` 演示分页查询(catalog 的 `Product.reviews` 声明 `sort_field`)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational(Phase 1)**:无依赖,立即开始;**阻塞所有 user story**。
- **User Stories(Phase 2+)**:均依赖 Foundational 完成。
- **Polish(Phase 7)**:依赖所有纳入的 user story 完成。

### User Story Dependencies

- **US1(P1, MVP)**:Foundational 完成后即可开始;不依赖其他故事。包含核心难点 v1(member root 路径识别分页包)。
- **US2(P1)**:依赖 US1 的 root 路径骨架(T008);在其上扩展 items 递归(核心难点 v2)。**最高风险**。
- **US3(P1)**:依赖 US1 的分页 RemoteLoader(T009);在其上扩展 UUID/Decimal 对齐。与 US2 彼此独立、可并行。
- **US4(P2)**:依赖 US1 的 wiring(T010,要有分页关系才能渲染);渲染层,与执行(US2/US3)正交。
- **US5(P2)**:依赖 Foundational(T001 声明 + T003 内省);校验层,独立小改。

### Within Each User Story

- 测试先写、先失败再实现(TDD)。
- 声明/数据原语 → member 端机械 → 挂载方 wiring/分流 → 端到端测试。
- 故事完成后在 checkpoint 独立验证,再进入下一优先级。

### Parallel Opportunities

- Foundational 的 `[P]` 任务(T001/T002/T003)可并行。
- 各故事的 `[P]` 测试任务可与同故事其他 `[P]` 任务并行。
- US2(items 递归)与 US3(UUID 对齐)在 US1 完成后可并行(不同关注、不同文件侧重)。
- US4(渲染)与 US2/US3(执行)正交,可并行推进。
- Polish 的 `[P]` 任务(T026/T028/T029)可并行。

---

## Parallel Example: Foundational + US1 Tests

```bash
# Foundational [P] 任务互不依赖、不同文件,可并行:
Task: "T001 RemoteRelationship.sort_field in src/nexusx/federation/relationship.py"
Task: "T002 BatchRoot +paginated/sort_field in src/nexusx/federation/contract.py"
# 之后顺序:T003(introspect 序列化,依赖 T002)
# → T007(分页 root)→ T008(root 路径 v1)→ T009(分页 RemoteLoader)→ T010/T011(wiring+分流)→ T012(e2e)

# US1 的 [P] 测试可与实现并行起草(先失败):
Task: "T004 [US1] test_federation_pagination_decl.py"
Task: "T005 [US1] test_federation_pagination_loader.py"
Task: "T006 [US1] test_federation_pagination_root.py"
```

---

## Implementation Strategy

### MVP First(US1 Only)

1. Phase 1 Foundational(关键阻塞)。
2. Phase 2 US1(基础分页,标量 items,int key)。
3. **STOP and VALIDATE**:SC-001/SC-002(分页正确 + 每服务一条 gql);专项验证 T008(member root 路径识别,核心难点 v1)。
4. 可演示:catalog 挂 reviews,分页取 reviews。

### Incremental Delivery

1. Foundational → 声明 + 内省暴露就位。
2. + US1 → 基础分页 MVP(可演示;核心难点 v1 验证)。
3. + US2 → 分页 + items 嵌套子树(核心难点 v2 全通过;最高风险)。
4. + US3 → UUID/Decimal 对齐。
5. + US4 → 渲染分页形状 + 既有零回归。
6. + US5 → 分页错配启动期全捕获。
7. Polish → 全量回归 + 文档/demo。

### Parallel Team Strategy

- Foundational 完成后:US2(items 递归)与 US3(UUID 对齐)可由不同人并行(均依赖 US1,彼此独立);US4(渲染)与执行层正交可穿插;US5 独立小改可穿插。

---

## Notes

- `[P]` = 不同文件、无未完成依赖。
- `[Story]` 标签映射到 spec.md 的 user story,便于追溯。
- 每 user story 独立可完成、可测试。
- 测试先写、先失败再实现。
- 每个任务或逻辑分组后 commit。
- 在任一 checkpoint 可停下独立验证该故事。
- 避免:模糊任务、同文件冲突、破坏独立性的跨故事依赖。
- **T008 + T014 是 research R4 钉牢的头号技术风险**(member executor root 路径:US1 识别分页包、US2 items 递归),实现时优先用 US1 最小切片验证 T008,再开 T014;全程确保非分页 root(`by_filter`/`by_id`/全量 `by_<key>_in`)零影响。
- **US4 的零回归(SC-004)是硬约束**:未声明 `sort_field` 的远程关系必须与 012 逐字节一致,每个故事完成后都应顺带跑一次 012 回归套件。
