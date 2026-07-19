---

description: "Task list for fixing router model_dump bug (issue #107)"
---

# Tasks: 修复 UseCase Router 把嵌套 BaseModel 参数拍平成 dict 的 Bug

**Input**: Design documents from `/specs/011-fix-router-model-dump/`

**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/router-handler-contract.md ✓, quickstart.md ✓

**Tests**: 包含（spec FR-008 强制要求新增回归测试，TDD red-green 流程）

**Organization**: 按 spec.md 的 3 个 user story 组织（US1 修复 / US2 标量侧回归 / US3 schema 正交回归）

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 / US2 / US3 (map to spec.md user stories)
- 所有路径相对仓库根

## Path Conventions

- 源码：`src/nexusx/use_case/router.py`（单文件修改）
- 测试：`tests/test_use_case_router.py`（单文件扩充）
- 制品：`specs/011-fix-router-model-dump/`（可选）

---

## Phase 1: Setup

**Purpose**: 切分支、锁定基线、捕获修复前快照

- [X] T001 切到新分支 `fix/011-router-model-dump`（基于 master 最新 a1edfca）
- [X] T002 在 master 最新 commit 上跑 `pytest tests/test_use_case_router.py -v`——**发现 5 个测试因 FastAPI 0.139.x 的 Mount 结构变化在 master 上预先失败，与本 bug 无关**；其余 23 个测试通过作为有效基线
- [X] T003 [P] 捕获修复前 OpenAPI schema 快照到 `/tmp/openapi_before.json`
- [X] T004 [P] 捕获修复前 compose SDL 快照到 `/tmp/sdl_before.sdl`（使用 `render_sdl()`，非 `to_sdl()`）

**Checkpoint**: 基线锁定，bug 可复现，schema 快照已存档

---

## Phase 2: Foundational

**Purpose**: 无——本特性是单文件 bug fix，无跨 story 的基础工作

> 跳过此 Phase。US1 的前置依赖只是 Phase 1 的基线锁定（已完成）。

---

## Phase 3: User Story 1 - 修复嵌套 BaseModel 参数被拍平（Priority: P1）🎯 MVP

**Goal**: 去掉 `_make_handler` 中的 `body.model_dump()`，改为 `getattr(body, pname)` 按字段名取值，使 service 方法体收到的嵌套 BaseModel 参数与签名声明一致

**Independent Test**: 跑 quickstart 场景 2——`repro_bug.py` 在修复后返回 HTTP 200 与正确 JSON，无 `AttributeError`

### Tests for User Story 1（TDD red-first）

> **NOTE**: 全部测试加到 `tests/test_use_case_router.py` 末尾新建的 `TestNestedBaseModelParams` test class。运行后应当全部 RED（修复前）。

- [X] T005 [US1] 在 `tests/test_use_case_router.py` 新增测试 DTO：`ItemInput(BaseModel)` (`text: str`, `checked: bool = False`)、`ItemOutput(BaseModel)` (`text: str`, `checked: bool`)
- [X] T006 [US1] 在 `tests/test_use_case_router.py` 新增 `NestedModelService(UseCaseService)` 与 `nested_client` fixture，包含 7 个方法覆盖不同参数形态
- [X] T007 [US1] 加 `test_list_of_basemodel`：覆盖 `list[ItemInput]`
- [X] T008 [US1] 加 `test_single_nested_basemodel`：覆盖 `ItemInput`
- [X] T009 [US1] 加 `test_optional_basemodel_with_value` 与 `test_optional_basemodel_with_none`：覆盖 `Optional[ItemInput]` 两种输入
- [X] T010 [US1] 加 `test_optional_list_of_basemodel` 与 `test_optional_list_of_basemodel_omitted`：覆盖 `Optional[list[ItemInput]]`
- [X] T011 [US1] 加 `test_list_of_optional_basemodel`：覆盖 `list[ItemInput | None]`（含 null 元素）
- [X] T012 [US1] 加 `test_nested_two_levels`：覆盖 `list[list[ItemInput]]`（两层嵌套）
- [X] T013 [US1] 加 `test_basemodel_with_from_context`：Case 1——body 中含 `list[ItemInput]`，同时有 `Annotated[int, FromContext()]` 参数
- [X] T014 [US1] 跑测试确认 **7 RED + 2 PASSED**（PASS 的是 None/省略场景，RED 的是真正涉及嵌套 BaseModel 接收的场景）

### Implementation for User Story 1

> 全部修改集中在 `src/nexusx/use_case/router.py`。按顺序执行（同一文件，不可并行）。

