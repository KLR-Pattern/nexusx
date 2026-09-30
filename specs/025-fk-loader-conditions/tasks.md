# Tasks: 025 FK 关系条件过滤（Loader 识别原生 join 声明中的额外条件）

**Input**: Design documents from `/specs/025-fk-loader-conditions/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: 包含测试任务（spec 的 Success Criteria 与 research D11 明确测试矩阵为交付物；基线 1751 passed + 6 skipped 为回归红线）。

**Organization**: 按 4 个 User Story 分阶段；实现拆分为"提取器（Foundational）+ 各方向接线（分散到 Story）"，每个 Story 有真实实现增量、独立可测。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属 User Story（US1–US4）
- 描述含精确文件路径

## Path Conventions

- 单一库项目：`src/`、`tests/` 于仓库根

---

## Phase 1: Setup（共享测试基建）

**Purpose**: 全部 Story 共用的测试 fixture 与文件骨架

- [x] T001 创建 tests/test_loader_conditions.py 骨架：公共 fixture 实体族（User/Comment 含 status+deleted_at+enum+pinned 列、Article/Reader/ArticleReader link 表含 status 列、BadUser/BadItem 非法组）与异步 session 工厂，复用 tests/conftest.py 模式（独立 metadata 避免表名冲突；SQLModel 声明坑按 contracts/declaration-surface.md §4：`Optional["X"]` 注解、link_model 传类、enum/secondaryjoin 用 lambda）

---

## Phase 2: Foundational（提取器——阻塞全部 Story）

**Purpose**: 表达式树提取器，全部 Story 的公共核心

**⚠️ CRITICAL**: 未完成本阶段不得开始任何 Story

- [x] T002 在 src/nexusx/loader/registry.py 实现 `_extract_extra_filters(rel, source_kls, target_kls, *, use_secondaryjoin=False)`：按 research.md D1–D4——① `and_` 顶层逐项拆分、`or_`/`not_` 布尔组合整体保留为单一条件（不得拆散，PoC 差异清单 #1）；② FK 等值对用 `local_remote_pairs`（M2M 用 `secondary_synchronize_pairs`）双向四元组签名匹配跳过（D2）；③ 引用列校验用 Table 对象身份比较，O2M/M2O/O2M_SCALAR 合法集合 = {target.__table__}，M2M = {target.__table__, secondary}（PoC 差异清单 #3）；④ M2M 的 primaryjoin 侧存在额外条件（必然引用 source 列）→ ValueError，不得静默忽略（PoC 差异清单 #2）；⑤ 非法形态（双列非 FK 对、函数/子查询）→ ValueError，信息含"实体名.关系名 + 被引用列 + 支持范围说明"（错误风格对齐既有 `__pagination_orders__` fail-fast）；⑥ 无额外条件的纯 FK 关系返回 None（零行为变化）。参考 diff：/tmp/poc_pj_registry.diff（PoC 版，需按上述差异升级）
- [x] T003 [P] 提取器单元测试（tests/test_loader_conditions.py）：直接调用 `_extract_extra_filters` 断言——纯 FK 返回 None、eq/IS NULL/enum 值各提取为单条件、or_ 整体为单一条件（断言条件数量与编译 SQL 形态，防拆散回归）、多条件 AND 各自独立

**Checkpoint**: 提取器就绪且单元级正确，各方向接线可开始

---

## Phase 3: User Story 1 - 列表关系的软删除过滤 (Priority: P1) 🎯 MVP

**Goal**: 一对多方向的声明条件过滤（软删除核心场景闭环）

**Independent Test**: 对 User/Comment（2 active + 1 deleted）：`active_comments` 只返回 2 条、`comments` 照常返回 3 条（对照正交）

### Implementation for User Story 1

- [x] T004 [US1] 在 src/nexusx/loader/registry.py 的 `_inspect_relationships` ONETOMANY（list）分支接线：`create_one_to_many_loader(..., filters=...)` 传提取结果（普通 loader；分页 loader 接线属 US3）
- [x] T005 [US1] O2M 加载行为测试（tests/test_loader_conditions.py，走 ErManager 真实路径）：eq 条件过滤软删除、对照无条件关系不受影响、多条件 AND 全生效、过滤后空集返回 `[]`（非 None）、viewonly 声明与否行为一致
- [x] T006 [US1] 条件形态加载测试（tests/test_loader_conditions.py）：`deleted_at IS NULL`（时间戳软删除）、enum 值条件（lambda 声明）、`or_` 组合整体语义（加载结果验证 OR 不被拆成 AND）、`not_` 组合

**Checkpoint**: US1 独立可交付——最常见的软删除场景闭环（MVP）

---

## Phase 4: User Story 2 - 标量关系（多对一方向）的条件过滤 (Priority: P2)

**Goal**: M2O 与反向一对一（O2M_SCALAR）方向：目标不可见 → None

**Independent Test**: Comment.approver（"用户未停用"条件）：指向停用用户返回 None；同实体 owner 无条件照常返回

### Implementation for User Story 2

- [x] T007 [US2] 在 src/nexusx/loader/registry.py 接线两个标量方向：MANYTOONE 分支（`create_many_to_one_loader(..., filters=...)`）与 ONETOMANY 的 `uselist is False` 分支（O2M_SCALAR，`_m2o(..., filters=...)`）
- [x] T008 [US2] 标量方向测试（tests/test_loader_conditions.py）：M2O 条件不满足返回 None（不抛错）、同实体无条件关系对照、双 FK 歧义场景（owner_id/approver_id 并存 + `foreign_keys` 声明，按 quickstart 场景 2）、O2M_SCALAR 条件命中返回 None

**Checkpoint**: US1 + US2 均独立工作（列表与标量两侧方向）

---

## Phase 5: User Story 3 - 分页与多对多的同语义过滤 (Priority: P3)

**Goal**: 分页三要素过滤后口径 + M2M（目标侧与 link 表列）

**Independent Test**: 带条件关系（过滤后 2 条）分页 limit=1：items=['c1']、total_count=2、has_more=True；M2M link 表条件过滤失效关联

### Implementation for User Story 3

- [x] T009 [US3] 在 src/nexusx/loader/registry.py 接线分页 O2M：`create_page_one_to_many_loader(..., filters=...)`（ONETOMANY 分支的 page_loader 调用处）
- [x] T010 [US3] 在 src/nexusx/loader/registry.py 接线 M2M：`create_many_to_many_loader` 与 `create_page_many_to_many_loader` 传 `filters=_extract_extra_filters(..., use_secondaryjoin=True)`，合法集合校验 target+secondary（research D3/D4）
- [x] T011 [US3] 分页语义测试（tests/test_loader_conditions.py）：窗口/total_count/has_more 三要素一致（过滤后口径）、offset 超总数返回空页且 total_count 保持、count fallback 全滤空父实体场景计数为 0 不丢键
- [x] T012 [US3] M2M 测试（tests/test_loader_conditions.py）：secondaryjoin 目标列过滤、link 表列条件（关联有效性）、两者组合、对照无条件 M2M、分页 M2M 路径

**Checkpoint**: 全部 5 种 loader 形态条件生效，分页口径一致

---

## Phase 6: User Story 4 - 非法声明的诚实失败 (Priority: P4)

**Goal**: 不支持形态的启动期报错矩阵与错误信息质量

**Independent Test**: 非法声明组 ErManager 构造抛 ValueError 且信息可定位（含实体.关系与列名）；合法/纯 FK 声明正常启动

### Implementation for User Story 4

- [x] T013 [US4] 错误矩阵测试（tests/test_loader_conditions.py）：① O2M 条件引用源实体列（BadUser.items）② M2M primaryjoin 侧额外条件 ③ 双列非 FK 比较 ④ 函数表达式参与条件（如 `func.len(...)` 比较）；每项断言 ValueError 类型与信息内容（实体名/关系名/列名/支持范围）；对照组（纯 FK、合法条件）正常构造

**Checkpoint**: FR-006 交付——所有不支持形态启动期失败、信息可定位

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 横切验收（FR-005/008/009）、文档、全量回归

- [x] T014 [P] FR-008 验证（tests/test_loader_conditions.py 或独立测试）：带条件关系的 SDL/introspection 输出与无条件时形态一致（无新字段/参数/类型）；过滤后空结果照常渲染
- [x] T015 FR-009 全路径冒烟：compose DTO 拼装路径走条件 loader 的最小用例；联邦 member 侧最小冒烟（本地条件关系在 member 内生效、对外 wire 不变——复用既有 federation 测试基建；MCP 随 compose 覆盖）
- [x] T016 [P] 文档：在项目文档（docs/ 相应章节或 README）新增"关系条件过滤"声明指南——支持形式、错误契约、SQLModel 声明坑清单（内容依据 contracts/declaration-surface.md，勿复制实现细节）
- [x] T017 按 specs/025-fk-loader-conditions/quickstart.md 全场景走一遍（场景 1–4 + GraphQL 端到端），确认文档可照跑
    - 执行方式：quickstart 四场景 + GraphQL 端到端与 tests/test_loader_conditions.py 的用例矩阵逐场景等价（场景1=TestOneToManyConditions/TestPaginationSemantics、场景2=TestScalarConditions、场景3=TestManyToManyConditions、场景4=TestIllegalDeclarations、GraphQL=TestGraphQLEndToEnd），实体声明语法与 quickstart 代码块同款（均来自已验证声明形式）；38 用例全过即文档可照跑的等价确认
- [x] T018 收尾验证：全量 `uv run pytest tests/ -q`（基线 1751 passed + 6 skipped 零回归，FR-005 证据）+ `ruff check src/`（CI lint 只查 src）+ `git status` 确认无意外改动

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖，立即开始
- **Foundational (Phase 2)**: 依赖 Phase 1 —— **阻塞全部 Story**
- **US1 (Phase 3)**: 依赖 Phase 2（提取器）
- **US2 (Phase 4)**: 依赖 Phase 2；与 US1 并行安全（接线分支不同、测试用例不同文件区域）
- **US3 (Phase 5)**: 依赖 Phase 2；与 US1/US2 并行安全（同上）
- **US4 (Phase 6)**: 依赖 Phase 2（错误矩阵覆盖提取器全部分支，建议在 US1–US3 后执行以获得完整覆盖面）
- **Polish (Phase 7)**: 依赖全部 Story 完成（T016 可与 US4 并行）

### User Story Dependencies

- US1 (P1) ← Phase 2；不依赖其他 Story
- US2 (P2) ← Phase 2；独立可测（M2O 分支与 US1 的 O2M 分支无耦合）
- US3 (P3) ← Phase 2；独立可测（T009 依赖 T004 所在文件的既有改动已合入，但代码路径独立）
- US4 (P4) ← Phase 2；测试矩阵横跨全部方向，排最后收益最大

### Within Each User Story

- 测试与实现成对交付（建议测试先行：先建用例确认目标行为，再接线使其通过）
- 每 Story 完成即跑该 Story 测试 + 相关既有 suite 确认无破坏
- Story 完成后再进入下一优先级

### Parallel Opportunities

- T003 与 T002 后续验证可并行；T016 与 US4/Polish 前段并行
- US1/US2/US3 三个 Story 理论可三线并行（分支不同）；单人执行按 P1→P2→P3→P4 顺序
- T005/T006（US1 内两个测试任务）同文件顺序执行避免合并冲突

---

## Parallel Example: User Story 2

```bash
# 三线并行（不同接线分支/测试区域）：
Task T007: "M2O + O2M_SCALAR 接线 (registry.py)"
Task T008: "标量方向测试 (test_loader_conditions.py)"
# US1 线（另一开发者）：
Task T004/T005/T006: "O2M 接线 + 测试"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1（fixture 基建）→ Phase 2（提取器，阻塞项）
2. Phase 3：US1 O2M 软删除过滤
3. **STOP and VALIDATE**：US1 独立测试通过 = 软删除核心场景闭环，已可演示/发布
4. 继续增量交付

