---

description: "skill 内容结构与模板优化的任务清单"
---

# Tasks: skill 内容结构与模板优化

**输入**: 设计文档来自 `/specs/006-skill-template-polish/`（plan.md / spec.md / research.md / data-model.md / contracts/skill-interface.md / quickstart.md）

**测试**: 本 feature 是文档/模板优化项目，无新增业务代码测试。Polish 阶段以 `quickstart.md` 的 7 组检查作为验收测试，**强制执行**。

**组织**: 按 spec.md 的 4 个 user story（US1~US4）+ Setup/Foundational/Polish 三层组织。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成任务依赖）
- **[Story]**: 任务归属的 user story（US1=自洽 / US2=入口总览 / US3=模板完整 / US4=决策引导）
- 每个任务都带具体文件路径

## Path Conventions

- 本 feature 修改对象是 `skill/` 子树
- 文档路径：`skill/SKILL.md` / `skill/spec-management.md` / `skill/phases/phaseN.md`
- 模板路径：`skill/template/src/...` / `skill/template/tests/...`
- spec 路径：`specs/006-skill-template-polish/...`

---

## Phase 1: Setup（项目准备）

**Purpose**: 建立修改基线，记录"修改前"状态用于最终对比

- [ ] T001 切换到 feature 分支 `006-skill-template-polish`（已由前置流程创建）；确认工作树干净
- [ ] T002 [P] 跑一遍 quickstart.md 检查 1 的 grep 命令，把"修改前"的命中数记录到 `specs/006-skill-template-polish/baseline.md`（用于 V&V 对比）
- [ ] T003 [P] 备份当前 `skill/SKILL.md`（git tag `skill-pre-polish-006`），方便回滚对比

---

## Phase 2: Foundational（路径与术语统一 — 阻塞所有 user story）

**Purpose**: 修复 P0 级矛盾点（路径不一致、frontmatter 非法字段、版本散落、中文化声明缺失），所有后续 user story 都依赖这些基础对齐

**⚠️ CRITICAL**: 此阶段未完成前，禁止进入 Phase 3+ 任何 user story

- [ ] T004 [P] 编辑 `skill/SKILL.md` 删除 frontmatter 中的 `argument-hint` 字段（保留 `name` / `description` 两个字段），把调用约定说明移到正文 Phase 0 章节前的"调用约定"段落
- [ ] T005 [P] 全局路径统一：`grep -rn "spec/phase" skill/` 找到所有单数路径引用，逐处替换为 `specs/<编号>-<需求简述>/phaseN.md` 或上下文相关的具体路径；覆盖 `skill/SKILL.md` + `skill/phases/phase1.md` ~ `phase4.md` + `skill/spec-management.md`
- [ ] T006 [P] 在 `skill/spec-management.md` 文件开头（`## 目录命名` 之前）新增 `## 语言要求` 章节，声明所有 spec-kit 产物使用中文，引用项目 `CLAUDE.md` 的对应规则
- [ ] T007 [P] 在 `skill/spec-management.md` 末尾新增 `## 从旧结构迁移` 章节（FR-009），覆盖：① `spec/` 单数 → `specs/<编号>-*/` 复数；② Phase 0 从 SKILL.md 内联 → `phases/phase0.md` 外置；③ 老项目存量 spec 文件的迁移建议
- [ ] T008 [P] 在 `skill/SKILL.md` frontmatter 之后新增 `## 适用版本` 章节，声明 `nexusx >= 3.2`，附特性-版本对照（虚拟实体=3.2+，UseCase GraphQL MCP=3.0+）
- [ ] T009 编辑 `skill/phases/phase1.md` / `phase2.md` / `phase3.md`：移除正文中散落的"3.0 起"、"3.2+"等零散版本门槛，改为引用"参见 SKILL.md 适用版本"；保留具体 API 引用（如 `create_use_case_graphql_mcp_server`）旁边的版本说明时简化为"3.0+"

**Checkpoint**: 所有 P0 矛盾点的基础对齐完成；后续 user story 可以开始

---

