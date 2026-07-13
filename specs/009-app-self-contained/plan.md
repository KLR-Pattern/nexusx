# 实施计划：业务应用（Application）自包含数据库连接信息

**分支**：`009-app-self-contained` | **日期**：2026-07-13 | **Spec**：[spec.md](./spec.md)

**输入**：功能规格说明 `/specs/009-app-self-contained/spec.md`

## 概要

引入 `Application` 类作为 nexusx mcp 中**可独立导出、可合并**的最小单元——封装 SQLModel 业务模型 + 数据库连接信息（URL/engine/session 工厂三选一）+ GraphQL 元数据。配套重构 `MultiAppManager` 与 `create_mcp_server` 接受新抽象，旧 `AppConfig` 字典形式作为弃用兼容窗口保留一个 minor 周期。

核心技术结论（详见 [research.md](./research.md)）：
- `Application` 构造完全同步（`GraphQLHandler.__init__` 已是同步），只有 `dispose()` 是异步
- 连接信息字段"至多提供一个"，零也合法（schema-only 模式）
- 通过 URL 自造的 engine 由 `Application` 拥有、`dispose()` 释放；外部传入的 engine/session 工厂不拥有
- FastMCP `FastMCP(name, lifespan=...)` 与 transport-level `mcp.http_app().lifespan()` 正确组合，可用 lifespan 自动 dispose

## Technical Context

**Language/Version**：Python ≥ 3.10（`pyproject.toml::requires-python`）

**Primary Dependencies**：
- `sqlmodel >= 0.0.14`（业务模型层）
- `SQLAlchemy 2.x` 异步引擎（间接，经 SQLModel 传递）
- `fastmcp >= 3.1, < 3.2`（optional dep `[fastmcp]`，MCP 服务接入）
- `aiodataloader >= 0.4.3`（关系加载）

**Storage**：异步 SQL 数据库（SQLite + aiosqlite / PostgreSQL + asyncpg / MySQL + aiomysql 等 SQLAlchemy 支持的驱动）；每个 app 默认独立连接池。

**Testing**：`pytest >= 7.0` + `pytest-asyncio >= 0.21.0`；`ruff` + `mypy` 静态检查

**Target Platform**：跨平台 Python 库（Linux/macOS/Windows）；运行时无平台假设。

**Project Type**：library（schema-to-GraphQL 工具集）

**Performance Goals**：N/A —— 本改造不引入热路径开销。`Application` 构造仅在启动期发生一次；运行期 `manager.get_app(name)` 仍是 O(1) dict lookup。

**Constraints**：
- 向后兼容：所有现有 8 个 call site（3 个 demo、1 个技能模板、4 个测试文件）在新版本下必须仍可运行（dict 形式触发 `DeprecationWarning` 但功能等价）
- 同步契约：现有 18 个 `test_multi_app_manager.py` 测试用同步 `MultiAppManager(apps)` + `manager.apps` 访问——构造期必须保持同步，AppResources 必须 eager 填充
- 资源安全：URL 自造 engine 必须在 mcp 服务关闭时通过 lifespan 释放；幂等 dispose
- 安全：FR-013 要求 URL 凭据脱敏

**Scale/Scope**：8 个 call site 迁移；新增 1 个模块（`application.py`）；3 个 demo + 1 个技能模板 + 5 个测试文件更新。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` 当前为未填写的模板——无项目级硬性 principle 约束。本特性的设计原则由 spec 与既有架构共识约束：

| 检查项 | 状态 | 说明 |
|---|---|---|
| 库优先 / 自包含 | ✅ Pass | `Application` 让 app 成为独立可用单元，强化（而非违反）"库优先"精神 |
| 向后兼容窗口 | ✅ Pass | dict 形式保留 + `DeprecationWarning`；不一次性破坏 |
| 测试覆盖 | ✅ Pass | 现有 18 个单元测试 + 新增 lifespan/dispose/redaction 测试 |
| 复杂度可控 | ✅ Pass | 1 个新类、1 个新模块；无新依赖；`MultiAppManager` 改动局限于初始化与生命周期方法 |
| 资源安全 | ✅ Pass | lifespan 自动 dispose；幂等；所有权清晰 |

无 violations，无需 Complexity Tracking 表。

## Project Structure

### Documentation (this feature)

```text
specs/009-app-self-contained/
├── plan.md              # 本文件
├── spec.md              # /speckit-specify 产出
├── research.md          # Phase 0 研究产物
├── data-model.md        # Phase 1 数据模型
├── quickstart.md        # Phase 1 端到端验证手册
├── contracts/
│   └── application-public-api.md   # Application 类公共 API 契约
└── checklists/
    └── requirements.md  # /speckit-specify 阶段已生成
