# Implementation Plan: 可组合 ErManager（ComposedErManager）—— 同进程多 engine 组合

**Branch**: `feat/composable-er-manager` | **Date**: 2026-08-07 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/019-composable-er-manager/spec.md`

## Summary

** primary requirement**：让 nexusx 支持同进程内多个数据库 engine 共存——不仅能画进一张 ER 图，还能在 resolver 后端真的跨 engine 关联查询（blog.User resolve 出 shop.Order，且二级钻取通）。

**technical approach**：引入 `ComposedErManager`——一个「按 entity 委托的查询代理 + 跨边界关系叠加层」。多个自洽的子 ErManager（各自单 engine、loader 焊死各自 session）组合成一个总代理，它满足 `LoaderRegistry` 协议，`create_resolver()` 产出单一总代理 Resolver，跨 engine resolve 对用户透明。本质是「同进程版的 federation」（与 012 跨进程 federation 对偶）。

**spike 已验证**（`spike_composed_er.py`）：
- UseCase 路径跨 engine resolve（含二级钻取）4 断言全绿
- ER 图合并（4 实体同图 + 跨库边）全绿
- Resolver 本体、ErDiagram 生成层 0 改动

**三阶段**：
- 阶段 1（P1）：ComposedErManager 产品化 + UseCase 路径 + ER 图（纯 additive，0 现有 public API 改动）
- 阶段 2（P2）：entity-first GraphQLHandler 注入分支（非 breaking）
- 阶段 3（边界）：auto_query_config 多 engine session 归属

## Technical Context

**Language/Version**: Python ≥3.10（`requires-python = ">=3.10"`，spike 在 3.12 验证）

**Primary Dependencies**: SQLModel、SQLAlchemy（async）、Pydantic v2、aiodataloader（DataLoader）、FastMCP（可选）

**Storage**: N/A（本特性是组合层，不引入新存储；下游 engine 由用户提供的 session_factory 决定——SQLite/PostgreSQL/MySQL 均可）

**Testing**: pytest（async），项目现有 `tests/` 套件（含 federation e2e、conftest session fixtures）。本特性新增组合性测试（见 spec US5 矩阵）。

**Target Platform**: 跨平台（library，随 nexusx 分发）

**Project Type**: library（nexusx 是已发布库，版本 5.3.0）

**Performance Goals**:
- 组合体委托开销 = 一次 dict 查找（`entity → member` 路由），O(1)，可忽略
- 跨 engine 关联走 DataLoader N+1 batch（与同 engine 同机制），不引入额外往返
- 阶段 1 完成后跑现有 benchmark（`benchmarks/`）确认无回归

**Constraints**:
- **公共 API 不 breaking**（已发布库）：阶段 1 必须 pure additive；阶段 2 改动限定为可选注入参数 + 类型注解放宽（见 spec「Public API 兼容性」分析）
- Resolver 本体、ErManager 本体、ErDiagram 生成层 0 改动（spike 已证）

**Scale/Scope**: 中等。ComposedErManager 核心 ~80 行（spike 实证）+ 测试矩阵（US5 A–E）+ demo。不涉及大规模代码迁移。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` 为未填写模板（placeholder），无成文 gate。

本特性遵循项目既有纪律（CLAUDE.md + memory）：
- **组合优先于吸收**：ComposedErManager 是组合层，不把「多 engine 编排」语义吸收进 ErManager/框架核心（DD-04）
- **公共 API 不 breaking**：阶段 1 pure additive 是硬约束
- **Spec-kit 产物中文**：本 plan 及所有产物用中文撰写
- **Entity 只承载 resource，计算放 DTO/Resolver**：本特性不改 entity 纪律，跨边界关系声明在组合体层（DD-02），不污染实体

**Gate 结论**：PASS（无成文 constitution gate；项目纪律无违反）。Phase 1 设计后复查。

## Project Structure

### Documentation (this feature)

```text
specs/019-composable-er-manager/
├── plan.md              # 本文件
├── research.md          # Phase 0：Deferred 项决策 + spike 验证细节
├── data-model.md        # Phase 1：ComposedErManager 结构 + LoaderRegistry 协议
├── quickstart.md        # Phase 1：验证场景（基于 spike）
├── contracts/           # Phase 1：public API 契约
│   └── composable-er-manager.md
└── tasks.md             # Phase 2 输出（/speckit-tasks，本命令不生成）
```

### Source Code (repository root)

```text
src/nexusx/
├── loader/
│   ├── registry.py          # ErManager（0 改动）
│   ├── composed.py          # 【新】ComposedErManager + LoaderRegistry Protocol（阶段 1 核心）
│   └── ...
├── resolver.py              # Resolver（0 改动，已 loader_registry: Any）
├── handler.py               # GraphQLHandler（阶段 2 加 er_manager 注入分支）
├── er_diagram.py            # ErDiagram（0 改动，鸭子类型）
├── voyager/er_diagram_dot.py # ErDiagramDotBuilder（0 改动）
└── __init__.py              # 导出 ComposedErManager（+ 可选 LoaderRegistry）

tests/
├── test_composed_er_manager.py        # 【新】阶段 1 单元/集成（US1/US2/US4 + 协议）
├── test_composed_federation.py        # 【新】US5 federation 叠加矩阵 A–E
└── （现有 federation 测试保持零回归）

demo/
└── composed_er/             # 【新】多 engine 组合 demo（可选，阶段 1 末）
```

**Structure Decision**：
- `ComposedErManager` 独立成 `src/nexusx/loader/composed.py`（与 ErManager 同包，但独立文件，避免 `registry.py` 膨胀）。从 `nexusx.loader` 和顶层 `nexusx` 导出。
- `LoaderRegistry` Protocol 与 ComposedErManager 同文件（它是组合体实现的契约）。
- 测试分两个文件：基础组合（阶段 1）+ federation 叠加（US5 矩阵，独立文件便于定位组合性回归）。

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

无 constitution gate 违反。本节空。

## Plan Workflow 输出

### Phase 0: research.md（待生成）

解决 spec clarify 阶段 Deferred 的实现决策（跨边界 loader 取 session、dispose/engine 所有权、Protocol 抽象时机、ER 图分簇、Application 集成）+ 记录 spike 验证要点与已知坑。

### Phase 1: data-model.md / contracts/ / quickstart.md（待生成）

- `data-model.md`：ComposedErManager 属性/方法签名 + LoaderRegistry Protocol + 跨边界关系叠加层数据流
- `contracts/composable-er-manager.md`：public API 契约（构造签名、协议方法、与 ErManager/Resolver/GraphQLHandler 的交互边界、Public API 兼容性承诺）
- `quickstart.md`：基于 spike 的端到端验证场景（两 engine + 跨库 resolve + ER 图 + federation 叠加）
