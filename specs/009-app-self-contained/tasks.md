---

description: "Task list for feature 009-app-self-contained"
---

# Tasks: 业务应用（Application）自包含数据库连接信息

**Input**: 设计文档来自 `/specs/009-app-self-contained/`

**Prerequisites**: [plan.md](./plan.md)、[spec.md](./spec.md)、[research.md](./research.md)、[data-model.md](./data-model.md)、[contracts/application-public-api.md](./contracts/application-public-api.md)、[quickstart.md](./quickstart.md)

**Tests**: 包含必要的测试任务——新行为（Application 类、lifespan dispose、URL 脱敏）必须有测试覆盖；现有 18 个 manager 单元测试作为回归基线（迁移形式，非 TDD）。

**Organization**: 按 spec 用户故事分组（US1 P1 多 app 合并、US2 P2 独立使用、US3 P3 dict 兼容迁移）。

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: 可并行（不同文件、无未完成任务依赖）
- **[Story]**: 任务所属用户故事
- 描述含具体文件路径

---

## Phase 1: Setup（共享基础设施）

**Purpose**: 为新模块准备空骨架，让 import 链可达

- [X] T001 创建 `src/nexusx/mcp/application.py` 空文件 + module docstring 占位（说明本模块用途、引用 spec/contracts）

---

## Phase 2: Foundational（阻塞性前置 - Application 核心抽象）

**Purpose**: 实现 `Application` 类——所有用户故事的基础。本阶段完成前不得开始任何用户故事。

**⚠️ CRITICAL**: US1 / US2 / US3 都依赖 `Application` 类存在。

- [X] T002 在 `src/nexusx/mcp/application.py` 实现 `Application.__init__`：参数（name、base、url、engine、session_factory、description、query_description、mutation_description、aliases、engine_kwargs，全部 keyword-only）；互斥校验（url/engine/session_factory 至多一个）；aliases 内部校验（list[str]、非空、不与 name 冲突）；按 [data-model.md §2.1](./data-model.md) 与 [contracts §2](./contracts/application-public-api.md) 字段表实现
- [X] T003 在 `src/nexusx/mcp/application.py` 实现 `Application.resources` / `session_factory` 属性——构造期 eager 填充 `_resources`（用 GraphQLHandler + TypeTracer + SDLGenerator 构造 AppResources）；schema-only 模式下 `_session_factory=None`
- [X] T004 在 `src/nexusx/mcp/application.py` 实现 `Application.dispose()` 幂等方法——仅当 `_owns_engine=True` 且未 disposed 时 `await engine.dispose()`；置 `_disposed=True`
- [X] T005 在 `src/nexusx/mcp/application.py` 实现 `Application.__aenter__` / `__aexit__`——前者返回 self，后者调 `await self.dispose()`
- [X] T006 [P] 在 `src/nexusx/mcp/application.py` 实现 URL 凭据脱敏工具函数 `_redact_url(s: str) -> str` 与 `Application.__repr__`（输出脱敏 URL）；覆盖 FR-013
- [X] T007 在 `src/nexusx/mcp/application.py` 实现私有 helper `_coerce_to_application(app, index)`：Application 直接透传；dict 触发 `DeprecationWarning` 并构造 Application；其他类型 TypeError
- [X] T008 [P] 在 `tests/mcp/test_application.py` 新增 Application 单元测试：构造（含 url/engine/session_factory 三种模式 + schema-only）；互斥字段报错；aliases 校验；`dispose()` 幂等（连续调 3 次无副作用）；`__repr__` 脱敏（构造带密码 URL，验证 repr 不含密码）
- [X] T009 在 `src/nexusx/mcp/__init__.py` 的 `__all__` 加入 `Application`，并 import 之；module docstring 添加 Application 的示例代码块

**Checkpoint**: `Application` 类完整、独立可用、有单元测试覆盖。可进入用户故事阶段。

---

## Phase 3: User Story 1 - 跨项目合并多个 app 到统一 mcp 服务（Priority: P1）🎯 MVP

**Goal**: 让 `create_mcp_server(apps=[Application(...), Application(...)])` 工作；lifespan 退出时自动 dispose；现有 18 个 manager 测试不打破

**Independent Test**: 按 [quickstart.md §2](./quickstart.md) 启动 `demo/multi_app`，mcp client 调 `list_apps` / `graphql_query(app_name=...)` 全部正常；Ctrl+C 后日志显示 dispose 调用

### Implementation for User Story 1

