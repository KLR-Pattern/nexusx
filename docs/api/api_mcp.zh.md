# MCP API 参考

MCP 服务配置的完整 API 参考。

## create_single_app_mcp_server

使用 `create_single_app_mcp_server` 创建单应用 MCP 服务。

```python
from nexusx.mcp import create_single_app_mcp_server

mcp = create_single_app_mcp_server(
    base=SQLModel,
    name="My API",
    session_factory=async_session,
    allow_mutation=False,
)
```

!!! tip
    适用于单应用场景。如果你需要管理多个独立的应用（如 blog + shop），使用 `create_multi_app_mcp_server`。

### 参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| `base` | `type` | 是 | SQLModel 基类 |
| `name` | `str` | 否 | 服务名称，默认 `"nexusx API"` |
| `desc` | `str \| None` | 否 | Query 与 Mutation 的 schema 描述 |
| `allow_mutation` | `bool` | 否 | 是否注册 mutation，默认 `False` |
| `session_factory` | `Callable \| None` | 否 | 数据库关系加载使用的异步 session 工厂 |
| `enable_pagination` | `bool` | 否 | 是否为列表关系生成分页元数据 |
| `auto_query_config` | `AutoQueryConfig \| None` | 否 | 是否生成标准 `by_id` / `by_filter` 查询 |

### 生成的工具

| 工具 | 说明 |
|------|------|
| `get_schema()` | 获取完整 GraphQL schema（SDL）——唯一发现入口：实体类型、关系字段、`Result { items, pagination }` 包装、全部操作 |
| `graphql_query(query)` | 执行 GraphQL 查询 |

传入 `allow_mutation=True` 后，才会额外注册
`graphql_mutation(mutation)`。

## create_multi_app_mcp_server

使用 `create_multi_app_mcp_server` 创建多应用 MCP 服务。

```python
from nexusx.mcp import Application, create_multi_app_mcp_server

mcp = create_multi_app_mcp_server(
    apps=[
        Application(name="blog", base=BlogBase, url=BLOG_DATABASE_URL),
        Application(name="shop", base=ShopBase, url=SHOP_DATABASE_URL),
    ],
    name="Multi-App API",
)
```

!!! tip
    适用于需要管理多个独立应用的场景。生成的工具包括 `list_apps`、`list_queries` 等，支持渐进式应用发现。

### 参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| `apps` | `list[Application \| dict]` | 是 | 应用列表；dict 形式已弃用 |
| `name` | `str` | 否 | 服务名称 |
| `allow_mutation` | `bool` | 否 | 是否注册 mutation 导航与执行工具 |

### 生成的工具

| 工具 | 说明 |
|------|------|
| `list_apps()` | 列出所有应用 |
| `list_queries(app_name)` | 列出应用的查询 |
| `get_query_schema(entity, method, app_name, response_type="sdl")` | 获取查询 schema |
| `graphql_query(query, app_name)` | 执行查询 |

传入 `allow_mutation=True` 后，还会注册 `list_mutations`、
`get_mutation_schema` 和 `graphql_mutation`。

## Application

`Application` 是多应用场景下**自包含、可独立导出**的单元。每个 `Application`
封装 SQLModel `base` 加完整的数据库连接信息（URL / engine / session 工厂三选一），
可作为 Python 包发布到 PyPI 或私有索引，再由合并项目组装到 `create_multi_app_mcp_server`
里使用，无需在合并项目里重新声明连接资源。

```python
from nexusx.mcp import Application, create_multi_app_mcp_server

blog = Application(
    name="blog",
    base=BlogBaseEntity,
    url="postgresql+asyncpg://user:pass@host/blog",  # app 自带 engine
    description="博客系统 API",
)
shop = Application(
    name="shop",
    base=ShopBaseEntity,
    url="postgresql+asyncpg://user:pass@host/shop",
)

mcp = create_multi_app_mcp_server(apps=[blog, shop], name="多应用 API")
```

### 独立使用（无需挂到 mcp server）

`Application` 也可独立使用——文档生成、schema 内省、或脚本里直接跑 GraphQL：

```python
from nexusx.mcp import Application

# schema-only 模式：不需要数据库连接，即可访问 SDL 与内省数据
app = Application(name="blog", base=BlogBaseEntity)
print(app.resources.sdl_generator.generate())   # GraphQL SDL
print(app.resources.entity_names)               # entity 类名集合

# 提供 url 时 Application 自己造 engine 并拥有
async with Application(
    name="blog",
    base=BlogBaseEntity,
    url="sqlite+aiosqlite:///blog.db",
) as app:
    async with app.session_factory() as session:
        # 直接用 session 跑查询
        ...
    # 离开上下文时自动 engine.dispose()
```

### 资源所有权

| 构造方式 | 是否拥有 engine | `dispose()` 行为 |
|---|---|---|
| `url="..."` | 是 | `await engine.dispose()`（幂等） |
| `engine=<已有>` | 否 | no-op（engine 归调用方） |
| `session_factory=<已有>` | 否 | no-op |
| 都不提供（schema-only） | N/A | no-op |

### URL 凭据脱敏

通过 `url=` 构造时，密码在 `repr(app)`、错误消息、日志中自动脱敏（FR-013）：

```
Application(name='blog', url='postgresql+asyncpg://user:***@host/blog', owned=True)
```

## 旧版 dict 配置

`create_multi_app_mcp_server` 的 `apps` 参数仍兼容以下字典结构，但会触发
`DeprecationWarning`。新代码应使用 `Application` 实例。

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | 应用名称 |
| `base` | `type` | SQLModel 基类 |
| `description` | `str` | 应用描述 |
| `session_factory` | `Callable` | session 工厂 |
| `url` | `str` | 数据库 URL（与 `session_factory` 二选一） |
| `engine` | `AsyncEngine` | 外部 engine（与 `session_factory` 二选一） |
| `aliases` | `list[str]` | 可选路由别名 |
