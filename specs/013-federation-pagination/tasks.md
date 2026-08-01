# Tasks

- [x] 确认 sorting ownership、静态 order selection、root naming 和 ER capability。
- [x] 实现 `OrderTerm`、`PageOrder`、`BatchPageConfig` 并导出公共 API。
- [x] 实现 profile 名、字段、方向、nullable、default 和 tie-breaker 校验。
- [x] 仅按 `batch_pages` 生成 `page_by_<key>_in`。
- [x] 修复 DESC/outer ordering，并支持多 term/null ordering。
- [x] 为每个 entity+key 生成唯一 package type 和 order enum。
- [x] 用 `BatchRoot.page` 暴露 semantic capability。
- [x] 用 `RemoteRelationship.pagination/order` 替代 `sort_field/sort_direction`。
- [x] mounter 校验 protocol/root/profile，并解析 member default。
- [x] loader 发送 enum order 并严格校验 response。
- [x] 迁移 SDL/introspection/executor/tests/demo/docs。
- [x] 保留 selection-aware `total_count` 优化。
- [x] Ruff、targeted pytest、full pytest。
