---
description: "nexusx Phase 0 八步访谈——在 /speckit-specify 之前自动 prepend（before_specify hook），也可独立调用。访谈结果写入 spec.md 的 Phase 0 需求确认纪要区块。"
---

# nexusx Phase 0 八步访谈

**用途**：在执行 `/speckit-specify` **之前**完成 nexusx Phase 0 八步访谈，把结论填入 spec.md 的 "Phase 0 需求确认纪要" 区块。

**触发方式**：
- **自动**：装了 nexusx preset 后，`/speckit-specify` 命令的 `before_specify` hook 会先跑本命令（参考 `.specify/extensions.yml`）
- **手动**：直接调用 `/nexusx-phase0`——适合用户想先做访谈再写 spec、或 hook 被禁用时的 fallback

**插拔安全**：
- 本命令独立可调用，不依赖 spec-kit 命令
- hook 失败 / 被禁用时，spec-kit 原生 `/speckit-specify` 流程仍正常工作（spec.md 内 Phase 0 区块作为占位提示，用户可手动填写或留空）
- 移除 nexusx preset 后，本命令与 hook 都消失，spec-kit 主流程完全不受影响

**输出位置**：`<spec-dir>/spec.md` 的 `## Phase 0 需求确认纪要` 区块（spec-template.md 顶部预留）。如果 spec.md 不存在，本命令仅产出访谈纪要供后续手动写入。

---

## 八步访谈流程

### Step 0-1 术语与实体定义

逐一列出本特性涉及的业务实体。每个实体说明业务含义、核心字段、字段约束。

| 实体 | 业务含义 | 核心字段（名称+类型+语义） | 字段约束 |
|------|----------|-----------------------------|----------|
| [Entity 1] | [一句话业务含义] | [关键属性] | [唯一/非空/枚举/联合唯一] |

### Step 0-2 实体关系

用文本 ER 图展示实体间关系。

```
User ──1:N──→ Post
Post ──N:M──→ Tag   (中间表: PostTag)
```

### Step 0-3 聚合根

明确本特性的聚合根（业务入口实体）。每个聚合根必须明确是 SQLModel 实体还是虚拟实体。

| 聚合根 | 类型 | 数据持久化 | 选用理由 |
|--------|------|------------|----------|
| [Aggregate 1] | SQLModel / 虚拟实体 | 落表 / 不落表 | [判断依据] |

### Step 0-4 Service 切分候选方案 ⚠️ 用户裁定

**Constitution Principle IV 强制门**：本节必须由用户从候选方案中选择，禁止模型自行决定。

提出至少 2 个候选方案（按业务功能域 / 按聚合根 / 混合），列出优劣，等用户选择。

### Step 0-5 GraphQL 定位

GraphQL 在本项目中是辅助开发测试与 AI 测试接口，不是正式 API。

### Step 0-6 第三方库确认

| 功能领域 | 推荐方案 | 维护状态已调查 | 备注 |
|----------|----------|----------------|------|
| 认证 | [候选] | [是/否] | [兼容性说明] |

### Step 0-7 DB 选型 + 迁移策略

从 In-memory SQLite / File-backed SQLite / Docker PostgreSQL / Docker MySQL / External DB 中选择。

**用户最终选择**: 等用户明确选定。

### Step 0-8 检查清单

进入 Phase 1（plan 阶段）之前，以下必须全部 ✅：

- [ ] 所有实体和字段完整，约束清晰
- [ ] 实体关系方向和基数正确
- [ ] 聚合根明确，类型（SQLModel / 虚拟）已确认
- [ ] **Service 切分方案由用户明确选择**
- [ ] 核心用例覆盖主要业务场景
- [ ] 第三方库选型确认
- [ ] **DB 选型 + 迁移策略由用户明确选定**
- [ ] 无明显遗漏或未讨论的边界情况

---

## 完成后

把八步结论以 `### Session YYYY-MM-DD` 区块形式追加到 spec.md 的 `## Phase 0 需求确认纪要` 下，然后由 spec-kit 原生 `/speckit-specify` 接管剩余的 spec 撰写流程（用户故事、需求、成功标准等）。

如果是从 hook 自动触发（before_specify），完成后控制权自动交回 spec-kit specify 命令。
