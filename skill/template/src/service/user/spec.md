# UserService

## 目的

用户管理服务，提供用户列表与创建能力，作为 task / sprint 服务的依赖方（`TaskSummary.owner` 引用 `UserSummary`）。

## 用途

- 列出所有用户
- 创建新用户

## 方法需求

| 方法 | 说明 | 返回 |
|------|------|------|
| `list_users` | 获取全部用户 | `list[UserSummary]` |
| `create_user` | 创建用户 | `UserSummary` |

## DTO

- `UserSummary` — `id`, `name`（User 实体的最小投影；作为单一来源被 task / sprint 服务复用，演示 nexusx 的 DTO 按需投影与跨 service 复用模式）

## 调用链

```
UserService.list_users / create_user
    ↓ 委托
service/user/methods.py:list_users / create_user
    ↓ 操作
src.db.async_session → User 表
    ↓ DTO 转换
UserSummary.model_validate(user) → Resolver().resolve(dtoList)
```

service.py 不直接操作数据库，所有 DB 访问通过 methods.py。

## 变更记录

| 阶段 | 变更 |
|------|------|
| Phase 2 | methods.py 实现 `list_users`, `create_user` |
| Phase 3 | 初始创建 UserService；UserSummary DTO 沉淀到 `user/dtos.py` 作为单一来源 |
