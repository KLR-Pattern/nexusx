# Story: Federation Pagination

## Original Need

在 `feat/federation-pagination` 上评估并重构远程 relationship 分页。讨论确认：排序字段与方向应归 member schema 内部；mounter 只静态选择 member 定义的语义 order；order 不开放给业务客户端；旧分页 API 未发布，可直接替换。

## Overview Design

```text
Business query reviews(limit, offset)
  -> mounter relationship metadata resolves static order profile
  -> one GraphQL request to member page_by_<key>_in(keys, limit, offset, order)
  -> member resolves profile to validated SQL order expressions
  -> per-key window pagination + nested item subtree
  -> mounter aligns packages by join key
```

| Decision | Result |
|---|---|
| Sorting ownership | Member |
| Pagination capability | `AutoQueryConfig.batch_pages` |
| Mounter control | `RemoteRelationship.pagination/order` |
| Client control | `limit` and `offset` only |
| Protocol | `offset-v1` |
| Compatibility | Remove unreleased old pagination API |
