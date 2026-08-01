# Implementation Plan: nexusx 多服务联邦(nexusx-to-nexusx Federation)

**Branch**: `012-federation` | **Date**: 2026-07-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/012-federation/spec.md`

**Note**: 本文件由 `/speckit-plan` 产出。研究产物见 [research.md](./research.md)。

## Summary

让任意 nexusx 服务能挂载其他 nexusx 服务,组合成一张相对自身的统一图;客户端像查单体一样发一条嵌套查询,入口服务把跨服务遍历编排成"对每个被挂服务发**一条 gql 嵌套查询**"。技术路径(spec + research 收敛):

- **拓扑**:相对组合、无 router;挂载对称;编排 per-query(由查询入口服务承担)。挂载一个服务 = 挂载它的整个查询面,传递可达 inherent。
- **schema 源**:ER 图信息(`RelationshipInfo` + 实体字段),非 SDL;经成员 ER 内省端点暴露,远程关系带目标服务+端点,挂载方传递式拉取(visited-set 去环)。
- **物化**:init 期(async,放 lifespan)拉取→校验→`create_model` 物化远程类型(裸 `__name__`,`FederatedTypeRegistry` 持规范身份)→冻结。
- **取数**:`RemoteLoader` 向被挂服务 `/graphql` 发一条 gql 嵌套查询(以 `by_<key>_in` 为入口),被挂服务用自己的 executor 解析自身组合子图返回;每服务一次批量,不在网络层造 N+1。
- **渲染**:把 `SDLGenerator` 与 `IntrospectionGenerator` 的关系字段来源从 `get_type_hints` 改为注册表(FR-017),使远程关系字段与物化远程类型进入对外 schema。
- **校验**:全部 init 期 fail-fast(服务/类型/join 字段/批量 root/前缀/裸名/成环)。

## Technical Context

**Language/Version**:Python ≥ 3.10(`pyproject.toml::requires-python`)

**Primary Dependencies**:
- 现有:`pydantic >= 2.0`、`fastapi`、`sqlmodel`、`aiodataloader`、`graphql-core`(均为既有)
- **新增**:`httpx`(async HTTP 客户端,供 RemoteLoader 调被挂服务 `/graphql`),放入**新的可选 extra `nexusx[federation]`**(未启用联邦的用户不安装;未装时 `er.federate(...)` 给明确 ImportError)。见 [research.md R3](./research.md)。

**Storage**:N/A(联邦层无状态;各 nexusx 服务拥有自己的库,联邦不触其存储)。

**Testing**:
- `pytest` + `pytest-asyncio`(已在 dev extras)
- 联邦是跨进程语义,需**端到端**测试:用 `httpx` 的 in-process `ASGITransport`(或起真实测试服务)模拟 catalog↔reviews↔users,断言每被挂服务只收一条 gql 查询、结果正确、fail-fast 各类错配。
- `ruff` + `mypy --strict`(与项目一致)。

**Target Platform**:跨平台 Python 库(Linux/macOS/Windows),运行时无平台假设。

**Project Type**:library(nexusx 新增 `federation` 子包 + 对既有 6 个文件的非破坏性扩展)。

**Performance Goals**:
- 一次查询中,**每个被挂服务恰好被发一条 gql 嵌套查询**(SC-003);被挂服务内部用自身 executor 一次批量解析子图,不在网络层产生逐层 N+1。
- 不设量化阈值:联邦开销瓶颈是网络 RTT 与被挂服务自身查询,非 nexusx 编排。

**Constraints**:
- **公共 API 稳定**:不破坏现有 `Relationship`/`GraphQLHandler`/`ErManager`/`AutoQueryConfig`/SDL/Introspection 的对外契约;联邦以**新增**为主。
- **未启用零回归**:不调用 `er.federate(...)` 时,本地查询/SDL/Voyager/Introspection 行为与特性前逐字节一致(SC-005)。
- **init 期 fail-fast**:所有联邦错配在入口服务启动期检出,不进运行时(SC-004)。
- **不引入特权 router 角色**:挂载对称(FR-015)。

**Scale/Scope**:
- 新增子包 `src/nexusx/federation/`(约 6–8 个模块)。
- 修改既有文件约 6 个:`relationship.py`、`loader/registry.py`、`sdl_generator.py`、`introspection.py`、`standard_queries.py`、`execution/query_executor.py`(外加 `handler.py` 的 async federate 接入)。
- 新增 `pyproject.toml` 的 `[federation]` extra。
- 新增测试约 6 个文件(声明/物化/RemoteLoader/校验/schema 渲染/端到端)。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` 当前为未填写模板——无项目级硬性 principle。本特性设计原则由 spec 与既有架构共识约束(参照 `specs/011` 同样处理):