## Phase 3: User Story 1 - 文档与模板自洽 (Priority: P1) 🎯 MVP

**Goal**: 文档中提到的路径、API、文件位置与模板代码完全一致，零矛盾

**Independent Test**: 随机抽取 5 处 skill 文档中的具体陈述（路径、API、文件名），逐一在模板代码中找到对应实现，全部命中

### Implementation for User Story 1

- [ ] T010 [P] [US1] 删除 `skill/template/src/router/` 整个目录（与 phase3.md "不需要手写 router" 一致）
- [ ] T011 [P] [US1] 校准 `skill/phases/phase1.md`：确认所有文件路径与 `skill/template/src/` 实际结构对齐（db.py / models.py / database.py / main.py 命名一致），alembic 章节步骤与 `skill/template/pyproject.toml` 依赖示例对齐
- [ ] T012 [P] [US1] 校准 `skill/phases/phase2.md`：踩坑 #6 已经说"项目级 tests/"，模板要同步——本任务只改文档侧的描述措辞（具体迁移在 US3）；同步更新 `mount_method()` 示例与模板 `models.py` 一致
- [ ] T013 [P] [US1] 校准 `skill/phases/phase4.md`：术语、路径（`spec/` → `specs/<编号>-*/`）、版本声明对齐 Phase 0~3；不修改 `fe/` 模板代码（FR Out-of-Scope）
- [ ] T014 [US1] 重组 `skill/template/src/main.py`：默认仅挂载 REST（`create_use_case_router`）+ UseCase GraphQL MCP（`create_use_case_graphql_mcp_server`）+ Voyager（`create_use_case_voyager`）+ GraphQL HTTP（`GraphQLHandler` + `/graphql`）；JSON-RPC（`create_jsonrpc_router`）和 CLI（`create_use_case_cli`）以注释形式保留；为保留的 `create_mcp_server` 调用加注释说明它属于"base 实体层 MCP（与 UseCase MCP 不同的层级）"，避免与 phase3.md "3.0 起 UseCase MCP 只有 GraphQL 模式"冲突
- [ ] T015 [US1] 校准 `skill/template/pyproject.toml`：确认 `[tool.hatch.build.targets.wheel] packages = ["src"]`；补依赖 `uvicorn`（启动用）、`aiosqlite`（默认 in-memory sqlite driver）；持久化场景的 `alembic>=1.13` / `asyncpg` / `aiomysql` 以注释示例；同步更新 `skill/template/uv.lock`（`uv lock`）

**Checkpoint**: 文档与模板完全自洽；`grep -rn "spec/phase" skill/` 应为空（除 specs/ 复数）；模板可启动

---

## Phase 4: User Story 2 - 入口总览 + Phase 0 外置 (Priority: P1)

**Goal**: 新用户 5 分钟内能通过入口总览掌握四阶段全貌；Phase 0 与 Phase 1~4 结构对称

**Independent Test**: 找一名未用过 nexusx 的开发者，给他 5 分钟阅读 SKILL.md 顶部入口总览，能 80% 准确口述四阶段每阶段做什么

### Implementation for User Story 2

- [ ] T016 [US2] 新建 `skill/phases/phase0.md`：把 `skill/SKILL.md` 当前的 Phase 0 章节（Step 0-1 ~ Step 0-8 + 检查清单）整体迁移过来，按二级标题（`## Step 0-1`、`## Step 0-2` …）分节；保留所有子表格与示例；顶部加 Phase 0 目标说明
- [ ] T017 [US2] 重写 `skill/SKILL.md` 正文：① 在 frontmatter 后加 `## 调用约定`（一句话说明 `/nexusx-4phase [项目目录]`）；② 加 `## 适用版本`（FR-007，已在 T008 创建，此处仅校验）；③ 加 `## 入口总览` 章节，用一张表覆盖 Phase 0~4 的输入/产出文件/关键 API/典型坑（一屏可见）；④ 加 `## Phase 导航` 列出 phase0.md ~ phase4.md 的链接；⑤ **删除**原内联的 Phase 0 详细内容（已迁移到 phase0.md）；⑥ 保留"核心原则 / V 型验收模型"段落
- [ ] T018 [US2] 在 `skill/phases/phase0.md` 的 Step 0-3（聚合根-根类型选择）章节，为"虚拟实体（BaseModel，不落表）"概念补 10~20 行内联摘要，覆盖：何时选虚拟实体、`ErManager.add_virtual_entities()` 的调用时机、与 SQLModel 实体的差异；外部引用 `docs/guide/virtual_entities.md` 标注为"延伸阅读"

