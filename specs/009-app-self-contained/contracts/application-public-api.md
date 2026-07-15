# 契约：`Application` 公共 API

**功能**：[spec.md](../spec.md) · **数据模型**：[data-model.md](../data-model.md)

**位置**：`src/nexusx/mcp/application.py`（新增模块）

**导出路径**：`from nexusx.mcp import Application`

---

## 1. 类签名

```python
class Application:
    def __init__(
        self,
        *,
        name: str,
        base: type[SQLModel],
        url: str | None = None,
        engine: AsyncEngine | None = None,
        session_factory: Callable | None = None,
        description: str = "",
        query_description: str | None = None,
        mutation_description: str | None = None,
        aliases: list[str] | None = None,
        engine_kwargs: dict | None = None,
    ): ...

    @property
    def name(self) -> str: ...

    @property
    def resources(self) -> AppResources: ...

    @property
    def session_factory(self) -> Callable | None: ...

    async def dispose(self) -> None: ...

    async def __aenter__(self) -> Application: ...

    async def __aexit__(self, *exc_info) -> None: ...
```

**关键字参数 only**：所有参数必须以关键字形式传入（避免位置参数歧义）。

---

## 2. 构造契约

### 2.1 必填参数

- `name: str` —— 非空字符串；用于 `MultiAppManager` 路由
- `base: type[SQLModel]` —— SQLModel 基类；`EntityDiscovery` 从此派生所有 entity

### 2.2 连接信息参数（互斥，至多提供一个）

| 参数 | 提供时行为 | 所有权 |
|---|---|---|
| `url: str` | `Application` 内部 `create_async_engine(url, **engine_kwargs or {"echo": False})` + `async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)` | **Application 拥有** engine；`dispose()` 时释放 |
| `engine: AsyncEngine` | `Application` 包装此 engine，并自造 `async_sessionmaker(engine, ...)` | **调用方拥有** engine；`dispose()` 是 no-op |
| `session_factory: Callable` | `Application` 直接使用此工厂，不自造 | **调用方拥有**；`dispose()` 是 no-op |

**互斥校验**：同时提供 ≥2 个参数时立即 `ValueError`：

```python
ValueError: Provide at most one of: url, engine, session_factory
```

**全缺省（schema-only 模式）**：三者都不提供时合法——`Application` 不持有 engine/session_factory；`.resources` 仍正常构造（GraphQLHandler 接受 `session_factory=None`）；`.session_factory` 属性返回 `None`；执行 GraphQL 查询会在运行期失败。

### 2.3 元数据参数

- `description: str = ""` —— app 描述，出现在 mcp `list_apps` 工具返回
- `query_description: str | None = None` —— GraphQL Query 类型描述
- `mutation_description: str | None = None` —— GraphQL Mutation 类型描述
- `aliases: list[str] | None = None` —— 路由别名列表；构造期校验：
  - 必须是 `list[str]`
  - 每个元素非空
  - 不可与 `name` 重名
  - 跨 app 冲突由 `MultiAppManager` 检测
- `engine_kwargs: dict | None = None` —— 仅当 `url=` 提供时生效；传递给 `create_async_engine`（如 `{"echo": True, "pool_size": 20}`）

### 2.4 构造期副作用

`__init__` 完成后，下列对象必须已构造完毕（同步 eager）：
- `_engine`、`_session_factory`（按互斥规则）
- `_resources: AppResources`，其内部 `GraphQLHandler` / `TypeTracer` / `SDLGenerator` 全部就绪
- `_owns_engine: bool` 按来源规则确定
- `_disposed: bool = False`

---

## 3. 属性契约

### 3.1 `name` / `description` 等元数据

返回构造期 immutable 值。

### 3.2 `resources -> AppResources`

返回构造期 eager 填充的 `AppResources` 实例。每次访问返回同一对象。

**包含字段**（与现有 `src/nexusx/mcp/managers/app_resources.py:14-46` 一致）：
- `name: str`
- `description: str`
- `handler: GraphQLHandler`
- `tracer: TypeTracer`
- `sdl_generator: SDLGenerator`
- `entity_names: set[str]`（property）

### 3.3 `session_factory -> Callable | None`

返回内部 session 工厂。schema-only 模式下返回 `None`。

