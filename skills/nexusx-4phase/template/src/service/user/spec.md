# UserService

## 服务目的

用户管理服务，提供用户查询与创建能力。

## 用途

- 列出全部用户
- 创建用户并返回公开 DTO

## 方法需求

| 方法 | 说明 | 返回 |
|------|------|------|
| `list_users` | 获取全部用户 | `list[UserSummary]` |
| `create_user` | 按名称创建用户 | `UserSummary` |

## DTO

- `UserSummary` — id, name

## 变更记录

| 阶段 | 变更内容 |
|------|----------|
| Phase 3 | 初始创建，实现 list_users 和 create_user |
