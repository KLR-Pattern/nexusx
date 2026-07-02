---
description: nexusx preset — specify with Phase 0 八步访谈 (entities/关系/聚合根/Service切分/DB选型).
handoffs:
  - label: Build Technical Plan
    agent: speckit.plan
    prompt: Create a plan for the spec. I am building with nexusx (SQLModel + FastAPI + MCP).
  - label: Clarify Spec Requirements
    agent: speckit.clarify
    prompt: Clarify specification requirements
    send: true
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Pre-Execution Checks

**Check for extension hooks (before specification)**:
- Check if `.specify/extensions.yml` exists in the project root.
- If it exists, read it and look for entries under the `hooks.before_specify` key
- If the YAML cannot be parsed or is invalid, skip hook checking silently and continue normally
- Filter out hooks where `enabled` is explicitly `false`. Treat hooks without an `enabled` field as enabled by default.
- For each remaining hook, output based on its `optional` flag per the standard spec-kit format (Automatic Pre-Hook emits `EXECUTE_COMMAND:`; Optional Pre-Hook shows the prompt)
- If no hooks are registered, skip silently

## Outline

The text after `__SPECKIT_COMMAND_SPECIFY__` in the triggering message **is** the feature description.

### 1. Short-name & directory setup

1. **Generate a concise short name** (2-4 words) for the feature (action-noun format when possible; preserve technical acronyms like OAuth2/JWT)
2. **Branch creation** (optional, via `before_specify` hook): if a hook ran successfully it will have output JSON with `BRANCH_NAME` and `FEATURE_NUM`. Note these for reference
3. **Create the spec feature directory** under `specs/`:
   - Resolution order: user-provided `SPECIFY_FEATURE_DIRECTORY` > auto-generated `specs/<NNN>-<short-name>` (check `.specify/init-options.json` for `feature_numbering`: `timestamp` → `YYYYMMDD-HHMMSS-<name>`; `sequential` (default) → next 3-digit number)
   - `mkdir -p SPECIFY_FEATURE_DIRECTORY`
   - Resolve active `spec-template` through the preset stack (equivalent to `specify preset resolve spec-template` — nexusx preset provides this)
   - Copy resolved template to `SPECIFY_FEATURE_DIRECTORY/spec.md`
   - Set `SPEC_FILE` to `SPECIFY_FEATURE_DIRECTORY/spec.md`
   - Persist path to `.specify/feature.json`: `{ "feature_directory": "<resolved path>" }`
   - **One feature per invocation**; spec dir name and git branch name are independent

### 2. Load context

4. Load the resolved `spec-template` (nexusx preset version) to understand required sections
5. **IF EXISTS**: Load `/memory/constitution.md` for project principles (nexusx preset constitution defines 8 hard rules)

### 3. Phase 0 八步访谈 *(nexusx preset — interactive)*

<!--
  ⚠️ Constitution Principle IV 强制门：必须在向用户提出 Service 切分候选方案并取得明确选择后才能继续。
  禁止模型自行决定 Service 切分。
-->

按 `spec.md` 模板的 `## Phase 0 需求确认纪要` 区块逐项与用户访谈。**每步等待用户回复后才继续**。

#### Step 0-1 术语与实体定义

从 feature description 提取候选取实体，**表格化呈现**给用户逐行确认：

| 实体 | 业务含义（一句话） | 核心字段（名称+类型+语义） | 字段约束 |
|------|----------|----------|----------|
| [候选 1] | ... | ... | ... |

询问：补充、修改、删除哪些？

#### Step 0-2 实体关系

基于 Step 0-1 实体，绘制文本 ER 图：

```
User ──1:N──→ Post
Post ──N:M──→ Tag (中间表: PostTag)
```

每条关系标方向（1:N / N:1 / M:N）+ 业务含义 + 是否需要中间实体。**与用户确认关系方向和基数**。

#### Step 0-3 聚合根 + 根类型

明确每个聚合根是 **SQLModel 实体**还是 **虚拟实体**（普通 `pydantic.BaseModel`）：

| 聚合根 | 类型 | 选用理由 |
|--------|------|----------|
| [候选] | SQLModel 实体 / 虚拟实体 | [判断依据] |

**判断依据**：根字段全部来自 DB → SQLModel；来自请求上下文（JWT、headers）或聚合多源 → 虚拟。

#### Step 0-4 Service 切分候选方案 ⚠️ 强制门

**禁止模型自行决定**。必须向用户提出**至少一种候选方案**：

```
方案 A：按业务功能域
  auth/    → register, login
  chat/    → create_conversation, list_messages, send_message
  优势：业务内聚
  劣势：chat 域可能过大

方案 B：按聚合根
  user/         → register, login
  conversation/ → create_conversation, list_messages
  message/      → send_message
  优势：每 service 粒度均匀
  劣势：conversation/message 强耦合被拆开

方案 C：混合
  ...
```

**强制门**：如果未向用户提出候选方案并取得明确选择（A / B / C / 用户的修正），**立即标记 `SPEC_PHASE0_BLOCKED`** 并停在此处输出：

```
⚠️ SPEC_PHASE0_BLOCKED
等待用户从 A/B/C 选择 Service 切分方案，或提出修正。
```

收到用户回复后才继续 Step 0-5。

#### Step 0-5 GraphQL 定位

告知用户：GraphQL 在 nexusx 中是**辅助开发测试**接口（不是正式 API）。业务方法定义在 `service/<domain>/methods.py`，挂载到 Entity（GraphQL 辅助）+ UseCaseService（REST/MCP 正式）。无需用户确认。

#### Step 0-6 第三方库确认

