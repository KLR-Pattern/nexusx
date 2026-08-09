# Research: Federation 配置正交化

spec 已经过 clarify（无 NEEDS CLARIFICATION）。本文档记录**实现层**的技术决策（spec 定了 WHAT，这里定 HOW 的关键选择）。

---

## 决策 1：`__federation_keys__` 怎么被框架识别/收集

- **选择**：entity 上的类级 dunder（`__federation_keys__ = ["product_id"]`），GraphQLHandler / ErManager 初始化时扫描 base 的所有 entity 子类，收集带 `__federation_keys__` 的 entity + 其字段。
- **理由**：和 `__pagination_orders__` 同模式（已有的 entity 级 dunder，`registry.py:145` 已在读它）。复用现有扫描机制，零新概念。
- **替代（否决）**：字段注解 `Annotated[int, FederationKey(...)]` —— 更细粒度但侵入每个字段定义，且扫描注解成本高、与 SQLModel Field 定义交错。

## 决策 2：`__pagination_orders__` 单一 + 本地关系归 target（FR-004/005）

- **选择**：`__pagination_orders__` 是 entity 的**单一** BatchPageConfig（该 entity 自己的行怎么排序），不再按维度分 dict。排序归**被排序对象**：
  - 联邦批量分页（owner 被外部拉取）→ 读 owner 自己的 `__pagination_orders__`
  - 本地关系分页（Review.comments）→ 读 **target** 的 `__pagination_orders__`（Comment 的），不在 owner 配
- **理由**：排序与分桶维度（federation key）/关系归属**正交**。旧设计把 order 绑在 federation key 维度（dict[key]）+ 本地关系放 owner，导致：① 同一 entity 多 federation key 重复配同一排序；② Comment 被 N 个 owner 挂载时每个 owner 重复配 Comment 排序。单一 + 归 target 消除两者。
- **替代（否决）**：`dict[federation_key, cfg]` + 靠 federation_keys 路由本地/联邦 —— 把"按哪个字段进"和"怎么排"耦合，且本地关系归 owner 致重复。

## 决策 3：AutoQueryConfig 退化后的根生成

- **选择**：AutoQueryConfig 不再持有 `batch_keys` / `batch_pages`。根生成函数（`_create_by_keys_in_query` / `_create_page_by_keys_in_query`）改为接收**从 entity 扫描来的 federation keys + 对应 order profile**（order profile 从该 entity 的 `__pagination_orders__` 取）。
- **理由**：声明（entity）/ 生成（AutoQueryConfig 的 `_create_*` 函数）分离。AutoQueryConfig 退化为只持有 `default_limit` / `generate_by_id` / `generate_by_filter` 开关 + 触发根生成的执行者，回归本职。
- **调用点**：`add_standard_queries` / handler 初始化时，遍历 entity 的 `__federation_keys__`，对每个 key 调 `_create_*` 生成根。

## 决策 4：γ DTO join key 从源 entity 推导

- **选择**：DTO（DefineSubset）`federation_public=True` 时，join key 从其**源 entity**（`__subset__.kls`）的 `__federation_keys__` 推导。
  - 源 entity **单** federation key → DTO 自动用之，无需声明。
  - 源 entity **多** federation key → DTO 须显式选哪个（`SubsetConfig(federation_key="product_id")` 作**选择器**，引用 entity 已声明的 key 名，而非自己声明 key 值）。
- **理由**：join key 单一来源（entity）。`SubsetConfig.federation_join_key` 退化为「选择器」（多 key 时指名），默认（单 key）自动推导，不再承载 key 的语义声明。
- **开放（plan 阶段不阻塞）**：多 federation key 的 DTO 选择机制具体签名 —— 倾向 `federation_key: str | None`（选 entity 的哪个 key），默认 None=自动单 key。

## 决策 5：`by_<key>_in` vs `page_by_<key>_in` 由 entity 级 `__pagination_orders__` 决定

- **选择**：entity 声明了 `__pagination_orders__` → 其**每个** federation key 都额外生成 `page_by_<key>_in`（共用这一个 profile）；未声明 → 只 `by_<key>_in`。能否分页是 entity 的能力，不是某个字段的属性。
- **理由**：page_/by_ 从 per-key profile 有无 → entity 级一刀切，更直白。多 federation key 共用一个排序 profile（正交：federation key 只管入口，排序只管怎么排）。
- **替代（否决）**：per-key dict profile —— 同一 entity 多 federation key 要重复配同一排序。

---

## 风险与回滚

- **风险**：federation 还嫩 + 这是个跨多模块的 breaking 重构（standard_queries / subset / loader.registry / federation/），改动面大。
- **缓解**：三层联邦 demo（catalog→reviews→users）作为端到端回归锚点（SC-004）；先迁 demo 验证声明模型跑通，再迁测试/文档。
- **回滚**：单分支 `020-federation-config-orthogonal`（或基于当前 fix/paged 分支再开），不合 master 前可整体回滚。
