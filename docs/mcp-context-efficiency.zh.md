# MCP 与 context 效率

当你通过 MCP 把数据暴露给 AI agent 时，首要约束变成了 agent 的 context 窗口——而不是数据本身。context 在三个互相独立的维度被消耗，而大多数方案只解决了其中一个。本文梳理 context 压力的三个来源，以及 nexusx 如何分别处理。

## context 压力的三个来源

### 1. tool 定义全量预加载

最常见的做法是把 REST 端点一个个包成 MCP tool：`GET /users` → `list_users`，`GET /users/{id}/orders` → `list_user_orders`……一个中等应用轻松堆出 50–60 个 tool。

每个 tool 的**定义**（schema、参数、描述）在 agent 还没动手前就全量灌进了 context。实测一个 MCP server 的 tool 定义能烧掉 **55000+ tokens**——第一条用户消息还没处理，context 已经没了一半。

### 2. 返回无法裁剪

agent 只想要一个用户的名字，调 `list_users` 拿回来的却是：

```json
[
  {"id":1,"name":"张三","email":"…","password_hash":"…","last_login_ip":"…","department_id":7,"meta":{…}},
  … ×50
]
```

它只要 1 个字段，却被灌了 20 字段 × 50 行，一万多 token 的垃圾。多聊几轮 agent 明显退化——不是模型弱，是它的 working memory 全被返回数据占满了。

### 3. 关联数据需要 N 次往返

agent 真正的任务很少是「取一张表」，而是「取一棵树」。「产品 1 的评价有没有差评？谁写的？」横跨 `Product → Reviews → Comments → Author` 四层。

REST 包装的 MCP 没法一次拿。agent 只能一层层串：调 `list_reviews(product_id)` → 记 review_id → 调 `list_comments(review_id)` → 记 author_id → 调 `get_user(author_id)`。N 层 = N 次往返，每次返回又一坨 JSON，而且 agent 得自己记中间 id。错一个，整条链断。

---

## nexusx 如何分别处理

### 渐进披露（来源 1）

nexusx 不把所有 tool 定义全量灌进 context，而是让 agent 按需下钻：

1. `list_apps`——有哪些应用 / 服务（名字 + 一句描述）；
2. `describe_compose_schema`——某服务暴露了哪些方法（仍紧凑）；
3. `describe_compose_method`——某方法的完整签名和返回类型（SDL）；
4. `compose_query`——执行。

每层只返回 agent 要的那一小段。多数时候 agent 在第 1、2 层就能决定要不要继续，真正用到的才下钻到签名和执行。tool 定义从「全量预灌」变成「按需加载」。

### 字段选择（来源 2）

nexusx 的 MCP 底层跑 GraphQL，所以 agent 在调用时声明要哪些字段，而不是吃一个固定形状。要 `name` 就只回 `name`——一万多 token 缩成几百。

注意：字段选择控的是**返回体积**，不是 SQL 查询本身。哪些列可查是定义时钉死的边界（通过 `DefineSubset`）；查询时的 selection 只决定序列化时放什么进响应。

### 一棵查询表达整棵树 + 批量加载（来源 3）

字段选择扩展到关联树：agent 不只声明字段，还声明要下钻哪些关联、每层取什么。一条查询表达多跳关联 + 每层字段。

底层一个批量加载器（DataLoader）把同一层的请求——「取这 50 个 task 的 owner」——合并成一次查询，而不是一行一查。查询次数随**深度**增长，不随**行数**增长：50 个 owner 也是一次查询，不是 50 次。

---

## 一个完整的业务定义

三个机制都从同一个业务方法里长出来。一个完整的 nexusx 定义有三部分——实体、DTO、服务：

