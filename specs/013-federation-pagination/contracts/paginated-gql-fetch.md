# Contract: Paginated Federation Fetch

Mounter 发送：

```graphql
query {
  Review {
    page_by_product_id_in(
      product_id_list: [1, 2]
      limit: 5
      offset: 0
      order: HIGHEST_RATING
    ) {
      product_id
      items { id title rating }
      pagination { has_more total_count }
    }
  }
}
```

约束：

- `order` 是 enum literal，不加引号。
- order 由 mounter 初始化时静态解析，业务客户端不能覆盖。
- 响应必须是标准 GraphQL object，且 `data.<Type>.<root>` 必须为 list。
- 每个 package 必须为 object，包含 join key、list-valued `items` 和 object-valued `pagination`。
- `pagination.has_more` 必须存在且为 bool；选择 `total_count` 时必须存在且为非负 int。
- malformed response 抛 `RemoteQueryError`。
- 合法响应中缺失某个 input key 才映射为空页。
- UUID join key 使用统一 wire normalization 对齐。
- Decimal join key 不支持（mounter 在 `federate()` 声明校验阶段拒绝）。
