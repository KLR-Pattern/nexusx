# Phase 0: Requirement Confirmation

## 需求说明

重构 federation pagination 的职责边界和 wire contract，不新增业务实体。

## 验收标准

| # | 验收项 | 状态 |
|---|---|---|
| 1 | 物理排序归 member | 已确认 |
| 2 | member 使用命名 order profile | 已确认 |
| 3 | mounter 静态选择 profile | 已确认 |
| 4 | order 不开放给客户端 | 已确认 |
| 5 | root 使用 `page_by_<key>_in` | 已确认 |
| 6 | ER 只暴露 semantic capability | 已确认 |
| 7 | 旧 API 直接删除 | 已确认 |

## 实现描述

Phase 0 已通过多轮讨论完成。该迭代不涉及 DB 选型、业务 service 切分或新实体。
