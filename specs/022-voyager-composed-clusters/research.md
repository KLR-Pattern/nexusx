# Research — 022 Voyager Composed 分组与配色

Phase 0 决策记录。所有结论基于对当前代码的实测阅读（file:line 标注），非推测。

## 现状盘点（探索结论）

### R1. ER 图/UseCase 页的 styling 管道（复用基础）

federation 已实现完整的"按 service 分 cluster + opt-in 上色"管道，本特性逐段复用：

| 环节 | 位置 | 机制 |
|---|---|---|
| 颜色声明 | `federation/registry.py:81,292` | `RemoteService(color=...)` → `_service_colors`（`setdefault`，先到先得） |
| 节点归属 | `voyager/er_diagram_dot.py:150-158`、`voyager/use_case_voyager.py:171-176` | `module = parse_qualified_name(fed_qn)[0] if fed_qn else cls.__module__` |
| styling 汇总 | `er_diagram_dot.py:257-275`、`use_case_voyager.py:301-321` | `(module_color, federated_modules)` 二元组 |
| cluster 渲染 | `render.py:344-405` + `cluster.j2` | 前缀匹配 → `pencolor`+`penwidth=3`；`federated_modules` → `rounded,dashed` |
| 节点继承色 | `render.py:307,363` | `render_schema_node(node, color)` 已支持 |

**关键结论：分组的本质是改写节点的 `module` 字段**（module 即 cluster 归属键）。federation 把 remote type 的 module 改写为 service 名，cluster 自动出现。member 分组照搬：把 member 实体的 module 改写为其 `service_name`。

### R2. ComposedErManager 的既有聚合（数据源已备）

`loader/composed.py`：
- `get_all_entities()` / `get_all_relationships()`（含跨边界叠加）—— ER 图数据已通（019 验证）
- `_fed_registry` 聚合视图（`_CompositeFedRegistryView`，composed.py:38-82）—— 含 `service_colors()` 聚合
- `get_dto_classes()`（composed.py:391-396）—— 聚合各 member 的 `dto_classes`
- member 的 `service_name` 属性已存在（`loader/registry.py:424,441`，federation 用）

**缺口**：没有"类 → 所属 member"的查询接口；member 本地颜色无声明入口。

### R3. 渲染层缺口

`templates/dot/cluster.j2` 仅支持 `pencolor`/`pen_width`/`cluster_style`，无背景填充。graphviz cluster 背景色 = `fillcolor` 属性 + `style` 含 `filled`。`digraph.j2` 无全局 bgcolor，不需动。

### R4. demo 现状

`demo/composed_er_manager/app.py`：blog_er/shop_er 未设 `service_name`，实体同在 `models.py`，**未挂载 voyager**。是本特性 demo 的直接改造对象。

---

## Unknown 1：member 分组信息的暴露形状

**Decision**：ComposedErManager 新增 property `_member_styling`，返回**单一映射** `dict[type, tuple[str, str | None]]`——key 为实体类或 DTO 类，value 为 `(service_name, color)`。仅含**设了 `service_name` 的 member** 的实体与 `dto_classes`。

**Rationale**：
- 与 `_fed_registry` 同风格：消费面用 `getattr(er_manager, "_member_styling", None)` 探测，单体 ErManager 无此属性 → 自动回落现状（FR-008 免费满足）
- entity 与 DTO 都是 `type`，key 空间统一，无需 `{"entities":…, "dtos":…}` 两层结构
- tuple `(name, color)` 比嵌套对象轻；color 可为 None（有名字无颜色 → 分组不配色）

**Alternatives**：
- *方法 `member_module_of(cls)`*：两处消费面各需 module 与 color 两次查询，映射一次给全。**拒绝**。
- *复用 `_fed_registry.service_colors()`*：那是 federation 语义（RemoteService 的色），member 本地色是另一个维度。**拒绝**（语义混淆）。

## Unknown 2：`service_name` 重名（FR-009 fail-fast 的时机）

**Decision**：校验放 **ComposedErManager 构造期**——聚合时发现两个 member 的 `service_name` 相同 → `ValueError`（与既有"实体互斥校验"同位置、同风格，composed.py:131-138 旁）。