| 检查项 | 状态 | 说明 |
|---|---|---|
| 公共 API 稳定 | ✅ Pass | `Relationship`/`GraphQLHandler`/`ErManager`/`AutoQueryConfig`/SDL·Introspection 对外契约零破坏;新增 `RemoteRelationship`/`federate()`/`by_<key>_in` 生成策略;`RelationshipInfo` 新增**可选**字段 `target_service`(默认 None,不影响现有) |
| 未启用零回归 | ✅ Pass | 不调 `federate()` 时,SDL/Introspection/Executor/Voyager 行为不变;FR-017 的 registry 化改动对既有 custom relationship(本就在注册表)是 no-op 行为对齐 |
| schema 路径改动必要 | ⚠️ Justified | FR-017 改 `SDLGenerator`/`IntrospectionGenerator` 的关系字段来源(type-hint→registry)。非破坏:既有 ORM 关系同时存在于 type hints 与注册表,行为不变;`__relationships__` custom 关系此前**不进 SDL**(潜在 bug),本次一并修正 |
| 测试覆盖 | ✅ Pass | 端到端(catalog+reviews+users)+ 单元(声明/物化/RemoteLoader/校验/渲染)+ `ruff`/`mypy --strict` |
| 复杂度可控 | ⚠️ Justified | 新增 `federation/` 子包 + 1 可选依赖(httpx)。见下方 Complexity Tracking |
| 向后兼容 | ✅ Pass | 可选 extra、可选字段、新增 API;软依赖 httpx(未装时明确报错而非崩溃) |

无不可接受的 violations。两项 ⚠️ 在 Complexity Tracking 显式论证。

## Project Structure

### Documentation (this feature)

```text
specs/012-federation/
├── plan.md              # 本文件
├── spec.md              # /speckit-specify 产出
├── research.md          # Phase 0 研究产物(9 条核实)
├── data-model.md        # Phase 1 数据模型
├── quickstart.md        # Phase 1 验证指南
├── contracts/           # Phase 1 对外契约
│   ├── remote-relationship.md      # RemoteRelationship 声明 API
│   ├── er-introspection.md         # ER 内省端点协议
│   ├── gql-fetch.md                # gql 嵌套取数契约(RemoteLoader ↔ /graphql)
│   └── batch-query-root.md         # by_<key>_in root + AutoQueryConfig 扩展
└── tasks.md             # Phase 2 产出(/speckit-tasks 后续生成)
```

### Source Code (repository root)

