# 契约:分页 gql 取数(分页 RemoteLoader ↔ /graphql)

**特性**:`specs/013-federation-pagination` | 对应 FR-006/FR-009/FR-010/FR-011,研究 [research.md R4/R5/R7](../research.md)

这是**取数契约**:挂载方的分页 RemoteLoader 如何向被挂服务取分页 + 嵌套子树。复用 012 的传输(GraphQL-over-HTTP + member 自解析子图),入口从 `by_<key>_in` 改为 `by_<key>_in_page`。

## 传输

沿用 012:标准 GraphQL-over-HTTP(`POST <被挂服务>/graphql`,`{query, variables}` → `{data, errors}`);transport 可注入,测试用 `httpx ASGITransport` in-process。

## 分页 RemoteLoader 构造的 gql 文档

从 executor 注入的 `FieldSelection`(含客户端 `limit`/`offset` args)+ `RemoteRelationship.sort_field` + 收集到的 join key 构造,**以 `by_<join_remote>_in_page` 为入口**:

```graphql
query {
  Review {
    by_product_id_in_page(
      product_id_list: [1, 2, 3],     # 本层全部 join key
      limit: 5,                        # batch 级标量,来自客户端 args
      offset: 0,
      sort_field: "created_at"         # 挂载方声明的 sort_field(含方向)
    ) {
      product_id                       # join key(供对齐)
      items {                          # 分页后的 reviews
        id
        title
        rating
        comments { text }              # items 子树:被挂服务自解析
      }
      pagination { has_more total_count }   # total_count 仅客户端 select 时算
    }
  }
}
```

- 入口 = `by_<join_remote>_in_page`(见 [paginated-batch-root.md](./paginated-batch-root.md))。
- `limit`/`offset` 来自客户端 gql args;`sort_field` 来自挂载方 `RemoteRelationship.sort_field` 声明(FR-010)。
- `items` 内的嵌套子树(本地关系 + 更深跨服务 hop)由 member 用自己 executor 解析(FR-007/R4),挂载方不感知。

## 响应对齐(按 join key,不依赖顺序)

`batch_load_fn(keys)` 按 join key 把 per-key 分页包对齐到各 parent:

1. 解析 `data["Review"]["by_product_id_in_page"]` → per-key 包列表。
2. 按 `product_id`(包内的 fk 字段)建桶。
3. 对每个输入 key(经 `_normalize_join_key` 处理 UUID/Decimal 字符串化),取其桶 → `{items:[Target...], pagination}`。
4. `items` 里的实体反序列化进物化远程类型;子树已由 member 解析成型。
5. 缺失 key → `{items:[], pagination:{has_more:false, total_count:0}}`。

## 不变量

- **每被挂服务每 `batch_load_fn` 恰好一条 gql**(SC-002),沿用 012 的 DataLoader 合并。
- **按 join key 对齐,不依赖返回顺序**(R7)——规避 Apollo 列为头号风险的"顺序错配=静默数据错";UUID/Decimal 沿用 012 `_normalize_join_key`。
- member **自解析 items 子树**(FR-011),保住"每服务一次批量";挂载方只在服务边界拼接。
- `total_count` 仅客户端 selection 请求时出现在响应(R6)。

## 错误处理

沿用 012:HTTP 非 2xx / 超时 / 响应含 `errors` → 该 `batch_load_fn` 抛出,executor 按 per-field 异常路径上报(`{message, path}`,GraphQL-spec 合规);缺失 key 静默映射为空分页包(数据缺失非错误)。

## 相关

- [paginated-batch-root.md](./paginated-batch-root.md):入口 root。
- [paginated-remote-relationship.md](./paginated-remote-relationship.md):`sort_field` 声明来源。
- spec FR-006/FR-009/FR-010/FR-011;research.md R4/R5/R7;[data-model.md §2](../data-model.md)。