```python
# 1. SQLModel 实体 + 关系
class User(BaseEntity, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    tasks: list["Task"] = Relationship(back_populates="owner")

class Sprint(BaseEntity, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    tasks: list["Task"] = Relationship(back_populates="sprint")

class Task(BaseEntity, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    owner: User | None = Relationship(back_populates="tasks")
    sprint: Sprint | None = Relationship(back_populates="tasks")

# 2. DefineSubset DTO —— 对外字段边界 + 嵌套关系
class UserSummary(DefineSubset):
    __subset__ = (User, ("id", "name"))         # 实体的其他字段（email 等）不进边界

class TaskSummary(DefineSubset):
    __subset__ = (Task, ("id", "title"))
    owner: UserSummary | None = None            # 关系字段，自动下钻

class SprintSummary(DefineSubset):
    __subset__ = (Sprint, ("id", "name"))
    tasks: list[TaskSummary] = []               # Sprint → Tasks → Owner 一棵树

# 3. UseCaseService —— 业务方法（对外就是一个能力）
class SprintService(UseCaseService):
    @query
    async def list_sprints(cls) -> list[SprintSummary]: ...
```

这三部分对应三个机制：

- **渐进披露 = 服务（第 3 段）**：`SprintService` + `@query` 方法在 MCP 上暴露成 `list_apps → describe_compose_schema → describe_compose_method → compose_query`，用不到的方法连签名都不进 context。
- **字段选择 = `__subset__`（第 2 段）**：`UserSummary.__subset__ = (User, ("id","name"))` 把对外字段钉死成 id/name，`email`、`password_hash` 等列根本不在边界里。
- **一棵树 + 批量加载 = DTO 嵌套关系 + 实体 `Relationship`（第 1+2 段）**：`SprintSummary.tasks` / `TaskSummary.owner` 匹配实体的 `Relationship(...)`，nexusx 自动下钻、用 DataLoader 批量加载。查询次数随深度，不随行数。

nexusx 吃的是实体里已有的关系元数据——你不用重新描述「一个任务属于哪个用户」。一个方法同时生成 **REST + GraphQL + MCP + CLI**，共享同一套类型契约和批量加载器。

> 这套在项目本来就用 SQLModel 时最契合。

---

## 端到端：一次 MCP 交互

拿电商例子——agent 回答「产品 1 的评价有没有差评？谁写的？」：

**① `list_apps`** → `[{"name": "catalog", "description": "商品目录与评价"}]`。一条紧凑描述进 context，agent 选了 `catalog`。

**② `describe_compose_schema(app: "catalog")`**：
```
→ ProductService { product(id): ProductDetail,  top_rated(): [ProductDetail] }
  ReviewService  { by_product(product_id): [ReviewDetail] }
```
agent 锁定 `ProductService.product(id)`。

**③ `describe_compose_method(app, service, method)`**：
```
→ product(id: Int!): ProductDetail
  ProductDetail { id name reviews: [Review!]! }
  Review        { id rating text comments: [Comment!]! author: UserSummary }
  Comment       { text author: UserSummary }
  UserSummary   { id name }
```
完整类型链可见——`product → reviews → comments → author` 路径、每层字段、参数类型。

**④ `compose_query`** —— 一条嵌套 selection：
```
{ ProductService { product(id: 1) {
    name
    reviews { rating text
      comments { text author { name } } } } } }
```
返回一棵完整树，只含选中字段；`password_hash` 这类内部列不出现。底层按层批量加载——4 层关联、几次批量查询，不是 4 轮往返拼 id。

三个 context 压力来源在这一次交互里全被处理：①–③ 是渐进披露，④ 是一条嵌套 selection（返回小 + 一棵树 + 批量加载）。

---

## 三个正交的机制

每个能力各管一个维度：

- **渐进披露**（发现时）— tool 数量
- **selection**（查询时）— 返回体积
- **批量加载 / DataLoader**（执行时）— 查询次数、N+1
- **DefineSubset**（定义时）— 字段边界、安全

一个业务方法，四个协议（REST / GraphQL / MCP / CLI）同源。

---

## 相关

- [MCP Service](./advanced/mcp_service.zh.md) —— 如何把 SQLModel API 暴露为 MCP
- [MCP API](./api/api_mcp.zh.md) —— MCP 配置参考
