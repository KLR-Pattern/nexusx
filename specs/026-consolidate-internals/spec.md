# Feature Specification: 026 内部收敛（M1 — 零行为变化的去重、类型化与死代码清理）

**Feature Branch**: `feat/issue-160-m1-consolidate`

**Created**: 2026-11-24

**Status**: Draft

**Input**: Issue #160 路线图 M1（"Consolidate"）。来源：7.0.0 全面 review（`review/review_7.0.0.md`，R1–R10 / DESIGN_5 / DESIGN_6 / DESIGN_7 / DEAD / SIG_3 / SIG_9 / SIG_11 / API_3_7 / BUG_4 起步）。

## Clarifications

### Session 2026-11-24

- Q: 这是重构里程碑，"用户故事"里的用户是谁？ → A: 三类读者——**贡献者**（改一处即改全部，不再在 20 份私有副本里找）、**维护者**（类型系统能看见变体字段，`mypy --strict` 在叶子模块真正生效）、**schema 消费者 / AI agent**（`Decimal` 字段不再在两条路径上表现不同；同步 `@query` 方法不再被静默丢弃）。
- Q: 哪些事**不在** M1 做？ → A: 任何改变 SDL / 响应形状 / 公共签名的事（归 M2 / M3）；`loader/registry.py` 与 `loader/composed.py` 的 mypy 清零若超出 DESIGN_5 顺手可及的范围，顺延到 M2（M1 只对清零的模块开 strict 强制，不强制未清零的）。
- Q: `RelationshipInfo` 改 ABC、`direction` 改 `Literal`、`BatchPageCapability` 搬家——算不算 breaking？ → A: 运行时值不变（字符串值原样、wire 原样）；`RelationshipInfo` 不再可直接实例化（基类本就不该实例化，7.0.0 的 docstring 已如此声明）。按 minor 发布，changelog 写明。

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 类型解包逻辑只有一个实现（Priority: P1）

作为贡献者，我要把 `Optional[X]` / `list[X]` / `Annotated[X, …]` / `Mapped[X]` 解开一层。今天同样的逻辑散落在 20+ 处私有副本里（`type_converter.TypeConverter`、`type_utils.is_list_annotation`、`type_compat._is_optional`、`standard_queries._unwrap_optional_type`、`subset._unwrap_annotation`、`resolver._extract_dto_cls_and_cardinality`、`response_builder._extract_entity_from_annotation`、`selection.*`、`compose_type_mapper._strip_annotated`、`introspector.*`、`voyager/type_helper.*`），其中至少一份已经与"共享"注释矛盾（`selection._is_list_annotation`）。我希望有一个无 nexusx 依赖的叶子模块提供唯一的实现，所有调用方只委托；`x.__func__ if hasattr(x, "__func__") else x` 这种 21 处重复同样收敛为一个 `unwrap_func`。

**Why this priority**: M2 的 schema IR 要有类型化的输入；R1 是 DESIGN_1（三管线收敛）与 DESIGN_5（变体类型化）的前置。零行为变化，风险最低，先做。

**Independent Test**: 全库 `rg "def _?is_optional|def _?unwrap_optional|def _strip_annotated|def _?is_list_annotation|def _get_core_types"` 只命中叶子模块；`rg "\.__func__ if hasattr\(" src` 只命中 1 处；1857+ 测试全绿；SDL / introspection 输出与基线逐字节一致。

**Acceptance Scenarios**:

1. **Given** 一个 `Annotated[Optional[list[Mapped[X]]], …]` 注解，**When** 任意调用方解包，**Then** 得到 `X` 且 `is_list` / `is_optional` 判定与改动前完全一致（用改动前的实现作为对照表锁进测试）。
2. **Given** 某处调用方仍有一份私有副本，**When** CI 运行 `ruff`（未使用导入 / 未使用函数），**Then** 构建失败——副本必须删除而非保留。

---

### User Story 2 - 关系变体在类型层可辨别（Priority: P1）

作为维护者，我希望 7.0.0 引入的四个关系变体在类型层面就能说明自己有没有 loader、有没有分页能力：`RelationshipInfo` 是 ABC、`direction` 是 `Literal`、带 loader 的变体 `loader` 字段必填、每个变体提供 `loader_classes()`。消费点（`composed.py` ×6、`response_builder.py` ×4、`resolver.py` ×3、`sdl_generator.py` ×2、`introspection.py` ×2、`query_executor.py` ×2、`pagination_schema.py` ×1）不再 `getattr(rel_info, "loader", None)` 式地探字段，`mypy` 的 `attr-defined` 报错消失。`BatchPageCapability` 从 `federation/contract.py` 搬到 `loader/pagination.py`（federation 原地 re-export，wire 不变），`loader/registry.py` 不再为它 lazy import federation。`RemoteRelationship` 与 `Relationship` 共享一个 ABC（`is_list` / `target_entity` 只写一次），`get_custom_relationships` 只接受该 ABC。

**Why this priority**: 这是宪法"非法状态不可表示"在消费层的兑现；也是 M2 窗口 SQL 合一（`loader_classes()` 是 `get_loader` 路由的统一入口）的前置。

