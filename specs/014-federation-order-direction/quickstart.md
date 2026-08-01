# Quickstart:order/direction 验证

**特性**:`specs/014-federation-order-direction` | **日期**:2026-08-01

可运行的端到端验证场景,证明 order/direction 开放后整条链路工作。前置:`demo/federation/` 三服务(users / reviews / catalog),reviews 暴露至少两个 order profile。

---

## 前置:reviews 暴露多 profile

reviews 服务的 `AutoQueryConfig.batch_pages` 配两个单列 profile:

```python
BatchPageConfig(
    default_order="HIGHEST_RATING",
    orders={
        "HIGHEST_RATING": PageOrder([OrderTerm("rating", "desc")]),
        "NEWEST":         PageOrder([OrderTerm("created_at", "desc")]),
    },
)
```

启动三服务(`bash start_all.sh`),catalog 挂 reviews(`RemoteRelationship(pagination=True)` —— 不再写 `order=`,见 D6)。

---

## 验证 1:mounter schema 暴露 order + direction 参数

取 catalog 的 SDL 与 `__schema` 内省:

```bash
curl -s localhost:8022/graphql -d '{"query":"{ __schema { queryType { fields { name } } } }"}'
```

**断言**:
- `reviews` 字段签名含 `order: <XxxOrder>`(enum 值 = `HIGHEST_RATING`、`NEWEST`)。
- `reviews` 字段含 `direction: Direction`(enum: ASC、DESC)。
- `order` 默认值 = `HIGHEST_RATING`(member 的 default_order)。
- SDL 与 `__schema` 暴露一致(FR-006)。

---

## 验证 2:查询者挑 order + direction(US1)

对同一 `Product.reviews` 发两条查询:

```graphql
{ Product { by_filter {
  reviews(limit: 5, order: HIGHEST_RATING, direction: DESC) { items { rating } } } } }

{ Product { by_filter {
  reviews(limit: 5, order: NEWEST, direction: ASC) { items { rating created_at } } } } }
```

**断言**:
- 第一条:items 按 `rating` desc 排序。
- 第二条:items 按 `created_at` asc 排序(与第一条结果不同且各自正确)。
- member reviews 服务每条查询**只收到一条** gql(SC-006,每服务一次批量不破坏)。

---

## 验证 3:direction 翻转 nulls(US3)

reviews 增加一个 nullable 列的 profile(如 `RATING` = `rating desc, nulls_last`),数据里含 NULL rating。查 `direction: DESC` 与 `direction: ASC`:

**断言**:
- DESC:NULL rating 在末尾。
- ASC:NULL rating 在开头(nulls 跟随翻转:nulls_last → nulls_first)。

---

## 验证 4:单列约束(SC-005)

reviews 定义一个多列 profile:

```python
"BAD": PageOrder([OrderTerm("rating","desc"), OrderTerm("created_at","desc")])
```

**断言**:reviews 服务启动期 fail-fast,错误指明 `BAD` 是多列 profile(本期只支持单列)。

---

## 验证 5:RemoteRelationship.order 废弃(SC-004)

catalog 的 `RemoteRelationship` 不写 `order=`(或写了启动期告警/拒绝)。

**断言**:
- 不写 `order=` 时,federate 成功,order 由查询参数决定。
- order 的唯一来源是 GraphQL 查询参数(缺省走 member default_order)。

---

## 验证 6:单体零回归(SC-007)

跑既有单体 nexusx 全量测试(未启用 federation):

```bash
uv run pytest tests/ -q
```

**断言**:全绿(本特性只动 federation 分页链路,单体路径不受影响)。

---

## 相关

- [spec.md](./spec.md):User Story 与 FR/SC。
- [contracts/order-direction.md](./contracts/order-direction.md):参数与翻转语义契约。
- [data-model.md](./data-model.md):实体形状。
- [013 quickstart](../013-federation-pagination/quickstart.md):基础分页 demo 启动方式。
