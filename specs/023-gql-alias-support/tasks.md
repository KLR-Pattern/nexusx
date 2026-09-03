# Tasks: GraphQL Alias 支持（修复静默折叠）

**Input**: Design documents from `/specs/023-gql-alias-support/`

**Prerequisites**: plan.md ✅、spec.md ✅、research.md ✅、data-model.md ✅、contracts/ ✅、quickstart.md ✅

**Tests**: 测试任务保留——spec 的 SC-001~006 全部为自动化断言，quickstart.md 即验证场景清单。各 story 测试任务前置（先写、确认失败、再实现）。

**Organization**: 按用户故事分组（US1 止血 → US2+US4 query 侧与联邦边界 → US3 mutation 侧），每阶段末有回归检查点，可独立交付。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1/US2/US3/US4，映射 spec.md）
- 描述含精确文件路径

## Path Conventions

单库结构：`src/nexusx/` + `tests/`（仓库根）。

---

## Phase 1: Setup（基线）

**Purpose**: 确认回归基准，供 SC-005 对照

- [x] T001 运行全量基线：`uv run pytest tests/ -q` 全过并记录用例数；`ruff check src/` 通过（此数为零回归基准）

---

## Phase 2: User Story 1 - 不支持的别名必须明确报错（Priority: P1）🎯 MVP

**Goal**: compose 路径收到任何别名即返回带位置的错误，消灭静默丢弃；可独立发布止血（约半天）

**Independent Test**: 对 compose 查询入口发送带别名的 query/mutation，断言 `errors` 非空且服务方法零调用（调用日志断言）

### Tests for User Story 1（先写、确认失败）

- [x] T002 [P] [US1] 在 tests/test_compose_executor.py 增加负向用例：别名 query / 别名 mutation / 嵌套别名三种形态 → 响应 `errors` 含"别名不支持"且 `extensions.code: "ALIAS_CONFLICT"`；用方法调用计数断言零执行

### Implementation for User Story 1

- [x] T003 [US1] 在 src/nexusx/use_case/compose_executor.py 的 `execute_compose_query` 步骤 2（introspection 拒绝）之后新增 AST 级别名检测：遍历 `document` 各层选择集，发现任何 alias → 返回 `_error_response`（错误信息标注"当前版本 compose 查询暂不支持别名"，供后续阶段放宽时改写）

**Checkpoint**: US1 独立可交付（PR 可先发）；quickstart 场景 4 的 compose 半边应通过

---

## Phase 3: User Story 2 + 4 - query 侧方法级别名 & 联邦边界（Priority: P2）

**Goal**: query 方法级别名全链路生效（两次执行、响应键=别名、投影隔离、冲突报错）；联邦 wire 保证永不含别名（member 零改动）

**Independent Test**: 发送 `high/low` 两个不同参数的别名查询，两条路径都返回两组正确结果；联邦矩阵中 member 收到的查询字符串零别名

### Tests for User Story 2 & 4（先写、确认失败）

- [x] T004 [P] [US2] 在 tests/test_query_parser.py 增加：key=`alias or name` 语义用例（别名保留、参数/子字段隔离）+ 冲突三形态（别名重复、别名撞字段名、无别名同名字段重复）+ 顶层分组重复，均断言明确报错
- [x] T005 [P] [US2] 在 tests/test_compose_executor.py 增加：query 扇出（两别名不同参数各自执行、结果分组正确）、同方法同参数不去重（FR-011 query 半边）、单别名失败不影响兄弟别名
- [x] T006 [P] [US2] 在 tests/test_query_executor.py 增加：entity-first query 别名（执行次数=N、参数各自正确、响应键=别名、各别名按自己声明的子字段投影）
- [x] T007 [P] [US4] 在联邦测试矩阵（tests/test_federation_remote_loader.py 等）增加 wire 断言：FakeTransport/HTTP 捕获层断言发往 member 的查询字段区零别名（覆盖 β 物化、γ DTO、分页三路径）

### Implementation for User Story 2 & 4

- [x] T008 [US2] 在 src/nexusx/query_parser.py 修改 `_parse_selection_set`：dict key 改为 `alias or field_name`；插入同层响应键冲突检测（重复 key 抛带位置错误）；`parse_document` 顶层 operation 级同族检测
- [x] T009 [US2] 在 src/nexusx/use_case/compose_executor.py 适配：`_execute_service_methods` 方法查找改用 `method_sel.name`（约 :185/:189），响应键沿用 dict key（约 :221/:225）；mutation 别名保留 US1 的拒绝闸门（本阶段仅放行 query，见 contracts 阶段交付语义表）
- [x] T010 [P] [US2] 在 src/nexusx/execution/query_executor.py 适配：`field_sel` 查找改为 `alias or method_name`（约 :207），响应键 `entity_data` 改用别名（约 :268）
- [x] T011 [P] [US4] 在 src/nexusx/federation/remote_loader.py 修改 `_render_selection`（约 :247）：渲染字段名一律用 `child.name`（原始字段名），不透传 dict key（联邦边界闸门，member 零改动）
- [x] T012 [P] [US2] 移除 src/nexusx/handler.py:324 的 `validate_no_aliases` 内部调用；更新 src/nexusx/query_parser.py:83 docstring（函数保留原语义，用途改为外部可选校验工具，见 research D5）
- [x] T013 [US2] 嵌套层与 CLI 显式报错：entity-first lenient 路径（src/nexusx/core_builder.py `build_model` 或其调用上层）检测嵌套别名并明确报错（替代静默 `Any`）；src/nexusx/use_case/selection.py `parse_selection` 显式拒绝别名（CLI `--select`，给清晰错误而非"未知字段"）
- [x] T014 [US2] 阶段检查点：全量 `uv run pytest tests/ -q` 零回归 + `ruff check src/`；quickstart 场景 2/4/5 通过

