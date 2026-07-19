# 实施计划：修复 UseCase Router 把嵌套 BaseModel 参数拍平成 dict 的 Bug

**分支**：`011-fix-router-model-dump` | **日期**：2026-07-19 | **Spec**：[spec.md](./spec.md)

**输入**：功能规格说明 `/specs/011-fix-router-model-dump/spec.md`
**关联 Issue**：KLR-Pattern/nexusx#107

## 概要

`src/nexusx/use_case/router.py` 的 `_make_handler` 在四个 case 里都用 `body.model_dump()` 把 FastAPI 已校验的 request model 拍平成 dict 再传给 service 方法，导致 service 方法签名声明 `List[ItemInput]` / `ItemInput` / `Optional[ItemInput]` 等嵌套 BaseModel 参数时，方法体实际收到 `List[dict]` / `dict` / `Optional[dict]`，签名说谎、`it.text` 抛 `AttributeError`。

修复方式（spec FR-002 钉死）：去掉 `body.model_dump()`，改为按字段名从 request model 直接做属性访问（`getattr(body, pname)`）。这样 Pydantic 在 `model_validate` 阶段已经构造好的嵌套 BaseModel 实例原样传给方法体，类型契约不再断链。

修复后行为变化：嵌套 BaseModel 参数以 BaseModel 实例形态传入方法体；标量 / `List[scalar]` / `FromContext` / 默认值 / alias 等其他形态行为完全不变；OpenAPI / compose schema 生成路径完全不变（schema 与 router 是两条正交路径）。

## Technical Context

**Language/Version**：Python ≥ 3.10（`pyproject.toml::requires-python`，issue 报告环境为 3.13）

**Primary Dependencies**：

- 现有：`pydantic >= 2.0`（修复直接依赖）、`fastapi >= 0.100.0`、`sqlmodel >= 0.0.14`
- **不引入任何新依赖**——`getattr` 是 Python 内置，无需任何 Pydantic / FastAPI 特定 API
- 不修改 `[chat]` / `[fastmcp]` 等 extras

**Storage**：N/A（router 是无状态路由生成器，不持久化任何数据）

**Testing**：

- `pytest` + `pytest-asyncio`（已在 dev extras）
- 现有 `tests/test_use_case_router.py`（457 行，覆盖 scalar / FromContext / 默认值 / OpenAPI / 可扩展性）必须全过
- 新增针对嵌套 BaseModel 的回归测试（详见 [tasks.md](./tasks.md) 后续生成）
- `ruff` + `mypy --strict` 静态检查（与项目一致）

**Target Platform**：跨平台 Python 库（Linux/macOS/Windows），运行时无平台假设

**Project Type**：library（nexusx use_case 子模块的 router bug fix）

**Performance Goals**：

- 单次 use case 调用的 router handler 开销相比修复前**不退化**（预期略快——`getattr` 比 `model_dump` 的递归遍历便宜）
- 不设置量化阈值：handler 不是热路径的瓶颈（FastAPI request parsing / response serialization 才是）

**Constraints**：

- **修复范围**：仅触及 `src/nexusx/use_case/router.py`；不修改 `_classify_params` / `_build_request_model` / `create_router` 的对外签名（私有 helper `_make_handler` 的签名会变，详见 [research.md R3](./research.md)）
- **schema 路径正交**：不修改 `compose_type_mapper.py` / `compose_schema.py` / `introspector.py`——schema 生成路径与 router 路径独立（spec FR-007、SC-004）
- **零 API 变化**：`UseCaseService` / `@query` / `@mutation` / `create_router` / `UseCaseAppConfig` 公共 API 签名完全不变（spec Assumptions）
- **现有测试不破**：`tests/test_use_case_router.py` 现有 30+ 个用例必须全过；新增针对嵌套 BaseModel 的用例（spec SC-002、SC-003）
- **Pydantic 2.x 行为依赖**：依赖 `pydantic.BaseModel.model_validate` 在 FastAPI request model 阶段已递归构造嵌套 BaseModel 实例；不依赖 Pydantic 1.x（项目要求 `pydantic>=2.0`，issue 报告 2.13.4）

