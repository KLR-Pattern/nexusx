# Implementation Plan: 026 内部收敛（M1）

**Branch**: `feat/issue-160-m1-consolidate` | **Date**: 2026-11-24 | **Spec**: spec.md
**Input**: review/review_7.0.0.md + issue #160 路线图

## Summary

零行为变化的内部收敛：新建叶子模块 `nexusx/annotation_utils.py` 收编 20+ 份类型解包副本（R1）与 21 处 `__func__` 解包（R2）；关系变体 ABC / `Literal` / `loader_classes()`，消费点改 `isinstance`（DESIGN_5），`BatchPageCapability` 下沉到 `loader/pagination.py`（wire 不变）；`RemoteRelationship` 与 `Relationship` 共享 ABC（DESIGN_7）；8 处 `dir()` 扫描收敛（R3）；死代码与撞名清理（DEAD / R7）；`mypy --strict` 对清零叶子模块强制（BUG_4 起步）；小项收口（SIG_3/9/11、API_3_7、DESIGN_1 Decimal、DESIGN_6 partial、R8、R10）。

## Technical Context

- **Language/Version**: Python ≥3.10（`types.UnionType` / `annotationlib` 分支已存在，沿用）
- **TDD**: 改动前以现有测试为基线（1863 passed）；R1 用"改动前实现"做对照表测试锁行为；SDL / introspection 用 `tests/test_sdl_generator.py` + `test_introspection.py` 现有断言 + 新增 golden 字符串比对
- **Targets**: `src/nexusx/`；测试 `tests/`
- **依赖**: 不新增第三方依赖；`import-linter` 推到 M4

## Constitution Check

- §二.1（变体 union 是进程内唯一真源）：DESIGN_5 让类型层与之一致 ✓
- §二.2（wire 零改动）：`BatchPageCapability` 搬家 + `federation.contract` re-export，fragment JSON 不变 ✓
- §二.3（无全局开关）：不新增开关 ✓
- §二.5（量参数无默认）：不触碰 ✓
- `CLAUDE.md`：spec 产物中文 ✓；不碰 `uv.lock` ✓

## Project Structure

### Documentation (this feature)

- `specs/026-consolidate-internals/{spec,plan,tasks,data-model}.md`

### Source Code

- 新增 `src/nexusx/annotation_utils.py`（叶子：只依赖 stdlib `typing`）
- 改动 `src/nexusx/{type_converter,utils/*,loader/{registry,pagination,query_meta,factories,composed},resolver,response_builder,sdl_generator,introspection,execution/query_executor,relationship,federation/{relationship,contract,manager,remote_loader},scanning/method_scanner,discovery/entity_discovery,subset,context,standard_queries,use_case/{business,__init__},er_diagram,voyager/*}`
- 删除 `src/nexusx/execution/field_tree_builder.py`、`src/nexusx/utils/naming.py`、`tests/test_field_tree_builder.py`

## Complexity Tracking

| 风险 | 对策 |
|---|---|
| R1 改动 20+ 文件，纯机械但面广 | 先加对照表测试，再逐文件替换；每替换一批跑全量 |
| DESIGN_5 改 `loader` 字段必填 | 先 grep 所有构造点确认都传了 loader；federation e2e 作护栏 |
| `BatchPageCapability` 搬家影响 wire | `contract.py` 原地 re-export + 现有 fragment 测试 |
| mypy strict 强制意外阻断 CI | 只对清零模块 override；未清零模块显式 `disallow_untyped_defs = false` 列出 |