- [X] T015 [US1] 修改 `_make_handler` 函数签名：在 `request_model` 与 `context_extractor` 之间新增参数 `body_params: list[str]`
- [X] T016 [US1] 改写 Case 1 handler 闭包：`kwargs = {p: getattr(body, p) for p in body_params}`，ctx 注入逻辑不变
- [X] T017 [US1] 改写 Case 2 handler 闭包：同上 getattr 字典推导
- [X] T018 [US1] Case 3 / Case 4 handler 闭包保持不变（无 body）
- [X] T019 [US1] 修改 `create_router()` 中 `_make_handler` 调用点，传 `body_params=body_params`
- [X] T020 [US1] 跑测试确认 **9 GREEN**（含 2 个一直 PASS 的 None/省略场景）

**Checkpoint**: 修复已落地，US1 验收场景全部通过——issue #107 复现脚本可正常工作

---

## Phase 4: User Story 2 - 标量 / FromContext / 默认值 / alias 行为零变化（Priority: P2）

**Goal**: 通过显式回归测试断言，证明修复只针对嵌套 BaseModel，不影响其他参数形态

**Independent Test**: US2 的全部回归测试通过 + 现有 `tests/test_use_case_router.py` 中 30+ 个用例零失败

### Tests for User Story 2

> 这些测试**不应**因修复而失败——它们是回归保护。如果其中任何一个在修复后变红，说明修复引入了非预期行为变化。

- [X] T021 [P] [US2] `test_scalar_int_unchanged`：声明 `n: int`，服务方法体内 `type(n) is int` 守卫
- [X] T022 [P] [US2] `test_scalar_str_unchanged`：声明 `s: str`，同样 type 守卫
- [X] T023 [P] [US2] `test_scalar_list_unchanged`：声明 `tags: list[str]`，断言元素全部 `type(t) is str`
- [X] T024 [P] [US2] `test_default_value_omitted` 与 `test_default_value_overridden`：声明 `count: int = 10`，覆盖省略 + 显式传值
- [X] T025 [P] [US2] FromContext 路径由现有 `test_from_context_injected` / `test_from_context_with_body_param` 覆盖（已通过）
- [X] T026 [P] [US2] `test_alias_field_unchanged`：声明 `Annotated[str, Field(alias="userName")]`，POST 按 alias 提交 JSON
- [X] T027 [US2] 跑全套 `pytest tests/test_use_case_router.py`：**39 passed + 5 failed**，5 个失败全是 T002 锁定的 FastAPI Mount 预先失败，与本修复无关

**Checkpoint**: 标量侧 / FromContext 侧 / 默认值 / alias 全部行为保持——US2 验收

---

## Phase 5: User Story 3 - Schema 生成路径完全正交（Priority: P3）

**Goal**: 通过 diff 验证，证明修复未影响 OpenAPI / compose schema 生成（spec FR-007、SC-004）

**Independent Test**: OpenAPI schema 与 compose SDL 在修复前后 diff 为空

### Tests for User Story 3

- [X] T028 [US3] 捕获修复后 OpenAPI schema 到 `/tmp/openapi_after.json`
- [X] T029 [US3] `diff /tmp/openapi_before.json /tmp/openapi_after.json` 输出为空 ✓
- [X] T030 [US3] 捕获修复后 compose SDL 到 `/tmp/sdl_after.sdl`
- [X] T031 [US3] `diff /tmp/sdl_before.sdl /tmp/sdl_after.sdl` 输出为空 ✓
- [X] T032 [P] [US3] compose 相关测试全过：**91 passed**（test_compose_schema / introspection / recursive_types / introspect / executor）

**Checkpoint**: schema 路径正交性已验证——US3 验收

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 静态检查、文档草稿、端到端冒烟

- [X] T033 [P] `ruff check src/nexusx/use_case/router.py tests/test_use_case_router.py` — All checks passed
- [X] T034 [P] `mypy --strict src/nexusx/use_case/router.py` — Success: no issues（清理了 Case 2 handler 中遗留的 unused `type: ignore`）
- [X] T035 [P] 跳过——已切到修复分支，bug 复现由 T014 的 7 RED 测试充分证明
- [X] T036 跑 quickstart 场景 2（`repro_bug.py` 等价脚本）：HTTP 200 + 正确 JSON ✓
- [X] T037 [P] 与 T033/T034 重叠，最终门禁通过
- [X] T38 CHANGELOG 草稿写入 `specs/011-fix-router-model-dump/changelog-entry.md`（含行为变化摘要、影响范围、迁移提示、建议版本号 patch）

**Checkpoint**: 静态检查全过、CHANGELOG 草稿就绪、端到端冒烟通过——可发起 PR

