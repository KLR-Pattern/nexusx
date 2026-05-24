# 让 AI Agent 直接调用你的业务逻辑，而不是让它在 OpenAPI Spec 里迷路

你有一个订单系统。你想让 AI agent 帮客服查订单、看客户历史、取消订单。

你需要做什么？

## 一个真实的困境

**方案一：给 LLM 一份 OpenAPI spec。**

几百个 endpoint，几千行 JSON Schema。LLM 读一遍就花了上万 token，调用时还经常拼错参数名、选错 endpoint。你在 prompt 里精心写了"查询待处理订单请调用 GET /orders?status=pending"，agent 照样调 GET /order?state=pending。

**方案二：手写 MCP tools。**

每个业务方法包装成一个 MCP tool：参数校验、DTO 转换、关系数据加载、N+1 处理……写完 OrderService 的 5 个方法，已经 300 行胶水代码了。更痛苦的是，业务逻辑改了，胶水代码也要跟着改。

**方案三：用 Hasura / PostGraphile。**

自动生成 GraphQL API，确实省事。但生成的是给人类用的 API——所有表、所有字段一次性暴露。LLM 拿到一个 200 行的 schema，还是不知道该查什么。更关键的是，不是所有关系都在数据库里——跨服务的评论系统、计算字段、聚合查询，这些 Hasura 帮不了你。

**核心矛盾：** 你的 SQLModel 定义里已经包含了数据结构、字段类型、关系、业务操作。但要让 LLM 可用，还得做大量胶水工作。

## 一个直觉：模型已经描述了一切

看这段代码（来自 `models.py`）：

```python
class Customer(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str
    tier: str = "regular"

    orders: list["Order"] = SQLRelationship(back_populates="customer")

class Order(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    status: str = "pending"
    total_amount: float = 0.0
    created_at: str = ""

    customer_id: int = Field(foreign_key="zh_customer.id")
    customer: Optional["Customer"] = SQLRelationship(back_populates="orders")
    items: list["OrderItem"] = SQLRelationship(back_populates="order")
```

这段代码里已经有了：
- **数据结构**：字段名、类型、约束
- **关系**：Customer → Order 一对多，Order → Item 一对多
- **业务语义**：status 的值域，tier 的含义

再看业务方法（来自 `services.py`）：

```python
class OrderService(UseCaseService):
    @query
    async def get_orders(cls, status: str = "", limit: int = 10) -> list[OrderDTO]:
        """Get orders, optionally filtered by status."""

    @mutation
    async def cancel_order(cls, order_id: int) -> OrderDTO | None:
        """Cancel an order by ID."""
```

方法签名、参数类型、返回类型、docstring 描述——LLM 需要理解一个 API 的全部信息，这里已经有了。

**为什么不能直接变成 agent 可用的能力？**

