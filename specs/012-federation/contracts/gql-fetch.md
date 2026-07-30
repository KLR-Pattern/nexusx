# 契约:gql 嵌套取数(RemoteLoader ↔ /graphql)

**特性**:`specs/012-federation` | 对应 FR-010/FR-011/R5/R8

这是**取数契约**:挂载方的 `RemoteLoader` 如何向被挂服务取多级嵌套数据。复用被挂服务既有的 `graphql_query` 面(`GraphQLHandler.execute`),零自创协议。

## 传输

标准 GraphQL-over-HTTP:

```
POST <被挂服务>/graphql
Content-Type: application/json

{ "query": "<gql 文档>", "variables": { ... } }
```

响应:`{ "data": {...}, "errors": [...] }`(标准 GraphQL 响应)。

## RemoteLoader 构造的 gql 文档

从 executor 注入的 `FieldSelection` 嵌套子树 + 收集到的 join key 构造,**以 `by_<join_remote>_in` 为入口**:

```graphql
query {
  Review {
    by_product_id_in(product_id_list: [1, 2, 3]) {     # 入口 = 批量 root,携带本层全部 join key
      id
      product_id                                        # 标量 + join key(供对齐)
      title
      rating
      author {                                          # 嵌套远程子选区:被挂服务自己解析
        id
        name
      }
    }
  }
}
```

- 入口字段名 = `by_<join_remote>_in`(见 [batch-query-root.md](./batch-query-root.md))。
- 参数名 = `<join_remote>_list`,值为本层父实体的 `fk` 去重集合。
- 选区 = `FieldSelection` 子树(标量 + 嵌套关系);**嵌套关系由被挂服务用自己的 executor 解析**(含其自身挂载的下游)。

## 响应对齐(DataLoader 位置契约)

`batch_load_fn(keys)` 必须**按 `keys` 顺序**返回对齐结果。RemoteLoader:

1. 解析 `data["Review"]["by_product_id_in"]` → 行列表。
2. 按 `product_id`(join_remote 字段)分组。
3. 按 `keys` 顺序映射:每个 key → 其对应行集合(`is_list=True` → `list[行]`;`is_list=False` → 单行或 `None`)。
4. 行反序列化进**物化远程类型**实例(`FederatedTypeRegistry` 提供)。
5. 缺失 key → `[]`(to-many)或 `None`(to-one)。

## 不变量

- **每被挂服务每 `batch_load_fn` 恰好一条 gql 查询**(SC-003)。DataLoader 天然合并同帧多次 `load`。
- 被挂服务**用自己的 executor 解析整条嵌套子图**(其 N+1-proof 批量身份);挂载方只在服务边界拼接,不在单服务内部逐层 fetch(FR-010)。
- 嵌套子图里的更深服务(如 reviews 内部解析 `author` 时调 users)由被挂服务自己编排——挂载方不感知。
- transport(httpx)可注入,便于测试用 `ASGITransport` in-process(见 [quickstart.md](../quickstart.md))。

## 错误处理

- HTTP 非 2xx / 超时 → 该 `batch_load_fn` 抛出,executor 按现有 per-field 异常路径上报(`{message, path}`,GraphQL-spec 合规)。
- 响应含 `errors` → 同上。
- 缺失 key 静默映射为 `None`/`[]`(数据缺失非错误)。

## 相关
- [batch-query-root.md](./batch-query-root.md):入口 root 的生成。
- [er-introspection.md](./er-introspection.md):`join_remote` 字段存在性校验依赖。
- spec FR-010/FR-011;plan `federation/remote_loader.py`、`federation/http.py`;data-model.md §5。
