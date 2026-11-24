# Tasks: 026 内部收敛（M1）

**Input**: Design documents from `/specs/026-consolidate-internals/`
**Prerequisites**: plan.md, spec.md
**Tests**: 基线 1863 passed + 6 skipped 为回归红线；R1 对照表测试、变体 ABC 测试为新增交付物。
**Organization**: 两个 PR——#162（PR A：机械收敛 US1/US3/US5 + R3）与 PR B（变体类型化 US2 + R8/SIG_11 + mypy 强制 US4，基于 #162 分支堆叠）。
**Format**: `[ID] [P?] [Story] Description`，含精确路径。

## Phase A — 叶子模块与机械收敛（PR A）

- [x] T001 [P1] [US1] 新建 `src/nexusx/annotation_utils.py`：`unwrap_optional / is_optional / is_list / list_inner / strip_annotated / unwrap_mapped / core_types / is_pydantic / unwrap_func`，零 nexusx 依赖
- [x] T002 [P1] [US1] 新建 `tests/test_annotation_utils.py`：用改动前各副本的输入/输出做对照表（含 `Annotated[Optional[list[X]]]`、`X | None`、`Mapped[list['X']]`、空 `list`、非类型入参）
- [x] T003 [P1] [US1] `type_converter.TypeConverter` 委托叶子模块；删除 `utils/type_compat`、`utils/type_utils.is_list_annotation`、`standard_queries._unwrap_optional_type`、`subset._unwrap_annotation`、`resolver._extract_dto_cls_and_cardinality` 内部解包、`response_builder._extract_entity_from_annotation`、`use_case/selection._{is_list_annotation,_get_core_types,_strip_annotated,_safe_issubclass}`、`use_case/compose_type_mapper._strip_annotated`、`use_case/introspector._{is_optional_type,_collect_core_types}`、`voyager/type_helper.{is_list,get_core_types,safe_issubclass}` 的副本
- [x] T004 [P1] [US1] R2：21 处 `.__func__ if hasattr(…)` → `unwrap_func`
- [x] T005 [P2] [US3] R3：`scanning/method_scanner.py` 新增 `iter_operations(entity)` / `iter_pagination_roots(entity)`；`sdl_generator`（×3）、`introspection`（×2）、`utils/pagination_schema.iter_pagination_roots`、`discovery/entity_discovery`、`er_diagram*` 改为消费；`dir()` 扫描 8 → 1
- [x] T006 [P2] [US3] R4/R5/R6：`_pascal*`、`_camel_to_snake`、FromContext 检测各合为一处
- [x] T007 [P2] [US3] R7：`compose_schema.FieldInfo → ComposeField`、`voyager/type.FieldInfo → VoyagerField`（保留别名）
- [x] T008 [P2] [US3] DEAD：删 `execution/field_tree_builder.py` + `tests/test_field_tree_builder.py`、`utils/naming.py`、`schema_helpers.collect_enum_types`、`type_utils.get_return_entity_type`、`QueryParser(entity_field_names=)`、两处空 `if TYPE_CHECKING: pass`、`sdl_generator` 失效 `noqa`、两层 `_is_active_paginated_relationship` 包装；`validate_no_aliases` / `parse_document` / `to_camel_case` 加 `DeprecationWarning`（M4 删）
- [x] T009 [P2] [US3] R10：`subset.py` 4 处同包 `try/except ImportError` → 直接导入
- [x] T010 [P3] [US5] DESIGN_1：`Decimal` 加入 `SCALAR_TYPE_MAP`（两路一致，SDL 新增 `scalar Decimal`）；`_SCALAR_NAMES`（compose）同步
- [x] T011 [P3] [US5] DESIGN_6 partial：`context._expose_cache/_send_to_cache → WeakKeyDictionary`；`response_builder._MODEL_CACHE` key 含 `id(relation_entity_resolver)`
- [x] T012 [P3] [US5] SIG_3：`nexusx.use_case.__all__` 加 `create_use_case_router`；SIG_9：`get_dto_loader` 一参形式 `DeprecationWarning`；API_3_7：同步 `@query` 跳过时 `logger.warning`

## Phase B — 变体类型化（PR B）

- [x] T013 [P1] [US2] `loader/pagination.py` 新增 `BatchPageCapability`（自 `federation/contract.py` 搬入），`contract.py` re-export；`standard_queries.PaginationRootMeta.page_capability` / `registry._resolve_local_page_capability` / `RemotePagedRelationship.page_capability` 改为直接导入（去 lazy）
- [x] T014 [P1] [US2] `registry.py`：`RelationshipDirection = Literal[...]`；`RelationshipInfo(ABC)`；三个带 loader 变体的 `loader` 必填；四变体 `loader_classes()`；模块级 `plain_loader_of(rel)` / `page_capability_of(rel)` 做一次 isinstance 收口
- [x] T015 [P1] [US2] 消费点 20 处 `getattr` → `isinstance` / `loader_classes()` / `plain_loader_of` / `page_capability_of`：`composed.py` ×6、`response_builder.py` ×4、`resolver.py` ×3、`sdl_generator.py` ×2、`introspection.py` ×2、`query_executor.py` ×2、`pagination_schema.py` ×1
- [x] T016 [P1] [US2] DESIGN_7：`relationship.RelationshipBase(ABC)`（`is_list` / `target_entity` 共享），`Relationship` 与 `federation.RemoteRelationship` 继承；`get_custom_relationships` 只接受基类；删除 `relationship._remote_relationship_cls` 懒加载
- [x] T017 [P2] [US2] R8：`response_builder.get_relation_entity` 已注册实体以 registry 为唯一真源；合并 `__sqlmodel_relationships__` / `__annotations__` 两段重复
- [x] T018 [P3] [US5] SIG_11：`ErManager.register_dto_batch_roots()`；`add_dto_batch_roots` 改走它
- [x] T019 [P1] [US2] 测试：`tests/test_relationship_variants.py` 加 ABC 实例化 TypeError、`loader_classes()` 期望表、旧导入路径 `federation.contract.BatchPageCapability` 可用

## Phase C — mypy 强制（PR C，或并入 A/B 末尾）

- [x] T020 [P2] [US4] 清零：`decorator`、`context`、`relationship`、`discovery/entity_discovery`、`scanning/*`、`utils/*`、`loader/pagination`、`loader/query_meta`（尽力 `loader/factories`）
- [x] T021 [P2] [US4] `pyproject.toml` `[[tool.mypy.overrides]]`：清零模块 `strict = true`；`.github/workflows/ci.yml` 加 `uv run mypy src/nexusx`
- [x] T022 [P2] [US4] changelog `[Unreleased] — 7.1.0` 条目（Minor：ABC / Literal / Decimal 标量 / 弃用警告）
