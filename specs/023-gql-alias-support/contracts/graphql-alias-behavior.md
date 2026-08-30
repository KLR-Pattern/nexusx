# Contract: GraphQL Alias 行为矩阵（specs/023）

对外行为契约——两条查询路径（compose / entity-first）统一适用。错误结构见 [data-model.md §2](../data-model.md)。

## 行为矩阵

| # | 场景 | 行为 | 依据 |
|---|---|---|---|
| 1 | query 方法级别名，同方法不同参数（`high: list(p: 高)` + `low: list(p: 低)`） | 两次独立执行（参数各自正确），响应键 = 别名，各别名按自己声明的子字段投影 | FR-002/003 |
| 2 | query 方法级别名，同方法同参数 | 仍逐个独立调用（**不做方法级结果去重**）；联邦场景同 selection 同参数命中同一加载器 key 缓存，同一节点对 member 只发一次请求 | FR-011 |
| 3 | mutation 方法级别名 ×N | 按声明顺序串行**全部执行**（N 个别名 = N 次副作用，禁止执行级去重），响应键 = 别名 | FR-004/011 |
| 4 | mutation 第 k 个失败 | 前 k-1 个已成功结果保留；第 k 个键为 null + `MUTATION_FAILED`；其后全部 null + `SKIPPED_PRIOR_FAILURE`（fail-stop） | FR-005/006 |
| 5 | query 某别名失败 | 该别名 null + 错误条目，其余别名不受影响（无 fail-stop） | US2 场景 3 |
| 6 | 同层响应键重复（别名重复 / 别名撞字段名 / 无别名同名字段重复） | 报错 `ALIAS_CONFLICT`，不执行任何方法；**不做字段合并** | FR-007 |
| 7 | 顶层 entity group / service 名重复 | 同 #6，报错 | FR-007 |
| 8 | 嵌套字段级别名（返回值内部字段改名，如 `t1: title`） | 报错"不支持"（本期范围外，明确报错非静默） | FR-009 |
| 9 | 联邦远程关系字段层别名（β 嵌套远程字段） | 报错"不支持"（**设计排除项**，非待办） | FR-009 |
| 10 | CLI `--select` 投影语法内的别名 | 报错"不支持" | FR-009 |
| 11 | `enable_mutation=False` 收到别名 mutation | 与单次 mutation 一致地被拒绝（能力开关与调用次数正交） | FR-004 |
| 12 | mounter 发往 member 的机造查询 | **永不含别名**（member 零改动） | FR-008 |

## 阶段交付语义（渐进放宽）

| 阶段 | 行为变化 |
|---|---|
| A（止血） | compose 入口对**一切**别名报错"不支持"（此时 #1-#5 尚未实现，先保证不静默） |
| B1a | #1、#2、#5-#10、#12 生效（query 侧 + 全部报错路径 + 联邦闸门）；mutation 别名仍按 A 报错 |
| B1b | #3、#4、#11 生效（mutation 侧） |

## 公共 API 兼容

- `FieldSelection.sub_fields`：类型签名不变（`dict[str, FieldSelection]`），key 含义变更为响应键——changelog 显著说明，minor 6.2.0
- `QueryParser.validate_no_aliases()`：**保留原语义**（检测并拒绝别名），供外部自定义防线使用；库内调用移除
- entity-first mutation 异常响应：从「整组 null」变为「逐字段三态」——行为改进，changelog 说明
