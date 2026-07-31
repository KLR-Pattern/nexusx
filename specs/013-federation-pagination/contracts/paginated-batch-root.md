# Contract: Member Paginated Batch Root

只有 `AutoQueryConfig.batch_pages[Entity][key]` 配置的 key 生成分页 root：

```graphql
page_by_product_id_in(
  product_id_list: [Int!]!
  limit: Int
  offset: Int! = 0
  order: ReviewProductIdPageOrder!
): [ReviewProductIdPagePackage!]!
```

规则：

- root 名固定为 `page_by_<key>_in`。
- key 参数名继续为 `<key>_list`；ER contract 暴露实际参数名和类型。
- order 是 member 生成的 GraphQL enum，不接受任意字符串或物理字段。
- mounter 始终显式传 order；直接 GraphQL 调用可使用 member default。
- 返回每个 input key 对应的 `{key, items, pagination}` package。
- package type 名包含 entity 和 key，避免多 batch key 冲突。
- `total_count` 未选择时不执行 COUNT。

ER capability：

```json
{
  "name": "page_by_product_id_in",
  "arg_name": "product_id_list",
  "arg_type": "list[int]",
  "page": {
    "protocol": "offset-v1",
    "default_order": "NEWEST",
    "orders": [
      {"name": "NEWEST", "description": "Newest first"},
      {"name": "HIGHEST_RATING", "description": null}
    ]
  }
}
```
