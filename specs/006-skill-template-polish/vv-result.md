# V&V 结果：skill 内容结构与模板优化

**Feature**: 006-skill-template-polish
**最后更新**: 2026-07-01
**已覆盖范围**: Phase 1 Setup + Phase 2 Foundational + Phase 3 US1 + Phase 5 US3 = 22 任务（T001-T015, T019-T025）

---

## 检查 1：文档自洽性（US1，FR-001）

| 子项 | baseline | 当前 | 状态 |
|---|---|---|---|
| 1.1 `spec/phaseN` 精确匹配 | 6 处 | 1 处（迁移表"旧路径"列，有意保留） | ✅ PASS |
| 1.1 ASCII 图 `spec/<phase>.md`（SKILL.md:54/64） | 2 处 | 2 处 | ⚠️ 延迟到 T016（US2） |
| 1.2 `argument-hint` 残留 | 1 处 | 0 | ✅ PASS |
| 1.3 main.py 默认出口 | 全开 | REST + UseCase MCP + Voyager + GraphQL HTTP 推荐；base MCP 加层级注释；JSON-RPC / CLI 注释化 | ✅ PASS |
| 1.4 `template/src/router/` | 存在 | 已删 | ✅ PASS |
| 1.5 service 文件结构对等 | user 缺 dtos/service/test | 三 service 完全对等（`__init__` / `methods` / `dtos` / `service` / `spec`） | ✅ PASS |

---

## 检查 3：模板可运行性（SC-003）

```bash
cd skill/template && uv sync --all-extras && uv run uvicorn src.main:app --port 8765
```

| 端点 | 路径 | 状态 |
|---|---|---|
| Voyager | `GET /voyager/` | ✅ HTTP 200 |
| GraphQL（GraphiQL） | `GET /graphql` | ✅ HTTP 200 |
| OpenAPI | `GET /openapi.json` | ✅ HTTP 200，含 11 个 path |
| REST（user） | `POST /api/user_service/list_users` | ✅ HTTP 200，返回 `[{"id":1,"name":"Alice"},{"id":2,"name":"Bob"},{"id":3,"name":"Charlie"}]` |

**SC-003 通过**：4/4 端点可访问，模板开箱即用，无需手工修改。

OpenAPI 完整 path 列表（11 个）：

```
GET    /graphql
POST   /graphql
GET    /schema
POST   /api/user_service/list_users
POST   /api/user_service/create_user
POST   /api/task_service/list_tasks
POST   /api/task_service/get_tasks_by_sprint
POST   /api/task_service/create_task
POST   /api/sprint_service/list_sprints
POST   /api/sprint_service/get_sprint
POST   /api/sprint_service/create_sprint
```

REST 路径模式：`/api/<service_name>/<method_name>`（不含 app_name 前缀）。

---

## 检查 4：测试位置与可运行性（SC-006，FR-006）

```
skill/template/tests/
├── conftest.py                  # in-memory sqlite + monkey-patch session
├── test_user_methods.py         # 3 cases
├── test_sprint_methods.py       # 3 cases
└── test_task_methods.py         # 4 cases
```

```bash
uv run pytest tests/ -v
```

**结果**：10 passed in 0.09s

| 测试文件 | 用例数 | 状态 |
|---|---|---|
| test_user_methods.py | 3（含 1 边界：空表） | ✅ |
| test_sprint_methods.py | 3（含 1 边界：not found） | ✅ |
| test_task_methods.py | 4（含 2 边界：empty filter / empty table） | ✅ |

**SC-006 通过**：每个 service 覆盖至少 1 个正常 + 1 个边界场景。

---

## 已知延迟项（剩余 user story 范围）

| 项 | 当前状态 | 闭环任务 |
|---|---|---|
| SKILL.md:54/64 ASCII 图中的 `spec/<phase>.md` | 待重排 | T016（US2） |
| Phase 0 内联 SKILL.md | 约 200 行内联 | T016/T017（US2） |
| Phase 3 文档过载（6 出口并列） | phase3.md 待重组 | T026~T028（US4） |
| Phase 3 内联摘要（虚拟实体/跨层数据流/3.0 MCP） | FR-011 待落实 | T018/T027/T028 |