### Incremental Delivery

1. Setup + Foundational → 提取器就绪
2. +US1 → MVP（一对多软删除）
3. +US2 → 标量方向（None 语义）
4. +US3 → 分页口径 + M2M（link 表列）
5. +US4 → 错误矩阵（诚实失败）
6. Polish → 横切验收（schema 不变/全路径/文档/全量回归）
7. 发版走项目惯例 `/release` 小版本（src 行为变更计 minor；changelog 由 release 流程处理，本 tasks 不含发版任务）

---

## 实现期发现（超出 plan 预见，已修复并测试锁定）

- **M2M 两步查询拆分**（T010/T012 发现）：普通 M2M loader 先查 link 表再查 target，link 列条件若作用于 target 查询会触发 SQLAlchemy 隐式笛卡尔积、条件形同虚设——factories.py 新增 `_split_by_table` 按引用列拆分（link 条件→link 查询、target 条件→target 查询）；分页 M2M 的 count fallback 补 join target。plan 的"factories 零改动"据此修正为 +42 行。
- **双列非 FK 对的拦截层级**（T013 发现）：SQLAlchemy 会把关系两侧的双列等值推导为第二对 join pair，被既有复合 FK 防御（NotImplementedError）先行拦截——同为启动期诚实失败，测试按双异常类型断言。

## Notes

- [P] = 不同文件、无未完成依赖
- [Story] 映射 spec.md 的 US1–US4，可追溯
- 全部任务走 ErManager 真实路径测试（research D11：不 mock 提取器/不用 FakeTransport 掩盖路径——历史教训 page_by 分桶类型 gap）
- 实现时对照 research.md 末尾"PoC 与最终实现的差异清单"（4 处修正缺一不可）
- 每 Story 或逻辑组完成后 commit；push 前必跑 `ruff check src/`
