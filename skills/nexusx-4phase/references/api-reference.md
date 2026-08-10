# nexusx Public API Reference（6.0+）

> 所有公共 API + 最小 code snippet，按使用场景分类。详细原理见 SKILL.md「nexusx 原理与工作机制」。

---

## ① 装饰器 @query / @mutation

```python
@query
async def list_users(cls) -> list[User]: ...

@mutation
async def create_user(cls, name: str) -> User: ...
```

## ② Entity 定义

```python
class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    posts: list["Post"] = Relationship(back_populates="author")
```

## ③ DefineSubset + SubsetConfig

```python
class UserSummary(DefineSubset):
    __subset__ = SubsetConfig(kls=User, fields=("id", "name"))
    # 元组简写也行: __subset__ = (User, ("id", "name"))
```

## ④ γ DTO 联邦公开（member public DTO）

```python
class ReviewDTO(DefineSubset):
    __subset__ = SubsetConfig(kls=Review, fields=("title", "rating", "product_id"),
                              federation_public=True)
    # join key ← Review.__federation_keys__（单 key 自动 / 多 key 用 federation_key= 选择器）
    # order   ← Review.__pagination_orders__（单一，DTO 不自带）
    # 022: 不需 dto_classes=[ReviewDTO] —— 自动从源 entity 发现
```

## ⑤ federation member 声明（entity dunder）

```python
class Review(SQLModel, table=True):
    __federation_keys__ = ["product_id"]            # 联邦入口（纯标记）
    __pagination_orders__ = BatchPageConfig(         # 单一排序（被排序对象自己）
        default_order="HIGHEST_RATING",
        orders={"HIGHEST_RATING": PageOrder([OrderTerm("rating", "desc")])},
    )
    # → 自动生成 by_product_id_in + page_by_product_id_in
```

## ⑥ federation 联邦边（mounter 侧）

```python
class Product(SQLModel, table=True):
    __relationships__ = [RemoteRelationship(
        fk="id", target=list[reviews.Review],
        name="reviews", join_remote="product_id")]
    # 无 pagination 参数（021: mounter 自动探测 member 的 page_by_product_id_in）
```

## ⑦ Paged（字段级分页，固化）

```python
class SprintTopTasks(DefineSubset):
    __subset__ = (Sprint, ("id", "name"))
    tasks: Annotated[list[TaskSummary], Paged(limit=2)] = []  # 固定 top-2
```

## ⑧ Loader / ExposeAs / SendTo / Collector

```python
# Loader — DataLoader 注入（显式指定 batch key）
def resolve_author(self, loader=Loader("users")): return loader.load(self.author_id)

# ExposeAs + SendTo + Collector — 跨层数据流
class SprintReport(DefineSubset):
    __subset__ = SubsetConfig(kls=Sprint, fields=["id", "name"],
                              expose_as=[("name", "sprint_name")],   # 暴露给子节点
                              send_to=[("owner", "contributors")])   # 子→父
    contributors: list[UserSummary] = []
    def post_contributors(self, c=Collector("contributors")): return c.values()
```

## ⑨ Relationship（自定义非 ORM 关系）

```python
class Task(SQLModel, table=True):
    __relationships__ = [Relationship(
        target=list[Tag], name="tags", loader=load_tags_batch)]
```

## ⑩ FromContext（请求级 context 注入）

```python
class ReportService(UseCaseService):
    @query
    async def my_tasks(cls, user_id: Annotated[int, FromContext()]) -> list[dict]: ...
```

## ⑪ entity-first MCP（对偶命名）

```python
# 多 app（progressive disclosure: list_apps → list_queries → get_schema → graphql_query）
from nexusx.mcp import Application, create_multi_app_mcp_server
mcp = create_multi_app_mcp_server(
    apps=[Application(name="blog", base=BlogBase, url=BLOG_URL)],
    name="Gateway")

# 单 app（简化: get_schema + graphql_query）
from nexusx.mcp import create_single_app_mcp_server
mcp = create_single_app_mcp_server(base=BaseEntity, url=DB_URL)
```

## ⑫ use-case-first 工厂（统一 create_use_case_* 前缀）

```python
config = UseCaseAppConfig(name="api", services=[UserService, TaskService])

app.include_router(create_use_case_router(config))                        # FastAPI REST
app.include_router(create_use_case_jsonrpc_router(config, path="/rpc"))  # JSON-RPC
cli = create_use_case_cli(config)                                       # Typer CLI
mcp = create_use_case_graphql_mcp_server(apps=[config])                # GraphQL MCP
voyager = create_use_case_voyager(services=[...], er_manager=er)       # Voyager
```

## ⑬ GraphQLHandler（entity-first 执行入口）

```python
handler = GraphQLHandler(
    base=BaseEntity, session_factory=sf,
    auto_query_config=AutoQueryConfig(),   # 纯开关（default_limit 等）
    enable_pagination=True,                 # 本地关系分页总开关
    service_name="api",
)
result = await handler.execute('{ User { by_name(name: "Alice") { id name } } }')
```

## ⑭ ErManager + Resolver（Core API 执行）

```python
er = ErManager(entities=[User, Post], session_factory=async_session)
resolver = er.create_resolver()
result = await resolver.resolve([UserSummary(id=1)])
```

## ⑮ ComposedErManager（同进程多 engine 组合）

```python
from nexusx import ComposedErManager
composed = ComposedErManager(members=[er1, er2], cross_relationships=[...])
handler = GraphQLHandler(er_manager=composed)
```

## ⑯ ErDiagram + build_dto_select

```python
ErDiagram.from_sqlmodel([User, Post]).to_mermaid()         # ER 图（mermaid）
stmt = build_dto_select(UserSummary, where=User.id == 1)   # 按 DTO 列裁剪 select
```

## ⑰ RemoteService / RemoteRef（federation 声明）

```python
reviews = RemoteService("reviews", url="http://localhost:8021", color="#3b82f6")
# reviews.Review 即 RemoteRef —— 用于 RemoteRelationship target + DTO 字段类型
```

---

## 已移除的旧 API（6.0 breaking，不再可用）

| 旧 API | 替代 |
|---|---|
| `AutoQueryConfig(batch_keys=...)` | entity `__federation_keys__` |
| `AutoQueryConfig(batch_pages=...)` | entity `__pagination_orders__` |
| `SubsetConfig(federation_join_key=...)` | 从 entity `__federation_keys__` 推导（`federation_key=` 选择器） |
| DTO 级 `__pagination_orders__` | 读源 entity `__pagination_orders__` |
| `RemoteRelationship(pagination=...)` | 自动探测 `page_by_` |
| `dto_classes=[DTO]`（for public DTO） | `federation_public=True` 自动发现（022） |
| AppConfig dict（`apps=[{...}]`） | `Application(...)` |
| `AutoQueryConfig(session_factory)` | `session_factory` 传 `GraphQLHandler` / `Application` |
| `create_mcp_server` | `create_multi_app_mcp_server` |
| `create_simple_mcp_server` | `create_single_app_mcp_server` |
| `create_jsonrpc_router` | `create_use_case_jsonrpc_router` |
