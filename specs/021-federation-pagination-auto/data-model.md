# Data Model: 联邦分页自动化

## RemoteRelationship（改动：去 pagination）

```python
# 旧（020 及之前）
RemoteRelationship(fk=..., target=..., name=..., join_remote=..., pagination=True/False)
# 新（021：去 pagination 参数）
RemoteRelationship(fk=..., target=..., name=..., join_remote=...)
```

联邦分页不再由 mounter 声明，而是由 member 的 `__pagination_orders__`（→ `page_by_` 自动暴露）+ 查询参数（limit）决定。

## federation manager 改动点

| 文件 | 改动 |
|---|---|
| `federation/manager.py` `_validate_and_wire_remote_relationship` | `pagination` 来源从 `rrel.pagination` → 探测 member fragment 的 `page_by_<join_remote>_in` 存在 |
| `federation/manager.py` `_check_target` | `pagination` 参数语义：True/False 由 page_by_ 存在决定（而非 rrel.pagination） |
| `federation/remote_loader.py` | loader wire 跟随（有 page_by_ → paged + full；无 → plain） |
| `utils/pagination_schema.py` `is_active_paginated_relationship` | REMOTE_PAGED 判定从 rrel.pagination → member 暴露 page_by_（loader 有 page_by_） |
| `sdl_generator.py` / `introspection.py` | 跟随 is_active（Result 渲染：member 有 page_by_ → Result） |

## 联邦分页行为（自动）

| member 侧（被拉） | mounter schema | 查询 |
|---|---|---|
| 有 `__pagination_orders__`（暴露 page_by_） | `Result{items, pagination}`（limit 可选） | `rel(limit:N) { items pagination }` 或 `rel { items }`（全量） |
| 无（只 by_） | `list` | `rel { ... }` |
| to-one（target 非 list） | 单对象（不分页） | `rel { ... }` |

## 不变项

- `__federation_keys__`（member 入口，020）
- `__pagination_orders__`（member 单一排序，020）
- `enable_pagination`（本地关系分页，member/mounter 对称，各管本地）
- `RemoteRelationship` 的 `fk`/`target`/`name`/`join_remote`（联邦边核心声明）
- to-one 关系（从不分页，by_id_in）
