# Spec 管理与工作流

## 语言要求

所有 spec-kit 产物 MUST 使用中文撰写，与项目 `CLAUDE.md` 的中文化要求保持一致。适用范围：

- 用户故事、需求条目、验收场景、假设说明等叙述性内容 → MUST 中文
- 框架名、API 名、代码标识符（如 `create_use_case_router`、`SQLModel`）→ 保留原文
- 章节标题、表格表头 → MUST 中文

包括但不限于：`story.md`、`phaseN.md`、`spec.md`、`plan.md`、`tasks.md`、`checklists/*.md`、`contracts/*`、`research.md`、`data-model.md`、`quickstart.md`。

## 目录命名

```
specs/<编号>-<需求简述>/
```

- **编号格式**: 三位序号（按项目递增），如 `001`、`004`
- **需求简述**: 英文短横线连接，如 `chat-demo`

示例: `specs/004-non-sqlmodel-roots/`

> 与 speckit 工作流（`.specify/`）共用同一 `specs/` 目录，编号互通。

## 文件结构

```
specs/<编号>-<需求简述>/
├── story.md        # 用户原始需求 + Overview Design
├── phase0.md       # 需求确认
├── phase1.md       # Schema + ER Diagram
├── phase2.md       # Loader 实现
├── phase3.md       # UseCase + MCP
└── phase4.md       # TS SDK
```

## 文件内容格式

每个 phase 文件分三个部分：

```markdown
# Phase N: <阶段标题>

## 需求说明

（记录用户在对话中提出的原始需求、约束条件和确认结论）

## 验收标准

（V 降阶段定义的验收标准表格，每项标注验证方式）

## 实现描述

（记录该阶段的具体技术实现方案、产出文件和关键决策，以及 V 升的逐条回查结果）
```

## 写入时机

| 文件 | 写入时机 |
|------|----------|
| story.md | 用户首次描述需求时记录原始表述；Phase 0 确认后补充 Overview Design（见下方说明） |
| phase0.md | Phase 0 全部确认后，进入 Phase 1 之前 |
| phase1.md | V 降写入验收标准 → 实现 → V 升回查全部通过后写入完整内容 |
| phase2.md | V 降写入验收标准 → 实现 → V 升回查全部通过后写入完整内容 |
| phase3.md | V 降写入验收标准 → 实现 → V 升回查全部通过后写入完整内容 |
| phase4.md | V 降写入验收标准 → 实现 → V 升回查全部通过后写入完整内容 |

> 如果同时使用 speckit（`.specify/`），speckit 自己的 `spec.md`/`plan.md`/`tasks.md` 与本工作流的 `phaseN.md` 共存于同一 `specs/<编号>-<需求简述>/` 目录：speckit 描述实现计划，`phaseN.md` 记录每阶段验收与产出。

## story.md 的 Overview Design 部分

Phase 0 全部确认后、进入 Phase 1 之前，在 `story.md` 中补充 `## Overview Design` 部分，内容包含：

- **业务流程**：核心用户操作路径（用文本流程图）
- **实体关系**：ER 图（文本格式）
- **聚合根**：明确入口实体
- **关键设计决策**：第三方库选型、分页策略、幂等策略等（表格形式）
- **四阶段产出**：每个 Phase 的预期交付物概要

目的：让团队在进入 Phase 1 之前对系统全貌有清晰共识。

## 执行工作流

当用户要求创建四阶段项目时：

1. **创建 spec 目录**: 用户首次描述需求时，在项目根目录创建 `specs/<编号>-<需求简述>/`，将用户原始需求写入 `story.md`，预建 phase0 ~ phase4 空文件
2. **Phase 0**: 按 SKILL.md 中 Step 0-1 ~ 0-8 逐步与用户确认（**Step 0-7 DB 选型必须明确，决定 Phase 1 是否引入 alembic**）。确认后写入 `phase0.md`，补充 `story.md` 的 Overview Design。用户全部确认后才继续
3. **创建项目结构**: 目录 + pyproject.toml（依赖 `nexusx>=3.2`）。**注意**：nexusx 默认不包含 ASGI 服务器，pyproject.toml 需额外添加 `uvicorn` 和 async DB driver 依赖（in-memory/file sqlite → `aiosqlite`；postgresql → `asyncpg`；mysql → `aiomysql`），启动命令为 `uvicorn src.main:app --reload`。持久化场景还需加 `alembic>=1.13`
4. **Phase 1~4**: 依次读取对应 phase 文件（`phases/phase1.md` ~ `phases/phase4.md`），按 V 型模型执行。每个阶段完成后暂停等用户确认

## 迭代功能的处理

当用户在现有项目上做增量迭代时：

1. **仍需创建 spec 目录** — `specs/<编号>-<需求简述>/`，story.md 记录原始需求
2. **Phase 0 快速确认** — 只确认变更部分（新增实体/字段/方法），不变的部分不重复讨论
3. **允许合并 Phase 实现，但 spec 写入不可跳过** — 可以将 Phase 1-3 合并为一次编码，但编码完成后必须逐 Phase 回填 spec 文件（验收标准 + 产出文件）
4. **交付前执行 spec 完整性检查** — 确认所有 phaseN.md 非空后再告知用户完成

## 交付前校验

- **交付前必须校验 spec 文件完整性** — 在告诉用户"任务完成"之前，检查 `specs/<编号>-*/` 下所有 .md 文件是否有内容（非空文件）。合并 Phase 实现时尤其容易遗漏 spec 写入。可用 `wc -l` 快速检查。空文件 = 未完成

## 从旧结构迁移

老项目如果使用了 skill 早期的结构约定，按以下规则迁移到当前结构。**迁移时 MUST 保留 spec 编号**（只允许改描述部分），保证 git 历史连续与外部引用不断裂。

### 路径迁移

| 旧路径 | 新路径 | 说明 |
|---|---|---|
| `spec/phase0.md` 等单数形式 | `specs/<编号>-<需求简述>/phaseN.md` | 与 `## 目录命名` 一致 |
| Phase 0 内联在 SKILL.md | `phases/phase0.md` 外置 | skill 文档侧的迁移，项目侧无影响 |
| `service/<domain>/test.py` | `tests/test_<domain>_methods.py` | 模板代码侧的迁移，规避循环导入 |

### 操作步骤

1. **重命名而非复制**：`git mv specs/<旧编号>-<旧描述>/ specs/<旧编号>-<新描述>/`，保留编号
2. **路径引用全量替换**：在 `story.md` / `phaseN.md` 中 grep 旧路径，逐处替换
3. **跑完整性校验**：交付前校验（见上一节）

### 跳过 Phase 0 的判定标准

老用户做增量迭代时，可跳过 Phase 0 的完整重过，但仅限以下场景：

- ✅ 仅新增字段 / 方法 / 关系 → 跳过 Step 0-1~0-3 的完整重过，只确认 delta
- ❌ 聚合根变更、新业务域、DB 选型切换 → MUST 重做 Phase 0 对应 Step

详见 `phases/phase0.md` 的"老用户迭代"章节（双向引用）。
