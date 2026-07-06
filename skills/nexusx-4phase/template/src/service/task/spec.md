# TaskService

## 目的

任务管理服务，提供任务的查询和筛选能力，支持自动加载负责人信息。

## 用途

- 列出所有任务（含负责人）
- 按 Sprint 筛选任务

## 需求

| 方法 | 说明 | 返回 |
|------|------|------|
| `list_tasks` | 获取全部任务，owner 通过 DataLoader 自动加载 | `list[TaskSummary]` |
| `get_tasks_by_sprint` | 按 sprint_id 筛选任务 | `list[TaskSummary]` |

## DTO

- `TaskSummary` — id, title, done, owner(UserSummary)
- `UserSummary` — id, name

## 变更记录

| 阶段 | 变更 |
|------|------|
| Phase 3 | 初始创建，实现 list_tasks 和 get_tasks_by_sprint |