**Checkpoint**: query 侧 + 联邦边界完成；mutation 别名仍按 US1 报错（阶段语义正确）

---

## Phase 4: User Story 3 - Mutation 侧方法级别名（Priority: P3）

**Goal**: mutation 别名按声明顺序串行全执行、三态反馈（已成功保留/失败独立报错/跳过标注）；entity-first 整组作废语义同步移除

**Independent Test**: 发送 3 个别名 add_node（第 2 个制造失败）：节点 1、3 正常创建且按别名返回，节点 2 有 `MUTATION_FAILED` 条目；两路径行为一致

### Tests for User Story 3（先写、确认失败）

- [x] T015 [P] [US3] 在 tests/test_compose_executor.py 增加：Issue #140 端到端复现（N 个别名 add_node 全建全返回，SC-006）、部分失败三态（失败键 null + `MUTATION_FAILED`、后续 `SKIPPED_PRIOR_FAILURE`）、同方法同参数 N 次 = N 次副作用（FR-011 mutation 半边）、`enable_mutation=False` 拒绝与调用次数正交
- [x] T016 [P] [US3] 在 tests/test_query_executor.py 增加：entity-first 三态与 compose 一致用例；同步更新依赖"整组 null"的存量用例（D4 行为变更的回归面）

### Implementation for User Story 3

- [x] T017 [US3] 在 src/nexusx/use_case/compose_executor.py 移除 T009 保留的 mutation 拒绝闸门；mutation 串行分支改为逐调用 try/except 三态收集（声明顺序不变，fail-stop：首个失败后跳过余下并标 `SKIPPED_PRIOR_FAILURE`）
- [x] T018 [P] [US3] 在 src/nexusx/execution/query_executor.py 移除 `group_failed` 整组作废（约 :290）：改为逐字段三态（失败字段 null + `extensions.code`，兄弟结果保留）；方法级 `enable_mutation` 校验逻辑不动
- [x] T019 [US3] 阶段检查点：全量回归零失败 + `ruff check src/`；quickstart 场景 1/3 通过

**Checkpoint**: 全部用户故事完成；SC-001~006 可对照验收

---

## Phase 5: Polish & Cross-Cutting Concerns

- [x] T020 [P] 文档：在 docs/ 增加 alias 行为说明（引用 specs/023-gql-alias-support/contracts/graphql-alias-behavior.md 的行为矩阵与阶段交付语义；docs-only 不计版本）
- [x] T021 最终验证：按 specs/023-gql-alias-support/quickstart.md 逐场景执行（6/6 通过）；全量回归 + ruff；对照 spec.md SC-001~006 逐条勾验

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1（Setup）**: 无依赖，立即开始
- **Phase 2（US1）**: 依赖 Phase 1；**独立可交付**（止血 PR 可先合先发）
- **Phase 3（US2+US4）**: 依赖 Phase 2 的检测框架（T003 的检测代码被 T009 改造为阶段闸门）；US4 的 T011 依赖 T008 的 key 语义
- **Phase 4（US3）**: 依赖 Phase 3（T009 留下的 mutation 闸门在 T017 移除）
- **Phase 5（Polish）**: 依赖 Phase 4 完成

### User Story Dependencies

- **US1 (P1)**: 无故事间依赖，MVP
- **US2+US4 (P2)**: 复用 US1 的检测入口；US4 是 US2 的横切约束（同一批交付、同一检查点 T014）
- **US3 (P3)**: 依赖 US2 的 key 语义与响应键改造；三态反馈的 compose 实现参考 US2 已就位的结构

### Within Each User Story

- 测试先写、确认失败、再实现（各 Phase 测试组在前）
- parser 语义（T008）先行 → executor 适配（T009/T010）→ 边界与杂项（T011/T012/T013）
- 每阶段末检查点必须全绿再进下一阶段

### Parallel Opportunities

- Phase 3 内：T004/T005/T006/T007 四个测试任务全部 [P]（不同测试文件）；T010/T011/T012 三项实现 [P]（不同源码文件，均只依赖 T008）
- Phase 4 内：T015/T016 测试 [P]；T018 与 T017 分别在两个执行器文件，实现层可 [P]（T018 依赖 T009 已完成的 entity-first key 改造，不依赖 T017）
- Phase 5：T020 与 T021 可并行（文档 vs 验证）

