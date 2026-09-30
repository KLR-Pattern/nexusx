# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]

**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Note**: 本模板由 `__SPECKIT_COMMAND_PLAN__` 命令填充。详见 `.specify/templates/plan-template.md` 的执行工作流。

## Summary

[从 spec.md 提取：核心需求 + nexusx 技术方案要点（DB 选型、service 切分、是否 TS SDK）]

## Technical Context *(nexusx preset)*

<!--
  nexusx preset：替换通用技术上下文字段为 nexusx 栈强制字段。
  所有未明确字段必须标记为 NEEDS CLARIFICATION；plan 阶段必须全部解决。
-->

**Language/Version**: Python ≥ 3.10（具体版本：[e.g., 3.12 或 NEEDS CLARIFICATION]）

**Primary Dependencies**: nexusx>=3.2, fastapi, uvicorn, sqlmodel, pydantic>=2.0, aiodataloader

**DB 选型**: [从 spec.md Step 0-7 确认结论复制：in-memory sqlite / file sqlite / docker pg / docker mysql / external ___]

**async DATABASE_URL**: [e.g., `sqlite+aiosqlite://` 或 `postgresql+asyncpg://user:pwd@localhost:5432/db` 或 NEEDS CLARIFICATION]

**sync DATABASE_URL_SYNC** *(持久化场景必填，供 alembic + load_seed 使用)*: [e.g., `sqlite:///./var/<name>.db` 或 NEEDS CLARIFICATION]

**Async DB Driver**:
- in-memory / file sqlite → `aiosqlite`
- postgresql → `asyncpg`
- mysql → `aiomysql`

**是否引入 alembic**:
- ✅ 持久化场景（file sqlite / docker / external）：**必须**引入，加 `alembic>=1.13` 依赖
- ❌ in-memory sqlite：不引入

**Testing**: pytest + pytest-asyncio（`tests/` 在项目根，不放 `service/*/` 子目录避免循环导入）

**Target Platform**: [e.g., Linux server / Docker / 本地开发]

**Project Type**: web-service（FastAPI + nexusx）

**Performance Goals**: [domain-specific 或 NEEDS CLARIFICATION]

**Constraints**: [e.g., <200ms p95 或 NEEDS CLARIFICATION]

**Scale/Scope**: [e.g., 10k users, N entities, M services]

## Phase 决策记录

### Service 切分最终方案

[从 spec.md Step 0-4 复制用户最终选择，并列出每个 service 的方法清单]

```
auth/    → register, login
chat/    → create_conversation, list_messages, send_message
```

### 是否生成 TS SDK

- [ ] **是** —— Phase 4 触发，需 `fe/` 子目录，使用 `@hey-api/openapi-ts` 从 `http://localhost:8000/openapi.json` 生成
- [x] **否**（默认）—— 不生成 SDK，跳过 Phase 4

**注意**：选"是"的前提是 Phase 3 使用 `create_use_case_router()` 自动生成 REST 路由（Constitution Principle VIII），否则 OpenAPI spec 响应类型为 unknown，SDK 类型生成失败。

### 第三方库确认清单

| 功能领域 | 选定方案 | 版本 | 维护状态 | 备注 |
|----------|----------|------|----------|------|
| 认证 | [候选] | [版本] | [活跃/维护中/已停更] | [集成要点] |
| 实时推送 | [候选] | [版本] | [活跃/维护中/已停更] | [集成要点] |

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

逐条对照 `presets/nexusx/templates/constitution-template.md` 的 8 条核心原则：

| # | 原则 | 状态 | 备注 |
|---|------|------|------|
| I | 关系懒加载强制 | ✅ / ⚠️ / ❌ | [备注] |
| II | 实体层零业务依赖 | ✅ / ⚠️ / ❌ | [备注] |
| III | 模型与字段自描述 | ✅ / ⚠️ / ❌ | [备注] |
| IV | Service 切分用户裁定 | ✅ / ⚠️ / ❌ | [备注] |
| V | methods.py 挂载时序 | ✅ / ⚠️ / ❌ | [备注] |
| VI | DTO 类型纯净性 | ✅ / ⚠️ / ❌ | [备注] |
| VII | UseCaseService 返回类型强制 | ✅ / ⚠️ / ❌ | [备注] |
| VIII | REST 路由与 MCP 传输协议 | ✅ / ⚠️ / ❌ | [备注] |

任何 ❌ 或 ⚠️ 都必须在下方 Complexity Tracking 中给出理由。

## Project Structure

```text
src/
├── models.py       # Phase 1 纯实体 → Phase 2 通过 mount_method() 挂载方法
├── db.py           # Phase 1（engine + session factory，URL 由 DB 选型决定）
├── database.py     # Phase 1（in-memory: create_all+seed；持久化: no-op，schema 由 alembic 管）
├── service/        # Phase 2 新增 methods.py，Phase 3 补充 service.py/dtos.py
│   └── <domain>/   # 按业务域划分（非按实体），具体见上方 Service 切分最终方案
│       ├── methods.py  # Phase 2: 独立业务方法（普通 async def）
│       ├── dtos.py     # Phase 3: DefineSubset DTO
│       ├── service.py  # Phase 3: UseCaseService
│       ├── test.py     # Phase 3: unittest
│       └── spec.md     # Phase 3: 服务说明
├── main.py         # 逐步扩展（voyager → graphql → create_use_case_router → mcp）
alembic/            # Phase 1 持久化场景才引入（file sqlite / docker / external）
├── env.py          # import src.models + sync URL + render_as_batch（sqlite）
├── script.py.mako  # 模板加 import sqlmodel
└── versions/
scripts/            # Phase 1 持久化场景
└── load_seed.py    # 一次性把 var/seed_data.json 灌入文件 DB
var/                # gitignored（file sqlite 场景）
├── <name>.db
└── seed_data.json
fe/                 # Phase 4 仅在"是否生成 TS SDK"为"是"时引入
├── openapi-ts.config.ts
├── package.json
└── src/sdk/
```

**REST 路由通过 `create_use_case_router(use_case_config)` 自动生成**，不需要手写 `router/` 目录。

## Complexity Tracking

> **仅在 Constitution Check 有 ⚠️ 或 ❌ 时填写**

| 违反项 | 为什么需要 | 拒绝的简化方案及理由 |
|--------|------------|---------------------|
| [e.g., 第 N 条] | [当前需求] | [为什么简化方案不行] |