**Rationale**：分组键 = service_name，重名会导致两个 member 的实体并入同一 cluster、颜色冲突（先到先得掩盖问题）；且 DOT cluster id 同名会崩。构造期 fail-fast 与 019 的"构造期互斥校验"纪律一致。

**Alternatives**：
- *渲染期报错*：错误离声明点远，排查成本高。**拒绝**。
- *自动加后缀区分*：静默改名违背最小惊讶，名字是用户声明语义。**拒绝**。

## Unknown 3：颜色前缀匹配的碰撞边界

**Decision**：**不改前缀匹配机制**（`render.py:355-360` `mod.fullname.startswith(k)`）。member 分组通过改写节点 `module` 为 `service_name` 生效，`module_color` 的 key 即 `service_name`，作用于以它为根的 module 子树——与 federation 行为完全同构。

**Rationale**：
- member 的实体 module 被改写为 service_name 后，`build_module_schema_tree` 建出的 module 树根就是 service_name，前缀匹配精确命中自身子树
- 若改为精确匹配（`==`），会破坏 federation 既有行为（service 名下可嵌套 `srv.Type` 展开的多级 module）——超出本特性范围

**已知限制（记录，不解决）**：本地存在与 service_name 同前缀的真实 Python module（如 service_name=`blog` 且存在模块 `blogging.models`）时，该 module 的 cluster 会被 member 色误命中。概率低（service_name 通常取 `blog`/`shop` 这类短名，Python module 是全限定路径），文档说明 + 测试锁定现状即可。spec Edge Cases 已声明。

**Alternatives**：
- *module_color 改精确匹配*：破坏 federation，另开特性。**拒绝**。
- *给 member cluster 换独立 id 前缀*（如 `member_blog`）：cluster id 可换但 module 键仍参与前缀匹配，治标不治本。**拒绝**。

## Unknown 4：单体 ErManager 设 color 的语义

**Decision**：`ErManager(color=...)` 在单体场景**存而不消费**——不产生任何可视化变化（FR-008/SC-004 要求单体输出与改动前逐字一致）。文档明确 color 仅在 Composed 场景经 `_member_styling` 被消费。

**Rationale**：单体本身即单一分组，配色无信息量；避免"单体也画一个自己的 cluster"这种无意义变化。

**Alternatives**：
- *单体也给自己包一个 cluster*：改变所有存量用户的图布局，breaking。**拒绝**。

## Unknown 5：UseCase 页的数据通路

**Decision**：`VoyagerContext._get_voyager()`（`voyager_context.py:53-70`）在既有 `fed_registry` 透传旁增加 `member_styling` 透传；`UseCaseVoyager.__init__` 加 `member_styling: dict | None = None` 参数。

**Rationale**：与 fed_registry 的传递路径完全对称（`_get_voyager` 里 `getattr(er_manager, ...)` 探测 → config 透传），消费面改动最小。Route 节点不参与（`use_case_voyager.py:129` route 的 module 保持 `serviceCls.__module__`，spec 假设已声明）。

**Alternatives**：
- *UseCaseVoyager 直接持有 er_manager*：耦合反转（它现在只收 fed_registry），且非 composed 场景会被迫传入 None er_manager。**拒绝**。

## Unknown 6：fillcolor 的渲染细节

**Decision**：
- `cluster.j2` 增加 `{% if fill_color %}fillcolor = "{{ fill_color }}"{% endif %}`
- 有 cluster_color 时 `cluster_style` 输出 `rounded,filled`（远端 federation 保持 `rounded,dashed,filled`——dashed 与 filled 可共存）
- `DiagramRenderer._render_module_schema` 把 `cluster_color` 同时作为 `pen_color` 与新参数 `fill_color` 传入

**Rationale**：graphviz 语义 `style="filled"` + `fillcolor` 是 cluster 背景的标准做法；节点是 HTML-like table 自带底色，不会被 cluster 填充遮挡。federation 的既有 `pencolor` 路径自动获得填充能力（对齐"复用 federation 机制"的决策——federation 颜色也从边框升级为边框+背景，视觉一致性更好）。

**Alternatives**：
- *仅 member 用填充、federation 保持纯边框*：两套视觉规则，用户需记两件事。**拒绝**（统一）。

---

## 结论

无未解决 unknown。全部决策可直接进 Phase 1。
