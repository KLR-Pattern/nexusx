# Quickstart: 联邦分页验证

关联:[spec.md](./spec.md)、[plan.md](./plan.md)、[contracts/](./contracts/)。本文是**端到端验证指南**(非实现清单;实现细节归 tasks.md,/speckit-tasks 产出)。

## 前置

- 012-federation 联邦基础可工作(catalog + reviews + users 三服务 demo,见 `demo/federation/`)。
- 依赖已就位(`nexusx[federation]` extra 含 httpx)。

## 场景 1:基础分页(对应 US1)

**起服务**(沿用 `demo/federation/` 三个 app;reviews 的 `Review` 配 `by_product_id_in`):

```bash
uv run uvicorn demo.federation.users_app:app   --port 8020 &
uv run uvicorn demo.federation.reviews_app:app --port 8021 &
uv run uvicorn demo.federation.catalog_app:app --port 8022 &
```

catalog 的 `Product.reviews` 声明 `sort_field`(开启分页):

```python
RemoteRelationship(
    fk="id", target=list[reviews.Review],
    name="reviews", join_remote="product_id",
    sort_field="rating",          # ← 声明即分页
)
```

**查**:

```graphql
{ Product { by_filter {
    id name
    reviews(limit: 5, offset: 0) {
      items { title rating }
      pagination { has_more total_count }
    }
  } } }
```

**期望**:返回按 rating 排序的前 5 条 review;`has_more`/`total_count` 正确;reviews 服务**只收到一条** gql(分页 root `by_product_id_in_page`,携带全部 product_id + 共享 limit/offset/sort_field)。

## 场景 2:分页 + items 嵌套子树(对应 US2,核心难点)

```graphql
{ Product { by_filter {
    reviews(limit: 5) {
      items { title comments { text } }     # items 内 comments 由 reviews 自解析
      pagination { has_more }
    }
  } } }
```

**期望**:每个分页 review 的 comments 正确解析;分页元数据不受子树影响;仍只发一条 gql。此场景验证 [research.md R4](./research.md)(member executor root 路径对 items 递归)——**最高风险点**,须专项通过。

## 场景 3:多 parent 批量 + UUID 对齐(对应 US3)

构造 N 个 Product(含 UUID 主键)查各自 `reviews(limit:5)`,期望每个 Product 拿到自己的分页页、按 UUID 正确对齐(不因 JSON 字符串化错配)。

## 场景 4:未声明零回归(对应 US4)

同一联邦里一条远程关系声明 `sort_field`(分页)、另一条不声明(全量),期望:前者返回 `{items, pagination}`,后者返回扁平列表;既有 012 联邦测试套件全过。

## 场景 5:fail-fast(对应 US5)

构造 to-one 关系声明 `sort_field`、或 `sort_field` 非 member 合法字段,期望入口服务启动期 fail-fast。

## 自动化

以上场景均有对应 pytest(`tests/test_federation_pagination_*.py`),用 `httpx ASGITransport` in-process 起三服务,无需真实端口:

```bash
uv run pytest tests/test_federation_pagination_e2e.py -q
uv run ruff check src/nexusx && uv run mypy --strict src/nexusx
```

## 渐进实现提示

按 US1→US2→US3→US4→US5 推进;**US1(单 key + 标量 items)优先**验证 member root 路径识别与对齐,再开 items 子树递归(US2,核心难点)。任务分解见 tasks.md(/speckit-tasks 后续产出)。