- [X] T010 [US1] 重构 `src/nexusx/mcp/managers/multi_app_manager.py::MultiAppManager.__init__`：签名改为 `apps: list[Application | AppConfig]`；用 `_coerce_to_application` 转换每个元素；保留跨 app 校验（unique name、alias 冲突）；`self.apps` / `self.aliases` 仍 eager 填充（从 `app.resources` 读）
- [X] T011 [US1] 在 `MultiAppManager` 新增 `async def dispose()`（循环调每个 Application.dispose）与 `async def __aenter__/__aexit__`
- [X] T012 [US1] 在 `src/nexusx/mcp/server.py::create_mcp_server` 注册 FastMCP `lifespan=`：构造 `@asynccontextmanager` 函数，进入 yield、退出时 `await manager.dispose()`；传给 `FastMCP(name, lifespan=...)`
- [X] T013 [P] [US1] 在 `tests/mcp/test_multi_app_lifespan.py`（新建）添加集成测试：构造 1 个带 `url="sqlite+aiosqlite:///:memory:"` 的 Application + manager，触发 lifespan 进入与退出，断言 engine.dispose 被调用且幂等
- [X] T014 [US1] 跑 `uv run pytest tests/mcp/test_multi_app_manager.py -v` 验证现有 18 个测试在 dict 路径下仍通过（带 `DeprecationWarning` 但不 fail）；如有 fail，修复 MultiAppManager 兼容路径

**Checkpoint**: 多 app 合并到 mcp 服务可用、lifespan 自动 dispose、向后兼容不破坏。可独立 demo。

---

## Phase 4: User Story 2 - 单个 app 作为可独立使用的 Python 包（Priority: P2）

**Goal**: 验证 `Application` 独立使用——schema-only 模式可读 SDL、带连接的 app 可独立执行查询、外部 engine 共享时不被 app dispose

**Independent Test**: 按 [quickstart.md §3](./quickstart.md) 跑独立 Python 脚本（不挂 mcp server）调 `Application` 的 `.resources.sdl_generator.generate()`、`.resources.entity_names`、`async with session_factory() as session: ...`

### Implementation for User Story 2

- [X] T015 [P] [US2] 在 `tests/mcp/test_application.py` 追加独立使用场景测试：schema-only 模式构造（无 url/engine/session_factory），断言 `resources.entity_names` 与 SDL 正常输出、`session_factory is None`
- [X] T016 [P] [US2] 在 `tests/mcp/test_application.py` 追加外部 engine 共享场景测试：传入 `engine=create_async_engine(...)`，调 `await app.dispose()`，断言 engine 仍可用（执行一次简单 select 不报错）；并验证 `_owns_engine=False`
- [X] T017 [P] [US2] 在 `tests/mcp/test_application.py` 追加 `async with Application(...) as app:` 上下文管理测试：离开上下文后 `_disposed=True`
- [X] T018 [US2] 在 `docs/api/api_mcp.md` 与 `docs/api/api_mcp.zh.md` 新增章节"独立使用 Application"——展示不挂 mcp server 直接用 app 查 SDL / 执行查询的代码示例（中文叙述）

**Checkpoint**: 单 app 可独立使用、所有用法有测试覆盖、文档可循。

---

## Phase 5: User Story 3 - 平滑迁移现有 dict 式配置（Priority: P3）

**Goal**: 把仓库内所有 dict 形式 call site 迁移到 `Application`；验证 dict 兼容路径仍工作（带 DeprecationWarning）

**Independent Test**: 按 [quickstart.md §5](./quickstart.md) 临时回退一个 demo 到 dict 形式，验证 `python -W default::DeprecationWarning` 触发警告且功能等价；同时跑全测试套件确认无 fail

### Implementation for User Story 3

- [X] T019 [P] [US3] 迁移 `demo/multi_app/mcp_server.py`：2 个 dict 改为 2 个 `Application(name=..., base=..., url=BLOG_DATABASE_URL)` 等
- [X] T020 [P] [US3] 迁移 `demo/blog/mcp_server.py` 到 Application 形式
- [X] T021 [P] [US3] 迁移 `demo/auth/mcp_server.py` 到 Application 形式
- [X] T022 [P] [US3] 迁移 `skills/nexusx-4phase/template/src/main.py`（39-48 行）dict → `Application(name="template", base=BaseEntity, url=DATABASE_URL)`
- [X] T023 [P] [US3] 迁移 `tests/mcp/test_multi_app_manager.py` 全部 18 个测试：dict → `Application(name=..., base=...)`（schema-only 形式，断言不变）
- [X] T024 [P] [US3] 迁移 `tests/mcp/test_multi_app_tools.py` 的 fixture（79-94 行）到 Application 形式
- [X] T025 [US3] 在 `tests/mcp/test_dict_compat.py`（新建）添加 dict 兼容路径测试：传入 dict 形式断言功能等价 + `DeprecationWarning` 被触发（用 `pytest.warns(DeprecationWarning)`）

**Checkpoint**: 仓库内所有 call site 都用 Application；dict 兼容仍工作并发出警告；测试全绿。

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 文档完善、回归验证

