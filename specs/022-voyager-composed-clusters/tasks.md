# Tasks: Voyager 的 ComposedErManager 分组与配色

**Input**: Design documents from `/specs/022-voyager-composed-clusters/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/voyager-member-styling.md, quickstart.md

**Tests**: 本特性 spec 的全部 SC 均以自动化断言表达（DOT 字符串检查），测试任务按 TDD 顺序排在各实现任务之前，先失败后实现。

**Organization**: 按 user story 分组（US1 分组 → US2 配色 → US3 UseCase 页 → US4 subgraph），每个 story 独立可验收。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属 user story
- 所有测试写入同一个新文件 `tests/test_composed_voyager.py`，因此测试任务之间不标 [P]（同文件顺序追加）

## Path Conventions

- 单项目：`src/`、`tests/`、`demo/`、`docs/` 于仓库根

---

## Phase 1: Setup（基线确认）

**Purpose**: 锁定改动前基线，为 SC-004（单体输出逐字一致）提供对照

- [x] T001 跑既有相关套件确认全绿基线：`uv run pytest tests/test_federation_voyager.py tests/test_composed_er_manager.py tests/test_voyager_subgraph.py -q`，并用一段临时脚本把"单体 ErManager（2 实体）的 ER DOT 输出"存为基线字符串（供 T005 断言复用）

---

## Phase 2: Foundational（阻塞所有 story 的公共件）

**Purpose**: 声明侧与聚合侧——`color` 参数 + `_member_styling` 映射

- [x] T002 `src/nexusx/loader/registry.py`：`ErManager.__init__` 新增 `color: str | None = None` 关键字参数，存 `self._voyager_color`，不做值校验；docstring 注明"仅 Composed 场景经组合体消费，单体不生效"（contracts §1）
- [x] T003 `src/nexusx/loader/composed.py`：新增 property `_member_styling -> dict[type, tuple[str, str | None]]`（惰性构建一次缓存；仅含设了 `service_name` 的 member 的实体 + `dto_classes`；value 为 `(service_name, color)`）；构造期对设名 member 查重 `service_name`，重名抛 `ValueError`（错误信息含冲突名；FR-009；与实体互斥校验同位置）
- [x] T004 测试（tests/test_composed_voyager.py）：两个 member 同 `service_name` → 构造抛 `ValueError` 且信息含该名字；全部未设名 → 构造成功（FR-009）
- [x] T005 测试（tests/test_composed_voyager.py）：单体 ErManager（含设 `color` 与不设两种）的 ER DOT 与 T001 基线逐字一致（FR-008/SC-004）

**Checkpoint**: 声明与聚合就绪，两个消费面（ER 图 / UseCase 页）可以开始接入

---

## Phase 3: User Story 1 — ER 图按 member 分组 (Priority: P1) 🎯 MVP

**Goal**: 设了 `service_name` 的 member，其实体在 ER 图归入以该名字为标签的独立 cluster；跨 engine 边横跨两 cluster

**Independent Test**: 双 member（实体同 Python 模块、各设 service_name）生成 ER DOT，断言两个带标签 cluster + 实体归属正确

- [x] T006 [US1] 测试（tests/test_composed_voyager.py，先写先失败）：双 member 各设 `service_name`、实体定义在同一 Python 模块 → DOT 含两个以 service_name 为标签的 cluster，各 member 实体归属正确；跨边界关系（`Relationship` 声明）两端 cluster 不同（US1 验收 1/2）
- [x] T007 [US1] 实现 `src/nexusx/voyager/er_diagram_dot.py`：`_add_to_node_set` 的 module 解析扩为三级优先 `fed_qn service > _member_styling 命中（getattr 探测）> cls.__module__`（FR-003，research Unknown 1）；`_federation_styling()` 的 module_color 合并 member colors（user module_color 仍最高，data-model §4）；member 名不进 `federated_modules`

**Checkpoint**: 分组生效——MVP 达成（分组即可见，配色尚缺）

---

## Phase 4: User Story 2 — member 配色与 cluster 背景填充 (Priority: P2)

**Goal**: `ErManager(color=...)` 的 member cluster 呈现背景填充 + 边框色 + 节点表头继承；未设色不填充

**Independent Test**: 有色/无色 member 并存，断言 `fillcolor` 仅出现在有色 cluster

- [x] T008 [US2] 测试（tests/test_composed_voyager.py，先写先失败）：member A（`service_name` + `color`）cluster 含 `fillcolor`/`pencolor` 同色；member B（仅 `service_name`）cluster 无 `fillcolor`（US2 验收 1/2，opt-in 断言仿 test_federation_voyager.py 模式）
- [x] T009 [US2] 实现 `src/nexusx/voyager/templates/dot/cluster.j2` + `src/nexusx/voyager/render.py`：模板加 `{% if fill_color %}fillcolor = "{{ fill_color }}"{% endif %}`；`_render_module_schema` 有 cluster_color 时传 `fill_color=cluster_color` 且 `cluster_style` 含 `filled`（member 为 `rounded,filled`，federation 远端为 `rounded,dashed,filled`；research Unknown 6）
- [x] T010 [US2] 测试（tests/test_composed_voyager.py）：composed + federation 叠加——member 各自 federate 后，remote type 按远端 service 聚 dashed cluster，member 本地实体按 member 聚 rounded cluster，颜色各归各不串扰（US2 验收 3；复用 019 US5 矩阵测试的双 federate 场景搭法）

**Checkpoint**: 分组 + 配色完整（含与 federation 正交）

---

## Phase 5: User Story 3 — UseCase 页的 DTO 归属 (Priority: P3)

**Goal**: 注册进 member `dto_classes` 的 DTO 在 UseCase 页归入 member cluster 并吃 member 色

**Independent Test**: 注册 DTO 落 member cluster；未注册 DTO 维持 Python module 分组

- [x] T011 [US3] 测试（tests/test_composed_voyager.py，先写先失败）：member（`service_name`+`color`+`dto_classes=[某DTO]`）经 `VoyagerContext`/`UseCaseVoyager` 生成 UseCase 页 DOT → DTO 节点 module 为 service_name、cluster 应用 member 色；未注册 DTO 仍按 Python module 分组；Route 节点不受影响（US3 验收 1/2）
- [x] T012 [US3] 实现 `src/nexusx/voyager/voyager_context.py` + `src/nexusx/voyager/use_case_voyager.py`：`_get_voyager` 在 fed_registry 透传旁以同风格 `getattr(er_manager, "_member_styling", None)` 探测并放进 config；`UseCaseVoyager.__init__` 加 `member_styling` 参数，`_add_to_node_set` 的 module 解析同三级优先（fed_qn > member > `__module__`），`_federation_styling()` 同合并规则（FR-005；Route 的 module 保持 `serviceCls.__module__` 不动）

**Checkpoint**: 两个消费面（ER 图 + UseCase 页）行为对齐

---

## Phase 6: User Story 4 — 邻域 subgraph 继承分组与配色 (Priority: P4)

**Goal**: Related Entities 子图保留 member 分组与配色（与全图一致）

**Independent Test**: 跨 engine 边锚点的邻域子图仍含两个带色 cluster

- [x] T013 [US4] 测试（tests/test_composed_voyager.py）：对 blog 侧实体调 `get_er_diagram_subgraph`（或直接 `ErDiagramDotBuilder.filter_to_neighborhood` 后 `render_dot`）→ 子图 DOT 仍含两个 member cluster 及各自颜色、跨 engine 边保留（US4 验收 1）。**预期共享渲染路径自动通过**；若失败定位 `filter_to_neighborhood` 的 node_set 裁剪是否丢了 module 信息并修复

**Checkpoint**: 全部 story 验收完成

---

## Phase 7: Polish & Cross-Cutting Concerns

- [x] T014 demo 更新 `demo/composed_er_manager/app.py`：`blog_er`/`shop_er` 各加 `service_name="blog"/"shop"` 与浅色 `color`；挂载 voyager（`app.mount("/voyager", create_use_case_voyager(services=[], er_manager=composed, name="Composed ER"))` 或按该 demo 的 UseCase 结构适配）
- [x] T015 [P] 双语文档：`docs/advanced/composed_er_manager.md` + `.zh.md` 增"Voyager 分组与配色"节（color opt-in、依赖 service_name、建议浅色 `#RRGGBB`、已知前缀碰撞限制）；`docs/advanced/voyager.md` + `.zh.md` 各加一段 member 分组说明
- [x] T016 按 `specs/022-voyager-composed-clusters/quickstart.md` 全量验证：新套件 + 相邻回归 + `uv run pytest` 全量零回归；demo 起服务目测 voyager 页

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1**：无依赖，立即开始
- **Phase 2**：依赖 T001 基线；T003 依赖 T002（映射读 color 字段）；**阻塞所有 story**
- **Phase 3 (US1)**：依赖 Phase 2
- **Phase 4 (US2)**：依赖 Phase 3（fillcolor 断言需要分组 cluster 先存在）
- **Phase 5 (US3)**：依赖 Phase 2（与 US1/US2 无文件冲突，但建议在 US2 后做——use_case_voyager 的 styling 合并复用 US1 的模式）
- **Phase 6 (US4)**：依赖 Phase 4（配色入图后才可断言子图继承）
- **Phase 7**：依赖全部实现任务

