---

description: "nexusx preset 任务模板：phase-first 混合组织（Schema → Methods → Service → 可选 SDK）"
---

# Tasks: [FEATURE NAME]

**Input**: Design documents from `/specs/[###-feature-name]/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), data-model.md, research.md, contracts/

**Tests**: 示例中包含测试任务。仅当 spec.md 明确要求时才生成测试任务。

## 组织原则 *(nexusx preset)*

**Phase-first 混合**：顶层按 nexusx Phase 组织（Schema → Methods → Service → 可选 SDK），同一 Phase 内的任务用 `[USx]` 标签标注所属用户故事。

**理由**：nexusx 的硬约束是 phase 顺序 + V 型验收 + phase 间暂停。用户故事优先布局会把 Schema 工作散到 US1/US2/US3，掩盖"Schema 完成后暂停"的闸门。在 nexusx 中 Phase 3 之前无可交付物，所以"每故事 MVP 独立性"弱于 phase 推进。

**跨故事共享实体**（如 `User` 被 US1+US2 共用）放在 Phase 1 顶部，标注 `[US1] [US2]` 多标签。

## Format: `[ID] [P?] [P<phase>] [US?] Description`

- **[P]**: 可并行（不同文件，无依赖）
- **[P1] / [P2] / [P3] / [P4]**: nexusx phase 标签（必填）
- **[USx]**: 用户故事标签（多故事共享任务可标多个 `[US1] [US2]`）
- 任务描述必须包含具体文件路径

## Path Conventions

- 单项目：仓库根 `src/`、`tests/`
- 路径假设为单项目布局；如 plan.md 选择其他结构需相应调整

<!--
  ============================================================================
  以下任务为 nexusx preset 的样例骨架。`__SPECKIT_COMMAND_TASKS__` 命令必须根据：
  - spec.md 的 Phase 0 需求确认纪要（实体/关系/聚合根/Service 切分/DB 选型）
  - plan.md 的 Technical Context 与 Phase 决策记录
  - data-model.md 的实体定义
  替换为真实任务。

  任务必须按 nexusx phase 组织，每个 task 都带 `[P1]/[P2]/[P3]/[P4]` 标签。
  Phase 4 仅在 plan.md 的"是否生成 TS SDK"为"是"时生成。
  ============================================================================
-->

## Phase 1: Schema (Entities + DB + ER + mock seed)

**Goal**: 定义纯实体模型（字段 + 关系声明）+ DB engine + mock seed data + Voyager ER 可视化

**Reference**: `presets/nexusx/reference/phase1.md`（包含 alembic 详细配置、lazy=noload 强制、踩坑经验）

**V 降验收标准** *(写入 `specs/<NNN>-<name>/phase1.md`)*:
- [ ] 1. 每个 Entity 在 Voyager ER 图中正确显示
- [ ] 2. `models.py` 中每个 Entity 只包含字段 + Relationship，无 `@query/@mutation` 方法
- [ ] 3. mock seed 数据样本合理（数量、关联、边界值）
- [ ] 4. （持久化场景）alembic baseline 生成 + upgrade 成功

**Tasks**:

- [ ] T001 [P1] 创建 `src/db.py`：engine + async session factory（不导入 models，避免循环依赖；URL 取自 plan.md DB 选型）
- [ ] T002 [P1] [US1] [US2] 创建共享实体 `src/models.py`：定义被多个故事使用的实体（如 User），所有 Relationship 加 `sa_relationship_kwargs={"lazy": "noload"}`，每个 Model 加 docstring，每个 Field 加 description
- [ ] T003 [P1] [US1] 创建 US1 专属实体（在 `src/models.py` 或 `src/models/<domain>.py`）
- [ ] T004 [P1] [US2] 创建 US2 专属实体
- [ ] T005 [P1] 创建 `src/database.py`：in-memory → `init_db()` 做 create_all + mock seed；持久化 → no-op
- [ ] T006 [P1] 创建 `src/main.py`：FastAPI lifespan + Voyager ER 可视化（`create_use_case_voyager(services=[], er_manager=er)`）
- [ ] T007 [P1] 编写 mock seed data（持久化场景：写到 `var/seed_data.json`，由 `scripts/load_seed.py` 灌入）

**持久化场景额外任务**（plan.md DB 选型为 file sqlite / docker / external 时）:

- [ ] T008 [P1] `pyproject.toml` 加 `alembic>=1.13` + 对应 async driver（`asyncpg` / `aiomysql`）
- [ ] T009 [P1] `alembic init alembic`
- [ ] T010 [P1] 改 `alembic/env.py`：顶部 `import src.models  # noqa: F401`、`target_metadata = SQLModel.metadata`、sync URL 从 env var 读、SQLite 加 `render_as_batch=True`
- [ ] T011 [P1] 改 `alembic/script.py.mako` 加 `import sqlmodel`
- [ ] T012 [P1] `alembic.ini` 的 `sqlalchemy.url =` 留空（env.py 覆盖）
- [ ] T013 [P1] `.gitignore` 加 `var/`
- [ ] T014 [P1] `alembic revision --autogenerate -m "init schema"` → 检查迁移文件 → `alembic upgrade head`
- [ ] T015 [P1] 编写 `scripts/load_seed.py`：把 mock seed 一次性灌入文件 DB（保留 ID）