---

## Parallel Example: Phase 3

```bash
# 测试任务并行（四个不同测试文件）：
Task: "T004 parser key 语义与冲突检测用例 in tests/test_query_parser.py"
Task: "T005 compose query 扇出用例 in tests/test_compose_executor.py"
Task: "T006 entity-first query 别名用例 in tests/test_query_executor.py"
Task: "T007 federation wire 零别名断言 in tests/test_federation_remote_loader.py"

# T008 完成后，实现并行（三个不同源码文件）：
Task: "T010 entity-first 执行器适配 in src/nexusx/execution/query_executor.py"
Task: "T011 federation 渲染闸门 in src/nexusx/federation/remote_loader.py"
Task: "T012 移除 handler 内部校验调用 in src/nexusx/handler.py"
```

---

## Implementation Strategy

### MVP First（User Story 1 Only）

1. T001 基线 → T002/T003 止血
2. **STOP and VALIDATE**: compose 别名一律报错、零静默丢弃
3. 可独立发版（6.1.3 patch 亦可，按"行为变更即发版"惯例定夺——止血是把静默丢改为报错，属行为修复）

### Incremental Delivery

1. Setup + US1 → 止血 PR（可先合）
2. US2+US4 → query 侧能力 + 联邦闸门（6.2.0 minor 主体）
3. US3 → mutation 侧补齐（同 6.2.0 或 6.2.x，取决于发布节奏）
4. Polish → 文档与最终验收

### Parallel Team Strategy

单人顺序执行为默认（阶段闸门串行）；若并行，Phase 3 的三个实现文件可分给多人，检查点 T014 汇合。

---

## Notes

- [P] 任务 = 不同文件、无未完成依赖
- 关键回归面：T016（存量"整组 null"用例）与 T007（federation 矩阵）是两处最大风险点，安排在检查点前
- `core_builder.py` 的查找名/输出名分离（B2）与 `response_builder.py` 均不在本任务清单（spec FR-009 设计排除/范围外）
- commit 粒度建议：每阶段一组合（US1 一个、US2+US4 一个、US3 一个），检查点绿后提交

---

## Review 修复与增强（2026-09-01/02，超出原任务清单的记录）

分支 review（全文存 note-tool id 46）发现的问题与增强，3+2 个 commit：

### 修复（9f5c341 / 9d9f49f / b58f9f7）
- **P1 取消吞没**：compose 查询并发路径 `gather(return_exceptions=True)` 把 `CancelledError` 当业务失败转成 `QUERY_FAILED`——实测外部 `task.cancel()` 后返回正常响应且后续 mutation 照跑（master 回归）。修复 = `Exception` 走 per-field、其余 `BaseException` re-raise
- **P2 error path 合规**：别名存在时 `errors[].path` 用原始名而非 response key（GraphQL 规范要求 response key）；两路径统一（`group_key` / `path_key`），message/日志保留原始名（便于人查 schema）
- **P3 恒真断言**：`assert ... or True` 换成精确形态断言（校验失败方法被 skip → 组序列化为 `{}` 非 null）
- polish：per-field 错误补 `extensions.service_method`；`validate_no_aliases` 补冒烟测试

### 新增公共 API（query_parser 模块级，非 breaking）
- `find_nested_alias(sel) -> (dotted_path, 原字段名) | None`——FR-009 检测的唯一实现（原先 query_executor / compose_executor / selection.py 三处等价重复，全部收敛复用）
- `nested_alias_message(path, name)`——统一报错措辞（`'reviews' aliased to 'r'`）
- `ResponseKeyConflictError(ValueError)`——duplicate response key 的类型化异常；`GraphQLHandler` 单独 catch 以输出 `ALIAS_CONFLICT` code（与 compose 对齐）

### 行为增强（最终评估拍板，方案 A）
- **operation 级 mutation fail-stop**：原实现 fail-stop 只在单个 service/entity 组内生效，跨组不传播（实测 `SvcA` 失败后 `SvcB.write` 照常执行）——与 FR-006"失败之后的调用停止执行"字面不符、偏离 GraphQL operation 级串行语义。修复后 abort 标志跨组传播，后续组 mutation 一律 `SKIPPED_PRIOR_FAILURE`，query 不受影响。契约场景 4 已更新
- 已知边界（✅2026-09-03 已修复，issue #142，分支 fix/multi-operation-selection）：`parse_document` 按 document 合并顶层键，同 document 多 operation 选同名组会触发 duplicate-key 报错（master ≤6.1.2 上更糟——静默投影错配导致字段泄漏）。修复=`parse_operations` 按 operation 分组 + executor 按 operationName 选择（规范单执行），compose 侧限单 operation

### 验证
- 全量 1660 passed / 6 skipped / 0 failed；中间 commit 快照已验证可 bisect
