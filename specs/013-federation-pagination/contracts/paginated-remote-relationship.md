# Contract: RemoteRelationship Pagination

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

- `pagination=False` 保持原全量 list 行为。
- `pagination=True` 将业务 GraphQL field 渲染为 `{items, pagination}`，仅允许 to-many。
- `order=None` 使用 member capability 的 `default_order`。
- `order="<PROFILE>"` 必须匹配 member capability 中的 profile，否则 mounter 启动失败。
- `order` 是部署配置，不出现在业务 GraphQL field arguments 中。
- declaration 不包含物理 field、direction 或 null ordering。
