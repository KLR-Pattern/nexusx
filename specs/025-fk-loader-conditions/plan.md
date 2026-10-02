# Implementation Plan: 025 FK 关系条件过滤（Loader 识别原生 join 声明中的额外条件）

**Branch**: `025-fk-loader-conditions` | **Date**: 2026-09-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/025-fk-loader-conditions/spec.md`

## Summary

FK 自动生成的关联 Loader 目前只反射 FK 等值对（`WHERE fk IN (keys)`），relationship 上用 SQLAlchemy 原生 join 条件声明的额外条件（软删除 `status=='active'`、时间戳 `deleted_at IS NULL` 等）被静默丢弃。本特性让 ErManager 在生成 Loader 时**从 `rel.primaryjoin` / `rel.secondaryjoin` 中按表达式树提取"FK 等值对之外的额外条件"**，作为既有 `filters` 参数传入 5 个 loader 工厂（该参数是 pydantic-resolve 移植时预留的休眠管道，`_apply_filters` 已在普通/分页/计数 fallback 三处生效）——工厂层零改动。声明完全复用 SQLAlchemy 原生词汇，零 nexusx 自造参数。

可行性已由 PoC 验证（2026-09-30）：7/7 场景通过、全量 1751 passed 零回归；参考 diff 存于 `/tmp/poc_pj_registry.diff`（PoC 版提取器，plan 定稿的提取规则在其基础上升级为表达式树语义，见 research.md D1）。

## Technical Context

**Language/Version**: Python 3.12（项目 uv 环境）

**Primary Dependencies**: SQLAlchemy 2.0.50（lock 基线）、SQLModel、aiodataloader、pytest

**Storage**: N/A（纯内存反射 + 查询生成；不引入持久化）

**Testing**: pytest，基线 1751 passed + 6 skipped（零回归红线）

**Target Platform**: 库（PyPI 发布，任何 SQLAlchemy 2.0 + SQLModel 运行时）

**Project Type**: library

**Performance Goals**: 提取发生在 ErManager 构造期（一次性，随关系扫描）；loader 查询仅增加 WHERE 合取条件，无额外 JOIN/往返。不设新指标。

**Constraints**: 向后兼容（已发布库，minor 版本）；存量无条件关系查询形态零变化（FR-005）；不引入新公共 API 面（FR-004）

**Scale/Scope**: 改动集中于 `src/nexusx/loader/registry.py`（提取器 + 4 处接线），`factories.py` 零改动；测试矩阵覆盖 4 US × 5 loader 形态

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` 为未填写的空模板（项目尚未定制宪法），无适用 gate。项目既有纪律（来自 CLAUDE.md 与历史实践）替代性约束：

- spec-kit 产物中文 ✓（本 plan 及全部产物中文）
- 公共接口不 breaking ✓（纯增量行为，FR-005 存量零变化）
- Entity 只承载 resource ✓（不涉及 entity 结构变化；条件由 SQLAlchemy relationship 原生承载，非 nexusx 注入 entity 的内容）
- **Phase 1 后复查**：设计未引入 entity 上的计算/dunder，未新增公共 API，无违例。

## Project Structure

### Documentation (this feature)

```text
specs/025-fk-loader-conditions/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   └── declaration-surface.md
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/nexusx/loader/
├── registry.py          # 唯一改动点：_extract_extra_filters 提取器 + _inspect_relationships 4 处接线
└── factories.py         # 零改动（filters 参数与 _apply_filters 管道既存）

tests/
├── test_loader_conditions.py   # 新增：提取与加载行为矩阵（4 US × 5 形态）
└── （既有 suites 全量回归）
```

**Structure Decision**: 单一库项目结构，改动收拢在 `loader/registry.py` 一个文件（提取器内聚于关系扫描现场，与 `_extract_sort_field` 等 helper 同层）；不新建模块——提取器只服务 `_inspect_relationships` 一个调用方，无跨模块复用需求。

## Complexity Tracking

> 无 Constitution Check 违例，本表留空。
