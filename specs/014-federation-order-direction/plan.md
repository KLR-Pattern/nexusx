# Implementation Plan: Federation 分页 order/direction 开放给查询者

**Branch**: `feat/federation-order-direction` | **Date**: 2026-08-01 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/014-federation-order-direction/spec.md`

## Summary

把 federation 远程 to-many 分页的 order 选择权从「mounter 部署期静态绑定（`RemoteRelationship.order`）」改为「查询期由查询者经 GraphQL 参数决定」，同时开放排序方向（ASC/DESC）。member 定义单列 order profile 集合 → ER introspection 传 mounter → mounter 渲染成 schema 的 `order`(enum) + `direction` 参数 → 查询者挑 → mounter 透传 → member 按 direction 翻转 term 排序。索引控制权仍在 member（不开放任意 sort field）。只做 β 路径（GraphQL 直查）。

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: SQLModel、SQLAlchemy、Pydantic v2、aiodataloader、FastAPI、httpx（federation extra）
**Storage**: SQLModel（SQLite 测试 / PostgreSQL 生产）；分页沿用 013 的 SQLAlchemy 窗口函数
**Testing**: pytest（既有 federation e2e + 单元套件）
**Project Type**: library（nexusx）
**Constraints**: 保持「每个被挂服务每次遍历只发一条 gql」的 federation 招牌；direction 翻转后 window 内层与 outer order expressions 必须一致；federation 新功能、无向后兼容包袱
**Scale/Scope**: 跨 ~7 文件（member `standard_queries` / `contract` / `introspect` / `manager` / `registry` / `sdl_generator`+`introspection` / `remote_loader` / `relationship`）

## Constitution Check

`.specify/memory/constitution.md` 为模板占位符（未填写实际原则），无 gate 约束。本特性遵循 013-federation-pagination 既定的设计与契约模式，无违反。

## Project Structure

### Documentation (this feature)

```text
specs/014-federation-order-direction/
├── plan.md              # 本文件
├── research.md          # 设计决策（Phase 0）
├── data-model.md        # 实体（Phase 1）
├── quickstart.md        # 验证场景（Phase 1）
├── contracts/           # 契约（Phase 1）
│   └── order-direction.md
└── tasks.md             # /speckit-tasks 生成（本命令不创建）
```

### Source Code (改动点)

```text
src/nexusx/
├── standard_queries.py      # ① member: page_by_field_in 加 direction + 翻转 + 单列校验
├── federation/
│   ├── contract.py          # BatchPageCapability 沿用（确认 orders 序列化）
│   ├── introspect.py        # serialize_er_introspection（orders 已带）
│   ├── relationship.py      # ⑥ RemoteRelationship.order 废弃
│   ├── manager.py           # ② _validate_and_wire 存 page_capability + 校验放宽
│   └── remote_loader.py     # ④ build_paginated_gql_query 加 direction + 不 bake order
├── loader/registry.py       # ② RelationshipInfo 加 page_capability 字段
├── sdl_generator.py         # ③ federation 分页字段渲染 order enum + direction
└── introspection.py         # ③ __schema 镜像（复用 utils/pagination_schema）
tests/                       # e2e（order/direction）+ 单元（翻转/nulls）
demo/federation/             # reviews_app 暴露多 profile + catalog 查 order/direction
```

**Structure Decision**: 单 library 项目（`src/nexusx/`），改动集中在 federation 分页链路；无新顶层目录。

## Architecture

### Member Execution（改 `page_by_field_in`）
- `page_by_<key>_in` 新增 `direction: Direction`（ASC|DESC）参数，与 `order`/`limit`/`offset` 并列。
- 取所选 profile 的 terms，**在 `_build_order_expressions` 之前**按 direction 翻转：`direction` 覆盖 term 默认方向，`nulls` 跟随翻转（`desc+nulls_last` ↔ `asc+nulls_first`）；翻转后的 terms 同时用于 window 内层与 outer（保证一致，沿用 013 的稳定排序约束）。
- `PageOrder` 收紧为单列：`_resolve_page_orders` 校验 `len(terms)==1`（多列拒绝）。

### Federation Contract
- `BatchPageCapability`（013 已有）携带 `orders`（名+描述）+ `default_order` —— 这就是 mounter 渲染 enum 所需，**contract 结构不变**，仅确认 `serialize_er_introspection` 完整序列化 orders。
- 物理列/方向/nulls 仍不暴露（索引控制权 member）。

### Mounter 关系元数据
- `RelationshipInfo` 加 `page_capability: BatchPageCapability | None`（`registry.py`）。
- `manager._validate_and_wire` 从 `BatchRoot.page` 取 capability 存进 rel_info（供 SDL 渲染）。
- 校验放宽：`pagination=True` 不再强制 `RemoteRelationship.order`；改为校验 `page_capability.orders` 非空（fail-fast）。

### Mounter Schema（SDL + Introspection）
- federation 分页关系字段从 `reviews(limit, offset)` 改为 `reviews(limit, offset, order: <XxxOrder>, direction: Direction)`。
- `order` enum 值 = `rel_info.page_capability.orders` 的名集合；默认值 = `default_order`。
- `direction` 是 mounter 自有全局 enum（ASC/DESC），渲染一次。
- introspection（`__schema`）镜像同样参数（两条渲染路径同源，复用 `utils/pagination_schema` 共享判定）。

### Mounter RemoteLoader
- `create_paginated_remote_loader` 去掉 `order` 参数（不再 bake）。
- `build_paginated_gql_query` 加 `direction`；order/direction 都从 `selection.arguments` 取（缺省传 member default）。
- `batch_load_fn` 从注入的 selection 读 order/direction/limit/offset。

## Work Order

1. **member**：`page_by_field_in` 加 direction + 翻转逻辑（`_build_order_expressions` 前翻转 terms）；`_resolve_page_orders` 单列校验。单元测试（翻转 + nulls）。
2. **mounter 关系元数据**：`RelationshipInfo.page_capability` + manager `_validate_and_wire` 存值 + 校验放宽。
3. **mounter SDL/Introspection**：federation 分页字段渲染 order enum + direction（复用 pagination_schema 共享）；introspection 镜像。
4. **RemoteLoader**：去 bake order + `build_paginated_gql_query` 加 direction + 从 selection.arguments 取。
5. **RemoteRelationship.order 废弃**（API 删除）+ demo（reviews 多 profile + catalog 查 order/direction）+ 文档。
6. **e2e**（用户传 order/direction，member 收到正确排序）+ 全量 pytest + ruff。

## Compatibility

federation 为新功能、无外部兼容包袱。`RemoteRelationship.order` 作 API 删除（不保留 deprecation 期）。`BatchPageCapability` 结构不变。`by_<key>_in` 全量 root 不变。单体 nexusx（未启用 federation）零回归。

## Complexity Tracking

无 Constitution 违反，无需记录。
