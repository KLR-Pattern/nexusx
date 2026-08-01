# Implementation Plan: 本地分页 order/direction

**Branch**: `015-local-pagination-order-direction` | **Date**: 2026-08-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/015-local-pagination-order-direction/spec.md`

## Summary

把 federation 分页（specs/013/014）已有的"按 order profile + direction 排序分页"内核抽成 federation 与本地分页共享的 core，让本地分页关系（`enable_pagination` 的 list 关系，如 `Review.comments`）也支持查询期 order/direction 选择。

落点：本地 list 关系扩展 `Relationship.page_orders` 声明 profile 集合；本地 page_loader（`create_page_one_to_many_loader`）从固定 `sort_field` 改为 profile + direction 驱动（复用 `_build_order_expressions`/`_apply_direction`）；schema 渲染 order enum + direction；executor 从 `selection.arguments` 透传。未配 profile 的本地分页维持现状（向后兼容）。

## Technical Context

**Language/Version**: Python ≥3.10（pyproject `requires-python`）

**Primary Dependencies**: SQLModel、SQLAlchemy(async)、Pydantic v2、aiodataloader（nexusx 既有栈，无新增依赖）

**Storage**: SQLAlchemy ORM（关系分页走 `ROW_NUMBER() OVER (PARTITION BY fk ORDER BY …)`）

**Testing**: pytest（既有 `tests/test_loader_pagination.py` / `test_pagination_mixed.py` 单体分页模式 + `test_federation_pagination_e2e.py` ASGITransport 端到端模式）

**Target Platform**: 跨平台 Python 库（Linux/macOS/Windows）

**Project Type**: library

**Performance Goals**: 保持 per-parent batch（N+1-proof 不变量）—— order/direction 只改 `ORDER BY` 表达式，不改 `PARTITION BY fk` 的 batch 结构，仍是每层一次批量。

**Constraints**:
- 向后兼容：未配 `page_orders` 的本地分页关系行为不变（FR-003）
- 零回归：federation 分页（`Product.reviews`）的 order/direction 不受影响（SC-005）
- shared core 抽取不破坏 federation 分页既有行为

**Scale/Scope**: ~6 源文件 + 测试。中等。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` 当前为**占位模板**（未填实际原则），无强制约束。本 plan 参照 `014-federation-order-direction` 既有 spec/plan 风格（技术 spec + 设计决定论证），并遵循 nexusx 通用纪律：

- 复用优先（shared core 抽取，不重复实现排序逻辑）
- 向后兼容（未配 profile 的路径不变）
- fail-fast 校验（profile 声明在启动期校验）
- 每服务一次批量不变量（federation / 单体 N+1-proof）

**Gate**: PASS（无 constitution 实际原则可违反；遵循上述通用纪律）。

## Project Structure

### Documentation (this feature)

```text
specs/015-local-pagination-order-direction/
├── plan.md              # 本文件
├── research.md          # Phase 0: plan 级技术决策(DataLoader 注入/shared core 位置等)
├── data-model.md        # Phase 1: Relationship/RelationshipInfo 扩展 + shared core 实体
├── quickstart.md        # Phase 1: 验证场景
├── contracts/
│   └── local-pagination-order.md   # 公开 API 契约(Relationship.page_orders / GraphQL 字段签名)
└── tasks.md             # /speckit-tasks 生成(本 plan 不创建)
```

### Source Code (repository root)

```text
src/nexusx/
├── relationship.py            # ★ Relationship 扩展 page_orders/default_page_order
├── standard_queries.py        # shared core 所在: PageOrder/OrderTerm/Direction/_build_order_expressions
│                              #   /_apply_direction (已在此, federation 已用; 本地分页 import 调用, 不新建模块)
├── loader/
│   ├── factories.py           # ★ create_page_one_to_many/_many_to_many_loader: 固定 sort_field
│   │                          #   → profile+direction 驱动(复用 _build_order_expressions/_apply_direction)
│   └── registry.py            # ★ RelationshipInfo 加 page_capability; 关系物化时从 page_orders 构建
├── sdl_generator.py           # ★ 本地分页关系渲染 order enum + direction(复用 federation 渲染分支)
├── introspection.py           # ★ __schema 内省同步渲染 order/direction
└── execution/
    └── query_executor.py      # ★ 从 selection.arguments 提 order/direction 透传给本地 page_loader cmd

tests/
├── test_local_pagination_order.py         # 新: 本地分页 order/direction 端到端
├── test_local_pagination_order_render.py  # 新: SDL/内省渲染 order enum + direction
├── test_loader_pagination.py              # 既有: 回归(未配 profile 行为不变)
└── test_federation_pagination_e2e.py      # 既有: 回归(federation 分页不受影响)
```

**Structure Decision**: nexusx 是单体 library（`src/nexusx/`）。本特性在既有模块内改动，无新顶层模块。shared core 复用 `standard_queries.py` 已有的 `PageOrder`/`OrderTerm`/`_build_order_expressions`/`_apply_direction`（federation 在用），不新建模块——仅让本地分页也 import 调用，最小改动面、最小回归风险。

## Complexity Tracking

无 Constitution violation，本节不填。