**Checkpoint**: SKILL.md 瘦身到 ≤ 150 行；Phase 0 外置完成；新用户入口总览可读

---

## Phase 5: User Story 3 - 完整模板覆盖 (Priority: P2)

**Goal**: 模板项目覆盖 Phase 0~3 完整代码，所有示例 service 文件结构对等；模板可直接运行

**Independent Test**: `cd skill/template && uv sync && uvicorn src.main:app`，4 个端点（`/voyager` / `/graphql` / `/openapi.json` / REST）全部可访问；`pytest tests/` 全过

### Implementation for User Story 3

- [ ] T019 [P] [US3] 新建 `skill/template/src/service/user/dtos.py`：参考 `skill/template/src/service/sprint/dtos.py` 结构，定义 `UserDTO`（用 `DefineSubset` 投影 `User` 实体），字段包含 `id` / `name` / `tasks`（关系字段，`AutoLoad` 标记）
- [ ] T020 [P] [US3] 新建 `skill/template/src/service/user/service.py`：参考 `skill/template/src/service/sprint/service.py` 结构，定义 `UserService`（继承 UseCaseService），实现 `list_users` 和 `create_user` 两个 `@query` / `@mutation` 方法；**所有方法必须声明返回类型注解**（如 `-> list[UserDTO]`、`-> UserDTO`）
- [ ] T021 [US3] 测试文件迁移：把 `skill/template/src/service/sprint/test.py` → `skill/template/tests/test_sprint_methods.py`；`skill/template/src/service/task/test.py` → `skill/template/tests/test_task_methods.py`；删除原位置 `test.py`；调整 import（`from src.service.<domain>.methods import ...` 不变，monkeypatch 路径同步）
- [ ] T022 [US3] 新建 `skill/template/tests/test_user_methods.py`：覆盖 `create_user` 一个正常场景（创建成功，返回 UserDTO）+ 一个边界场景（重名 / 缺字段，返回预期错误）；测试通过 `pytest` 跑通
- [ ] T023 [US3] 更新 `skill/template/src/service/user/spec.md`：补 `UserService` 的服务目的、方法清单、DTO 说明（与 sprint/task 的 spec.md 对等）
- [ ] T024 [US3] 在 `skill/template/src/main.py` 的 `UseCaseAppConfig.services` 列表中加入 `UserService`（与 `TaskService` / `SprintService` 并列）；`create_use_case_voyager(services=...)` 同步加入
- [ ] T025 [US3] 启动验证：`cd skill/template && uv sync && uvicorn src.main:app --port 8765`，curl 探活 `/voyager/` / `/graphql` / `/openapi.json` / `/api/template/user_service/list_users`；4 个端点全 PASS；`pytest tests/` 全过

**Checkpoint**: 三个 service 文件结构对等；模板开箱即用；SC-003 + SC-006 通过

---

## Phase 6: User Story 4 - 决策引导清晰 (Priority: P3)

**Goal**: Phase 3 出口决策时间 ≤ 1 分钟；关键概念自包含

**Independent Test**: 阅读 `phase3.md` 出口决策部分后，能在 1 分钟内回答"AI agent 场景选什么 / 传统 HTTP 场景选什么"

### Implementation for User Story 4

