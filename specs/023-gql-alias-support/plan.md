# Implementation Plan: GraphQL Alias 支持（修复静默折叠）

**Branch**: `023-gql-alias-support` | **Date**: 2026-08-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/023-gql-alias-support/spec.md`

## Summary

修复 Issue #140（mutation 别名静默折叠）并为 query/mutation 的**方法级字段**实现 alias 支持。核心技术变更：`FieldSelection.sub_fields` 的 key 语义从 `field_name` 改为 `alias or field_name`（响应键），查找一律改走 `FieldSelection.name`（原始名）；6 处下游同步，其中 federation 渲染出口（`remote_loader._render_selection`）用 `child.name` 渲染，保证 wire 永不含 alias（member 零改动）。mutation 部分失败改为逐调用三态反馈（已成功保留 / 失败独立报错 / 跳过标注），entity-first 的"整组作废"语义同步移除。分三阶段交付：A 止血（compose 入口 fail loudly）→ B1a query 侧 → B1b mutation 侧。

## Technical Context

**Language/Version**: Python 3.12（uv 管理）

**Primary Dependencies**: graphql-core（AST 解析）、pydantic v2（投影/动态模型）、aiodataloader（批量加载）、FastAPI + FastMCP（HTTP/MCP 面）

**Storage**: N/A（纯查询层特性，无持久化变更）

**Testing**: pytest（pytest-asyncio）；全量基线 1505+ 用例，13 个测试文件直接触及 `QueryParser`/`sub_fields`

**Target Platform**: Python 库，随宿主部署（无独立运行时）

**Project Type**: library

**Performance Goals**: 别名解析为每选择集 O(n) 一次字典插入 + 冲突检测，无新增性能目标；联邦同参同选共享 DataLoader key 缓存为既有机制（`get_loader` 的 type_key/params_key 拆实例），不新增缓存

**Constraints**: 公共 API 兼容（次版本 6.2.0 + changelog 显著说明）；member 服务零改动；`validate_no_aliases` 保留原语义供外部使用，仅移除库内调用

**Scale/Scope**: 6 处源码下游（其中 5 处小改、1 处中改）；`core_builder`/`response_builder` 本期不动（B2 范围外，清单记录）

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` 为未填充的占位模板（无已批准的原则/门禁），无适用约束。**Gate 通过**。

## Project Structure

### Documentation (this feature)

```text
specs/023-gql-alias-support/
├── plan.md              # 本文件（/speckit-plan 产出）
├── research.md          # Phase 0 产出：8 项设计决策记录
├── data-model.md        # Phase 1 产出：FieldSelection 键语义契约 + 三态响应信封
├── quickstart.md        # Phase 1 产出：6 个端到端验证场景
├── contracts/           # Phase 1 产出：对外行为契约
│   └── graphql-alias-behavior.md
└── tasks.md             # Phase 2 产出（/speckit-tasks，本命令不创建）
```

### Source Code (repository root)

```text
src/nexusx/
├── query_parser.py            # [阶段 A+B1a] key 语义变更 + 同层响应键冲突检测
├── use_case/compose_executor.py   # [阶段 A] 入口校验；[B1a/B1b] 方法查找改 sel.name、
│                                   #            响应 key 用 dict key、mutation 三态反馈
├── execution/query_executor.py    # [B1a/B1b] field_sel 按 alias or name 查找、响应 key
│                                   #            同上、移除 group_failed 整组作废
├── federation/remote_loader.py    # [B1a] _render_selection 用 child.name（边界闸门）
├── core_builder.py                # 本期不动（B2：查找名/输出名分离时才改）
└── response_builder.py            # 本期不动（dormant，清单记录）

tests/
├── test_query_parser.py       # key 语义、冲突检测（含无别名同名字段重复）
├── test_compose_executor.py   # query 扇出、mutation 三态、同参不去重
├── test_query_executor.py     # entity-first 对齐用例、组级 null 移除回归
└── test_federation_*.py       # wire 无 alias 断言（β/γ/分页矩阵）
```

**Structure Decision**: 单库结构（`src/nexusx/` + `tests/`），沿用仓库现状；本 feature 不新增模块，全部为既有文件的行为变更，新建测试用例落在对应既有测试文件。

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

无违规，不适用。
