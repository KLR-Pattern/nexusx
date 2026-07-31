# Phase 3: Federation Assembly

## 需求说明

实现 `RemoteRelationship.pagination/order`、mounter capability validation、paginated loader 和业务 schema 组装。

## 验收标准

| # | 验收项 | 验证方式 |
|---|---|---|
| 1 | default/explicit order 在启动时正确解析 | manager tests |
| 2 | protocol/root/profile 错配 fail-fast | declaration tests |
| 3 | wire 总是发送显式 enum order | loader tests |
| 4 | malformed response 不静默变空页 | loader tests |
| 5 | items nested subtree 与 per-key alignment 正确 | e2e tests |

## 实现描述

`RemoteRelationship.pagination/order` 已替代物理 sort 声明。mounter 同时验证
full/page roots、join 类型、protocol、default/profile，并解析显式 order。
paginated loader 发送 enum literal，严格校验所有响应层级。β path 走分页 loader，
γ path 保留全量 loader；transitive coalesced page package 可被物化和序列化。

- [x] default/explicit order 初始化解析正确。
- [x] capability 错配 fail-fast。
- [x] wire 总是发送显式 order。
- [x] malformed response 抛 `RemoteQueryError`。
- [x] nested items 与 join-key alignment 正确。
