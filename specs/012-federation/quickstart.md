# Quickstart 验证指南:nexusx 多服务联邦

**特性**:`specs/012-federation` | **日期**:2026-07-26 | **Spec**:[spec.md](./spec.md) | **Plan**:[plan.md](./plan.md)

本文是**端到端验证指南**:如何起一个最小的三服务联邦(catalog + reviews + users),证明特性按 spec 工作。实现细节见 `tasks.md`(后续生成);契约细节见 [contracts/](./contracts/)。

## 前置

- Python ≥ 3.10,已 `uv sync`(或 `pip install -e '.[federation]'`)——**必须带 `[federation]` extra**(引入 httpx)。
- `pytest` + `pytest-asyncio`。
- 三个 nexusx 服务的实体定义就绪(见下);每个服务暴露 `/graphql`(包 `GraphQLHandler.execute`)与 `/nexusx/er-introspection`(见 [er-introspection.md](./contracts/er-introspection.md))。

## 场景拓扑

```
catalog(Product,本地 DB) ──reviews─→ reviews(Review + by_product_id_in)
                                         └──author──→ users(User + by_id_in)
```

- catalog 挂 reviews;reviews 挂 users(reviews 声明 `Review.author → users.User`)。
- 客户端只查 catalog,得到 `product { reviews { author { name } } }`,无服务前缀。

## 步骤 1:成员侧配置(reviews / users)

每个成员按被挂载时用到的 join key 生成 `by_<key>_in` root(见 [batch-query-root.md](./contracts/batch-query-root.md)):

```python
# reviews 服务
reviews_cfg = AutoQueryConfig(batch_keys={"Review": ["product_id", "author_id"]})
reviews_handler = GraphQLHandler(base=ReviewsBase, session_factory=reviews_session,
                                 auto_query_config=reviews_cfg)
# users 服务
users_cfg = AutoQueryConfig(batch_keys={"User": ["id"]})
users_handler = GraphQLHandler(base=UsersBase, session_factory=users_session, auto_query_config=users_cfg)
```

reviews 在自己的实体上声明 `Review.author → users.User`(见 [remote-relationship.md](./contracts/remote-relationship.md)):

```python
class Review(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    product_id: int
    author_id: int
    title: str
    rating: int
    __relationships__ = [
        RemoteRelationship(name="author", target="users.User",
                           join_local="author_id", join_remote="id", is_list=False),
    ]
```

## 步骤 2:挂载方配置(catalog)

catalog 声明 `Product.reviews → reviews.Review`,并在启动期 `federate`:

```python
class Product(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    __relationships__ = [
        RemoteRelationship(name="reviews", target="reviews.Review",
                           join_local="id", join_remote="product_id", is_list=True),
    ]

# 启动期(FastAPI lifespan 或 Application 启动钩子):
catalog_handler = GraphQLHandler(base=CatalogBase, session_factory=catalog_session)
await catalog_handler.federate(services={
    "reviews": "http://reviews:8000",
    "users":   "http://users:8000",
})
```

## 步骤 3:验证点(逐条对应 SC)

### V1. 启动成功 + 物化(SC-001 前置)
**预期**:`federate()` 完成,无异常;`catalog_handler.get_sdl()` 含 `type Review { ... }`、`type User { ... }`、`Product.reviews`、`Review.author`(全裸名)。
**失败迹象**:启动期抛 `FederationError` 并指明具体声明 → 命中 fail-fast(SC-004),按报错修配置。

### V2. 单跳取数 + 每服务一条查询(SC-001/SC-003)
**操作**:查 `{ Product { by_id(id: 1) { id reviews { title rating } } } }`(取多个产品)。
**预期**:返回正确嵌套 reviews;**reviews 服务只收到一条** gql 查询(携带全部 `product_id`)。
**断言**(测试):用 spy/计数器包住 reviews 的 `/graphql`,断言调用次数 = 1。

### V3. 多跳透明(SC-002)
**操作**:查 `{ Product { by_id(id: 1) { reviews { author { name } } } } }`。
**预期**:返回完整 `reviews.author.name`;客户端文档与 catalog 的对外 schema **不含** `reviews.`/`users.` 前缀;catalog 对 reviews 只发**一条** gql 查询(选区含 `author`,reviews 内部自行解析 author)。

### V4. 无过度取数
**操作**:查 `{ Product { by_id(id: 1) { id name } } }`(不触碰 reviews)。
**预期**:reviews / users 服务**零调用**。

### V5. schema 渲染完整 + 渲染=执行同源(SC-007)
**操作**:`catalog_handler.get_sdl()` 与 `catalog_handler.get_introspection_data()`。
**预期**:两者均含 `Review`/`User` 类型与 `reviews`/`author` 字段(裸名);SDL 声明的字段集 = executor 经注册表可解析的字段集。

### V6. fail-fast(SC-004)
逐项构造错配,断言启动失败且报错定位到声明:
- `target="ghost.Review"`(未注册 srv)
- reviews 片段无 `Review` / 无 `product_id` / 类型不兼容
- reviews 未生成 `by_product_id_in`
- 两个服务同名前缀
- 两个服务同名类型(各自 `User`)
- 挂载成环(A 挂 B、B 挂 A 且无可终止路径)

### V7. 单体零回归(SC-005)
**操作**:跑既有 nexusx 全量测试套件(未启用 `federate`)。
**预期**:与特性前 master 通过集合一致,零新增失败。

## 测试运行

```bash
# 联邦端到端(用 httpx ASGITransport,无需起真实端口)
pytest tests/test_federation_e2e.py -v

# 全量回归
pytest -q
ruff check src/nexusx tests
mypy --strict src/nexusx
```

> 端到端测试建议用 `httpx.AsyncClient(transport=ASGITransport(app=...))` 在进程内把 catalog/reviews/users 的 ASGI app 串起来,避免真实端口与 CI 抖动。详见 plan `tests/test_federation_e2e.py`。

## 相关
- 契约:[remote-relationship.md](./contracts/remote-relationship.md) · [er-introspection.md](./contracts/er-introspection.md) · [gql-fetch.md](./contracts/gql-fetch.md) · [batch-query-root.md](./contracts/batch-query-root.md)
- 数据模型:[data-model.md](./data-model.md)
- 研究:[research.md](./research.md)
