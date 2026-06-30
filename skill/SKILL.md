---
name: nexusx-4phase
description: 基于 nexusx 的四阶段开发模式，从 Schema 建模到 API 响应组装再到 TS SDK 的完整项目构建流程。
---

# nexusx 四阶段开发模式

## 适用版本

本 skill 假设 **nexusx >= 3.2**。特性-版本对照：

| 特性 | 起始版本 |
|---|---|
| UseCase GraphQL MCP（`create_use_case_graphql_mcp_server`） | 3.0+ |
| 虚拟实体（`ErManager.add_virtual_entities`） | 3.2+ |
| 跨层数据流（`ExposeAs` / `SendTo` / `Collector`） | 3.0+ |

正文中如提到具体 API 的版本门槛，均以此表为准；不再在各 phase 文档中散落声明。

## 调用约定

```
/nexusx-4phase [项目目录路径]
```

参数为目标目录路径（可选）。未提供时，skill 引导用户在当前位置或指定路径下创建项目。

基于 nexusx 的渐进式开发方法论。项目在一个 `src/` 目录下逐步演进，每个阶段在上一阶段基础上新增代码。

| Phase | 职责 | 产出 |
|-------|------|------|
| **Phase 0** | 需求确认 | 实体 + 关系 + 聚合根 + 用例方法（与用户反复确认） |
| **Phase 1** | Schema + ER Diagram + 聚合根入口 + mock seed | models + db(engine + session) + database(seed) + voyager |
| **Phase 2** | Loader 实现 | models 方法体实现，GraphQL 可查询 |
| **Phase 3** | UseCase 响应组装 + MCP | dtos + services + REST（或 JSON-RPC）+ MCP + CLI + Voyager 补充 services |
| **Phase 4** | OpenAPI spec → TS SDK | 端到端 SDK |

## 核心原则

- **需求确认是 Phase 0，必须反复与用户确认后才能进入 Phase 1**（详见下方「Phase 0: 需求确认」）
- 非功能模块与业务模块解耦，业务概念不侵入基础设施层
- **每个 Phase 采用 V 型验收：先定义验收标准（V 降），再实现，最后回查验收（V 升）**
- **每个 Phase 实现完成后必须暂停，展示验收结果，等用户确认后再进入下一阶段**
- Phase 间递进：同一项目目录下逐步丰富，只新增不修改已有代码

### V 型验收模型（贯穿所有 Phase）

每个 Phase 的结构统一为三段：

```
┌──────────────────────────────────────────────┐
│ V 降：定义验收标准                              │
│   "在当前 Phase 开始之前，先定义什么算做完。"      │
│   写入 phaseN.md 的"验收标准"部分               │
└──────────────────────────────────────────────┘
                      ↓
              ┌───────────────┐
              │   实现 Phase   │
              └───────────────┘
                      ↓
┌──────────────────────────────────────────────┐
│ V 升：逐条回查验收                             │
│   "一条一条对照验收标准，通过才可继续。"           │
│   用户逐条确认 → 写入 phaseN.md                 │
└──────────────────────────────────────────────┘
```

> `phaseN.md` 完整路径为 `specs/<编号>-<需求简述>/phaseN.md`，详见 `spec-management.md` 的「目录命名」。

验收标准必须是**可观察、可操作的**——不写"代码健壮"，写"GraphiQL 中执行 X query 返回 Y"。

## 阶段实现

每个阶段（含 Phase 0）有独立的详细指令文件：

- **Phase 0**（需求确认）: 读取 `phases/phase0.md` — 业务实体 / 关系 / 聚合根 / 用例方法 / 第三方库 / DB 选型的逐项确认
- **Phase 1**（Schema + ER Diagram）: 读取 `phases/phase1.md`
- **Phase 2**（方法实现 + Entity 挂载）: 读取 `phases/phase2.md`
- **Phase 3**（UseCase 响应组装 + MCP）: 读取 `phases/phase3.md`
- **Phase 4**（OpenAPI → TS SDK）: 读取 `phases/phase4.md`

每个阶段完成后，继续进行下一阶段之前暂停并等待用户确认。

对于 Spec 管理工作流（目录命名、文件格式、迭代规则、交付验证、迁移指引），读取 `spec-management.md`。

## 参考实现

读取本 skill 目录下 `template/` 中的代码作为生成参考。严格遵守 template 中的文件结构、import 风格和命名约定。

## 项目结构

单项目渐进演进，每个 Phase 在上一阶段基础上新增文件：

```
src/
├── models.py       # Phase 1 纯实体 → Phase 2 从 methods 挂载 @query/@mutation
├── db.py           # Phase 1（engine + session factory，不依赖 models；URL 由 Step 0-7 DB 选型决定）
├── database.py     # Phase 1（in-memory: create_all+seed；持久化: no-op，schema 由 alembic 管）
├── service/        # Phase 2 新增 methods.py，Phase 3 补充 service.py/dtos.py
│   ├── auth/       # 按业务域划分（非按实体）
│   │   ├── methods.py  # Phase 2: 独立业务方法
│   │   ├── dtos.py     # Phase 3: DTO
│   │   ├── service.py  # Phase 3: UseCaseService
│   │   └── spec.md     # Phase 3: 服务说明（测试不放此处，见下方 tests/）
│   └── chat/
│       ├── methods.py
│       ├── dtos.py
│       ├── service.py
│       └── spec.md
├── main.py         # 逐步扩展（voyager → graphql → create_use_case_router → mcp）
tests/              # 项目级测试目录（不在 service/<domain>/ 下，规避循环导入）
├── conftest.py     # 共享 fixture（in-memory sqlite + monkey-patch session）
└── test_<domain>_methods.py  # 每个业务域一个测试文件
alembic/            # Phase 1 持久化场景才引入（file sqlite / docker / external）
├── env.py          # 接 SQLModel.metadata + sync URL + render_as_batch（sqlite）
├── script.py.mako  # 模板加 import sqlmodel
└── versions/       # 自动生成的迁移文件
scripts/            # Phase 1 持久化场景
└── load_seed.py    # 一次性把 var/seed_data.json 灌入文件 DB（保留 ID）
var/                # gitignored（file sqlite 场景）
├── note-tool.db    # 实际 DB 文件
└── seed_data.json  # mock seed 数据
fe/                 # Phase 4 前端 SDK
├── openapi-ts.config.ts
├── package.json
└── src/sdk/        # 自动生成的 SDK
    ├── sdk.gen.ts      # SDK class（按 tag 分组）
    ├── types.gen.ts    # TS 类型定义
    └── client/         # HTTP client
```

**REST 路由通过 `create_use_case_router(use_case_config)` 自动生成**，不需要手写 `router/` 目录。也可使用 `create_jsonrpc_router()` 替代 REST（JSON-RPC 2.0 协议）。

## 阶段间变化对照

| 方面 | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|------|---------|---------|---------|---------|
| 实体 | 纯字段 + Relationship + docstring + mock seed | methods.py 实现 + `mount_method()` 挂载到 Entity | 继承 Phase 2 | - |
| 关系 | Relationship 声明 | DataLoader 实现 | DefineSubset 隐藏 FK | - |
| 查询 | 无方法 | methods.py + `mount_method()` 挂载 | UseCaseService 封装（复用 methods.py） | - |
| API | Voyager(ER diagram) | GraphiQL | GraphQL + REST（或 JSON-RPC）+ Voyager(+services) + MCP + CLI | TS SDK |
| 响应 | N/A | 完整实体 | DefineSubset DTO | OpenAPI spec |
