---
description: nexusx preset — plan with DB 选型 / alembic / TS SDK 决策访谈.
handoffs:
  - label: Create Tasks
    agent: speckit.tasks
    prompt: Break the plan into nexusx phase-tagged tasks (Schema → Methods → Service → optional SDK)
    send: true
  - label: Create Checklist
    agent: speckit.checklist
    prompt: Create a checklist for the following nexusx domain...
scripts:
  sh: scripts/bash/setup-plan.sh --json
  ps: scripts/powershell/setup-plan.ps1 -Json
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Pre-Execution Checks

**Check for extension hooks (before planning)**:
- Check `.specify/extensions.yml` for `hooks.before_plan` entries
- Standard handling: parse YAML, skip if invalid, filter by `enabled`, output per `optional` flag (Automatic → `EXECUTE_COMMAND:`; Optional → prompt display)
- If no `before_plan` hooks, skip silently

## Outline

1. **Setup**: Run `{SCRIPT}` from repo root and parse JSON for FEATURE_SPEC, IMPL_PLAN, SPECS_DIR, BRANCH. For single quotes in args like "I'm Groot", use escape syntax: `'I'\''m Groot'` (or double-quote if possible: `"I'm Groot"`).

2. **Load context**: Read FEATURE_SPEC + `/memory/constitution.md`（nexusx preset 版本，含 8 条硬规则 + V 型验收治理）+ IMPL_PLAN template.

3. **Verify Phase 0 completeness** *(nexusx preset)*:
   - 检查 FEATURE_SPEC 中 `## Phase 0 需求确认纪要` 八步全部填写
   - 特别确认 Step 0-4 Service 切分由用户明确选择（不是 `[NEEDS CLARIFICATION]`）
   - 特别确认 Step 0-7 DB 选型由用户明确选定
   - 任一缺失 → ERROR："Phase 0 不完整，请重新运行 `__SPECKIT_COMMAND_SPECIFY__` 补全访谈"

4. **Execute plan workflow** *(nexusx preset)*:
   - Fill `## Technical Context`（nexusx 字段：Language/Version、Primary Dependencies、DB 选型、async/sync DATABASE_URL、Async DB Driver、是否引入 alembic、Testing、Target Platform）
   - Fill `## Phase 决策记录`：从 spec 复制 Service 切分最终方案 + 与用户确认是否生成 TS SDK + 第三方库确认清单
   - Fill `## Constitution Check`：逐条对照 8 条原则
   - Evaluate gates（任何 ❌ 或 ⚠️ 必须在 Complexity Tracking 给理由，否则 ERROR）
   - Phase 0: Generate `research.md`（解决 Technical Context 中所有 NEEDS CLARIFICATION；研究 alembic 配置、async driver 选型、跨层数据流 ExposeAs/SendTo/Collector 适用性）
   - Phase 1: Generate `data-model.md`（实体定义，含 docstring + Field description）、`contracts/`（REST endpoints + GraphQL SDL）、`quickstart.md`
   - Phase 1: Update agent context by running the agent script
   - Re-evaluate Constitution Check post-design

## Mandatory Post-Execution Hooks

**You MUST complete this section before reporting completion to the user.**

Check `.specify/extensions.yml` for `hooks.after_plan` entries. Same handling as Pre-Execution:
- Mandatory → emit `EXECUTE_COMMAND: {command}`
- Optional → prompt display

If no `after_plan` hooks or `.specify/extensions.yml` missing, skip to Completion Report.

## Completion Report

Report branch, IMPL_PLAN path, generated artifacts (research.md / data-model.md / contracts/ / quickstart.md), and **nexusx Phase 决策摘要**（Service 切分 / DB 选型 / 是否 TS SDK）.

## Phases

### Phase 0: DB 选型 + alembic + 第三方库 + TS SDK 决策研究

1. **从 spec.md 复制决策**（已在 Phase 0 访谈中由用户裁定）：
   - DB 选型（in-memory / file sqlite / docker pg / docker mysql / external）
   - Service 切分最终方案
   - 第三方库候选

