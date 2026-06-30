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

## 下一步选项

| 选项 | 含义 | 工作量 |
|---|---|---|
| **A**：继续 US2 + US4 + Polish | 完成剩余 16 任务（T016-T018, T026-T028, T036-T038） | 中 |
| **B**：暂停，提交当前状态作为可发布内部预览 | commit + 推送（不 merge master） | 小 |
| **C**：先 commit 当前状态，再继续 US2/US4 | 兼具——保留检查点 + 继续推进 | 小+中 |

剩余任务依赖：
- US2（T016-T018）独立，可与 Polish 中除 T038 外的任务并行
- US4（T026-T028）依赖 US2 完成（phase3.md 重组需要 SKILL 总览稳定）
- T038（FR-012 双向引用）依赖 T016 完成（phase0.md 需先存在）
