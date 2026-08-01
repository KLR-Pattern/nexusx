# Implementation Plan

## Architecture

### Member Configuration

- 新增 `OrderTerm`、`PageOrder`、`BatchPageConfig`。
- `AutoQueryConfig.batch_pages[Entity][key]` 是分页能力的唯一来源。
- `add_standard_queries()` 在应用初始化时完成配置规范化和全部 SQL column 校验。
- 每个 configured key 生成 `page_by_<key>_in`、独立 GraphQL order enum 和独立 `{Entity}{Key}PagePackage`。

### Member Execution

- order profile 在 root 内解析为固定 SQLAlchemy order expressions。
- `ROW_NUMBER() OVER (PARTITION BY key ORDER BY ...)` 与 outer query 复用同一规范化 term 列表。
- 主键作为缺省 tie-breaker 追加。
- `limit+1` 判断 `has_more`；仅 selection 包含 `total_count` 时加入 window COUNT 和 offset-overflow count query。

### Federation Contract

- `BatchRoot.page` 替代 `BatchRoot.paginated`。
- `BatchPageCapability` 暴露 `protocol="offset-v1"`、`default_order`、`orders`。
- `RemoteRelationship.pagination` 决定关系 schema 是否分页；`order` 只静态选择 capability 中的 profile。

### Mounter and Loader

- 初始化时找到 `page_by_<key>_in`，验证 protocol、参数类型和 order。
- 无显式 order 时解析 member default；loader 中始终保存并发送显式 order。
- paginated loader 严格验证 GraphQL response 的每一层、package、join key、items 和 pagination。

## Work Order

1. 更新 spec 与契约。
2. 增加配置模型和启动校验测试。
3. 重写 member root SQL、命名和 package schema。
4. 更新 ER contract/introspection。
5. 更新 `RemoteRelationship`、mounter、loader 和 executor routing。
6. 迁移 SDL/introspection、测试、demo、文档。
7. 运行 targeted tests、Ruff 和完整 pytest。

## Compatibility

全量 `by_<key>_in` 不变。旧 federation pagination API 未发布，直接移除；不保留 root alias、参数 alias 或 deprecation path。