---

## Dependencies & Execution Order

### Phase 依赖

- **Phase 1 (Setup)**：无依赖，立刻开始
- **Phase 2 (Foundational)**：跳过（N/A）
- **Phase 3 (US1)**：依赖 Phase 1 完成（基线锁定 + 快照存档）
- **Phase 4 (US2)**：依赖 Phase 3 完成（修复已落地才能验证"零变化"）
- **Phase 5 (US3)**：依赖 Phase 1 的快照（T003/T004）+ Phase 3 的修复（T015-T019）才能 diff
- **Phase 6 (Polish)**：依赖 Phase 3-5 全部完成

### User Story 依赖

- **US1 (P1)**：核心修复——所有实现任务的根
- **US2 (P2)**：依赖 US1 修复落地（否则 "零变化" 断言无对照）
- **US3 (P3)**：依赖 US1 修复落地 + Phase 1 快照

### Within US1（任务内部顺序）

1. T005-T006 测试 fixture（DTO + Service）——前置
2. T007-T013 测试方法（TDD red）——可一次性写完再跑
3. T014 跑测试确认 RED
4. T015-T019 修改 router.py（严格顺序，同一文件）
5. T020 跑测试确认 GREEN

### Parallel Opportunities

- **Phase 1**: T003 与 T004 可并行（不同快照文件）
- **Phase 4 (US2)**: T021-T026 全部 [P]——都加测试到同一文件但是不同 test method，逻辑独立；实操中建议合并到 1-2 个 commit 里顺序写以免 merge conflict
- **Phase 5 (US3)**: T032 与 T028-T031 可并行（不同验证维度）
- **Phase 6**: T033 / T034 / T035 / T037 可并行（不同工具/场景）

---

## Parallel Example: User Story 2 (回归测试)

```bash
# 同时启动 US2 的多个回归测试编写（都加到 tests/test_use_case_router.py 但不同 test method）：
Task: "T021 加 test_scalar_uuid_unchanged"
Task: "T022 加 test_scalar_str_unchanged + test_scalar_int_unchanged"
Task: "T023 加 test_scalar_list_unchanged"
Task: "T024 加 test_default_value_unchanged"
Task: "T025 加 test_from_context_only_unchanged"
Task: "T026 加 test_alias_field_unchanged"
```

> 实操提示：同一文件的并行写改容易冲突。如果用 git worktree 隔离每个任务，最后 merge；如果手写，建议顺序执行。

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. **Phase 1**: T001-T004 切分支 + 锁基线 + 存快照
2. **Phase 3 (US1)**: T005-T020 完成，跑 `pytest tests/test_use_case_router.py::TestNestedBaseModelParams` 全过
3. **STOP and VALIDATE**: 跑 quickstart 场景 2（`repro_bug.py`）端到端验证

到这一步 issue #107 已经修好，可以发 PR 了。US2 / US3 是回归保险——建议合入 PR 前完成。

### Incremental Delivery

1. Setup → 基线锁定
2. US1 → 修复落地，独立验证（MVP！）
3. US2 → 标量侧回归测试通过
4. US3 → schema diff 验证通过
5. Polish → ruff/mypy/CHANGELOG，发起 PR

### Single-Developer Strategy（推荐路径）

由于本特性是单文件 ~20-30 行核心修改 + 单文件测试扩充，**实际不需要 parallel team**。推荐顺序执行：

```
T001 → T002 → T003/T004 (parallel)
→ T005 → T006 → T007-T013 (sequential, same file) → T014 (verify RED)
→ T015 → T016 → T017 → T018 (verify Case 3/4 unchanged) → T019 → T020 (verify GREEN)
→ T021-T026 (sequential, same file) → T027 (verify GREEN)
→ T028 → T029 (verify diff empty) → T030 → T031 (verify diff empty) → T032 (verify compose tests)
→ T033/T034 (parallel) → T035/T036/T037 → T038
```

---

## Notes

- 全部源码修改集中在 `src/nexusx/use_case/router.py`，无新文件
- 全部测试加到 `tests/test_use_case_router.py`（新建 `TestNestedBaseModelParams` test class，可选新建 `TestRouterRegression`）
- 严格 TDD：US1 测试先写、跑红，再写实现，跑绿
- Case 3 / Case 4（router.py:188-207）**不要动**——它们没有 `model_dump()` 调用
- T038 CHANGELOG 草稿不直接写 `CHANGELOG.md`——交由 `/release` skill 落地
- 修复完成后建议发起 PR 关闭 issue #107，PR 描述里链接本 spec 目录