调用方**不应**自行 dispose 此工厂背后的 engine——所有权归 `Application`（若 owned）或调用方传入方（若 external）。

---

## 4. 异步生命周期契约

### 4.1 `async dispose()`

**幂等性**：可多次调用，第二次起 no-op。

**行为**：
- 若 `_owns_engine=True` 且 engine 未 dispose：`await self._engine.dispose()`，置 `_disposed=True`
- 若 `_owns_engine=False`：no-op
- 若 `_disposed=True`：no-op

**异常**：dispose 过程中 engine.dispose() 抛出的异常会向上传播。调用方可 try/except；下一次 dispose() 仍是幂等 no-op（前提是 `_engine` 已被置为 None 或 `_disposed` 已 True）。

**URL 脱敏**：dispose 失败时的错误消息必须脱敏——错误字符串中不得出现完整 URL（spec FR-013）。

### 4.2 `async __aenter__` / `async __aexit__`

`async with Application(...) as app: ...` 模式：
- `__aenter__` 返回 `self`（资源已在 `__init__` eager 构造，无需额外启动）
- `__aexit__` 调用 `await self.dispose()`

---

## 5. URL 凭据脱敏契约（FR-013）

### 5.1 脱敏触发点

所有从 `Application` 输出到用户的字符串中，URL 凭据必须脱敏：
- `__repr__` / `__str__`
- 错误消息（构造期与 dispose 期）
- 日志（包括 GraphQLHandler 内部 logger）

### 5.2 脱敏规则

输入：`postgresql://user:p4ssw0rd@host:5432/db`
输出：`postgresql://user:***@host:5432/db`

实现路径：SQLAlchemy `URL.render_as_string(hide_password=True)` 或自写正则兜底。

### 5.3 不脱敏的位置

完整 URL 仅出现在：
- 内存中（`self._url` 字段，仅供内部 `create_async_engine` 使用）
- 传递给 `create_async_engine` 的瞬间

---

## 6. 与 `MultiAppManager` 的协作契约

### 6.1 接受 Application 作为输入

```python
from nexusx.mcp import Application, create_mcp_server

blog = Application(name="blog", base=BlogBaseEntity, url=BLOG_DATABASE_URL)
shop = Application(name="shop", base=ShopBaseEntity, url=SHOP_DATABASE_URL)

mcp = create_mcp_server(apps=[blog, shop], name="Multi-App Server")
```

### 6.2 接受 AppConfig 字典作为兼容输入（带弃用警告）

```python
mcp = create_mcp_server(
    apps=[
        {"name": "blog", "base": BlogBaseEntity, "url": BLOG_DATABASE_URL},
    ],
    name="Legacy Form",
)
# 触发：DeprecationWarning("Passing AppConfig dict is deprecated; use Application(...). ...")
```

### 6.3 跨 app 校验仍由 MultiAppManager 负责

`MultiAppManager.__init__` 在 coerce 完所有 Application 后执行：
- 检查 `app.name` 跨 app 不重复
- 检查 `app.aliases` 跨 app 不冲突
- 检查 alias 不与其他 app 的 name 冲突

冲突时立即 `ValueError`，错误信息列出冲突项与可用 app 列表（沿用现有 `multi_app_manager.py:159-161` 风格）。

---

## 7. 不变量（Invariants）

- 构造完成后，`resources` 字段不为 `None`
- 构造完成后，`session_factory` 要么是 `None`（schema-only），要么是有效 `Callable`
- `_owns_engine=True` 时 `_engine` 不为 `None`
- `dispose()` 后再次访问 `resources` 仍合法（不抛异常）；但通过 `resources.handler.execute()` 执行查询的行为未定义（取决于 SQLAlchemy engine.dispose 后的行为）
- `dispose()` 多次调用必须等价于单次调用（幂等）

---

## 8. 不属于 Application 职责的事项

- **跨 app 校验**：跨 app 的 name/alias 冲突检测归 `MultiAppManager`
- **app_name 路由**：mcp 工具调用时按 `app_name` 参数路由归 `MultiAppManager.get_app()`
- **FastMCP lifespan 集成**：归 `create_mcp_server`（PR3）
- **`create_simple_mcp_server` 改造**：本特性不涉及
- **`UseCaseAppConfig` 改造**：本特性不涉及
