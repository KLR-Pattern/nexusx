# Feature Specification: Federation Pagination

**Branch**: `feat/federation-pagination`
**Status**: Confirmed
**Updated**: 2026-07-31

## Goal

为 federation 的远程 to-many relationship 提供 member-side offset pagination，同时保持每个被挂服务一次批量 GraphQL 请求。物理排序规则必须由数据所属 member 定义，mounter 只能静态选择 member 暴露的语义 order profile。

## Confirmed Design

1. `AutoQueryConfig.batch_keys` 继续生成全量 root `by_<key>_in`。
2. `AutoQueryConfig.batch_pages` 显式声明分页能力；只有其中配置的 key 才生成 `page_by_<key>_in`。
3. member 用 `BatchPageConfig.orders` 定义命名 order profile；每个 profile 由一个或多个 `OrderTerm` 组成。
4. `RemoteRelationship.order` 是可选的静态 profile 名；`None` 表示使用 member 的 `default_order`。
5. `order` 不暴露给业务 GraphQL 客户端。客户端只传 `limit`/`offset`。
6. federation wire 总是显式发送 `keys`、`limit`、`offset`、`order`。
7. ER introspection 只暴露语义能力：protocol、default order、profile 名和描述，不暴露字段、方向或 null ordering。
8. 旧的 `by_<key>_in_page(sort_field, sort_direction)` 尚未发布，直接删除，不提供兼容层。

## Public API

```python
AutoQueryConfig(
    batch_keys={"Review": ["product_id"]},
    batch_pages={
        "Review": {
            "product_id": BatchPageConfig(
                default_order="NEWEST",
                orders={
                    "NEWEST": PageOrder(
                        terms=[OrderTerm(field="created_at", direction="desc")]
                    ),
                    "HIGHEST_RATING": PageOrder(
                        terms=[
                            OrderTerm(field="rating", direction="desc"),
                            OrderTerm(field="created_at", direction="desc"),
                        ]
                    ),
                },
            )
        }
    },
)
```

```python
RemoteRelationship(
    fk="id",
    target=list[reviews.Review],
    name="reviews",
    join_remote="product_id",
    pagination=True,
    order="HIGHEST_RATING",
)
```

业务 schema：

```graphql
reviews(limit: 5, offset: 0) {
  items { title rating }
  pagination { has_more total_count }
}
```

内部 member root：

```graphql
page_by_product_id_in(
  product_id_list: [1, 2]
  limit: 5
  offset: 0
  order: HIGHEST_RATING
)
```

## Requirements

- `RemoteRelationship.pagination=True` 仅允许用于 to-many。
- member 启动时校验 order 字段属于 entity 且是普通 SQL column；首期拒绝 relationship、JSON、BLOB 和任意 SQL expression。
- direction 仅允许 `asc`/`desc`。
- nullable order 字段必须显式指定 `nulls="first"|"last"`。
- profile 必须非空；profile 名必须是唯一、GraphQL enum-safe 的大写名称。
- `default_order` 必须存在。
- 未包含的主键列按确定性方向追加为稳定 tie-breaker。
- window `ROW_NUMBER()` 与 outer query 必须使用完全相同的 order expressions，包括方向和 null ordering。
- 索引适配仅告警，不阻止启动。
- mounter 初始化时校验 `offset-v1` protocol、分页 root 参数契约和选中的 order profile。
- malformed paginated remote response 必须抛 `RemoteQueryError`，只有合法响应中缺失某个 input key 才映射为空页。
- 多个 batch page key 必须生成不同 package type。
- `total_count` 仅在客户端选择时计算。

## Acceptance

- ASC/DESC、多列排序、nullable null ordering、稳定 tie-breaker 的分页结果正确。
- offset 越界、空 key、最后一页、多个 parent、UUID join key 正确。
- Decimal join key 不支持：mounter 在 `federate()` 声明校验阶段拒绝（根因：member page_by 按 SQL 列值分桶，对 wire 字符串 key 存在类型不匹配）。
- 同一 remote service 每个 batch 只发一条 GraphQL 请求。
- `items` 子树继续由 member executor 递归解析。
- 未配置 pagination 的 remote relationship 保持原全量行为。
- 旧 root 和旧参数不再出现在 SDL、ER contract 或实现中。
