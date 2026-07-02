# Feature Specification: [FEATURE NAME]

**Feature Branch**: `[###-feature-name]`

**Created**: [DATE]

**Status**: Draft

**Input**: User description: "$ARGUMENTS"

## Phase 0 需求确认纪要 *(nexusx preset mandatory)*

<!--
  nexusx preset 强制：specify 阶段必须先与用户完成 Phase 0 八步访谈，把结论记录在此区块。
  完整访谈流程见 commands/speckit.specify.md。本区块的填写质量是 Constitution Principle IV（Service 切分用户裁定）的验收依据。
-->

### Step 0-1 术语与实体定义

逐一列出本特性涉及的业务实体。每个实体说明业务含义、核心字段、字段约束。

| 实体 | 业务含义 | 核心字段（名称+类型+语义） | 字段约束 |
|------|----------|-----------------------------|----------|
| [Entity 1] | [一句话业务含义] | [关键属性，不要穷举] | [唯一/非空/枚举/联合唯一] |

### Step 0-2 实体关系

用文本 ER 图展示实体间关系，每条关系标明方向、基数、业务含义、是否需要中间实体。

```
User ──1:N──→ Post
Post ──N:M──→ Tag   (中间表: PostTag)
```

- **关系 1**: [方向] [业务含义]
- **关系 2**: [方向] [业务含义]

### Step 0-3 聚合根

明确本特性的聚合根（业务入口实体）。每个聚合根必须明确是 **SQLModel 实体**还是 **虚拟实体（普通 `pydantic.BaseModel`，不落表）**。

| 聚合根 | 类型 | 数据持久化 | 选用理由 |
|--------|------|------------|----------|
| [Aggregate 1] | SQLModel 实体 / 虚拟实体 | 落表 / 不落表 | [判断依据：字段全部来自 DB → SQLModel；来自请求上下文或聚合多源 → 虚拟] |

**判断依据**：如果根字段全部来自数据库表 → SQLModel；如果字段来自请求上下文（JWT、headers）或聚合多个源 → 虚拟实体。

### Step 0-4 Service 切分候选方案 ⚠️ 用户裁定

<!--
  ⚠️ Constitution Principle IV 强制门：本节必须由用户从候选方案中选择，禁止模型自行决定。
  Specify 命令在向用户提出至少一种候选方案并取得明确选择之前，禁止继续。
-->

**候选方案 A：按业务功能域**

```
auth/    → [methods]
chat/    → [methods]
```

- 优势：[业务内聚]
- 劣势：[可能过大]

**候选方案 B：按聚合根**

```
user/         → [methods]
conversation/ → [methods]
```

- 优势：[每 service 粒度均匀]
- 劣势：[强耦合被拆开]

**候选方案 C：混合（功能域 + 独立聚合）**

```
[domains...]
```

**用户最终选择**: [NEEDS CLARIFICATION: 待用户从 A/B/C 中选择或提出修正方案]

### Step 0-5 GraphQL 定位

GraphQL 在本项目中是**辅助开发测试与 AI 测试**接口，不是正式 API。业务方法定义在 `service/<domain>/methods.py`，挂载到 Entity（GraphQL 辅助）与 UseCaseService（REST + MCP 正式接口）。

### Step 0-6 第三方库确认

| 功能领域 | 推荐方案 | 维护状态已调查 | 备注 |
|----------|----------|----------------|------|
| 认证 | [候选] | [是/否] | [兼容性说明] |
| 实时推送 | [候选] | [是/否] | [兼容性说明] |
| 文件存储 | [候选] | [是/否] | [兼容性说明] |
| 数据迁移 | [候选] | [是/否] | nexusx 已覆盖 ORM/GraphQL/MCP，不在此讨论 |

**注意**：用户指定的库必须先调查维护状态；发现问题需告知用户并提供替代方案。

### Step 0-7 DB 选型 + 迁移策略

从下表选择一种 DB 与迁移策略。**此决策决定 Phase 1 是否引入 alembic、`database.py` 的 `init_db()` 策略**。

| 选项 | async DB URL | 持久化 | Alembic | 适用场景 |
|------|--------------|--------|---------|----------|
| In-memory SQLite | `sqlite+aiosqlite://` | ❌ 进程退出即丢 | ❌ | 纯原型 / Demo / 讨论 |
| File-backed SQLite | `sqlite+aiosqlite:///./var/<name>.db` | ✅ 文件 | ✅ 必须 | 本地开发 / 单人项目 |
| Docker PostgreSQL | `postgresql+asyncpg://...` | ✅ 容器卷 | ✅ 必须 | 团队开发 / 生产前演练 |
| Docker MySQL | `mysql+aiomysql://...` | ✅ 容器卷 | ✅ 必须 | 团队偏好 MySQL |
| External DB | 视驱动 | ✅ | ✅ 必须 | 已有 DB 基础设施 |

**用户最终选择**: [NEEDS CLARIFICATION: 待用户明确选定]

### Step 0-8 检查清单

进入 Phase 1（plan 阶段）之前，以下必须全部 ✅：

- [ ] 所有实体和字段完整，约束清晰
- [ ] 实体关系方向和基数正确
- [ ] 聚合根明确，每个聚合根类型（SQLModel / 虚拟）已确认
- [ ] **Service 切分方案由用户明确选择**（Constitution Principle IV）
- [ ] 核心用例覆盖主要业务场景，逻辑自洽
- [ ] 第三方库选型确认，维护状态已调查
- [ ] **DB 选型 + 迁移策略由用户明确选定**（影响 Phase 1 alembic）
- [ ] 无明显遗漏或未讨论的边界情况

---

## User Scenarios & Testing *(mandatory)*

<!--
  IMPORTANT: User stories should be PRIORITIZED as user journeys ordered by importance.
  Each user story/journey must be INDEPENDENTLY TESTABLE.
-->

### User Story 1 - [Brief Title] (Priority: P1)

[Describe this user journey in plain language]

**Why this priority**: [Explain the value and why it has this priority level]

**Independent Test**: [Describe how this can be tested independently]

**Acceptance Scenarios**:

1. **Given** [initial state], **When** [action], **Then** [expected outcome]
2. **Given** [initial state], **When** [action], **Then** [expected outcome]

---

### User Story 2 - [Brief Title] (Priority: P2)

[Describe this user journey in plain language]

**Why this priority**: [Explain]

**Independent Test**: [How to test independently]

**Acceptance Scenarios**:

1. **Given** [initial state], **When** [action], **Then** [expected outcome]

---

### Edge Cases

- What happens when [boundary condition]?
- How does system handle [error scenario]?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST [specific capability]
- **FR-002**: System MUST [specific capability]

*Marking unclear requirements:*

- **FR-XXX**: System MUST [NEEDS CLARIFICATION: reason]

### Key Entities *(include if feature involves data)*

- **[Entity 1]**: [What it represents, key attributes without implementation]
- **[Entity 2]**: [Relationships to other entities]

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: [Measurable metric, e.g., "Users can complete X in under Y minutes"]
- **SC-002**: [Measurable metric]

## Assumptions

- [Assumption about target users]
- [Assumption about scope boundaries]
- [Assumption about data/environment]