- [ ] T026 [US4] 重组 `skill/phases/phase3.md`：把现有 6 种出口的并列展示拆为两段——① `### 推荐默认组合`（REST + UseCase GraphQL MCP + Voyager + GraphQL HTTP，附场景说明）；② `### 可选扩展`（JSON-RPC、CLI，附"何时启用"指引）；段间加决策树/表格"按场景选出口"
- [ ] T027 [US4] 在 `skill/phases/phase3.md` 内补跨层数据流摘要段落（10~20 行）：覆盖 `ExposeAs(field_name, source=...)` / `SendTo(field_name)` / `Collector(field_name)` 三个 helper 的用途、典型场景；外部引用 `docs/api/api_cross_layer.md` 标注为"延伸阅读"
- [ ] T028 [US4] 在 `skill/phases/phase3.md` 内补 3.0 UseCase GraphQL MCP 迁移摘要段落（10~20 行）：覆盖老的 `create_use_case_mcp_server` / `create_use_case_flat_server` 已移除、新 `create_use_case_graphql_mcp_server` 4 层渐进披露模型；外部引用 `docs/migrations/3.0-use-case-graphql.md` 标注为"延伸阅读"

**Checkpoint**: Phase 3 文档不再过载；FR-005 + FR-011 通过

---

## Phase 7: Polish & 跨故事收尾

**Purpose**: 跑完整 quickstart.md 验证 + 人工评测，归档结果

- [ ] T029 [P] 执行 `quickstart.md` 检查 1（文档自洽性 grep），结果归档到 `specs/006-skill-template-polish/vv-result.md`
- [ ] T030 [P] 执行 `quickstart.md` 检查 2（入口总览可读性），结果归档到 vv-result.md
- [ ] T031 执行 `quickstart.md` 检查 3（模板可运行性 4 端点 curl），结果归档到 vv-result.md
- [ ] T032 [P] 执行 `quickstart.md` 检查 4（pytest tests/），结果归档到 vv-result.md
- [ ] T033 [P] 执行 `quickstart.md` 检查 5（核心概念自包含），结果归档到 vv-result.md
- [ ] T034 [P] 执行 `quickstart.md` 检查 6（spec-management 完整性），结果归档到 vv-result.md
- [ ] T035 人工评测：找一名有 FastAPI 基础但未用过 nexusx 的开发者，执行 SC-001（≤30 分钟产出 Phase 1 项目）+ SC-004（phase2.md 独立阅读理解度 ≥80%）；记录到 vv-result.md
- [ ] T036 [P] 整理 `specs/006-skill-template-polish/phase0.md` ~ `phase4.md` 五份 spec 文档（按 spec-management.md 的"写入时机"要求，回填每个 phase 的"需求说明 / 验收标准 / 实现描述"三段）
- [ ] T037 [P] 把 `specs/006-skill-template-polish/story.md` 补齐（如缺失），含原始需求 + Overview Design
- [ ] T038 建立 FR-012 双向交叉引用：① `skill/phases/phase0.md` 末尾加 `## 老用户迭代：何时跳过 Phase 0` 章节引用 `spec-management.md` 的"迭代功能的处理"；② `skill/spec-management.md` 的"迭代功能的处理"章节反向引用 `phases/phase0.md`；③ 两处都明确"仅新增字段方法 → 可跳过；聚合根 / 业务域 / DB 选型变更 → 必须重做"判定标准

