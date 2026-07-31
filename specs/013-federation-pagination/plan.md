# Implementation Plan: nexusx 联邦分页(Federation Pagination)

**Branch**: `013-federation-pagination` | **Date**: 2026-07-31 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/013-federation-pagination/spec.md`

**Note**: 本文件由 `/speckit-plan` 产出。研究产物见 [research.md](./research.md)。

## Summary

为 012-federation 的跨服务 to-many 关系引入 offset/limit 分页。技术路径(spec + 多轮设计收敛):

- **模型**:offset/limit,复用本地分页 `PageArgs`/`Pagination` 语义;不上 Relay cursor(单源 member 下无意义)。
- **控制**:分页决定还给 field——`RemoteRelationship.sort_field` 即分页开关(有 sort_field→分页+排序,无→全量),与本地 `Relationship.order_by` 对称;member 默认为每 batch key 生成全量 + 分页双 root,零配置。
- **wire**:分页 root `by_<key>_in_page(<key>_list, limit, offset, sort_field)`,page_args 是 batch 级标量;返回 per-key 分页包 `[{fk, items, pagination}]`;挂载方按 join key 对齐。
- **核心难点**:member executor 的 root 执行路径目前 entity-only,要让它认识分页 root 返回的 per-key 分页包、对 `items` 递归 BFS——把本地分页在"关系路径"已有的分页递归机制推广到"root 路径"。这是动 executor 核心抽象、风险最高处。
- **范围**:首期 β path(gql executor);γ path(Resolver)不做声明式分页;护栏(cost-based 拒绝)独立后续。

## Technical Context

**Language/Version**:Python ≥ 3.10(`pyproject.toml::requires-python`)。

**Primary Dependencies**:**无新增**。复用既有:`pydantic`、`sqlmodel`、`aiodataloader`、`httpx`(012 已引入的 `[federation]` extra)、本地分页 `loader/pagination.py`(`PageArgs`/`PageLoadCommand`/`Pagination`)。

**Storage**:N/A(分页无状态;数据仍在各服务自有库,member 用窗口函数 per-key 分页)。

**Testing**:
- `pytest` + `pytest-asyncio`;端到端用 `httpx ASGITransport` 起 catalog+reviews+users,断言分页正确性、每服务一条 gql、join key 对齐(含 UUID/Decimal)、total_count 可选、items 子树递归。
- member executor root 路径改造是核心,须专门单测(per-key 分页包识别、items 递归、pagination 透传、非分页 root 零影响)。
- `ruff` + `mypy --strict`(与项目一致)。

**Target Platform**:跨平台 Python 库。

**Project Type**:library(012 `federation/` 子包扩展 + 既有文件非破坏性扩展)。

**Performance Goals**:
- 分页查询下每被挂服务仍恰好一条 gql(SC-002);不在网络层产生逐层 N+1。
- `total_count` 可选——客户端不 select 时 member 不算 COUNT OVER(省大表成本)。
- 不设量化阈值:瓶颈是网络 RTT 与被挂服务自身查询,非 nexusx 编排。

**Constraints**:
- **公共 API 稳定**:`RemoteRelationship` 仅新增**可选** `sort_field`(默认 None→全量,行为不变);不破坏既有联邦/本地契约。
- **未声明零回归**:未声明 `sort_field` 的远程关系行为与 012 逐字节一致;既有 012 测试零回归;单体 nexusx 零回归(SC-004)。
- **member executor 改动隔离**:root 路径改造不得影响非分页 root(`by_filter`/`by_id`/`by_<key>_in` 全量)的行为。
- **分页协议 opt-in**:不强制;护栏独立后续。

**Scale/Scope**:
- 改 `federation/` 子包:`relationship.py`(RemoteRelationship +sort_field)、`manager.py`(wiring 分页 loader + 校验)、`remote_loader.py`(分页 RemoteLoader + build_gql_query 分页 + per-key 对齐)、`introspect.py`(暴露分页 root)、`contract.py`(BatchRoot +paginated/sort)。
- 改既有:`standard_queries.py`(`_create_by_keys_in_page_query` 窗口函数 root)、`execution/query_executor.py`(**member root 路径支持分页包**[核心] + mounter β 分页分流)、`sdl_generator.py`/`introspection.py`(分页字段渲染 `{items, pagination}`)。
- 复用:`loader/pagination.py`(`PageArgs`/`Pagination`)、`loader/factories.py` 的窗口函数 SQL 模式。
- 新增测试:分页声明/校验、分页 RemoteLoader、member root 分页包、β 分页分流、端到端分页(catalog+reviews+users)。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` 为未填写模板——无项目级硬性 principle(参照 012 处理)。本特性设计原则由 spec + 既有架构共识约束:

| 检查项 | 状态 | 说明 |
|---|---|---|
| 公共 API 稳定 | ✅ Pass | `RemoteRelationship` 仅新增可选 `sort_field`(默认 None);`RelationshipInfo` 复用既有 `page_loader`/`sort_field` 字段语义;无新依赖 |
| 未声明零回归 | ✅ Pass | 未声明 `sort_field` 的远程关系走全量 RemoteLoader(012 既有路径),行为不变;member 双 root 中全量 root 即 012 既有 |
| member executor root 路径改动 | ⚠️ Justified | FR-007 要求 member executor 认识分页 root 返回的 per-key 分页包并对 items 递归——特性成立硬前提(US2)。非破坏:非分页 root(返回 entity/list)走原路径;仅 root 返回分页包时走分治。见 Complexity Tracking |
| schema 渲染改动 | ⚠️ Justified | FR-013 要求分页远程关系渲染为 `{items, pagination}` 形状;非破坏:仅对声明 `sort_field` 的关系生效,其余不变 |
| 测试覆盖 | ✅ Pass | 端到端 + 单元(声明/校验/RemoteLoader/member root 分页包/β 分流/渲染) + ruff/mypy |
| 复杂度可控 | ⚠️ Justified | member executor root 路径改造是核心复杂度,见 Complexity Tracking |
| 向后兼容 | ✅ Pass | 纯叠加:可选字段、opt-in、零新依赖 |

无不可接受 violations。三项 ⚠️ 在 Complexity Tracking 论证。Phase 1 设计后复检:数据模型与契约未引入新持久化/新依赖,不改既有契约形状,以上判断维持。

## Project Structure

### Documentation (this feature)

```text
specs/013-federation-pagination/
├── plan.md              # 本文件
├── spec.md              # /speckit-specify 产出
├── research.md          # Phase 0 研究产物(9 条决策核实)
├── data-model.md        # Phase 1 数据模型
├── quickstart.md        # Phase 1 验证指南
├── contracts/           # Phase 1 对外契约
│   ├── paginated-remote-relationship.md  # RemoteRelationship.sort_field 声明 API
│   ├── paginated-batch-root.md           # by_<key>_in_page root 契约(签名+per-key 包)
│   └── paginated-gql-fetch.md            # 分页 RemoteLoader ↔ member /graphql 契约
└── tasks.md             # Phase 2 产出(/speckit-tasks 后续)
```

### Source Code (repository root)

