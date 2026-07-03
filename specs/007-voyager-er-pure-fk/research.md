# Phase 0 — 研究与决策：Voyager Hide Reverse Relationships 连线模式

**功能**：[spec.md](./spec.md) · **计划**：[plan.md](./plan.md)

**调研范围**：spec 中无 NEEDS CLARIFICATION 残留（已在 `/speckit-clarify` 阶段 Q1-Q5 全部解决）；本文件聚焦四个**实现层面**的决策——过滤发生位置、UI 状态传输路径、命名约定、过滤逻辑具体位置。同时核对当前代码现状以验证决策可行性。

---

## 现状核对（基于代码 grep 结果）

在确定决策前，先核实 spec 描述与代码现实一致：

- `loader/registry.py::RelationshipInfo` 已有 `direction: str` 字段，取值 `MANYTOONE | ONETOMANY | MANYTOMANY`（第 36 行），由 SQLAlchemy `inspect()` 在 `_inspect_relationships` 中自动反射（第 85-100 行附近）。
- `er_diagram_dot.py::_add_relationship_link`（第 199-237 行）当前**未消费** `direction` 字段——只用 `rel_info.name`、`rel_info.target_entity`、`rel_info.is_list`、`rel_info.description`，所有 relationship 一视同仁地生成 Link。
- `er_diagram_dot.py::analysis()` 第 120 行注释 "Build relationship map per entity (replaces fk_set)" 印证 spec Q4 的发现：FK 列约束连线早已被 relationship 取代。
- `create_voyager.py` 已有 `ErDiagramPayload`（第 64 行）与 `ErDiagramSubgraphPayload`（第 72 行），都含 `show_module` / `better_cluster_display` / `show_methods` 三个 bool 字段——本期扩展在此模式上追加同形字段。
- `voyager_context.py` 在 4 处构造 `ErDiagramDotBuilder`（第 108、128、171-175、229-233 行附近），都透传上述字段——本期需在 4 处追加 `hide_reverse_relationships` 透传。
- `store.js` 已有 `toggleBetterClusterDisplay` / `toggleShowModule` / `toggleBrief` / `togglePydanticResolveMeta` 等 toggle 函数，签名 `(val, onGenerate)`、写 localStorage、调 `onGenerate()`——本期新增的 toggle 函数完全照搬该模式。
- `vue-main.js:61` 已有 `loadToggleState("show_module_cluster", false)` 模式从 localStorage 恢复状态——本期新增同模式的初始化读取。

**结论**：spec 的所有假设与代码现状一致，决策无需修正。

---

## 决策 1：过滤发生位置——前端 SVG 隐藏 vs 后端 dot 裁剪

**Decision**：**后端 dot 裁剪**——在 `er_diagram_dot.py::_add_relationship_link` 内按 `rel_info.direction` 早退过滤 ONETOMANY，使后端传输给前端的 dot 字符串已经不含 ONETOMANY 连线。

**Rationale**：
- **数据已有**：`RelationshipInfo.direction` 字段已存在，后端无需新增反射逻辑。
- **子图跟随天然兼容**：spec 005 的 `filter_to_neighborhood` 在 `analysis()` 之后调用、消费 `self.links`；如果 Pure FK 过滤在 `analysis()` 内完成，子图自动继承过滤结果，无需为子图额外实现裁剪逻辑（满足 spec FR-007 与 Story 1 验收场景 9）。
- **不破坏现有契约**：`Link` 数据结构 shape 不变（不需要新增 `direction` 字段透出给前端），避免影响 `web/schema` 端点缓存与 service worker 缓存的 dot 字符串。
- **性能更优**：不传输冗余的 ONETOMANY 连线（典型 schema 下约 1/3–1/2 边数减少），dot 字符串更小、前端 SVG 渲染更快。
- **关注点分离**：前端只负责"用户勾选状态 → 传给后端 → 重新渲染"，不感知 ORM relationship 的 direction 语义；后端单一职责地决定"画哪些边"。

**Alternatives considered**：
- **A. 前端 SVG 隐藏**：后端仍生成全部 Link，但 `Link` 数据结构需新增 `direction` 字段透出；前端在 `graphviz.svg.js` 渲染管线或 `graph-ui.js` 内按 direction 隐藏 ONETOMANY 边。
  - 被否：(a) 破坏 `Link` shape（影响序列化缓存）；(b) 需要前端感知 ORM direction 语义，关注点混淆；(c) 传输浪费——边数据传到前端再隐藏；(d) 子图跟随需另写一遍前端过滤逻辑。
- **B. 后端 dot 末尾过滤**：`analysis()` 末尾统一遍历 `self.links` 删除 ONETOMANY。
  - 被否：需二次遍历，且 `_add_relationship_link` 内已经访问过 `rel_info.direction`（去重时通过 `rel_info.name`），早退比末尾过滤更经济。