**Independent Test**: `rg "getattr\((rel_info|first_rel|fed_rel|resolved|rel), \"" src` 为 0；`mypy` 对 `loader/registry.py` 不再报 `RelationshipInfo has no attribute "loader"`；`tests/test_relationship_variants.py` 全绿；federation e2e 全绿。

**Acceptance Scenarios**:

1. **Given** `RelationshipInfo` 基类，**When** 尝试实例化，**Then** 抛 `TypeError`（ABC）。
2. **Given** 一个 `RemoteCoalescedRelationship`，**When** 调 `loader_classes()`，**Then** 返回空元组（而不是 AttributeError）。
3. **Given** `from nexusx.federation.contract import BatchPageCapability`（旧导入路径），**When** 导入，**Then** 成功且是同一个类。
4. **Given** 一个 `page_capability` 为 `None` 的 `LocalRelationship`（未声明 `__pagination_orders__`），**When** SDL 渲染，**Then** 参数串仍为 `(limit: Int, offset: Int = 0, fetchAll: Boolean)`。

---

### User Story 3 - 重复扫描与死代码清理（Priority: P2）

作为贡献者，我希望 8 处 `for attr in dir(entity): getattr(entity, attr)` 扫描 `_graphql_query` / `_pagination_root` 收敛为一个共享的迭代器；两个 `_is_active_paginated_relationship` 的"套娃"包装层删除；11 项死代码删除（`FieldTreeBuilder`、`to_camel_case`、`collect_enum_types`、`get_return_entity_type`、`QueryParser(entity_field_names=)`、两处空 `if TYPE_CHECKING: pass`、失效 `noqa`）；仅测试在用的公共方法（`validate_no_aliases`、`parse_document`、`to_camel_case`）加 `DeprecationWarning`，M4 删除；`compose_schema.FieldInfo` / `voyager.type.FieldInfo` 与 `pydantic.FieldInfo` 撞名，改名并保留别名；`subset.py` 里 4 处同包 `try: from nexusx.x import … except ImportError`（伪装成可选依赖处理的环规避）改成直接导入。

**Why this priority**: 缩表面积、降低 M2 的阅读成本；纯机械。

**Independent Test**: `rg "for (attr_name|name) in dir\((entity|subclass|ent)\)" src` 为 1；`rg "__func__ if hasattr" src` 为 1；死代码对应的 `rg` 为 0；测试数不减少（删除的测试只有 `test_field_tree_builder.py`，并在 changelog 注明）。

---

### User Story 4 - `mypy --strict` 在清零的叶子模块真正生效（Priority: P2）

作为维护者，`pyproject.toml` 声明 `strict = true` 但 589 处报错（含 note）让声明形同虚设。我希望 M1 对清零的模块（`decorator`、`context`、`relationship`、`discovery`、`scanning`、`utils/*`、`loader/pagination`、`loader/query_meta`，尽力含 `loader/factories`）通过 `[[tool.mypy.overrides]]` 打开 `strict` 并在 CI 强制；未清零的模块显式列出，配置文件不再说谎。

**Independent Test**: `uv run mypy src/nexusx` 对上述模块 0 错误；CI 新增 `mypy` 步骤；现有模块错误数不增加。

---

### User Story 5 - 小项收口（Priority: P3）

- `Decimal` 两条路径表现不一致（compose 泛化报错、entity-first 静默映射为 `String`）→ 加入 `SCALAR_TYPE_MAP` 作为自定义标量 `Decimal`，两路一致。
- `context._expose_cache` / `_send_to_cache` 改 `WeakKeyDictionary`；`response_builder._MODEL_CACHE` 的 key 加入 `id(relation_entity_resolver)`。
- `create_use_case_router` 从 `nexusx.use_case` 也可导入（SIG_3）。
- `ErManager.get_dto_loader` 一参形式加 `DeprecationWarning`（SIG_9）。
- `add_dto_batch_roots` 不再读写 `er_manager._session_factory` / `_dto_batch_roots`，改走 `ErManager.register_dto_batch_roots()`（SIG_11）。
- `UseCaseService` 上的同步 `@query` / `@mutation` 方法被跳过时打 `logger.warning`（API_3_7）。
- `response_builder.get_relation_entity`：已注册实体以 registry 为唯一真源，SA / 注解 fallback 只服务未注册实体（R8）。

---

## Success Criteria *(mandatory)*

| 指标 | 7.0.1 基线 | M1 目标 |
|---|---|---|
| 函数内 lazy `from nexusx.` 导入（行） | 108 | ≤ 60 |
| `.__func__ if hasattr(` 站点 | 21 | 1 |
| `for … in dir(entity)` 装饰器扫描 | 8 | 1 |
| `getattr(rel_info\|…, "loader"\|…)` 鸭子读 | 20 | 0 |
| 同包 `try/except ImportError` 文件数 | 1（subset.py，4 处） | 0 |
| 死代码项 | 11 | 0（公共项已弃用） |
| `mypy --strict` 清零并强制的模块 | — | decorator / context / relationship / discovery / scanning / utils / loader/pagination / loader/query_meta（+ factories 尽力） |
| 测试 | 1863 passed | ≥ 1863 − (删除的死代码测试) ，0 failed |
| SDL / `__schema` 输出 | — | 与基线逐字节一致（除 `Decimal` 字段：String → Decimal） |
