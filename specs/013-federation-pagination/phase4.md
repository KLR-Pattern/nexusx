# Phase 4: Public Surface and Delivery

## 需求说明

迁移 demo/docs/tests，移除旧 API，并完成全量回归。

## 验收标准

| # | 验收项 | 验证方式 |
|---|---|---|
| 1 | docs/demo 使用新 API | repository search |
| 2 | 旧 root/参数无残留 | `rg` |
| 3 | Ruff 通过 | `ruff check` |
| 4 | targeted 和 full pytest 通过 | pytest |
| 5 | 所有 spec phase 文件非空且已回填 | `wc -l` |

## 实现描述

demo、英文/中文 federation 文档和测试已迁移到新 API。旧 root 和
`RemoteRelationship.sort_field/sort_direction` 已从 federation 实现删除；本地
relationship pagination 的同名内部字段保持不变。

- [x] docs/demo 使用新 API。
- [x] 旧 federation root/参数无代码残留。
- [x] `uv run ruff check .` 通过。
- [x] `uv run pytest -q`：`1346 passed, 6 skipped`。
- [x] 所有 story/phase/contract spec 文件非空。
