# Data Model: Federation 配置正交化

核心数据 = entity 上的两个 dunder + 复用的 BatchPageConfig + 退化的 AutoQueryConfig / SubsetConfig。

## `__federation_keys__`（新增，entity 级）

- **形态**：`__federation_keys__: list[str]` —— 字段名列表，如 `["product_id"]`
- **语义**：标记这些字段是联邦批量入口（**纯标记，不携带 order**）
- **消费方**：
  1. GraphQLHandler / ErManager 初始化扫描收集
  2. AutoQueryConfig 读它生成 `by_<key>_in` / `page_by_<key>_in` 根

## `__pagination_orders__`（已存在，语义扩展）

- **形态**：`__pagination_orders__: BatchPageConfig`（**单一**，该 entity 自己的行怎么排序）
- **语义（扩展）**：排序是被排序对象的单一属性，与 federation key（分桶维度）/关系归属正交。
  - 联邦批量分页（owner 自己被外部拉取）→ 读 owner 自己的 `__pagination_orders__`
  - 本地关系分页（如 Review.comments）→ 读 **target** entity 的 `__pagination_orders__`（Comment 的排序），不在 owner 配
- **不再有路由规则**：联邦读 owner、本地读 target，两者读不同 entity，天然不冲突。

## `BatchPageConfig`（已存在，不变）

- **形态**：`default_order: str` + `orders: dict[str, PageOrder]`（PageOrder = list[OrderTerm]）
- **语义**：一个维度的 order profile（默认排序 + 可选排序集）
- **复用**：本地关系维度 + 联邦批量维度共用同一格式（正交化的关键 —— order 格式统一）

## `AutoQueryConfig`（已存在，职责退化）

- **删除**：`batch_keys`、`batch_pages`
- **保留**：`default_limit`、`generate_by_id`、`generate_by_filter`、`enabled`
- **新职责**：读 entity 的 `__federation_keys__` + `__pagination_orders__`，调 `_create_by_keys_in_query` / `_create_page_by_keys_in_query` 生成根（声明/执行分离）

## `SubsetConfig`（DTO 层，退化）

- `federation_join_key` → 退化为 `federation_key`（**选择器**：源 entity 多 federation key 时选哪个；默认 None = 自动单 key）
- `federation_public` 保留（标记 DTO 为联邦公开）

## 关系图

```
entity (Review)                                  entity (Comment)
├── __federation_keys__ = ["product_id"]  ← 入口  └── __pagination_orders__ = BatchPageConfig(...)  ← Comment 自己的排序
└── __pagination_orders__ = BatchPageConfig(...) ← Review 自己的排序

两个轴正交，各读其主：
- 联邦批量分页：读 owner 自己（Review.__pagination_orders__）
    → entity 有 __pagination_orders__ → 每个 federation key 出 page_by_<key>_in
    → 无                              → 只 by_<key>_in
- 本地关系分页：读 target（Comment.__pagination_orders__），不在 owner 配
    → Comment 被 Review/Post/... 多 owner 挂载，排序只声明一次
```
