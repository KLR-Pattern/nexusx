# Spec 管理与工作流

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
├── phase2.md       # 业务方法实现 + Entity 挂载
├── phase3.md       # UseCase + 选定的服务接口
└── phase4.md       # TS SDK（启用时）
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
- **四个实施阶段产出**：Phase 1-4 的预期交付物概要

目的：让团队在进入 Phase 1 之前对系统全貌有清晰共识。

## 执行工作流

当用户要求创建四阶段项目时：

1. **创建 spec 目录**: 用户首次描述需求时，在项目根目录创建 `specs/<编号>-<需求简述>/`，将用户原始需求写入 `story.md`；phase 文件在对应阶段开始时创建，不预建无意义的空文件
2. **Phase 0**: 按 Step 0-1 ~ 0-8 完成预检。新项目确认关键决策；现有项目先从代码和配置提取结论。Step 0-7 的 DB/迁移策略必须明确。完成后写入 `phase0.md` 并补充 Overview Design
3. **创建项目结构**: 目录 + pyproject.toml（依赖 `nexusx>=6,<7`；启用 MCP/CLI 时使用 `nexusx[fastmcp,cli]>=6,<7`）。nexusx 默认不包含 ASGI server 和 DB driver，需额外添加 `uvicorn` 与对应 async driver。持久化场景还需加 `alembic>=1.13`
4. **Phase 1~4**: 依次读取对应 phase 文件，按 V 型模型执行。新项目在关键阶段等待确认；用户要求端到端执行或增量迭代时可连续完成并集中汇报

## 迭代功能的处理

当用户在现有项目上做增量迭代时：

1. **仍需创建 spec 目录** — `specs/<编号>-<需求简述>/`，story.md 记录原始需求
2. **Phase 0 快速确认** — 只确认变更部分（新增实体/字段/方法），不变的部分不重复讨论
3. **允许合并 Phase 实现，但适用阶段的 spec 写入不可跳过** — 可以将 Phase 1-3 合并为一次编码，完成后逐 Phase 记录验收标准与产出
4. **交付前执行 spec 完整性检查** — 只检查本次实际执行的 phase 文件；未启用 Phase 4 时不创建或强制填写 phase4.md

## 交付前校验

- **交付前必须校验适用 spec 文件完整性** — 检查本次创建的 story.md 与实际执行的 phaseN.md 是否非空。空文件应删除或补全，不能用占位文件冒充已完成阶段