---

## 决策 2：UI 状态传输路径——扩展现有请求体 vs 新增端点 vs URL 参数

**Decision**：**扩展现有请求体**——在 `ErDiagramPayload`、`ErDiagramSubgraphPayload` 各新增 `hide_reverse_relationships: bool = False` 字段；`/er-diagram`、`/er-diagram-subgraph` 路由逻辑不变（FastAPI 自动把请求体映射到 voyager_context 方法）。

**Rationale**：
- **与现有 toggle 模式一致**：`better_cluster_display` / `show_module` / `show_methods` 都以同样的"请求体 bool 字段"方式从 UI 传到后端，新增字段保持模式一致。
- **不破坏契约 shape**：bool 字段默认 `False`，老客户端不传该字段时行为与现状一致（兼容性变更）。
- **改动最小**：只在两个 Payload model 加一行、4 处 `ErDiagramDotBuilder` 构造点加一行透传，无新增端点、无新增路由。
- **支持 spec 005 子图跟随**：`ErDiagramSubgraphPayload` 同步扩展，前端 toggle 状态会同时影响主图请求和子图请求，子图天然跟随裁剪。

**Alternatives considered**：
- **A. 新增独立端点** `POST /er-diagram?hide_reverse=...` 或 `POST /er-diagram-hide-reverse`：被否——增加端点数量、与现有 toggle 模式不一致、Service worker 缓存策略需要新增条目。
- **B. URL 参数 / query string**：被否——spec FR-012 已明确"显示偏好不进入 URL"，避免分享 URL 时把个人偏好强加给接收方。
- **C. HTTP header**：被否——header 通常用于元数据（认证、追踪），不用于业务参数；与现有 toggle 不一致。

---

## 决策 3：命名约定——全栈标识对齐策略

**Decision**：全栈统一使用基于功能显示名 "Hide Reverse Relationships" 派生的命名：

| 层 | 命名 | 形式 |
|----|------|------|
| UI 可见 label | `Hide Reverse Relationships` | 英文 Title Case |
| localStorage key | `hide_reverse_relationships` | snake_case |
| Python Payload 字段 | `hide_reverse_relationships` | snake_case |
| Python 构造函数参数 | `hide_reverse_relationships` | snake_case |
| JS store.state.filter 字段 | `hideReverseRelationships` | camelCase |
| JS toggle 函数名 | `toggleHideReverseRelationships` | camelCase |
| pytest 测试文件 | `test_voyager_hide_reverse.py` | snake_case |

**Rationale**：
- **与功能显示名对齐**：用户在 UI 看到的名字与代码内标识符直接映射，便于跨层调试与日志关联。
- **沿用项目惯例**：
  - localStorage key：项目内 `better_cluster_display` / `brief_mode` / `pydantic_resolve_meta` 均为 snake_case。
  - Python 字段：项目内所有 Pydantic model 与构造函数参数均 snake_case。
  - JS store 字段：项目内 `state.filter.betterClusterDisplay` / `state.filter.showModule` 均 camelCase。
  - toggle 函数：项目内 `toggleBetterClusterDisplay` / `toggleShowModule` / `toggleBrief` 均以 `toggle` 前缀。
- **可搜索性**：完整短语 `hide_reverse_relationships` / `hideReverseRelationships` 全局唯一，便于跨文件查找。

**Alternatives considered**：
- **A. `pure_fk_edges` / `pureFkEdges`**：spec 假设区块提到的备选。被否——功能显示名已在 Q5 改名，"pure FK" 语义已不准（实际是按 direction 过滤、保留持有 FK 一侧，而非显示 FK 列约束连线）；继续用此命名会让后人困惑。
- **B. `hide_reverse_rels` / `hideReverseRels`**：被否——`rels` 是 `relationships` 的非标准缩写，项目内现有 toggle 都用完整单词（`cluster_display` 不是 `clstr_dsply`），保持一致性。
- **C. `hide_back_populates` / `hideBackPopulates`**：被否——`back_populates` 是 SQLAlchemy 实现细节术语，用户看 UI 时不懂；且本模式语义比"隐藏 back_populates"更广（任何 ONETOMANY 方向 relationship 都隐藏，不论是否真有 back_populates 配置）。
- **D. `forward_relationships_only` / `forwardRelationshipsOnly`**：被否——语义上等价但更长，且 "forward" 是相对概念（forward 相对什么？），不如 "hide reverse" 直观。

---

## 决策 4：过滤逻辑在 `_add_relationship_link` 内的具体位置——早退 vs 末尾 vs 渲染层

**Decision**：**入口处早退**——在 `_add_relationship_link` 函数体最开始（现有的 `_is_model_like_target` 检查之后、构造 `source_anchor` 之前）加判定：

