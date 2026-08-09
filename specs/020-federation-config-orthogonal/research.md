# Research: Federation 配置正交化

spec 已经过 clarify（无 NEEDS CLARIFICATION）。本文档记录**实现层**的技术决策（spec 定了 WHAT，这里定 HOW 的关键选择）。

---

## 决策 1：`__federation_keys__` 怎么被框架识别/收集

- **选择**：entity 上的类级 dunder（`__federation_keys__ = ["product_id"]`），GraphQLHandler / ErManager 初始化时扫描 base 的所有 entity 子类，收集带 `__federation_keys__` 的 entity + 其字段。
- **理由**：和 `__pagination_orders__` 同模式（已有的 entity 级 dunder，`registry.py:145` 已在读它）。复用现有扫描机制，零新概念。
- **替代（否决）**：字段注解 `Annotated[int, FederationKey(...)]` —— 更细粒度但侵入每个字段定义，且扫描注解成本高、与 SQLModel Field 定义交错。

## 决策 2：`__pagination_orders__` 统一路由（FR-005）

- **选择**：框架读 `__pagination_orders__` 时，对每个维度 key，先查 `__federation_keys__`：在 `__federation_keys__` 里 → 联邦批量维度（生成 `page_by_<key>_in` / `by_<key>_in`）；不在 → 本地关系维度（走 loader 本地分页）。
- **理由**：`__federation_keys__` 一物两用 —— 既是外键标记（生成批量根），也是 order 维度的路由信号。不必为路由单独再加声明。
- **注意**：维度名冲突（关系名 == 字段名）按 `__federation_keys__` 优先识别为联邦维度（spec Edge Case 已定）。

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

## 决策 5：`by_<key>_in`（无分页）vs `page_by_<key>_in`（有分页）的区分

- **选择**：`__federation_keys__` 标记的字段，若在 `__pagination_orders__` **有** order profile → 生成 `page_by_<key>_in`（分页根）；**无** → 只生成 `by_<key>_in`（批量根，不分页）。
- **理由**：order profile 的有无自然区分两种根，替代旧 `batch_keys`（→by）vs `batch_pages`（→page）的二分声明。一个字段是否分页，由它有没有 order profile 决定，不再由两个不同配置项决定。

---

## 风险与回滚

- **风险**：federation 还嫩 + 这是个跨多模块的 breaking 重构（standard_queries / subset / loader.registry / federation/），改动面大。
- **缓解**：三层联邦 demo（catalog→reviews→users）作为端到端回归锚点（SC-004）；先迁 demo 验证声明模型跑通，再迁测试/文档。
- **回滚**：单分支 `020-federation-config-orthogonal`（或基于当前 fix/paged 分支再开），不合 master 前可整体回滚。