这就是 [nexusx](https://github.com/nexusx-dev/nexusx) 做的事。

## nexusx 的架构：一次定义，MCP 优先

```
SQLModel + @query/@mutation
        ↓
    ┌───────────────┐
    │    nexusx     │ ← Relationship + DataLoader 统一关系层
    └───────────────┘
      ↓       ↓       ↓
    MCP     GraphQL  REST
   (主输出)  (schema) (执行路径)
```

nexusx 的核心不是 GraphQL 生成，也不是 ORM 映射。它做的事情是：**让你的业务方法直接变成 AI agent 可调用的 MCP 工具。**

GraphQL SDL 是给 LLM 看的类型描述格式。REST 路由是可选的额外输出。MCP 是第一公民。

## Agent 看到的世界：4 层渐进披露

nexusx 的 MCP 服务不是把所有 schema 一次灌给 LLM，而是设计了 4 层渐进披露。

**为什么渐进披露对 LLM 重要？**

LLM 的 context window 有限。把一个有 50 张表、200 个方法的系统的完整 schema 一次交给 agent，它会浪费大量 token 在无关字段上，注意力分散，调用准确率下降。

nexusx 的做法是让 agent 先理解大局，再按需深入——和人类认识一个新系统的方式一样。

### 第一层：发现应用

```
→ list_apps()

← {
  "success": true,
  "data": [
    {
      "name": "order_system",
      "description": "订单管理系统 — 管理客户、订单和商品",
      "services_count": 3
    }
  ]
}
```

Agent 知道有一个"订单管理系统"，里面有 3 个服务。

### 第二层：发现服务

```
→ list_services(app_name="order_system")

← {
  "success": true,
  "data": [
    {
      "name": "OrderService",
      "description": "Order management — query and manage orders.",
      "methods_count": 3
    },
    {
      "name": "CustomerService",
      "description": "Customer management — query customers and their order history.",
      "methods_count": 2
    },
    {
      "name": "ProductService",
      "description": "Product management — query products with review data.",
      "methods_count": 1
    }
  ]
}
```

3 个服务，各司其职。Agent 按需选择深入哪个。

### 第三层：理解能力

```
→ describe_service(app_name="order_system", service_name="OrderService")

← {
  "success": true,
  "data": {
    "name": "OrderService",
    "methods": [
      {
        "name": "get_orders",
        "signature": "get_orders(status: string, limit: integer) -> list[OrderDTO]",
        "parameters": {"status": {"type": "string"}, "limit": {"type": "integer"}},
        "kind": "query"
      },
      {
        "name": "cancel_order",
        "signature": "cancel_order(order_id: integer) -> OrderDTO",
        "parameters": {"order_id": {"type": "integer"}},
        "kind": "mutation"
      }
    ],
    "types": "type OrderDTO { id: Int, status: String!, ... }"
  }
}
```

Agent 看到了方法签名、参数类型、返回类型的 SDL 定义。**这些信息是从你的 Python 代码自动生成的，不是手写的。**

### 第四层：调用

```
→ call_use_case(
    app_name="order_system",
    service_name="OrderService",
    method_name="get_orders",
    params='{"status": "pending"}'
  )

← {
  "success": true,
  "data": [
    {
      "id": 1,
      "status": "pending",
      "total_amount": 16898.0,
      "customer": {"id": 1, "name": "张三", "tier": "gold"},
      "items": [
        {"product": {"name": "MacBook Pro 14", "price": 14999.0}, "subtotal": 14999.0},
        {"product": {"name": "AirPods Pro", "price": 1899.0}, "subtotal": 1899.0}
      ],
      "item_count": 2
    }
  ]
}
```

注意返回数据里的细节：
- `customer` 自动加载了——没有 N+1，DataLoader 批量处理
- `items` 里的 `product` 也自动加载了
- `subtotal` 是计算字段（`quantity * unit_price`）
- `item_count` 是派生字段（`len(self.items)`）

**用户写的是业务方法，得到的是 agent 可直接使用的数据。** 中间的关系加载、批量优化、类型转换，nexusx 全部处理了。

## 关系加载：看不见但最关键的一层

上面的返回结果里，`customer`、`items`、`product` 都是自动加载的关联数据。如果没有这一层，agent 拿到的就是一堆 ID——它还得再调用 API 查每个关联对象，一轮对话就耗在来回查询上了。

nexusx 的关系加载有两个层面：

### ORM 关系自动发现

只要 SQLModel 实体定义了 `SQLRelationship`，ErManager 就会自动创建对应的 DataLoader。Order → Customer、Order → OrderItem、OrderItem → Product，这些关系不需要任何额外代码。

在 DTO 层面，只需要声明字段类型（来自 `dtos.py`）：

```python
class OrderDTO(DefineSubset):
    __subset__ = SubsetConfig(kls=Order, fields=['id', 'status', 'total_amount', 'created_at', 'customer_id'])

    customer: CustomerDTO | None = None   # 自动加载
    items: list[OrderItemDTO] = []        # 自动加载
    item_count: int = 0

    def post_item_count(self):
        return len(self.items)
```

字段名 `customer` 匹配 Order 实体的 `customer` 关系，字段类型 `CustomerDTO` 是 BaseModel——Resolver 自动检测这两个条件，通过 DataLoader 批量加载，不需要手写 `resolve_*` 方法。

FK 字段（如 `customer_id`）需要在 subset 中声明以供 DataLoader 使用，但会自动从序列化输出中隐藏。

### 自定义 Relationship：不是所有关系都在数据库里

这是 nexusx 区别于 Hasura / PostGraphile 的关键能力。

Product 和 Review 之间没有 ORM 关系——Review 数据来自"外部评论服务"。但 agent 查询商品时，自然希望看到评论和评分。

nexusx 的解法是 `Relationship` + 自定义 loader（来自 `models.py`）：

```python
async def _reviews_by_product_id_loader(product_ids: list[int]) -> list[list[Review]]:
    """模拟调用外部评论服务: GET /api/reviews?product_ids=1,2,3"""
    async with async_session() as session:
        rows = (await session.exec(
            select(Review).where(Review.product_id.in_(product_ids))
        )).all()
    # 按 product_id 分组，保持和输入顺序一致
    ...

class Product(SQLModel, table=True):
    ...
    __relationships__ = [
        Relationship(
            fk="id",
            target=list[Review],
            name="reviews",
            loader=_reviews_by_product_id_loader,
        )
    ]
```

**你写一个批量加载函数，nexusx 负责调度。** 这个 loader 可以查数据库，也可以调 HTTP 接口，也可以读缓存——框架不关心数据来源，只关心签名正确。

调用结果（来自 `sample_output.py` 的真实输出）：

```json
{
  "name": "MacBook Pro 14",
  "price": 14999.0,
  "reviews": [
    {"rating": 5, "comment": "性能强劲，完全够用", "reviewer_name": "数码达人"},
    {"rating": 4, "comment": "续航可以再好一点", "reviewer_name": "极客用户"}
  ],
  "review_count": 2,
  "avg_rating": 4.5
}
```

`reviews` 通过自定义 Relationship 加载，`review_count` 和 `avg_rating` 是 `post_*` 派生字段。对 agent 来说，这和 ORM 关系加载没有任何区别。

**这就是 nexusx 的关系抽象：你定义关系，我负责高效加载。无论关系来自 ORM、外部 API、还是计算逻辑。**

## 和其他方案的对比

### vs 手写 MCP tools

少写 80% 的胶水代码。关系加载自动处理，DTO 自动生成，类型签名自动导出。业务方法改了，MCP 工具自动更新。

### vs 给 OpenAPI spec

渐进披露节省 token。agent 先看大局（list_apps → list_services），再按需深入（describe_service），最后精确调用（call_use_case）。不需要一次灌入完整 schema。

### vs Hasura / PostGraphile

不只是 ORM 映射。`Relationship` + 自定义 loader 让你可以接入任何数据源。MCP 输出是原生设计，不是 HTTP endpoint 套壳。

### vs Strawberry / Ariadne

不是 GraphQL 框架。GraphQL SDL 是给 LLM 的 schema 格式，不是给人类用的 API 层。nexusx 不需要你定义 GraphQL type、resolver、schema——它从 SQLModel 自动推导。

## 写在最后

"从模型定义到 agent 可调用的能力"这条路才刚开始。MCP 协议在快速演化，AI agent 的能力边界在快速扩展。但核心需求是稳定的：**agent 需要理解系统有什么能力，需要高效地调用这些能力，需要结构化的返回数据。**

nexusx 的架构围绕这三个需求设计：渐进披露解决理解问题，DataLoader + Relationship 解决效率问题，DefineSubset DTO 解决数据结构问题。无论 MCP 协议怎么变，这三层是稳定的。

---

*本文所有代码和输出均来自 `demo/zhihu_article/` 目录的真实运行结果。你可以克隆 [nexusx](https://github.com/nexusx-dev/nexusx) 仓库，运行 `uv run --with fastmcp python -m demo.zhihu_article.sample_output` 验证。*