**V 升 — 用户确认**:
- [ ] 在 Voyager 中确认 ER 图、实体纯字段、mock seed 合理、alembic（如有）已 upgrade

---

## Phase 2: Methods (业务逻辑 + Entity 挂载，GraphQL 可查询)

**Goal**: 按业务域在 `service/<domain>/methods.py` 中实现独立 async 方法，通过 `mount_method()` 挂载到 Entity

**Reference**: `presets/nexusx/reference/phase2.md`（包含 `_mount()` 桥接、`@functools.wraps` 必要性、测试 monkey-patch、踩坑经验）

**V 降验收标准** *(写入 `specs/<NNN>-<name>/phase2.md`)*:
- [ ] 每个 `@query`/`@mutation` 覆盖正常 + 异常场景，验证方式为 GraphiQL 执行
- [ ] `mount_method()` 在 `GraphQLHandler` 之前调用
- [ ] `pytest tests/` 通过

**Tasks** *(每个 domain 一组)*:

- [ ] T020 [P2] [US1] 创建 `src/service/<domain1>/methods.py`：实现 US1 相关业务方法（普通 `async def`，无 `cls`，无装饰器）
- [ ] T021 [P2] [US2] 创建 `src/service/<domain2>/methods.py`（不同 domain 可并行）
- [ ] T022 [P2] 在 `src/models.py` 末尾添加 `mount_method()` 函数：延迟 import methods + `_mount()` 桥接 classmethod 协议 + `@functools.wraps(fn)` 保留 docstring
- [ ] T023 [P2] 在 `src/main.py` 中 `GraphQLHandler` 创建之前显式调用 `mount_method()`
- [ ] T024 [P2] [US1] 编写 `tests/test_<domain1>_methods.py`（项目级 `tests/`，避免循环导入；monkey-patch `async_session`）
- [ ] T025 [P2] [US2] 编写 `tests/test_<domain2>_methods.py`

**V 升 — 用户确认**:
- [ ] 在 GraphiQL 中逐条执行验收表（每个方法的正常 + 异常场景）
- [ ] `pytest tests/` 全部通过

---

## Phase 3: Service (DTO + UseCaseService + REST + MCP + Voyager)

**Goal**: DefineSubset DTO + UseCaseService + 自动 REST 路由 + MCP server + Voyager services 可视化

**Reference**: `presets/nexusx/reference/phase3.md`（包含 DefineSubset 模式、跨层数据流 ExposeAs/SendTo/Collector、MCP http_app lifespan 合并、踩坑经验）

**V 降验收标准** *(写入 `specs/<NNN>-<name>/phase3.md`)*:
- [ ] 1. 每个 REST 端点返回字段符合 DTO 定义（FK 隐藏、关系包含）
- [ ] 2. Voyager 中 service 树展示完整
- [ ] 3. MCP 4 层工具可用（list_apps → describe_compose_schema → describe_compose_method → compose_query）
- [ ] 4. POST body 参数校验生效（缺参 422）

**Tasks** *(每个 service 一组)*:

- [ ] T030 [P3] [US1] 创建 `src/service/<domain1>/dtos.py`：DefineSubset DTO（禁 `from __future__ import annotations`，字段用 DTO 类型不用 SQLModel 实体，关系字段名匹配 ORM relationship 自动加载）
- [ ] T031 [P3] [US1] 创建 `src/service/<domain1>/service.py`：UseCaseService 复用 methods.py 逻辑（query 方法：methods → model_validate → Resolver().resolve；mutation 方法：同单条 get 模式），所有方法声明返回类型注解，service.py 不直接操作 DB
- [ ] T032 [P3] [US1] 创建 `src/service/<domain1>/spec.md`：服务目的、用途、需求、变更记录
- [ ] T033 [P3] [US2] 创建 `<domain2>` 的 dtos.py + service.py + spec.md（与 US1 并行）

