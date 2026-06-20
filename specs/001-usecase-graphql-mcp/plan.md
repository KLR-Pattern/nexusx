# Implementation Plan: UseCase Service → GraphQL → MCP

**Branch**: `001-usecase-graphql-mcp` | **Date**: 2026-06-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-usecase-graphql-mcp/spec.md`

## Summary

引入 `UseCaseService` → 真正 GraphQL schema → 4 层渐进式披露 MCP 的执行链（参考 `pydantic-resolve` 的 compose 实现），同时**硬移除**老的两个直接调用式 use_case MCP 入口（`create_use_case_mcp_server`、`create_use_case_flat_server`）。新模块新建独立的 schema 构建器（`TypeInfo` registry，非 graphql-core `GraphQLSchema`），复用既有 `query_parser.FieldSelection` 做字段投影、复用 `subset.build_subset_model()` 做实际投影、复用 `UseCaseManager` 做多应用路由；不复用 `GraphQLHandler`/`QueryExecutor`（强耦合 SQLModel）。Resolver 不在执行链外层包裹（service 方法内部已经显式 `Resolver().resolve(dtos)`）。

## Technical Context

**Language/Version**: Python >= 3.10（既有约束）

**Primary Dependencies**:
- `graphql-core`（既有，schema 解析/AST 工具）
- `fastmcp`（既有，MCP 服务）
- `pydantic`（既有，DTO 基础）
- `sqlmodel`、`aiodataloader`（既有，service 方法内部使用，新模块不直接依赖）

**Storage**: N/A（库特性，无新存储）

**Testing**: `pytest` + `pytest-asyncio`（既有，asyncio_mode=auto）；新增 4 个测试文件覆盖 schema 生成、执行、MCP 工具、introspection 拒绝。

**Target Platform**: 跨平台 Python（Linux/macOS/Windows），与既有发布一致。

**Project Type**: library（`src/nexusx/` 包）

**Performance Goals**: 不退化于既有 `mcp/` 模块。Layer 3 执行一次典型查询（3 service、含嵌套 DTO）的端到端延迟不超过既有 `GraphQLHandler.execute()` 同等查询的 1.2 倍。

**Constraints**:
- 公共 API 兼容性：除 FR-010 明确移除的两个入口外，其它既有导出（`UseCaseService`、`UseCaseAppConfig`、`FromContext`、`create_use_case_router`、`create_use_case_voyager`）签名与行为保持不变。
- Resolver 边界：GraphQL 执行层**不**在外层再套 `Resolver()`（FR-004a）。
- MCP 工具响应 shape：Layer 0–2 用 `{success, data}` 信封，Layer 3 用 GraphQL 标准 `{data, errors}`（FR-007）。
- 代码风格：`ruff` (line-length=100) + `mypy --strict` 必须通过。

**Scale/Scope**: 新增 5 个源文件（约 1500 行），删除 2 个源文件（约 800 行），净增约 700 行；新增 1 个 demo、4 个测试文件、1 份迁移指南。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` 仍是模板（未填写项目宪法）。无显式 gates。以下为本特性自我施加的约束（替代宪法作用，待项目宪法落地后回顾）：

| Principle | Status | Note |
|-----------|--------|------|
| Library-first | ✅ Pass | 新能力作为 `nexusx` 库的公共 API 提供，独立可测。 |
| Backwards compatibility | ⚠️ Violated (justified) | 移除 2 个老 MCP 入口（FR-010）。理由：避免生态内两套并行 MCP 实现长期共存；用户已确认"立即移除"。版本号 major bump（1.0.0 → 2.0.0）反映 breaking change。 |
| No parallel implementations | ✅ Pass | FR-011 + research.md 强制对每个新建/复用选择给出依据；执行链不与 `GraphQLHandler` 平行实现（语义不同：实体驱动 vs 服务驱动）。 |
| Type-safety | ✅ Pass | `mypy --strict` 必须通过。 |
| Test coverage | ✅ Pass | 4 个测试文件覆盖 schema/executor/MCP/introspection；老入口移除有专项测试。 |

## Project Structure

### Documentation (this feature)

