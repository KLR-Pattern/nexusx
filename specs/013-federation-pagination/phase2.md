# Phase 2: Member Loader

## 需求说明

实现 `page_by_<key>_in`、稳定多列排序、per-key pagination 和 selection-aware count。

## 验收标准

| # | 验收项 | 验证方式 |
|---|---|---|
| 1 | ASC/DESC 页顺序正确 | SQL integration tests |
| 2 | nullable null ordering 正确 | SQL integration tests |
| 3 | PK tie-breaker 保证稳定顺序 | duplicate-value test |
| 4 | window/outer order 一致 | result and SQL tests |
| 5 | 未选择 total_count 时无 COUNT | SQL listener test |

## 实现描述

已生成 `page_by_<key>_in`，profile 先规范化为固定 term 列表，缺失主键
自动按最后一个 term 的方向追加。window 和 outer query 从同一 term 列表生成
方向/null ordering。`limit+1` 计算 `has_more`，`total_count` 保持 selection-aware。

- [x] ASC/DESC 顺序正确。
- [x] nullable null ordering 正确。
- [x] 重复值由 PK tie-breaker 稳定排序。
- [x] window/outer order 一致。
- [x] 未选择 total_count 时 SQL 无 COUNT。