**Main.py 集成**:

- [ ] T040 [P3] 在 `src/main.py` 添加：
  - `UseCaseAppConfig` 聚合所有 Service
  - `app.include_router(create_use_case_router(app_config))` 自动生成 REST 路由
  - `mcp = create_use_case_graphql_mcp_server(apps=[app_config], name="API")` 创建 MCP server
  - MCP http_app 配置：`transport="streamable-http", stateless_http=True`，在 FastAPI lifespan 中嵌套 `async with mcp_http.lifespan(mcp_http):`
  - `create_use_case_voyager(services=app_config.services, er_manager=er)` 补充 services 可视化（注意：services 是 UseCaseService 子类列表，不是 apps/UseCaseAppConfig）

**V 升 — 用户确认**:
- [ ] curl `/api/<service>/<method>` 返回字段符合 DTO
- [ ] Voyager 中 services 节点可见
- [ ] MCP 客户端走 4 层工具链路完整
- [ ] 缺参请求返回 422

---

## Phase 4: TS SDK (可选 — 仅当 plan.md "是否生成 TS SDK" 为 "是")

<!--
  Conditional emission: `__SPECKIT_COMMAND_TASKS__` 命令读取 plan.md 的"是否生成 TS SDK"字段。
  为"否"时整段删除本 Phase，不保留空骨架。
-->

**Goal**: 从 FastAPI OpenAPI spec 生成 TypeScript SDK

**Reference**: `presets/nexusx/reference/phase3.md` 第 4 节 + 历史 `skill/phases/phase4.md`

**前提**: Phase 3 必须使用 `create_use_case_router()`（Constitution Principle VIII），否则 OpenAPI 响应类型为 unknown。

**Tasks**:

- [ ] T050 [P4] 创建 `fe/openapi-ts.config.ts`（`@hey-api/openapi-ts` + `operations: { strategy: 'byTags' }`）
- [ ] T051 [P4] 创建 `fe/package.json`（`generate-client` 脚本 + `@hey-api/openapi-ts` 依赖）
- [ ] T052 [P4] `cd fe && npm install && npm run generate-client`
- [ ] T053 [P4] 验证：每个 DTO 字段有 TS 类型、snake_case 字段名原样映射、嵌套关系递归结构正确

---

## Polish & Cross-Cutting Concerns

**Purpose**: 跨多个 phase 的改进

- [ ] T060 [P] 文档更新（每个 service 的 spec.md 补充变更记录）
- [ ] T061 [P] 性能优化（DataLoader 缓存命中率、SQL 列裁剪）
- [ ] T062 [P] Security hardening（认证集成、租户隔离）
- [ ] T063 [P] Run `quickstart.md` 端到端验证

---

## Dependencies & Execution Order

### Phase 依赖

- **Phase 1 Schema**: 无依赖，立即开始。完成后**必须暂停**等用户 V 升确认
- **Phase 2 Methods**: 依赖 Phase 1 完成。完成后**必须暂停**
- **Phase 3 Service**: 依赖 Phase 2 完成。完成后**必须暂停**
- **Phase 4 SDK** *(可选)*: 依赖 Phase 3 完成
- **Polish**: 依赖前面所有 phase

### 用户故事依赖

跨 phase 追踪同一用户故事：扫所有 phase 标题找 `[USx]` 标签。共享实体放在 Phase 1 顶部多标签。

### Parallel Opportunities

- 同 phase 内 `[P]` 标记任务可并行
- 不同 domain 的 methods.py / service.py 可跨 phase 并行（但需先完成对应 phase 的共享基础设施）

---

## Implementation Strategy

### Sequential Phase (默认)

1. Phase 1 Schema → V 升确认 → 暂停
2. Phase 2 Methods → V 升确认 → 暂停
3. Phase 3 Service → V 升确认 → 暂停
4. （可选）Phase 4 SDK
5. Polish

**关键**：nexusx 的硬约束是 phase 间暂停（Constitution "Phase 闸门规则"），禁止连续执行多个 phase 不暂停。

---

## Notes

- 每个任务必须含具体文件路径
- 每个 phase 完成后在 `specs/<NNN>-<name>/phaseN.md` 写入 V 降 + V 升 结果
- 交付前校验所有 phaseN.md 非空（空文件 = 未完成）
