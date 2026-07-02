---
description: nexusx preset — tasks with phase 标签 (Schema/Methods/Service/SDK) + reference linking.
handoffs:
  - label: Analyze For Consistency
    agent: speckit.analyze
    prompt: Run a project analysis for consistency
    send: true
  - label: Implement Project
    agent: speckit.implement
    prompt: Start the implementation in nexusx phases
    send: true
scripts:
  sh: scripts/bash/setup-tasks.sh --json
  ps: scripts/powershell/setup-tasks.ps1 -Json
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Pre-Execution Checks

**Check for extension hooks (before tasks generation)**:
- Check `.specify/extensions.yml` for `hooks.before_tasks` entries
- Standard handling: parse YAML, skip if invalid, filter by `enabled`, output per `optional` flag (Automatic → `EXECUTE_COMMAND:`; Optional → prompt display)
- If no `before_tasks` hooks, skip silently

## Outline

1. **Setup**: Run `{SCRIPT}` from repo root and parse FEATURE_DIR, TASKS_TEMPLATE, AVAILABLE_DOCS. For single quotes in args use escape syntax: `'I'\''m Groot'` (or `"I'm Groot"`).

2. **Load design documents** from FEATURE_DIR:
   - **Required**: plan.md (nexusx Technical Context + Phase 决策记录 + Constitution Check), spec.md (Phase 0 需求确认纪要 + User Stories)
   - **Optional**: data-model.md (entities), contracts/ (interface contracts), research.md (decisions), quickstart.md
   - **IF EXISTS**: `/memory/constitution.md` (nexusx 8 硬规则)
   - 注：不是所有项目都有所有文档；基于实际可用的生成任务

3. **Read nexusx-specific decisions** *(nexusx preset)*:
   - 从 plan.md `## Phase 决策记录 > Service 切分最终方案` 读 domain 列表（决定 Phase 2/3 的 service 数量）
   - 从 plan.md `## Phase 决策记录 > 是否生成 TS SDK` 读布尔值（决定是否生成 Phase 4）
   - 从 spec.md `## Phase 0 需求确认纪要 > Step 0-7 DB 选型` 读是否 alembic（决定 Phase 1 是否包含 alembic setup 任务）

4. **Execute task generation workflow**:
   - Load plan.md 提取 tech stack / libraries / structure
   - Load spec.md 提取 user stories 与优先级（P1, P2, P3...）
   - Load data-model.md 提取实体并映射到 user stories（跨故事共享实体放 Phase 1 顶部多标签）
   - Load contracts/ 映射接口契约到 user stories
   - Load research.md 提取决策用于 setup 任务
   - **按 nexusx phase 组织任务**（不是按 user story），见下方规则
   - 生成依赖图（phase 顺序 + phase 内部并行）
   - 验证完整性（每个 user story 在所需 phase 都有任务）

5. **Generate tasks.md**: Read nexusx tasks-template from TASKS_TEMPLATE (or fall back to `.specify/presets/nexusx/templates/tasks-template.md`). Fill with:
   - 正确的 feature name（来自 plan.md）
   - **Phase 1 Schema**（含 alembic setup 任务，仅当 DB 选型为持久化场景）
   - **Phase 2 Methods**（每个 domain 一组 methods.py + mount_method）
   - **Phase 3 Service**（每个 domain 一组 dtos.py + service.py + spec.md + main.py 集成）
   - **Phase 4 TS SDK**（仅当 plan.md "是否生成 TS SDK" 为"是"，否则整段删除）
   - **Polish & Cross-Cutting Concerns**
   - 所有任务必须遵循 nexusx checklist 格式（见下）
   - 每个 phase 顶部链接到 `presets/nexusx/reference/phaseN.md`
   - Dependencies section（phase 顺序 + 用户故事跨 phase 追踪）

## Mandatory Post-Execution Hooks

**You MUST complete this section before reporting completion to the user.**

Check `.specify/extensions.yml` for `hooks.after_tasks` entries. Same handling as Pre-Execution:
- Mandatory → emit `EXECUTE_COMMAND: {command}`
- Optional → prompt display

If no `after_tasks` hooks or `.specify/extensions.yml` missing, skip to Completion Report.

## Completion Report

Output path to generated tasks.md and summary:
- Total task count
- Task count per nexusx phase（Phase 1 / 2 / 3 / 4）
- Task count per user story
- Parallel opportunities identified
- Independent test criteria for each story
- Suggested MVP scope（Phase 1 + Phase 2 + Phase 3 of US1）
- Format validation: 所有任务遵循 checklist 格式 + phase 标签

Context for task generation: {ARGS}

The tasks.md should be immediately executable — each task must be specific enough that an LLM can complete it without additional context.

## Task Generation Rules *(nexusx preset)*

**CRITICAL**: Tasks MUST be organized by **nexusx phase**（不是 spec-kit 默认的 user-story-first）。每个 task 必须带 `[P1]/[P2]/[P3]/[P4]` phase 标签。

**Tests are OPTIONAL**: 仅当 spec.md 明确要求或用户要求 TDD 才生成测试任务。

### Checklist Format (REQUIRED)

Every task MUST strictly follow this format:

```text
- [ ] [TaskID] [P?] [P<phase>] [Story?] Description with file path
```

**Format Components**:

