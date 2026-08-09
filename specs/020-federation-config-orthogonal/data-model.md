# Data Model: Federation 配置正交化

核心数据 = entity 上的两个 dunder + 复用的 BatchPageConfig + 退化的 AutoQueryConfig / SubsetConfig。

## `__federation_keys__`（新增，entity 级）

- **形态**：`__federation_keys__: list[str]` —— 字段名列表，如 `["product_id"]`
- **语义**：标记这些字段是联邦批量入口（**纯标记，不携带 order**）
- **消费方**：
  1. GraphQLHandler / ErManager 初始化扫描收集
  2. AutoQueryConfig 读它生成 `by_<key>_in` / `page_by_<key>_in` 根
  3. `__pagination_orders__` 路由用它判断维度是对内还是对外

## `__pagination_orders__`（已存在，语义扩展）

- **形态**：`__pagination_orders__: dict[str, BatchPageConfig]` —— 维度名 → order profile
- **语义（扩展）**：维度 key 既可是**本地关系名**（对内分页），也可是 **federation key 字段名**（对外分页）。不再区分。
- **路由规则**：维度在 `__federation_keys__` → 联邦批量维度；不在 → 本地关系维度

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
entity (Review)
├── __federation_keys__ = ["product_id"]        ← 标记 + 路由信号
└── __pagination_orders__ = {                    ← 统一 order profile
      "comments": BatchPageConfig(...),           本地关系维度（不在 federation_keys）
      "product_id": BatchPageConfig(...),         联邦字段维度（在 federation_keys）
    }

框架读取：
- __federation_keys__ 每个 key
    → 有 order profile (在 __pagination_orders__) → 生成 page_by_<key>_in
    → 无 order profile                            → 生成 by_<key>_in
- __pagination_orders__ 每个维度
    → 在 __federation_keys__ → 给联邦批量根
    → 不在                      → 给本地 loader
```