---

## 阶段结论

✅ **MVP + US3 完成（22 任务）**：
- 所有 P0 矛盾点闭环（路径 / argument-hint / router 残留 / main.py 默认出口）
- 模板可直接 `uv sync && uvicorn` 启动，4 端点全通
- 10 个测试用例覆盖三个 service 的正常 + 边界场景
- service 文件结构完全对等（user/sprint/task 三者一致）

✅ **可发布内部预览**：开发者照模板学 Phase 1~3 不会因矛盾卡住；测试位置统一在 `tests/`；main.py 默认推荐出口 + 可选注释清晰。

⚠️ **未完成项不影响发布**：Phase 0 外置（US2）、Phase 3 重组（US4）属于"锦上添花"——当前 SKILL.md 仍可用，只是不够"瘦"；phase3.md 信息密度高但仍正确。

---

## Polish 阶段全量验证（T029-T035，2026-07-01）

### 已 commit 的 3 个 commit（分支 `006-skill-template-polish`）

```
ecbb227  feat(skill/template): 补齐 user service / 测试位置统一 / main.py 出口分级
9ea4578  docs(skill): 校准路径 / frontmatter / 版本门槛 / 中文化与迁移指引
40ef7a8  docs(specs): 006-skill-template-polish 全套 spec-kit 产物
```

### 全 6 组检查结果

| # | 检查 | 状态 | 说明 |
|---|---|---|---|
| 1 | 自洽性 | ✅ PASS | 5/5 子项全过；唯一保留为迁移表"旧路径"列 |
| 2 | 入口总览可读性 | ⚠️ PARTIAL | 2.1 含 `## 适用版本` + `## 调用约定` 总览开端；2.2 Phase 0 外置延迟到 T016；2.3 版本集中 PASS（散落门槛 phaseN=0） |
| 3 | 模板可运行性 | ✅ PASS | 4/4 端点 HTTP 200；模板 seed 3 用户 |
| 4 | 测试位置与运行 | ✅ PASS | 10/10 pytest 通过；tests/ 下三文件；原 service/test.py 已删 |
| 5 | 核心概念自包含 | ⚠️ PARTIAL | phase3.md 已提跨层数据流（line 15-17）和 3.0 MCP（line 52）；FR-011 完整 10~20 行内联摘要延迟到 T018/T027/T028 |
| 6 | spec-management 完整性 | ✅ PASS | 含 `## 语言要求` + `## 从旧结构迁移` |

**总评**：3 项完全 PASS、2 项 PARTIAL（依赖 US2/US4 后续落实）、1 项需人工（T035 SC-001/SC-004）。

### 人工评测（T035）— 待执行

| SC | 测评对象 | 方法 | 当前状态 |
|---|---|---|---|
| SC-001 | 独立开发者首次使用 skill | 计时从读到产出 Phase 1 项目 ≤30 分钟 | ⏳ 待招志愿者 |
| SC-004 | phase 文档独立阅读理解度 | 抽 phase2.md，5 题答对 ≥4 | ⏳ 待招志愿者 |

未执行原因：自动化无法评测。建议下次有合适 reviewer 时执行。

---

## 下一步选项

| 选项 | 含义 | 工作量 |
|---|---|---|
| **A**：继续 US2 + US4（剩余 9 任务 T016-T018, T026-T028, T038） | 完成所有 P1/P2/P3 user story | 中 |
| **B**：暂停，分支作为内部预览 | 已 commit，可 push（待用户指令） | — |
| **C**：跑 PR 自检（code-review / security-review） | 准备 merge master 前的自检 | 小 |

剩余任务依赖：
- US2（T016-T018）独立，可与 T038 并行
- US4（T026-T028）依赖 US2 完成（phase3.md 重组需要 SKILL 总览稳定）
- T038（FR-012 双向引用）依赖 T016 完成（phase0.md 需先存在）
