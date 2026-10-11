---
description: "nexusx Tasks phase 标签规则——在 /speckit-tasks 之前自动 prepend（before_tasks hook），说明 phase-first 混合排序与 [P1]-[P4] / [USx] 双标签规则。也可独立调用。"
---

# nexusx Tasks phase 标签规则

**用途**：在执行 `/speckit-tasks` **之前**输出 phase 标签规则提示，让生成的 tasks.md 符合 nexusx phase-first 混合排序。

**触发方式**：
- **自动**：装了 nexusx preset 后，`/speckit-tasks` 命令的 `before_tasks` hook 会先跑本命令
- **手动**：直接调用 `/nexusx-tasks-phase-tags`

**插拔安全**：
- 本命令是文档型提示，不修改文件
- hook 失败 / 被禁用时，spec-kit 原生 `/speckit-tasks` 仍正常工作（生成的 tasks.md 按 spec-kit 默认 user-story-first 排序，不带 [P1]-[P4] 标签）
- 移除 nexusx preset 后，本命令与 hook 都消失

**输出位置**：仅打印到对话上下文（提示 spec-kit tasks 命令遵循以下规则）。

---

## nexusx phase-first 混合排序规则

spec-kit 原生 tasks 命令默认按 **user-story-first** 排序（每个 user story 一个 phase）。nexusx 在此基础上叠加 **phase-first** 维度，形成"双层标签"：

### 标签格式

```text
- [ ] [TaskID] [P?] [Pn] [USx] 描述含文件路径
```

| 标签 | 含义 | 来源 |
|------|------|------|
| `[P]` | spec-kit 原生并行标记（可并行任务） | spec-kit 默认 |
| `[P1]` | nexusx Phase 1（Schema 阶段任务） | nexusx |
| `[P2]` | nexusx Phase 2（Methods 阶段任务） | nexusx |
| `[P3]` | nexusx Phase 3（Service 阶段任务） | nexusx |
| `[P4]` | nexusx Phase 4（TS SDK 阶段任务，条件生成） | nexusx（仅当 plan 决策 5 = "是"） |
| `[USx]` | spec-kit 原生 user story 标签 | spec-kit 默认 |

### Phase 划分（每个任务必须落且仅落一个）

- **[P1] Schema 阶段**：SQLModel 实体定义、字段约束、关系（Foreign key、Relationship）、`__tablename__`、表初始化
- **[P2] Methods 阶段**：实体的 `@query` / `@mutation` 方法、DTO（输入/输出）、字段级 description
- **[P3] Service 阶段**：Service 切分（按 Phase 0 用户裁定）、跨实体工作流、UseCase 编排、REST + MCP 端点
- **[P4] TS SDK 阶段**（条件）：基于 plan 决策 5 是否生成；包含 graphql-codegen 配置、SDK 入口、类型导出

### 排序规则

1. **首先**按 Phase 排序：[P1] → [P2] → [P3] → [P4]（如有）
2. **Phase 内**按 user story 聚合：同 user story 的任务相邻
3. **跨 Phase 的依赖**：[P3] Service 任务可能依赖 [P1] Schema 与 [P2] Methods；[P4] TS SDK 依赖 [P3]
4. **Setup / Foundational / Polish 任务**不带 phase 标签（与 spec-kit 默认一致）

### Phase 4 条件生成

读 plan.md 的 "决策 5：是否生成 TypeScript SDK"：
- **是** → tasks.md 末尾生成 Phase 4 区块（含 [P4] 任务）
- **否** → 跳过 Phase 4，tasks.md 末尾说明"未生成 Phase 4（plan 决策：不生成 TS SDK）"

### reference 文档引用

生成 tasks.md 时，对应 phase 的实现指南链接到：
- Phase 1 → `presets/nexusx/reference/phase1.md`
- Phase 2 → `presets/nexusx/reference/phase2.md`
- Phase 3 → `presets/nexusx/reference/phase3.md`

---

## 完成后

打印完规则提示后，控制权自动交回 spec-kit 原生 `/speckit-tasks` 命令——后者会按上述规则生成 tasks.md。
