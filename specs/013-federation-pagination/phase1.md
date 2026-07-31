# Phase 1: Schema and Contract

## 需求说明

定义 member pagination config、order profile 和 ER capability wire model。

## 验收标准

| # | 验收项 | 验证方式 |
|---|---|---|
| 1 | 公共 config 类型可导入 | import test |
| 2 | 非法 profile/column/direction/nulls/default 启动失败 | unit tests |
| 3 | ER 只暴露 semantic order | contract tests |
| 4 | 多 key package/enum 名唯一 | SDL/introspection tests |

## 实现描述

已实现 `OrderTerm`、`PageOrder`、`BatchPageConfig` 并从 `nexusx` 导出。
member 初始化会校验 profile 名、default、普通 SQL column、direction、
nullable null placement、JSON/BLOB 和任意 expression。ER 仅输出
`offset-v1`、default order、profile 名与描述。多 key 的 package/enum 名唯一。

- [x] 公共 config 类型可导入。
- [x] 非法配置启动失败。
- [x] ER 不泄漏物理排序。
- [x] 多 key schema 类型不冲突。