列出 feature 涉及的非业务功能领域（认证、实时推送、文件存储、数据迁移等）。对每个：
- 候选方案（成熟第三方库 vs 手写）
- 推荐理由
- **必须调查用户提到的库的当前维护状态**（避免停更库）

| 功能领域 | 推荐方案 | 维护状态 | 备注 |
|----------|----------|----------|------|
| 认证 | ... | 活跃/维护中/已停更 | ... |

#### Step 0-7 DB 选型 + 迁移策略 ⚠️ 强制门

向用户呈现 5 选项决策表：

| 选项 | async URL | 持久化 | Alembic | 适用 |
|------|----------|--------|---------|------|
| in-memory sqlite | `sqlite+aiosqlite://` | ❌ | ❌ | Demo |
| file sqlite | `sqlite+aiosqlite:///./var/X.db` | ✅ 文件 | ✅ | 本地开发 |
| docker pg | `postgresql+asyncpg://...` | ✅ 卷 | ✅ | 团队 |
| docker mysql | `mysql+aiomysql://...` | ✅ 卷 | ✅ | MySQL 偏好 |
| external | 视驱动 | ✅ | ✅ | 已有 DB |

**强制门**：用户未明确选定（含 async URL + sync URL + 是否 alembic + 是否 docker-compose）前，标记 `SPEC_PHASE0_BLOCKED` 等待。

#### Step 0-8 检查清单汇总

向用户展示 8 项 checklist 全部 ✅ 后才进入下一步：

- [ ] 实体和字段完整，约束清晰
- [ ] 实体关系方向和基数正确
- [ ] 聚合根明确，每个类型已确认
- [ ] **Service 切分由用户明确选择**（IV）
- [ ] 核心用例覆盖，逻辑自洽
- [ ] 第三方库选型确认
- [ ] **DB 选型 + 迁移策略明确**（影响 Phase 1 alembic）
- [ ] 无遗漏或未讨论的边界

### 4. Fill spec.md using Phase 0 answers

6. Write the specification to `SPEC_FILE`:
   - 用 Phase 0 八步访谈的答案填充 `## Phase 0 需求确认纪要` 区块
   - 用 spec-kit core 流程填充 `## User Scenarios & Testing` / `## Requirements` / `## Success Criteria` / `## Assumptions`
   - 解析用户描述中的 actors / actions / data / constraints
   - 不明确的标记 `[NEEDS CLARIFICATION: specific question]`，**全局最多 3 个**
   - 优先级：scope > security/privacy > UX > technical details
   - 合理默认：标准 web/mobile 性能、用户友好错误、标准认证模式、项目合适的集成模式

### 5. Specification Quality Validation

7. 创建 `SPECIFY_FEATURE_DIRECTORY/checklists/requirements.md` 验证 checklist，包含：
   - **Content Quality**: 无实现细节、聚焦用户价值、面向非技术干系人
   - **Requirement Completeness**: 无残留 `[NEEDS CLARIFICATION]`、需求可测、success criteria 可衡量且与实现无关、边界用例识别
   - **Feature Readiness**: 所有 FR 有清晰验收、用户场景覆盖主流程

8. 验证流程：
   - **全部通过** → 标记完成，进入 Mandatory Post-Execution Hooks
   - **非 NEEDS CLARIFICATION 失败** → 列出问题、更新 spec、重验证（最多 3 轮）
   - **残留 NEEDS CLARIFICATION** → 提取每个标记（最多 3 个），用表格向用户提问（Q1/Q2/Q3 同时呈现），等用户回复后替换标记，重新验证

## Mandatory Post-Execution Hooks

**You MUST complete this section before reporting completion to the user.**

Check `.specify/extensions.yml` for `hooks.after_specify` entries. Apply same logic as Pre-Execution Checks:
- Mandatory hook → emit `EXECUTE_COMMAND: {command}`
- Optional hook → show prompt and command path

If no `after_specify` hooks or `.specify/extensions.yml` missing, skip to Completion Report.

## Completion Report

Report to user:
- `SPECIFY_FEATURE_DIRECTORY` — feature 目录路径
- `SPEC_FILE` — spec 文件路径
- Phase 0 八步访谈全部完成（特别提示 Service 切分 + DB 选型已由用户裁定）
- Checklist 验证结果摘要
- Readiness for next phase (`__SPECKIT_COMMAND_CLARIFY__` 或 `__SPECKIT_COMMAND_PLAN__`)

**NOTE**: Branch creation 由 `before_specify` hook 处理；spec 目录和文件创建由本命令处理。

## Quick Guidelines

- **Phase 0 访谈阶段**：聚焦业务实体、关系、聚合根、Service 边界、DB 选型——这些决定后续 phase 走向。可以包含 nexusx 技术栈名（SQLModel / FastAPI / MCP），因为本项目就用 nexusx
- **User Scenarios / Requirements / Success Criteria 阶段**：聚焦 WHAT 和 WHY，避免 HOW（具体代码结构、字段名）
- **NEEDS CLARIFICATION** 上限 3 个，仅在多重合理解读且影响范围时使用

### Section Requirements

- **Phase 0 需求确认纪要**：nexusx preset 必填，未完成禁止进入 plan
- **User Scenarios**：必填，每个故事可独立测试
- **Requirements / Success Criteria / Assumptions**：必填
- 不适用的 section 整段删除，不留 "N/A"

## Done When

- [ ] Phase 0 八步访谈完成（Service 切分 + DB 选型由用户明确裁定）
- [ ] Specification written to `SPEC_FILE`，包含 nexusx Phase 0 区块 + spec-kit core 区块
- [ ] Validated against quality checklist
- [ ] Extension hooks dispatched or skipped per rules above
- [ ] Completion reported with feature dir / spec path / Phase 0 interview summary