```python
def _add_relationship_link(self, entity_kls, rel_info):
    if not _is_model_like_target(rel_info.target_entity):
        return
    # 新增：Pure FK 模式下隐藏 ONETOMANY 反向镜像
    if self.hide_reverse_relationships and rel_info.direction == 'ONETOMANY':
        return
    # 后续逻辑不变
    source_name = full_class_name(entity_kls)
    ...
```

**Rationale**：
- **早退避免无谓工作**：在 dedup 查询（`pair in self.link_set`）、`full_class_name` 调用、`Link` 对象构造之前退出，开销最小。
- **不破坏 `self.rel_name_set`**：`rel_name_set` 在 `analysis()` 第 121-125 行独立构建（与 `_add_relationship_link` 解耦），记录**全部** relationship 名字供 `_get_entity_fields` 渲染字段表使用——Pure FK 模式下 Fields tab 仍展示完整字段列表（含 ONETOMANY 方向 relationship 字段），符合 spec FR-007。
- **与现有去重逻辑同级**：现有的 `_is_model_like_target` 早退也是入口处过滤，新增 direction 早退与之模式一致，代码可读性好。
- **`MANYTOONE` / `MANYTOMANY` 全部保留**：spec FR-005 / FR-006 明确这两类方向都保留，早退条件 `direction == 'ONETOMANY'` 自动满足。

**Alternatives considered**：
- **A. `analysis()` 末尾统一过滤**：在 `for entity_kls, rels in all_relationships.items():` 循环结束后，遍历 `self.links` 反向查找对应的 `rel_info.direction` 并删除 ONETOMANY。
  - 被否：(a) 需要二次遍历；(b) 反查 link → rel_info 的映射需要额外索引；(c) 比 `_add_relationship_link` 早退更复杂。
- **B. `DiagramRenderer.render_dot` 渲染层过滤**：在生成 dot 字符串时跳过 ONETOMANY 边。
  - 被否：(a) 破坏单一职责——renderer 不应感知 ORM relationship 语义；(b) 渲染层只接收 `Link` 列表、不知道 direction；(c) 若要 renderer 知道 direction，需把 direction 透出到 `Link` 数据结构，回到决策 1 被否的方案 A。
- **C. 后端在生成 dot 后做字符串处理**（如 regex 删除 dot 中 ONETOMANY 边的行）：被否——字符串处理脆弱、不可维护。

---

## 决策 5：测试覆盖范围——后端单元测试 + 端到端人工验证

**Decision**：后端在 `tests/test_voyager_hide_reverse.py` 新增 pytest 用例覆盖：

1. **过滤逻辑单元测试**：构造含双向 `back_populates` 关系的 SQLModel 实体（如 `Post.author ↔ User.posts`），分别在 `hide_reverse_relationships=False` / `True` 下调用 `ErDiagramDotBuilder.analysis()`，断言 `self.links` 数量与方向。
2. **M2M 不被过滤**：构造含 `secondary="..."` 的 M2M 关系，断言 `hide_reverse_relationships=True` 下两端实体的 M2M 连线仍存在（双方向都保留）。
3. **MANYTOONE 单向 / ONETOMANY 单向**：构造无 `back_populates` 的单向 relationship，断言 MANYTOONE 单向保留、ONETOMANY 单向隐藏。
4. **端点契约扩展**：通过 FastAPI TestClient 调用 `POST /er-diagram`，请求体分别带 `hide_reverse_relationships: true` / `false` / 不带该字段（默认 false），断言响应 dot 字符串中 ONETOMANY 边的存在/缺失。
5. **子图跟随裁剪**：通过 `POST /er-diagram-subgraph` 在 `hide_reverse_relationships: true` 下请求某实体的子图，断言子图也按 Pure FK 模式裁剪。
6. ** Fields/Source/About 不受影响**：断言 SchemaNode 字段表（`node.fields`）在两种模式下完全一致（Pure FK 只裁剪连线、不裁剪字段展示）。

前端无自动化测试基线（与项目其他 toggle 一致），依赖 `quickstart.md` 的人工验证流程覆盖：
- localStorage 持久化、键盘可达、与其他 toggle 正交、URL 不含状态、子图跟随、刷新恢复等。

**Rationale**：
- 后端测试覆盖核心过滤逻辑，避免回归（特别是与 spec 005 子图的交互）。
- 前端沿用项目惯例（无前端测试基线），不引入新测试基础设施（避免破坏 Constitution 潜在的"不引入前端构建/测试工具链"约束）。

**Alternatives considered**：
- **A. 引入 Playwright/Cypress 做前端 e2e 测试**：被否——破坏现有"无前端构建工具链"模式，且本期功能 UI 行为简单（一个 checkbox toggle），人工验证足够。
- **B. 不写测试，全靠 quickstart 人工验证**：被否——后端过滤逻辑是本特性的核心，缺少自动化测试会在后续重构时（如 spec 005 子图逻辑改动）引入回归风险。