```text
src/nexusx/
├── federation/                       # 新增子包:联邦编排
│   ├── __init__.py                   # 公开导出(RemoteRelationship / federate / RemoteLoader ...)
│   ├── relationship.py               # RemoteRelationship 数据类 + "srv.typename" 解析
│   ├── registry.py                   # FederatedTypeRegistry(规范名↔物化类、两遍物化、rebuild namespace)
│   ├── remote_loader.py              # RemoteLoader 工厂(gql 嵌套查询构造 + httpx + 响应对齐)
│   ├── manager.py                    # federate() 编排(传递式 ER 拉取 + 校验 + 物化 + 注册 + 装 RemoteLoader)
│   ├── introspect.py                 # ER 内省端点(成员侧序列化)+ 片段拉取客户端(挂载侧)
│   ├── http.py                       # httpx transport 封装(可注入,便于测试)
│   └── contract.py                   # ER fragment / wire 类型(pydantic)
├── relationship.py                   # 改:get_custom_relationships 识别 RemoteRelationship
├── loader/
│   └── registry.py                   # 改:RelationshipInfo +target_service;ErManager.federate();远程关系 wiring
├── sdl_generator.py                  # 改:_generate_type 读注册表关系;generate 读 get_all_entities();远程目标→裸名(FR-017)
├── introspection.py                  # 改:_build_entity_type 同步 registry 化(FR-017)
├── standard_queries.py               # 改:AutoQueryConfig 批量 key 策略 + _create_by_keys_in_query(by_<key>_in)
├── execution/
│   └── query_executor.py             # 改:selection-aware loader 通道(传 FieldSelection 给远程 loader);按 target_service 路由
├── handler.py                        # 改:async federate 接入 / federate 后重建 SDL·Introspection(见 research R4)
└── __init__.py                       # 改:导出联邦公开 API

pyproject.toml                        # 改:新增 [project.optional-dependencies] federation = ["httpx"]

tests/
├── test_federation_declaration.py    # RemoteRelationship 解析、__relationships__ 识别
├── test_federation_materialization.py# 两遍物化、裸名、FederatedTypeRegistry、去环
├── test_federation_remote_loader.py  # gql 文档构造、响应对齐、N+1(每服务一条)
├── test_federation_validation.py     # 七类 fail-fast
├── test_federation_schema_render.py  # FR-017:SDL+Introspection 含远程类型/字段、渲染=执行同源
└── test_federation_e2e.py            # catalog+reviews+users 端到端(httpx ASGITransport)
```

**Structure Decision**:新增独立子包 `federation/` 承载全部联邦逻辑(组合缝原则——不把联邦散进既有模块);对既有 6 个文件做**非破坏性扩展**(新增可选字段、新增分支、关系字段来源向注册表对齐)。这是库特性,不涉及 apps/frontend/mobile,采用单项目结构。

## Complexity Tracking

> 两项 Constitution Check 标 ⚠️,在此论证。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| 新增 `federation/` 子包(~7 模块) | 联邦是独立横切能力(声明/物化/校验/远程取数/渲染对齐),揉进既有 `loader/`/`execution/` 会让这些模块职责膨胀、耦合远程语义 | 把联邦逻辑直接写进 `ErManager`/`QueryExecutor` 被否——`ErManager` 须保持"本地实体图注册表"的纯度,远程编排是另一层关切;独立子包 + 对既有文件的最小扩展更可测、可关停(不调 `federate()` 即零影响) |
| 新增可选依赖 `httpx`(`[federation]` extra) | RemoteLoader 须 async 调被挂服务 `/graphql`;stdlib 无合适的 async HTTP 客户端 | `aiohttp`(生态贴合度差、多一族依赖)、stdlib `urllib`(无原生 async)被否;放**可选 extra** 让未用联邦者零负担,`er.federate()` 在缺 httpx 时明确报错 |
| FR-017 改 SDL+Introspection 关系字段来源 | 现状 type-hint 驱动让 `__relationships__` 的 custom/remote 关系**不进对外 schema**,客户端无法查询远程字段(US5 不成立);这是特性成立的硬前提 | 维持 type-hint 驱动、仅靠物化类型注入伪注解被否——`create_model` 动态类强行注入注解比读注册表脆;向注册表对齐是唯一一致解,且对既有 ORM 关系 no-op(它们同时在两处) |

无其他 violations。本期不引入新抽象层 beyond `FederatedTypeRegistry`/`RemoteLoader`/`federate()`(均有明确单一职责),不引入运行时懒加载、不引入 SDL namespace-and-strip 翻译层(spec 已排除)。
