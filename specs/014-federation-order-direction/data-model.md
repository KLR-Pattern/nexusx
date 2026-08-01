# 数据模型:order/direction 开放给查询者

**特性**:`specs/014-federation-order-direction` | **日期**:2026-08-01 | **Spec**:[spec.md](./spec.md) | **Plan**:[plan.md](./plan.md)

本文描述 014 特性引入/扩展的核心数据结构。建立在 013-federation-pagination 数据模型之上；只钉 014 的**增量**形状与契约。

---

## 1. `PageOrder`(收紧,既有)

013 的 `PageOrder` 允许一个或多个 `OrderTerm`。014 **收紧为单列**:

| 字段 | 类型 | 说明 |
|---|---|---|
| `terms` | `list[OrderTerm]` | **必须恰好 1 个**(014 收紧;多列在 member `_resolve_page_orders` 启动期拒绝) |

`OrderTerm`(field/direction/nulls)形状不变。`BatchPageConfig`、`AutoQueryConfig.batch_pages` 形状不变。

**不变量**:单列约束让 direction 翻转语义无歧义(D3)。

---

## 2. `direction`(新增,查询参数)

查询者经 GraphQL 传入的排序方向,覆盖 profile 的默认方向。

| 形式 | 取值 | 缺省 |
|---|---|---|
| mounter schema 参数 `direction: Direction` | `ASC` \| `DESC`(mounter 自有全局 enum) | profile 默认方向 |
| member root 参数 `direction` | `ASC` \| `DESC`(member 自有 enum) | profile 默认方向 |

**翻转语义**(D4):direction != profile 默认方向时,翻转 term:`direction` 覆盖 `term.direction`,`nulls` 跟随翻转(`nulls_first ↔ nulls_last`)。翻转在 `_build_order_expressions` 之前对 terms 一次性完成,window 内层与 outer 共用翻转后 terms。

---

## 3. `page_capability`(沿用 013,mounter 侧落地)

member 经 ER introspection 暴露的分页能力,是 mounter 渲染 `order` enum 的**唯一数据源**。

```text
BatchPageCapability (013 既有,形状不变):
  protocol: "offset-v1"
  default_order: str                 # mounter 的 order 参数默认值
  orders: list[PageOrderDescriptor]
    PageOrderDescriptor:
      name: str                      # ← mounter order enum 的值
      description: str | None
```

**不变量**:物理列/方向/nulls 不在 capability 里(索引控制权 member)。mounter 只消费 `orders` 名集合 + `default_order`。

---

## 4. `RelationshipInfo`(扩展,既有)

mounter 侧关系元数据,新增 `page_capability` 字段供 SDL 渲染。

| 新增字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `page_capability` | `BatchPageCapability \| None` | `None` | federation 分页关系 = member 暴露的能力;本地/非分页 = `None` |

**填入点**:`manager._validate_and_wire` 从 `BatchRoot.page`(member introspection 来)取 capability,存进分页 rel_info。`page_capability.orders` 非空(否则 federate fail-fast)。

**向后兼容**:默认 `None`,既有本地关系构造路径不变。

---

## 5. `RemoteRelationship`(删字段,既有)

| 删除字段 | 原因 |
|---|---|
| `order` | order 改由查询参数决定(D1/D6);静态字段与查询参数双源冲突 |

`pagination`、`fk`、`target`、`join_remote` 等不变。`pagination=True` 仍声明分页能力,但不再绑死 order。

---

## 6. 状态流转:order/direction 解析

```
查询者: reviews(limit, offset, order: X, direction: DESC)
   │
   ▼  GraphQL enum 校验(order 必须在 member profile 集合内)
mounter executor: order/direction 进 selection.arguments
   │
   ▼  RemoteLoader 从 selection.arguments 读
build_paginated_gql_query(order=X, direction=DESC, ...) → 发给 member
   │
   ▼  member page_by_<key>_in
取 profile X 的 terms,按 direction 翻转(direction + nulls flip)
   │
   ▼  翻转后 terms 同时用于 window 内层 + outer
ROW_NUMBER() OVER (PARTITION BY key ORDER BY <翻转后 terms>) + outer
   │
   ▼  按 key 分组组装 per-key packages
返回 [{key, items, pagination}]
```

**缺省链**:查询者不传 order → mounter 用 `default_order`;不传 direction → member 用 profile 默认方向。

---

## 7. 校验规则(增量)

| 规则 | 校验对象 | 失败处置 |
|---|---|---|
| PageOrder 单列 | member `_resolve_page_orders` | member 启动失败,指明多列 profile |
| page_capability.orders 非空 | mounter `_validate_and_wire` | federate fail-fast |
| order ∈ profile 集合 | GraphQL enum(schema 层) | 查询拒绝(不进 member) |
| direction ∈ {ASC,DESC} | GraphQL enum(schema 层) | 查询拒绝 |
| direction 翻转后 window/outer 一致 | member `_build_order_expressions` 复用翻转 terms | (设计保证,非运行时校验) |