- [X] T026 [P] 更新 `src/nexusx/mcp/__init__.py` 的 module docstring（1-41 行）——补充 Application 类的介绍与跨项目合并场景示例
- [X] T027 [P] 更新 `src/nexusx/mcp/server.py::create_mcp_server` 的 function docstring（62-94 行）——示例改用 Application 形式，注明 dict 形式 deprecated
- [X] T028 [P] 更新 `docs/advanced/mcp_service.md` 与 `.zh.md`——多 app 合并示例改用 Application
- [X] T029 [P] 在 `docs/advanced/mcp_service.md`（或新建独立章节）新增"独立导出 app"指南：子项目 pyproject 配置、`create_app_config()` 工厂约定、entry-point 自动发现（提及为 roadmap）
- [X] T030 跑 `uv run pytest`（全部测试）+ `uv run ruff check src/nexusx/mcp/` + `uv run mypy src/nexusx/mcp/`，全绿
- [X] T031 跑 [quickstart.md](./quickstart.md) 全部 8 个验证场景（§1 单元测试、§2 多 app 合并、§3 独立使用、§4 URL 脱敏、§5 兼容性、§6 回归），人工记录结果

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: 无依赖，T001 立即开始
- **Phase 2 (Foundational)**: 依赖 T001 完成；**阻塞所有用户故事**
- **Phase 3 (US1)**: 依赖 Phase 2 完成（Application 类必须存在）
- **Phase 4 (US2)**: 依赖 Phase 2 完成；与 US1 无依赖，可并行
- **Phase 5 (US3)**: 依赖 Phase 2 + Phase 3 完成（US3 迁移测试需要 MultiAppManager 已重构）
- **Phase 6 (Polish)**: 依赖所有用户故事完成

### Within Phase 2 (Foundational)

- T002 → T003 → T004 → T005（顺序：同一文件，构造先于属性先于 dispose 先于上下文管理）
- T006（URL 脱敏）可与 T002-T005 并行（独立工具函数）——但实际上修改同一文件，建议串行
- T007（_coerce helper）依赖 T002-T005 完成（helper 内部要构造 Application）
- T008（test_application.py）可与 T002-T005 并行编写（TDD 风格），但跑通需要 T002-T005 完成
- T009 依赖 T002（要 import Application）

### Within Phase 3 (US1)

- T010 → T011 → T012（顺序：MultiAppManager 重构先于 dispose 方法先于 server lifespan）
- T013 可与 T010-T012 并行编写（独立测试文件）
- T014 依赖 T010 完成

### Within Phase 5 (US3)

- T019-T024 全部 [P]——不同文件，可同时进行
- T025 依赖 T007（_coerce_to_application）+ T010（MultiAppManager 接受 dict）

### Parallel Opportunities

- Phase 2: T008（测试）可与 T002-T007 并行编写（TDD）
- Phase 4: T015 / T016 / T017 三个测试场景并行（同一文件追加，建议串行避免合并冲突）
- Phase 5: T019-T024（demo/skill/test 迁移）全部不同文件，可全部并行
- Phase 6: T026-T029 不同 docs 文件，可并行

---

## Parallel Example: Phase 5 Call Site Migration

```bash
# 5 个 call site 迁移任务，不同文件，可并行：
Task: "迁移 demo/multi_app/mcp_server.py 到 Application 形式"
Task: "迁移 demo/blog/mcp_server.py 到 Application 形式"
Task: "迁移 demo/auth/mcp_server.py 到 Application 形式"
Task: "迁移 skills/nexusx-4phase/template/src/main.py"
Task: "迁移 tests/mcp/test_multi_app_manager.py（18 个测试）"
Task: "迁移 tests/mcp/test_multi_app_tools.py 的 fixture"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. ✅ Phase 1：T001 创建空骨架
2. ✅ Phase 2：T002-T009 实现 Application 类 + 单元测试 + 导出
3. ✅ Phase 3：T010-T014 重构 MultiAppManager + lifespan + 兼容验证
4. **STOP and VALIDATE**: 按 [quickstart.md §2](./quickstart.md) 启动 `demo/multi_app`，mcp client 调用全部工具正常
5. 此时已可发布——多 app 合并的核心价值已兑现

### Incremental Delivery

1. MVP（US1）→ 多 app 合并可用
2. +US2 → 单 app 独立使用 + 文档指南
3. +US3 → 仓库内全 call site 迁移 + dict 兼容窗口就位
4. +Polish → 文档完善 + 全量回归

### Single PR vs Multi PR

按 [plan.md](./plan.md) 实施序列，本任务清单可对应：

- **PR1 = T001 + T002-T009**（Phase 1 + Phase 2，additive）
- **PR2 = T010-T014**（Phase 3，MultiAppManager 重构）
- **PR3 = T015-T018**（Phase 4，独立使用 + 文档）
- **PR4 = T019-T025**（Phase 5，call site 迁移）
- **PR5 = T026-T031**（Phase 6，文档 + 验证）

或压缩为单 PR：T001-T025 一次性提交，T026-T031 文档+验证单独 PR。

---

## Notes

- 所有 Application 类实现须严格对齐 [contracts/application-public-api.md](./contracts/application-public-api.md) 的契约
- dispose() 幂等性是 SC-004 的关键验证点——任何路径下重复调 dispose 不得抛错
- URL 凭据脱敏（FR-013）必须覆盖 `__repr__`、错误消息、日志——见 [quickstart.md §4](./quickstart.md) 验证脚本
- 现有 18 个 manager 测试在 PR2 阶段必须保持通过（dict 路径兼容），在 PR4 阶段迁移到 Application 形式
- 提交节奏：建议每个任务（或同 [P] 组）一次 commit，便于回滚