```text
specs/001-usecase-graphql-mcp/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── public-api.md        # Public Python API contracts
│   ├── mcp-tools.md         # 4 MCP tool contracts
│   └── schema-builder.md    # ComposeSchema builder API
├── checklists/
│   └── requirements.md   # From /speckit-specify
└── tasks.md             # Phase 2 output (/speckit-tasks, NOT this command)
```

### Source Code (repository root)

```text
src/nexusx/
├── use_case/
│   ├── __init__.py             # MODIFIED — remove old exports, add new
│   ├── business.py             # UNCHANGED — UseCaseService, BusinessMeta
│   ├── context.py              # UNCHANGED — FromContext
│   ├── types.py                # UNCHANGED — UseCaseAppConfig
│   ├── manager.py              # TRIMMED — keep UseCaseManager + UseCaseResources core
│   ├── introspector.py         # DELETED — superseded by compose_schema.py
│   ├── server.py               # DELETED — old 4-layer MCP (FR-010)
│   ├── flat_server.py          # DELETED — old flat MCP (FR-010)
│   ├── router.py               # UNCHANGED — FastAPI REST (FR-010a)
│   ├── jsonrpc.py              # UNCHANGED — JSON-RPC (FR-010a, orthogonal)
│   ├── compose_schema.py       # NEW — TypeInfo registry + introspection + SDL emit
│   ├── compose_type_mapper.py  # NEW — Pydantic/scalar/enum → GraphQL type (fork of type_converter)
│   ├── compose_executor.py     # NEW — parse → plan → execute service methods → project
│   └── compose_mcp_server.py   # NEW — 4-layer MCP server entry point
├── __init__.py                 # MODIFIED — re-exports updated
└── [other modules unchanged]

demo/
└── use_case/
    ├── mcp_server.py              # MODIFIED — switch demo to new entry point
    └── mcp_server_graphql.py      # NEW — explicit GraphQL MCP demo

docs/
└── migrations/
    └── 2.0-use-case-graphql.md    # NEW — migration guide for removed APIs

tests/
└── use_case/
    ├── test_compose_schema.py         # NEW
    ├── test_compose_executor.py       # NEW
    ├── test_compose_mcp_server.py     # NEW
    ├── test_introspection_rejected.py # NEW
    └── test_old_api_removed.py        # NEW — assert ImportError on old entry points
```

**Structure Decision**:
- 新代码全部落在 `src/nexusx/use_case/` 下，以 `compose_*` 前缀命名，与既有 `mcp/`（SQLModel 驱动）模块解耦但共享 `use_case/` 内部的 `business.py`/`manager.py`/`types.py`/`context.py`。
- 不在 `src/nexusx/mcp/` 下新增文件 —— 那个目录是 SQLModel GraphQL MCP 专属，本特性是 UseCase 驱动的另一条路。
- 老 MCP 文件硬删除，不保留 shim（FR-010 明确要求导入失败）。
- Demo 保留原 `mcp_server.py` 文件名（更新内容），额外加 `mcp_server_graphql.py` 作为新入口的显式范例。

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| 移除 2 个公共 API（FR-010） | 避免生态内两套 MCP 长期共存造成维护与文档负担；用户已确认立即移除。 | Deprecate-and-keep：被否决，理由是用户基数小、并行实现成本高、收敛方向明确。 |
| 新建 `compose_type_mapper.py` 而非复用 `type_converter.py` | `type_converter.py` 与 SQLAlchemy/SQLModel 强耦合（`is_mapped_wrapper()`、`is_relationship()`），UseCase 模式只处理 Pydantic。 | 复用：会引入 SQLModel 依赖到 UseCase 链路，违反"两种模式正交"原则。复用选择在 research.md 中逐项列出。 |
| 新建 `compose_executor.py` 而非复用 `execution/query_executor.py` | 既有 executor 假设 SQLModel 实体 + DataLoader BFS 加载关系；UseCase 链路 service 方法内部已自管 Resolver，外层只需调方法 + 字段投影。 | 复用：会导致双层 Resolver 触发（FR-004a 明确禁止）。 |
