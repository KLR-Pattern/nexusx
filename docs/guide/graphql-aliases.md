# GraphQL 别名（Alias）支持

自 specs/023 起，nexusx 的两条 GraphQL 查询路径（UseCase compose 与 entity-first）均支持**方法级字段别名**：一次请求中对同一个方法发起多次调用、各自携带参数，响应按别名分组。

## 快速示例

```graphql
query { TaskService {
  high: list_tasks(priority: "high") { id title }
  low:  list_tasks(priority: "low")  { id }
} }
```

两个别名是两次独立调用：`data.TaskService.high` 与 `data.TaskService.low` 各自携带对应参数的结果，子字段投影也各自独立。

批量写同样支持（串行、按声明顺序）：

```graphql
mutation { MindmapService {
  n1: add_node(content: "one")   { display_id }
  n2: add_node(content: "two")   { display_id }
  n3: add_node(content: "three") { display_id }
} }
```

## 行为要点

| 场景 | 行为 |
|---|---|
| query 同方法不同参数 | 各自独立执行，响应键 = 别名 |
| query 某别名失败 | 该别名键为 `null` + `QUERY_FAILED`（携带 `extensions.service_method` 定位失败方法），其余别名不受影响 |
| query/mutation 同方法同参数 | 仍逐个执行，**不做方法级去重**；联邦场景下同选择同参数命中加载器缓存，同一节点只发一次 member 请求 |
| mutation 部分失败 | 已成功的结果保留；失败键为 `null` + `MUTATION_FAILED`（entity-first 为 `RESOLVER_ERROR`）；其后按 fail-stop 跳过并标 `SKIPPED_PRIOR_FAILURE` |
| mutation 失败的 fail-stop 范围 | **operation 级**：跨 entity group / service 组传播——后续组的 mutation 一律跳过（对齐 GraphQL 串行语义）；query 不受影响 |
| 响应键冲突（别名重复 / 别名撞字段名 / 无别名同名字段重复） | 报 `ALIAS_CONFLICT` 错误，不执行任何方法；**不做字段合并** |
| 嵌套字段级别名（返回值内部字段改名） | 明确报错（范围外） |
| 联邦远程关系字段层别名 | 明确报错（设计排除） |
| CLI `--select` 投影内的别名 | 明确报错 |

完整行为矩阵见 [specs/023-gql-alias-support/contracts/graphql-alias-behavior.md](../specs/023-gql-alias-support/contracts/graphql-alias-behavior.md)。

## 联邦边界：别名到 mounter 为止

mounter 发往 member 的机造查询**永不含别名**——别名在 mounter 层被消化，member 端零改动、零别名负担。

## 错误响应结构

失败或被跳过的别名在 `data` 中对应键为 `null`，`errors` 条目携带 `path`（**响应键**，即别名——与 `data` 的键一致，按 GraphQL 规范可定位）与 `extensions.code`：

```json
{
  "data": { "MindmapService": { "n1": { "display_id": 1 }, "n2": null, "n3": null } },
  "errors": [
    { "message": "...", "path": ["MindmapService", "n2"], "extensions": { "code": "MUTATION_FAILED", "service_method": "MindmapService.add_node" } },
    { "message": "Skipped 'n3' because a prior mutation failed", "path": ["MindmapService", "n3"], "extensions": { "code": "SKIPPED_PRIOR_FAILURE" } }
  ]
}
```

compose 路径 query 失败的码为 `QUERY_FAILED`（同样携带 `service_method`）；entity-first 路径方法异常的码为 `RESOLVER_ERROR`。

## 迁移说明（自 6.1.x 升级）

- 同名字段不再"后者覆盖前者"——此前被静默丢弃的重复选择现在会得到明确错误
- compose 路径中，某个 query 方法的失败不再作废整个响应：失败方法自己的键为 `null` + `QUERY_FAILED`，其余方法结果保留
- entity-first 路径中，一个方法的异常不再作废整个实体分组：失败方法自己的键为 `null`，兄弟结果保留
- mutation 失败后的跳过范围是整个 operation（跨组传播），而非仅当前分组
- `QueryParser.validate_no_aliases()` 保留原语义，但 nexusx 内部不再调用——需要禁用别名的自定义防线可继续使用