```text
src/nexusx/
├── federation/
│   ├── relationship.py    # 改:RemoteRelationship +可选 sort_field(方向);to-one 声明分页启动期拒
│   ├── manager.py         # 改:wiring 分页 RemoteLoader;_validate 对 sort_field 校验(to-many、合法字段)
│   ├── remote_loader.py   # 改:分页 RemoteLoader(build_gql_query 分页变体 + page_args 透传 + per-key 包按 join key 对齐成 {items,pagination})
│   ├── introspect.py      # 改:序列化分页 root(BatchRoot +paginated/sort_field)
│   └── contract.py        # 改:BatchRoot +paginated:bool、sort_field
├── standard_queries.py    # 改:_create_by_keys_in_page_query(PARTITION BY fk 窗口函数 + peek-by-1 has_more + 可选 COUNT);默认每 batch key 生成双 root
├── execution/
│   └── query_executor.py  # 改[核心]:member root 路径识别分页包→items 递归 BFS→序列化 {items,pagination}(FR-007);mounter β path 远程关系分页分流(FR-009)
├── sdl_generator.py       # 改:声明 sort_field 的远程关系渲染为 {items:[...],pagination:{...}}(FR-013)
├── introspection.py       # 改:同上(__schema 分页形状)
└── loader/
    ├── pagination.py      # 复用(PageArgs/Pagination);可能小扩展(per-key 包形状)
    └── factories.py       # 复用窗口函数 SQL 模式(create_page_one_to_many_loader 的 ROW_NUMBER/COUNT OVER)

tests/
├── test_federation_pagination_decl.py    # RemoteRelationship.sort_field 声明 + 校验(to-one 拒、非法字段拒)
├── test_federation_pagination_loader.py  # 分页 RemoteLoader:gql 构造、per-key 对齐、UUID/Decimal、total_count 可选
├── test_federation_pagination_root.py    # member root 返回分页包:items 递归、pagination 透传(核心难点单测)
├── test_federation_pagination_render.py  # SDL/Introspection 分页形状
└── test_federation_pagination_e2e.py     # catalog+reviews+users 端到端分页(含嵌套子树、多 key)
```

**Structure Decision**:不新增子包——分页是 012 `federation/` 子包 + 既有 `standard_queries`/`executor` 的**扩展**,沿用 012 的组合缝(子包 + 对既有文件非破坏性扩展)。核心改动集中在 `execution/query_executor.py`(member root 路径 + mounter β 分流)与 `federation/remote_loader.py`(分页取数),二者是本特性的风险与工作量重心。

## Complexity Tracking

> 三项 Constitution Check 标 ⚠️,在此论证。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| member executor root 路径改造(FR-007) | 本地分页的 items 递归机制只在"关系路径"(`_load_field_paginated`);联邦 member 分页发生在"root 路径"(member 收到 `by_<key>_in_page` root 请求),root 路径目前 entity-only,不认识 per-key 分页包、不能对 items 递归。不改则分页只能取裸标量,无法承载真实查询(US2 不成立) | "mounter 端截断"被否——数据已全量过网、total_count 失真;"member root method 自己解析子树"被否——root method 拿不到完整 selection、重复实现 BFS。把关系路径已有机制搬到 root 路径是唯一一致解;隔离:仅 root 返回分页包时走分治,非分页 root 零影响 |
| 分页字段 schema 渲染改动(FR-013) | 声明 `sort_field` 的远程关系返回类型从扁平 list 变为 `{items, pagination}`,须在 SDL/Introspection 同步,否则客户端无法发现/查询 | 维持扁平 list 渲染被否——与实际返回形状不符,客户端查询会错;改动仅对声明 sort_field 的关系生效,其余 no-op |
| 默认生成双 root(member 零配置) | 让"分页决定"完全落在挂载方 field 声明,消除 member 能力配置层 + federate 能力校验;member 总有能力,不会出现"要分页但 member 没能力"错配 | "member 按 AutoQueryConfig 声明分页能力"被否——多一层配置 + 一类校验,且 member 不知谁会分页它;默认双 root 的代价仅是 member schema 多一个 root(不被调即不执行,无害) |

无其他 violations。本期不引入新抽象层 beyond 分页 RemoteLoader(单一职责);不引入 cursor、不引入 γ 声明式分页、不引入护栏(均 spec 显式排除)。渐进实现顺序见 tasks.md(后续 /speckit-tasks):US1 最小切片(单 key + 标量 items)优先验证 member root 路径,再铺开 items 子树递归 / 多 key / 嵌套跨服务。
