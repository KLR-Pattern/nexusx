---
description: "nexusx Plan 决策访谈——在 /speckit-plan 之前自动 prepend（before_plan hook），承载 DB 选型 / alembic / 第三方库 / TS SDK 决策。也可独立调用。"
---

# nexusx Plan 决策访谈

**用途**：在执行 `/speckit-plan` **之前**完成 nexusx 专属决策访谈，把结论填入 plan.md 的 Technical Context 区块。

**触发方式**：
- **自动**：装了 nexusx preset 后，`/speckit-plan` 命令的 `before_plan` hook 会先跑本命令
- **手动**：直接调用 `/nexusx-plan-decisions`

**前置条件**：spec.md 必须存在且 Phase 0 需求确认纪要已填写（参考 `/nexusx-phase0`）。本命令开始时会校验 Phase 0 完整性，缺失则提示用户先跑 `/nexusx-phase0`。

**插拔安全**：
- 本命令独立可调用
- hook 失败 / 被禁用时，spec-kit 原生 `/speckit-plan` 流程仍正常工作（Technical Context 由用户手动填写或留 NEEDS CLARIFICATION 占位）
- 移除 nexusx preset 后，本命令与 hook 都消失

**输出位置**：`<spec-dir>/plan.md` 的 Technical Context 区块（plan-template.md 中预留）。

---

## 决策 1：DB 选型 + async driver

从 spec Phase 0 Step 0-7 的用户选择中确认并细化：

| 项 | 决策 |
|----|------|
| DB 类型 | In-memory SQLite / File-backed SQLite / Docker PostgreSQL / Docker MySQL / External DB |
| async driver | aiosqlite / asyncpg / aiomysql |
| async URL 形态 | `sqlite+aiosqlite://` / `sqlite+aiosqlite:///./var/<name>.db` / `postgresql+asyncpg://...` 等 |
| 同步 URL（alembic 用） | 对应 sync driver（sqlite / psycopg2 / mysqlclient） |

## 决策 2：alembic 迁移策略

| 项 | 决策 |
|----|------|
| 是否引入 alembic | 是 / 否（仅 In-memory SQLite 跳过） |
| 初始 migration 来源 | 自动从 SQLModel metadata 生成 / 手写 |
| seed 数据策略 | `init_db()` 钩子 / migration hook / 手动 |

## 决策 3：第三方库维护状态调查

对每个第三方库（来自 Phase 0 Step 0-6）调查：

- 最新 release 版本与日期
- 是否仍活跃维护（最近 commit / release 时间）
- 与本项目 Python 版本、SQLModel / FastAPI 版本的兼容性
- 替代方案（如果维护状态不佳）

发现废弃或兼容性问题需告知用户、提供替代方案。

## 决策 4：Service 切分最终方案（基于 Phase 0 Step 0-4 用户选择）

把 Phase 0 用户选择的 Service 切分候选方案落到具体目录结构与边界：

```text
src/<project>/service/
├── <domain1>/
│   ├── methods.py
│   ├── dtos.py
│   └── service.py
└── <domain2>/
    └── ...
```

## 决策 5：是否生成 TypeScript SDK（Phase 4）

| 项 | 决策 |
|----|------|
| 是否生成 TS SDK | 是 / 否 |
| SDK 输出位置 | `sdk/<project>-ts/` 或 `packages/<project>-sdk/` |
| GraphQL schema 来源 | SDL 文件 / introspection |
| 生成工具 | graphql-codegen / 自研 |

如果选 "是"，tasks 阶段会条件生成 Phase 4 任务；如果选 "否"，tasks 阶段跳过 Phase 4。

---

## 完成后

把 5 个决策结论写入 plan.md 的 Technical Context，然后由 spec-kit 原生 `/speckit-plan` 接管剩余的 plan 撰写流程（research.md / data-model.md / contracts/ / quickstart.md 生成）。

如果是从 hook 自动触发（before_plan），完成后控制权自动交回 spec-kit plan 命令。