```

### Source Code (repository root)

```text
src/nexusx/
└── mcp/
    ├── __init__.py             # 导出 Application
    ├── application.py          # 【新增】Application 类 + _coerce_to_application()
    ├── server.py               # 【修改】create_mcp_server 接受 Application|AppConfig，挂 lifespan
    ├── managers/
    │   ├── __init__.py
    │   ├── app_resources.py    # 不变
    │   ├── multi_app_manager.py # 【修改】coerce dict → Application；新增 async dispose
    │   └── single_app_manager.py # 本次不动（roadmap）
    ├── tools/                  # 不变
    ├── builders/               # 不变
    └── types/
        ├── __init__.py
        ├── app_config.py       # 保留（deprecation window）
        └── errors.py

tests/mcp/
├── test_application.py         # 【新增】Application 单元测试（构造、所有权、dispose 幂等、URL 脱敏）
├── test_multi_app_manager.py   # 【修改】18 个测试改用 Application 形式
├── test_multi_app_tools.py     # 【修改】fixture 改用 Application
└── test_simple_mcp.py          # 不变

demo/
├── multi_app/mcp_server.py     # 【修改】dict → Application
├── blog/mcp_server.py          # 【修改】
└── auth/mcp_server.py          # 【修改】

skills/nexusx-4phase/template/src/main.py   # 【修改】技能模板更新
```

**Structure Decision**：单项目库（Option 1）。改动集中在 `src/nexusx/mcp/`，新增 1 个模块 `application.py`，对 `server.py` / `multi_app_manager.py` / `__init__.py` 做局部修改。`tests/`、`demo/`、`skills/.../template/` 同步迁移。

## 实施序列（建议 5 个 PR，可压缩为 2-3 个）

1. **PR1（additive）**：新增 `application.py` + 导出 `Application`。**不动** `MultiAppManager`，**不动**任何 call site。所有现有测试通过。
2. **PR2**：`MultiAppManager.__init__` 接受 `list[Application | AppConfig]`；`_coerce_to_application()` 把 dict 转 `Application` 并发 `DeprecationWarning`。现有 8 个 call site 全部仍工作（dict 路径兼容）。
3. **PR3**：`create_mcp_server` 注册 FastMCP `lifespan=`，关闭时调 `await manager.dispose()`。新增 lifespan 测试。
4. **PR4**：迁移 8 个 call site 到 `Application` 形式（demo × 3、skill template × 1、tests × 4 文件）。
5. **PR5**：文档更新（`docs/api/api_mcp.md`、`docs/advanced/mcp_service.md` 及 `.zh.md`、module docstring、function docstring）；新增"独立导出 app"指南章节。

若偏好单 PR：合并 PR1-PR4 为一个（核心代码 + 测试 + 迁移），PR5（文档）分开。

## Phase 0/1 产物

详见：
- [research.md](./research.md) —— 5 个核心决策（深度 A、类名、零连接信息模式、所有权判定、lifespan 组合）的依据与替代方案
- [data-model.md](./data-model.md) —— `Application`、`AppResources`、`MultiAppManager`、`AppConfig`（弃用）的字段、关系、状态机
- [contracts/application-public-api.md](./contracts/application-public-api.md) —— `Application` 公共方法签名与契约
- [quickstart.md](./quickstart.md) —— 端到端验证手册（独立导出场景、合并场景、URL 脱敏验证、兼容性验证）

## 验证策略

| 层次 | 命令/动作 |
|---|---|
| 单元测试 | `uv run pytest tests/mcp/ tests/test_mcp.py tests/test_mcp_schema_enhanced.py -v` |
| 静态检查 | `uv run ruff check src/nexusx/mcp/ && uv run mypy src/nexusx/mcp/` |
| 集成（多 app） | `cd demo/multi_app && uv run python -m multi_app.mcp_server`（启动 + mcp client 调用 list_apps/graphql_query） |
| 集成（单 app 包发布） | 见 [quickstart.md](./quickstart.md) §3 "独立导出 app 包" 场景 |
| 弃用警告 | `python -W default::DeprecationWarning -c "..."` 触发 dict 形式时看到警告 |
| URL 脱敏 | 详见 [quickstart.md](./quickstart.md) §4：故意构造错误 URL，确认错误消息中无明文密码 |

## Roadmap（本次范围外）

- **`create_simple_mcp_server`** 改造为 `Application`-based（保持现状）
- **`UseCaseAppConfig` / `create_use_case_graphql_mcp_server`**（`src/nexusx/use_case/`）平行改造
- **entry-point 自动发现**（`[project.entry-points."nexusx.apps"]`）：让合并项目 `pip install blog-app` 后零代码注册到 mcp server
