# Data Model: 联邦分页(Federation Pagination)

关联:[spec.md](./spec.md)、[plan.md](./plan.md)、[research.md](./research.md)、[contracts/](./contracts/)。

## 概览

本特性**不新增持久化实体**——分页是无状态的取数协议,数据仍在各服务自有库。本文的"数据模型"指**协议形状与内存结构**:声明字段、wire 包、member root 契约、复用的既有类型。无迁移、无状态机。

## 1. 声明层

### RemoteRelationship(扩展,012 既有)

新增可选字段 `sort_field`(分页开关 + 排序字段):

| 字段 | 类型 | 默认 | 语义 |
|---|---|---|---|
| `sort_field` | `str \| None` | `None` | 声明→该 to-many 关系分页(按此字段 + 方向排序);`None`→全量(012 行为) |

- 排序方向:随 `sort_field` 携带,默认 ASC(具体编码——字符串内嵌方向 or 独立参数——见 [contracts/paginated-remote-relationship.md](./contracts/paginated-remote-relationship.md),实现阶段定)。
- 约束:`sort_field` 仅对 to-many(`target=list[...]`)有效;to-one 声明→启动期 fail-fast(FR-002)。
- **不**新增 `default_page_size`/`max_page_size` 字段——复用本地固定默认(20/100),对齐本地(R3)。

## 2. wire 层

### per-key 分页包(member 分页 root 返回)

```
[
  { fk: <join_key值>, items: [Target, ...], pagination: { has_more: bool, total_count?: int } },
  ...
]
```

- 每个包对应一个输入 key;`fk` 为 join_remote 字段值,供挂载方对齐。
- `total_count` 仅客户端 selection 请求时存在(FR-005/R6);否则 member 不算 COUNT,包里只有 `has_more`。
- `items` 是目标实体列表,其子树由 member executor 递归解析(FR-007/R4)。

### 挂载方对齐结果(per parent)

```
{ items: [Target, ...], pagination: { has_more: bool, total_count?: int } }
```

挂载方按 join key 把 per-key 包对齐到各 parent(FR-006);缺失 key → `{items:[], pagination:{has_more:false, total_count:0}}`。

## 3. member 端 root 契约

### by_<key>_in_page(默认生成,零配置)

- 签名:`by_<join>_in_page(<join>_list: [...], limit: int, offset: int, sort_field: String)`(FR-004)。
- 每个 batch key 默认同时生成 `by_<key>_in`(全量,012 既有)与 `by_<key>_in_page`(分页)两个 root(FR-003)。
- 实现:窗口函数 `PARTITION BY <join> ORDER BY <sort_field> <dir>` + peek-by-1 判 `has_more` + 可选 `COUNT(*) OVER` 算 `total_count`(FR-008)。

### BatchRoot(contract 扩展)

`BatchRoot`(012 既有)新增字段,供 ER 内省暴露给挂载方:

| 字段 | 类型 | 默认 | 语义 |
|---|---|---|---|
| `paginated` | `bool` | `False` | 标记分页 root |
| `sort_field` | `str \| None` | `None` | 默认排序字段(member ORDER BY 兜底) |

## 4. 复用的既有类型(零改动或最小改动)

- **`PageArgs`**(`loader/pagination.py`):`(limit, offset, default_page_size=20, max_page_size=100)`——直接复用。
- **`Pagination`**(`loader/pagination.py`):`{has_more, total_count?}`——直接复用。
- **`RelationshipInfo`**(`loader/registry.py`):复用既有 `page_loader`/`sort_field` 字段语义;远程分页关系把分页 RemoteLoader 挂到 `page_loader`,`sort_field` 取自 `RemoteRelationship.sort_field`。
- **窗口函数 SQL 模式**(`loader/factories.py::create_page_one_to_many_loader` 的 `ROW_NUMBER() OVER (PARTITION BY ...)` + `COUNT(*) OVER`):member 分页 root 复用此模式。

## 5. 状态/生命周期

- 分页无状态机:声明在类定义期 → `federate()` 启动期校验 + wiring(挂分页 RemoteLoader)→ 运行期按客户端 `limit`/`offset` 取数。
- 不涉及持久化、无迁移、无热感知(被挂服务变更排序字段需重启入口服务重新 init,同 012)。
