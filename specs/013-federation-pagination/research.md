# Design Decisions

## Sorting Ownership

物理排序属于 member。只有 member 能可靠判断字段是否为真实 column、nullable 行为、主键稳定性和索引适配。把 `sort_field`/`sort_direction` 放在 `RemoteRelationship` 会泄漏存储细节，并允许多个 mounter 对同一数据定义互相冲突的排序。

## Static Order Selection

`RemoteRelationship.order` 静态选择命名 profile，不开放给业务客户端。这样 schema 行为稳定、mounter 可在启动时 fail-fast，并避免客户端探测或控制 member 的任意排序路径。需要新排序语义时，由 member 发布 profile，再由 mounter 配置选择。

## Explicit Member Capability

分页不再为每个 batch key 自动生成。`batch_pages` 是 member 对成本、排序和索引负责的显式能力声明。`batch_keys` 和 `batch_pages` 分离，使全量 batch lookup 不隐式承诺分页能力。

## Root Naming

采用 `page_by_<key>_in`。`page` 是操作类型，`by_<key>_in` 是筛选条件；比旧的后缀 `_in_page` 更接近“分页查询符合 key in keys 的记录”的语义，并避免把 `page` 误解为 `in` 条件的一部分。

## Capability Privacy

ER 只暴露 order profile 的名称和描述。物理字段、方向和 null placement 是 member 内部实现，允许 member 在不改变 federation contract 的情况下重构索引或列。

## Stable Ordering

offset pagination 必须有 total order。profile 未包含所有主键列时自动追加主键；window 和 outer ordering 共用同一组表达式，避免 DESC 或 null ordering 在外层被意外恢复为 ASC。
