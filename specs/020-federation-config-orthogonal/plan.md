# Implementation Plan: Federation 配置正交化

**Branch**: `020-federation-config-orthogonal` | **Date**: 2026-08-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/020-federation-config-orthogonal/spec.md`

## Summary

把 federation member 侧配置正交化：**联邦外键降为纯标记**（entity `__federation_keys__`）、**order profile 统一**（`__pagination_orders__` 不区分对内对外）、**γ join key 归并到 entity**、**AutoQueryConfig 退化为执行者**（读 entity 生成 by_/page_by 根）。解决正交性分析 5 个问题。breaking（直接删旧配置，federation 用户少）。

## Technical Context

- **Language/Version**: Python 3.10+（requires-python >=3.10）
- **Primary Dependencies**: SQLModel, pydantic 2, graphql-core, fastapi, aiodataloader, fastmcp
- **Storage**: N/A（配置模型重构，不涉及持久化）
- **Testing**: pytest + pytest-asyncio + pytest-cov（基线 1517 passed，当前在 fix/paged-core-api-no-context-override 分支）
- **Project Type**: library（nexusx）
- **Performance Goals**: federation fetch 行为等价（新声明模型 vs 旧 batch_keys/batch_pages），零回归
- **Constraints**: breaking 改动（直接删 `batch_keys`/`batch_pages` + `federation_join_key`，无 deprecated 期）；聚焦 member 侧（mounter `join_remote` 不动）
- **Scale/Scope**: member 侧联邦配置模型重构 —— standard_queries / loader.registry / subset / federation(remote_loader,introspect,manager) / entity dunder 扫描 / demo / docs / tests

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

项目 `.specify/memory/constitution.md` 为空模板（未定义 principles），无强制 gate。遵循项目既有纪律：

- **公共 API breaking 须显式标注**（memory: feedback_public_api_not_breaking）—— 本 feature 是 breaking，changelog 须标注；满足。
- **entity 只承载 resource、计算放 DTO**（memory: project_entity_resource_no_computation）—— `__federation_keys__` 是声明标记（resource 元信息），不是计算逻辑；符合。
- **spec-kit 产物用中文**（CLAUDE.md）—— 满足。

无违反。Phase 1 后复查。

## Project Structure

单 library 项目，复用既有 `src/nexusx` 结构。

```text
src/nexusx/
├── standard_queries.py      # AutoQueryConfig: 删 batch_keys/batch_pages，改读 entity 生成 by_/page_by 根
├── subset.py                # SubsetConfig: federation_join_key 退化为「选择器」（多 key 时选哪个），不再声明 key 值
├── loader/
│   └── registry.py          # 读 entity __federation_keys__ + __pagination_orders__（统一路由，FR-005）
├── federation/
│   ├── introspect.py        # γ DTO 内省: join key 从源 entity __federation_keys__ 推导（不再 DTO federation_join_key）
│   ├── remote_loader.py     # β/γ fetch 读统一声明
│   └── manager.py           # federate 调度（声明底座统一，内部调度可仍分 β/γ）
└── (entity dunder 扫描)     # __federation_keys__ 识别（GraphQLHandler/ErManager 初始化收集，复用 __pagination_orders__ 扫描模式）

demo/federation/
├── reviews_app.py           # 迁移: __federation_keys__ + __pagination_orders__（删 batch_keys/batch_pages）
├── catalog_app.py           # mounter 基本不变；ReviewDTO 删 federation_join_key
└── users_app.py             # 迁移（若有 batch 配置）

docs/advanced/federation.md(+.zh)  # 新声明模型文档
tests/                             # federation 相关测试迁移 + 新声明模型测试
```

**Structure Decision**: 单 library，无新目录。核心改动在 standard_queries / subset / loader.registry / federation/，加 entity dunder 扫描（复用 `__pagination_orders__` 已有的扫描机制，registry.py:145）。

## Complexity Tracking

无 Constitution 违反，无需填。