1. **Checkbox**: 总是以 `- [ ]` 开头
2. **Task ID**: 顺序号 T001, T002, T003... 全局递增（不重置 per phase）
3. **[P] marker**: 仅当可并行（不同文件、无依赖）时包含
4. **[P1] / [P2] / [P3] / [P4]**: nexusx phase 标签（**必填**）
5. **[USx] label**: 多故事共享任务可标多个 `[US1] [US2]`；单故事任务标一个；非故事任务（如 alembic setup）不标
6. **Description**: 清晰动作 + 具体文件路径

**Examples**:

- ✅ CORRECT: `- [ ] T001 [P1] Create src/db.py with engine + async session factory`
- ✅ CORRECT: `- [ ] T002 [P1] [US1] [US2] Create shared User entity in src/models.py`
- ✅ CORRECT: `- [ ] T020 [P2] [US1] Implement create_user in src/service/auth/methods.py`
- ❌ WRONG: `- [ ] T001 Create project structure`（缺 phase 标签）
- ❌ WRONG: `- [ ] [US1] Create User model`（缺 ID 和 phase）
- ❌ WRONG: `- [ ] T020 Create service`（缺 phase 标签 + 文件路径）

### Task Organization

1. **Phase 1 Schema** *(reference: `presets/nexusx/reference/phase1.md`)*:
   - `src/db.py`（engine + session factory）
   - `src/models.py`（纯实体，无方法，所有 Relationship 加 `lazy=noload`，每个 Model 加 docstring，每个 Field 加 description）
   - `src/database.py`（init_db 策略）
   - `src/main.py`（FastAPI lifespan + Voyager ER）
   - mock seed data（持久化场景：`var/seed_data.json` + `scripts/load_seed.py`）
   - **持久化场景额外**：alembic init、env.py、script.py.mako、baseline migration

2. **Phase 2 Methods** *(reference: `presets/nexusx/reference/phase2.md`)*:
   - `src/service/<domain>/methods.py`（每个 domain 一份，普通 async def）
   - `src/models.py` 末尾的 `mount_method()` 函数（`_mount()` 桥接 + `@functools.wraps`）
   - `src/main.py` 在 `GraphQLHandler` 之前调用 `mount_method()`
   - `tests/test_<domain>_methods.py`（项目级 tests/，monkey-patch async_session）

3. **Phase 3 Service** *(reference: `presets/nexusx/reference/phase3.md`)*:
   - `src/service/<domain>/dtos.py`（DefineSubset，禁 `future annotations`，字段用 DTO 类型）
   - `src/service/<domain>/service.py`（UseCaseService，复用 methods.py，所有方法声明返回类型注解，service.py 不直接操作 DB）
   - `src/service/<domain>/spec.md`
   - `src/main.py` 集成：`UseCaseAppConfig` + `create_use_case_router()` + `create_use_case_graphql_mcp_server()` + MCP http_app lifespan 合并 + `create_use_case_voyager()` 补 services

4. **Phase 4 TS SDK** *(conditional — 仅当 plan.md "是否生成 TS SDK" 为 "是")*:
   - `fe/openapi-ts.config.ts`
   - `fe/package.json`
   - 生成 + 验证
   - **如 plan.md 标"否"**，整段 Phase 4 删除，不保留空骨架

5. **Polish & Cross-Cutting Concerns**:
   - 文档更新（每个 service spec.md）
   - 性能优化
   - Security hardening
   - `quickstart.md` 端到端验证

### Phase 标签使用规则

| Task 类型 | Phase 标签 | 故事标签 |
|------|------|------|
| Schema 实体（共享） | `[P1]` | 多个 `[US1] [US2]` |
| Schema 实体（单故事） | `[P1]` | 单个 `[USx]` |
| Schema 基础设施（db.py / main.py） | `[P1]` | 不标 |
| alembic setup（仅持久化） | `[P1]` | 不标 |
| Methods.py（按 domain） | `[P2]` | `[USx]` |
| mount_method 桥接 | `[P2]` | 不标（所有故事共用） |
| DTO + Service（按 domain） | `[P3]` | `[USx]` |
| main.py router 集成 | `[P3]` | 不标 |
| TS SDK | `[P4]` | 不标 |
| Polish | 不标 | 不标 |

### Conditional Phase 4 Emission Logic

```
if plan.md "## Phase 决策记录 > 是否生成 TS SDK" == "是":
    emit Phase 4 tasks
else:
    omit Phase 4 entirely
```

## Phase Structure

- **Phase 1 Schema**: 项目初始化 + 实体定义 + DB engine + Voyager ER；完成后**必须暂停**等用户 V 升确认
- **Phase 2 Methods**: 业务方法实现 + 挂载；完成后**必须暂停**
- **Phase 3 Service**: DTO + UseCaseService + REST + MCP + Voyager services；完成后**必须暂停**
- **Phase 4 TS SDK** *(可选)*: SDK 生成
- **Polish**: 跨 phase 改进

## Done When

- [ ] tasks.md generated with nexusx phase structure（Schema / Methods / Service / 可选 SDK / Polish）
- [ ] 所有任务带 `[P1]/[P2]/[P3]/[P4]` phase 标签 + 具体文件路径
- [ ] Phase 4 仅在 plan.md 决策为"是"时存在
- [ ] 每个 phase 顶部链接到 `presets/nexusx/reference/phaseN.md`
- [ ] Extension hooks dispatched or skipped per rules above
- [ ] Completion reported with task count per phase + per story + MVP scope