2. **填充 plan.md Technical Context 的待定字段**：
   - async DATABASE_URL：根据 DB 选型填具体值
   - sync DATABASE_URL_SYNC：持久化场景必填（alembic + load_seed 用）；in-memory 留空
   - Async DB Driver：sqlite→aiosqlite、pg→asyncpg、mysql→aiomysql
   - 是否 alembic：in-memory 否；其他是
   - Testing：pytest + pytest-asyncio（项目级 `tests/`）

3. **TS SDK 决策访谈**：

   向用户提问："本特性是否需要生成 TypeScript SDK？"
   - **是** → plan.md 标记为"是"；Phase 4 触发，需 `fe/` 子目录 + `@hey-api/openapi-ts`；前提是 Phase 3 用 `create_use_case_router()`
   - **否**（默认）→ plan.md 标记为"否"，跳过 Phase 4

   决策结果写入 plan.md `## Phase 决策记录 > 是否生成 TS SDK` 区块。

4. **alembic 配置研究**（仅持久化场景）：参考 `presets/nexusx/reference/phase1.md` 的 alembic 配置部分，记录：
   - `alembic/env.py` 必须加 `import src.models  # noqa: F401`（否则 autogenerate 空）
   - `script.py.mako` 必须加 `import sqlmodel`（否则 NameError）
   - SQLite 必须 `render_as_batch=True`
   - `alembic.ini` `sqlalchemy.url =` 留空，env.py 覆盖

5. **Generate research.md** with format:
   - Decision: [选了什么]
   - Rationale: [为什么]
   - Alternatives considered: [还看了什么]

**Output**: research.md with all NEEDS CLARIFICATION resolved

### Phase 1: Design & Contracts

**Prerequisites**: `research.md` complete

1. **Extract entities from feature spec + spec.md Phase 0 Step 0-1** → `data-model.md`:
   - Entity name + docstring + fields (with description)
   - Relationships（全部带 `sa_relationship_kwargs={"lazy": "noload"}`）
   - Validation rules from requirements
   - State transitions if applicable

2. **Define interface contracts** → `/contracts/`:
   - REST endpoints（每个 service 的方法 → 一个 POST 路由，由 `create_use_case_router()` 自动生成）
   - GraphQL SDL（基于 SQLModel 实体 + Phase 2 挂载的 methods）
   - MCP tools 4 层（list_apps → describe_compose_schema → describe_compose_method → compose_query）
   - 跨层数据流标注（如有 ExposeAs / SendTo / Collector 用法）

3. **Create quickstart validation guide** → `quickstart.md`:
   - 端到端可运行验证场景
   - 包含：prerequisites、setup commands、test/run commands、expected outcomes
   - 用链接引用 contracts/ 和 data-model.md，不复制内容
   - 不含完整实现代码、迁移文件、完整测试套件

4. **Agent context update**: 更新 `__CONTEXT_FILE__` 中 `<!-- SPECKIT START -->` 与 `<!-- SPECKIT END -->` 之间的 plan 引用

**Output**: data-model.md, /contracts/*, quickstart.md, updated agent context

## Key rules

- Use absolute paths for filesystem operations; use project-relative paths for references in docs
- ERROR on Constitution gate failures or unresolved clarifications
- nexusx preset 强制：plan.md 的 Technical Context 必须填 nexusx 字段，不能保留 spec-kit 通用字段

## Done When

- [ ] Phase 0 (spec.md) 完整性验证通过
- [ ] Plan workflow executed：Technical Context 填 nexusx 字段、Phase 决策记录完整、Constitution Check 全 ✅ 或 Complexity Tracking 给理由
- [ ] research.md 生成且所有 NEEDS CLARIFICATION 解决
- [ ] data-model.md / contracts/ / quickstart.md 生成
- [ ] Extension hooks dispatched or skipped per rules above
- [ ] Completion reported with branch / plan path / artifacts / nexusx Phase 决策摘要
