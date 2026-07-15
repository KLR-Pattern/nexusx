# MCP API 参考

MCP 服务配置的完整 API 参考。

## create_simple_mcp_server

使用 `create_simple_mcp_server` 创建单应用 MCP 服务。

```python
from nexusx.mcp import create_simple_mcp_server

mcp = create_simple_mcp_server(
    base=SQLModel,              # SQLModel 基类
    name="My API",              # 服务名称
    session_factory=async_session,  # session 工厂
)
```

!!! tip
    适用于单应用场景。如果你需要管理多个独立的应用（如 blog + shop），使用 `create_mcp_server`。

### 参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| `base` | `type` | 是 | SQLModel 基类 |
| `name` | `str` | 是 | 服务名称 |
| `session_factory` | `Callable` | 否 | session 工厂 |

### 生成的工具

| 工具 | 说明 |
|------|------|
| `get_schema()` | 获取 GraphQL schema |
| `graphql_query(query)` | 执行 GraphQL 查询 |
| `graphql_mutation(mutation)` | 执行 GraphQL 变更 |

## create_mcp_server

使用 `create_mcp_server` 创建多应用 MCP 服务。

```python
from nexusx.mcp import create_mcp_server

mcp = create_mcp_server(
    apps=[
        {"name": "blog", "base": BlogBase, "description": "Blog API"},
        {"name": "shop", "base": ShopBase, "description": "Shop API"},
    ],
    name="Multi-App API",
)
```

!!! tip
    适用于需要管理多个独立应用的场景。生成的工具包括 `list_apps`、`list_queries` 等，支持渐进式应用发现。

### 参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| `apps` | `list[dict]` | 是 | 应用配置列表 |
| `name` | `str` | 是 | 服务名称 |

### 生成的工具

| 工具 | 说明 |
|------|------|
| `list_apps()` | 列出所有应用 |
| `list_queries(app_name)` | 列出应用的查询 |
| `get_query_schema(name, app_name)` | 获取查询 schema |
| `graphql_query(query, app_name)` | 执行查询 |

## Application

`Application` 是多应用场景下**自包含、可独立导出**的单元。每个 `Application`
封装 SQLModel `base` 加完整的数据库连接信息（URL / engine / session 工厂三选一），
可作为 Python 包发布到 PyPI 或私有索引，再由合并项目组装到 `create_mcp_server`
里使用，无需在合并项目里重新声明连接资源。

```python
from nexusx.mcp import Application, create_mcp_server

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

mcp = create_mcp_server(apps=[blog, shop], name="多应用 API")
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

## AppConfig

`AppConfig` 是多应用配置类型（`create_mcp_server` 的 apps 参数中的字典结构）。

> **已弃用**：推荐使用 `Application` 实例。dict 形式仅为向后兼容保留，触发 `DeprecationWarning`。

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | 应用名称 |
| `base` | `type` | SQLModel 基类 |
| `description` | `str` | 应用描述 |
| `session_factory` | `Callable` | session 工厂 |
| `url` | `str` | 数据库 URL（与 `session_factory` 二选一） |
| `engine` | `AsyncEngine` | 外部 engine（与 `session_factory` 二选一） |
| `aliases` | `list[str]` | 可选路由别名 |

