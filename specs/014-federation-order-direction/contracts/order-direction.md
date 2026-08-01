# Contract: Federation 分页 order/direction 参数

**特性**:`specs/014-federation-order-direction` | **日期**:2026-08-01

本文钉死 order/direction 开放后,federation 分页关系在「业务查询(mounter schema)」「member root」「ER introspection」三处的参数契约。建立在 013-federation-pagination 契约之上;只描述 014 增量。

---

## 1. 业务查询(mounter 对外 schema)

federation 分页关系字段(from mounter SDL / `__schema`):

```graphql
reviews(
  limit: Int
  offset: Int = 0
  order: <XxxOrder>          # enum,值 = member page_capability.orders 名集合
  direction: Direction       # enum: ASC | DESC(mounter 自有全局类型)
): <Target>Result!
```

约束:

- `order` enum 的**值集合** = member 暴露的 profile 名(单一数据源:`BatchPageCapability.orders`)。
- `order` 默认值 = member 的 `default_order`。
- `direction` 是 mounter 自有 enum(`ASC`|`DESC`),整个 schema 渲染一次,跨关系共用。
- `direction` 缺省 = profile 默认方向。
- SDL 与 `__schema` 内省两条路径暴露**一致**的参数(同源渲染)。

---

## 2. member root(`page_by_<key>_in`)

mounter RemoteLoader 发给 member 的内部 gql:

```graphql
page_by_<key>_in(
  <key>_list: [<keys>]
  order: <XxxOrder>          # member 自有 enum(013 既有)
  direction: Direction       # 新增: ASC | DESC
  limit: Int
  offset: Int
)
```

约束:

- `direction` 是**新增**参数,与 013 的 `order`/`limit`/`offset` 并列。
- `direction` 缺省 → 用 profile 的默认方向(向后兼容直连调用)。
- member 收到 `direction` 后:取 `order` profile 的 terms,按 `direction` 翻转(direction 覆盖 + nulls flip),翻转后 terms 同时用于 window 内层与 outer。
- 返回值形状不变(per-key `{fk, items, pagination}` packages,沿用 013)。

---

## 3. direction 翻转语义

```
profile 默认                  查询者传 direction=反方向
─────────────────────────────────────────────────────────
field desc, nulls_last   →   field asc,  nulls_first
field asc,  nulls_first  →   field desc, nulls_last
```

- 「翻转」= 完全相反:direction 覆盖 + nulls 同步翻转。
- 查询者传 direction = profile 默认方向时:不翻转,原样。
- window 内层 `ROW_NUMBER() OVER (PARTITION BY key ORDER BY <terms>)` 与 outer `ORDER BY <terms>` **必须用翻转后完全一致的 terms**(沿用 013 稳定排序约束,含 PK tie-breaker)。

---

## 4. ER introspection(不变)

`BatchPageCapability`(013 既有)已经是 mounter 渲染 `order` enum 的充分数据:

```text
BatchPageCapability:
  protocol: "offset-v1"
  default_order: str
  orders: list[PageOrderDescriptor(name, description)]
```

- 014 **不扩展**此结构(D7:`orders` 名集合已是单一数据源)。
- 物理列/方向/nulls 仍不暴露(索引控制权 member)。
- mounter federate 时校验 `orders` 非空(否则无法渲染 enum,fail-fast)。

---

## 5. 跨服务 enum 一致性

| 维度 | 一致性来源 |
|---|---|
| `order` enum 的**值** | 都源自 `BatchPageCapability.orders` 名集合(member→wire→mounter) |
| `order` enum 的**类型名** | mounter 自定(member 的 enum 名不外泄到 mounter schema;gql 传值不传名) |
| `direction` enum | mounter 自有(`ASC`\|`DESC`),不依赖 member |

**不变量**:mounter schema 的 `order` enum 值 ⊆ member `orders` 名集合(值层面一致即可,名各自定)。

---

## 6. 缺省与失败

| 情况 | 行为 |
|---|---|
| 查询者不传 `order` | mounter 用 `default_order` |
| 查询者不传 `direction` | member 用 profile 默认方向 |
| `order` 值不在 enum | GraphQL schema 层拒绝(不进 member) |
| `direction` 值不在 {ASC,DESC} | GraphQL schema 层拒绝 |
| member `orders` 为空 | federate 启动期 fail-fast(mounter 无 enum 可渲染) |
| member 定义多列 PageOrder | member 启动期 fail-fast(单列约束) |

相关:[013 分页契约](../013-federation-pagination/contracts/paginated-gql-fetch.md)、[013 远程关系契约](../013-federation-pagination/contracts/paginated-remote-relationship.md)。