**Scale/Scope**：

- 修改 1 个文件：`src/nexusx/use_case/router.py`（约 20-30 行变更——四个 case 的 handler 闭包 + 把 `body_params` 传入 `_make_handler`）
- 修改 1 个测试文件：`tests/test_use_case_router.py`（新增 1 个 test class，约 5-8 个 test methods，覆盖 `List[Model]` / `Model` / `Optional[Model]` / `Optional[List[Model]]` / `List[Optional[Model]]` / 嵌套两层 / 标量回归 / FromContext + body 混合）
- 不新增源码文件、不修改 `pyproject.toml`、不动 `docs/`

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` 当前为未填写的模板——无项目级硬性 principle 约束。本特性的设计原则由 spec 与既有架构共识约束：

| 检查项 | 状态 | 说明 |
|---|---|---|
| 公共 API 稳定 | ✅ Pass | `UseCaseService` / `@query` / `@mutation` / `create_router` / `UseCaseAppConfig` 签名零变化；仅私有 helper `_make_handler` 的形参列表变化 |
| schema 路径正交 | ✅ Pass | 不修改 `compose_type_mapper.py` / `compose_schema.py` / `introspector.py`，schema 生成行为完全不变 |
| 测试覆盖 | ✅ Pass | 现有 30+ router 测试全过 + 新增针对嵌套 BaseModel 的回归测试；ruff + mypy --strict |
| 复杂度可控 | ✅ Pass | 单文件 ~20-30 行变更；不引入新依赖；不引入新抽象——`getattr(body, pname)` 是最朴素的字段访问 |
| 向后兼容 | ⚠️ Soft-break | 行为变化：service 方法体收到 BaseModel 实例而非 dict。如果用户曾因 bug 写过 `it["text"]` 风格代码（无 isinstance 守卫），代码会从 AttributeError 转为正常工作；如果用户写过 `it["text"]` 并依赖它（极少数），会从 KeyError 转为 AttributeError。前者是修复，后者需要文档说明 |
| 修复彻底性 | ✅ Pass | 修复覆盖四个 case 中所有涉及 body 的两个（Case 1 / Case 2）；Case 3 / Case 4 无 body，天然不受影响 |
| 实现简洁性 | ✅ Pass | 用户在 specify 阶段已钉死"去掉 `model_dump()`"路径，拒绝"先 dump 再 TypeAdapter validate"二次校验绕弯方案（spec FR-002） |

无不可接受的 violations，无需 Complexity Tracking 表。Soft-break 一项在 CHANGELOG 显式声明即可（spec FR-009）。

## Project Structure

### Documentation (this feature)

```text
specs/011-fix-router-model-dump/
├── plan.md              # 本文件
├── spec.md              # /speckit-specify 产出
├── research.md          # Phase 0 研究产物
├── data-model.md        # Phase 1 数据模型（router 数据流）
├── quickstart.md        # Phase 1 验证指南
├── contracts/
│   └── router-handler-contract.md  # Phase 1 _make_handler 内部契约
└── tasks.md             # Phase 2 产出（/speckit-tasks 后续生成）
```

### Source Code (repository root)

```text
src/nexusx/use_case/
└── router.py            # 修改 _make_handler（4 个 case）+ 把 body_params 传入

tests/
└── test_use_case_router.py  # 新增 TestNestedBaseModelParams test class
```

**Structure Decision**：单文件修改 + 单测试文件扩充。这是 nexusx use_case 子模块下的 bug fix，不需要新增子模块、不需要新增目录。修复点高度集中（`_make_handler` 一个函数 + `create_router` 里调用它的地方），符合"复杂度可控"的检查项。

## Complexity Tracking

> 无 Constitution Check violations，本表为空。
