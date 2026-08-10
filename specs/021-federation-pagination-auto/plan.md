# Implementation Plan: 联邦分页自动化（去掉 RemoteRelationship.pagination）

**Branch**: `021-federation-pagination-auto` | **Date**: 2026-08-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/021-federation-pagination-auto/spec.md`

## Summary

去掉 `RemoteRelationship.pagination`（per-edge），联邦分页改为 **member 能力（`__pagination_orders__` → `page_by_<key>_in` 自动暴露）+ 查询参数（limit 运行时驱动）**。mounter 零联邦分页配置（无 `RemoteRelationship.pagination`，`enable_pagination` 也不控联邦）。`enable_pagination` member/mounter 对称（各管本地关系）。020（已 merge）的分页维度收尾。

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: SQLModel + SQLAlchemy + aiosqlite（async）、httpx（federation transport）、Starlette（ASGI）、pydantic v2
**Storage**: SQLModel/SQLAlchemy（entity）；联邦跨服务用 httpx
**Testing**: pytest + pytest-asyncio（基线 1517 passed）
**Target Platform**: library（pip 安装，Python 服务内嵌）
**Project Type**: library（nexusx）
**Performance Goals**: 联邦零 N+1（每服务一次批量根）
**Constraints**: 联邦还嫩（错误路径待加固，note 9 P1）；本 feature 聚焦分页配置正交，不涉及错误路径
**Scale/Scope**: federation manager 核心（loader wire）+ SDL/introspection + 测试

## Constitution Check

无 constitution（`.specify/memory/constitution.md` 是空模板）。GATE: pass（无项目级约束）。延续 020 精神（声明在 member，消费方读）。

## Project Structure

### Documentation (this feature)

```text
specs/021-federation-pagination-auto/
├── plan.md              # 本文件
├── research.md          # Phase 0：实现决策
├── data-model.md        # Phase 1：数据模型 + 改动点
├── quickstart.md        # Phase 1：验证场景
├── contracts/           # Phase 1：契约（联邦边新形态）
└── tasks.md             # Phase 2（/speckit-tasks，本命令不生成）
```

### Source Code (改动点)

```text
src/nexusx/
├── federation/
│   ├── manager.py          # _validate_and_wire_remote_relationship / _check_target（核心：page_by_ 探测）
│   └── remote_loader.py    # loader wire（paged vs plain，跟随 page_by_ 探测）
├── sdl_generator.py        # is_active_paginated_relationship 调用（REMOTE_PAGED 判定改）
├── introspection.py        # 同上
└── utils/pagination_schema.py  # is_active_paginated_relationship 定义（REMOTE_PAGED 判定改）

tests/  # 去 pagination 后的 β/γ/多层/to-one/无 limit 测试 + 迁移现有
demo/federation/  # 三层 demo 迁移（删 RemoteRelationship pagination=）
```

**Structure Decision**: 单 library（src/nexusx），改动聚焦 `federation/manager.py`（loader wire 探测 page_by_）+ `utils/pagination_schema.py`（is_active 判定）+ `sdl_generator.py`/`introspection.py`（同步）+ 测试/demo 迁移。`standard_queries.py`（page_by_ 生成）020 已改，本 feature 不动。