**Checkpoint**: 所有 SC 验证通过；spec 文档闭环；可交付

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖，立即开始
- **Foundational (Phase 2)**: 依赖 Setup 完成；**阻塞所有 user story**
- **US1 (Phase 3)**: 依赖 Foundational；阻塞 US2（共享 SKILL.md）、阻塞 US3（共享 main.py）
- **US2 (Phase 4)**: 依赖 US1 完成（避免 SKILL.md 写入冲突）
- **US3 (Phase 5)**: 依赖 US1 完成（main.py 默认出口先定，再补 user service）；与 US2 可并行（不同文件：US2 改 SKILL/phase0，US3 改 template/service/*）
- **US4 (Phase 6)**: 依赖 US1（T013 改 phase3.md 路径）**和** US2（SKILL 总览结构稳定）都完成；T026~T028 必须在 T013 之后执行（同改 `phases/phase3.md`，避免合并冲突）
- **Polish (Phase 7)**: 依赖所有 user story 完成

### User Story Dependencies

- **US1 (P1)**: Foundational 完成后开始；阻塞下游
- **US2 (P1)**: US1 完成后开始
- **US3 (P2)**: US1 完成后开始；可与 US2 并行
- **US4 (P3)**: US2 完成后开始；可与 US3 并行

### Within Each User Story

- 文档校准类任务（不同 phase 文件）可并行
- 模板代码类任务（同 main.py）必须串行
- 每个故事完成后跑对应 Independent Test 自检

### Parallel Opportunities

- Setup 阶段 T002 / T003 可并行（不同操作）
- Foundational 阶段 T004 / T005 / T006 / T007 / T008 可并行（不同文件）；T009 串行
- US1 阶段 T010 / T011 / T012 / T013 可并行（不同文件）；T014 / T015 串行（同 main.py / pyproject.toml）
- US2 阶段：T016 → T017 串行（SKILL.md 先迁出再重写）；T018 可与 T016/T017 并行（改的是新 phase0.md 的局部章节）
- US3 阶段 T019 / T020 可并行（user/dtos.py 和 user/service.py 不同文件）；T021 → T022 → T023 → T024 → T025 串行
- US4 阶段 T026 → T027 → T028 必须串行（同改 `phases/phase3.md`，避免合并冲突）；且整体必须在 T013（US1 阶段的 phase3 路径校准）完成之后
- Polish 阶段大部分检查可并行

---

## Parallel Example: User Story 3（与 US2 并行启动）

```bash
# 当 US1 完成、US2 正在进行时，另一人可以并行启动 US3：

# US3 内部并行任务（不同文件）：
Task: "T019 新建 skill/template/src/service/user/dtos.py"
Task: "T020 新建 skill/template/src/service/user/service.py"

# US3 串行任务（同文件依赖）：
Task: "T021 迁移 sprint/task 的 test.py 到 tests/"
# 等 T021 完成后：
Task: "T022 新建 tests/test_user_methods.py"
# 等 T022 完成后：
Task: "T023 更新 user/spec.md"
Task: "T024 注册 UserService 到 main.py"
Task: "T025 启动验证 4 端点"
```

---

## Implementation Strategy

### MVP First（仅 US1）

1. 完成 Phase 1 Setup（建基线）
2. 完成 Phase 2 Foundational（**关键** — 阻塞一切）
3. 完成 Phase 3 US1（自洽性修复，14 处 P0/P1 中风险最高的 6 处）
4. **STOP and VALIDATE**: 跑 quickstart.md 检查 1，矛盾点应为 0
5. 此时 skill 已经"无矛盾、可运行"，可作为内部预览版发布

### Incremental Delivery

1. Setup + Foundational → 基线就绪
2. + US1 → 自洽性达成（P0 全闭环）→ 验证 → Demo
3. + US2 → 入口总览可用（新用户上手成本骤降）→ 验证 → Demo
4. + US3 → 模板完整（开箱即用）→ 验证 → Demo
5. + US4 → 决策引导清晰（Phase 3 不再过载）→ 验证 → Demo
6. Polish → V&V 归档 + 人工评测 → 交付

### Solo Developer Strategy（单人执行）

按 Phase 顺序串行：Setup → Foundational → US1 → US2 → US3 → US4 → Polish
每个 phase 完成后 commit，便于回滚。Polish 阶段失败时定位到具体 SC 重新迭代。

---

## Notes

- [P] 标记 = 不同文件 + 无未完成任务依赖；同文件任务一律串行
- [Story] 标签严格映射到 spec.md 的 US1~US4
- 模板代码修改后必须 `cd skill/template && uv sync` 验证依赖解析
- 所有 spec-kit 产物（含本 tasks.md）使用中文
- 实施过程中如发现新矛盾点，**不要在本 tasks.md 直接加任务**——回到 spec.md / plan.md 走变更流程
- 每个 phase 完成后跑对应 quickstart.md 检查作为 checkpoint
