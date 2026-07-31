# TODO

## Federation Pagination Review

记录日期：2026-07-31。

### P1

- [x] 修复 DESC 分页结果错误。
  - order profile 统一生成 window 与 outer query 的方向/null ordering 表达式。
  - `HIGHEST_RATING` e2e 和重复值 PK tie-breaker 测试已覆盖。

- [x] 修复同一实体多个分页 key 的 package schema 冲突。
  - package 和 order enum 均按 entity + key 唯一命名。
  - SDL、ER capability 测试覆盖两个不同 key。

- [x] 分页 RemoteLoader 拒绝不完整或畸形响应。
  - response/data/type/root/package/join key/items/pagination 均严格校验。
  - malformed response 抛 `RemoteQueryError`；仅合法响应缺 key 映射为空页。

### P2

- [x] 启动期校验 member 分页能力。
  - `BatchRoot.page` 暴露 `offset-v1`、default order 和 semantic profiles。
  - mounter 校验 root、protocol、default/profile，并始终解析出显式 order。

- [x] 修复分页 root 的 GraphQL selection 序列化。
  - `items`、`pagination` 和 join key 仅在客户端选择时返回。
  - key-only 直接 root 查询已覆盖。

- [x] 删除不受约束的 `sort_direction` wire。
  - direction 仅存在于 member 的 `OrderTerm`，只允许 `asc`/`desc`。
  - mounter 与业务客户端只能选择命名 order profile。

## Verification Notes

- `total_count` 仅在客户端选择时执行 COUNT，并覆盖 offset 越界场景。
- federation 子集：`97 passed`。
- member config/SQL 专项测试通过。
- 完整回归：`1346 passed, 6 skipped`。
- `uv run ruff check .` 通过。