### Parallel Opportunities

- T002 与 T001 可并行（不同关注点）
- T015（文档）与 T014（demo）可并行（不同文件）
- 其余多为同文件（tests/test_composed_voyager.py 顺序追加）或存在实现依赖，建议顺序执行

---

## Implementation Strategy

### MVP First (Phase 1–3)

1. T001 基线 → 2. T002+T003 声明与聚合 → 3. T004/T005 防回归测试 → 4. T006/T007 US1 分组
5. **STOP and VALIDATE**：`uv run pytest tests/test_composed_voyager.py -v`（分组断言绿 + 基线一致）

### Incremental Delivery

分组（US1）→ 配色（US2）→ UseCase 页（US3）→ subgraph 锁定（US4）→ demo/文档/全量（Phase 7）。每步增量可独立验收，不破坏前序。

---

## Notes

- 所有测试写 `tests/test_composed_voyager.py` 一个文件（同 story 内测试先于实现；跨 story 顺序追加）
- 断言模式参照 `tests/test_federation_voyager.py`（opt-in：无色时 `fillcolor` 不得出现）
- 实现中禁止改动 federation 的既有行为路径（`federated_modules` dashed、`module_color` 前缀匹配机制本身）——只做叠加
- 完成每个 story 后 commit（项目惯例：中文 spec 产物 + 英文 commit message）
