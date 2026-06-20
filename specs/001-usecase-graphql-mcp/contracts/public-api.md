# Contract: Public Python API

**Feature**: `001-usecase-graphql-mcp` | **Date**: 2026-06-20

本文档定义新特性对外的 Python 公共 API 契约。所有新增/移除条目都会反映到 `src/nexusx/__init__.py` 与 `src/nexusx/use_case/__init__.py`。

---

## C1. 新增公共 API

### `nexusx.create_use_case_graphql_mcp_server`

```python
def create_use_case_graphql_mcp_server(
    apps: list[UseCaseAppConfig],
    name: str = "nexusx UseCase GraphQL API",
) -> "FastMCP":
    """创建一个 4 层渐进式披露 MCP server，背后是 UseCase GraphQL schema。

    Args:
        apps: 一个或多个 UseCaseAppConfig。每个 config 在 server 启动时
              构造一次 ComposeSchema（eager）。
        name: MCP server 名称，出现在 MCP 协议握手响应中。

    Returns:
        FastMCP 实例。可直接 .run() / 挂到 FastAPI / 嵌套到其它 MCP server。

    Raises:
        ComposeSchemaError: 启动期 schema 生成失败（同名 service、同名方法、
                            不支持的类型、DTO 字段引用 SQLModel 实体等）。
    """
```

**Consumers**:
- 顶层 `src/nexusx/__init__.py` 导出
- demo: `demo/use_case/mcp_server_graphql.py`

---

### `nexusx.build_compose_schema`

```python
def build_compose_schema(app: UseCaseAppConfig) -> ComposeSchema:
    """为一个 UseCaseAppConfig 构造 ComposeSchema。

    适用于：
    - 用户想直接拿 schema 给自定义 GraphiQL / 自定义 MCP 入口
    - 测试中需要单独检查 schema 内容

    Args:
        app: 单个 UseCaseAppConfig。

    Returns:
        ComposeSchema 实例。

    Raises:
        ComposeSchemaError: schema 生成失败。
    """
```

**Consumers**:
- 顶层 `src/nexusx/__init__.py` 导出
- `create_use_case_graphql_mcp_server` 内部调用（不暴露给消费者）

---

### `nexusx.ComposeSchema`（类型）

```python
class ComposeSchema:
    """UseCaseService 派生出的 GraphQL schema 产物。

    不可变。一旦构造完成，registry 不再修改。
    """

    app_name: str
    registry: dict[str, TypeInfo]  # readonly

    def render_introspection(self) -> dict[str, Any]: ...
    def render_sdl(self) -> str: ...
    def render_method_sdl(self, service_name: str, method_name: str) -> str | None: ...
```

---

### `nexusx.ComposeSchemaError`（异常）

```python
class ComposeSchemaError(Exception):
    """ComposeSchema 构造期错误的基类。

    Subclasses:
        DuplicateServiceError: 同名 service
        DuplicateMethodError: 同 service 同名方法
        UnsupportedTypeError: 方法参数或返回类型不被支持
        SQLModelInDtoFieldError: DTO 字段引用了 SQLModel 实体（违反既有约定）
        MissingReturnAnnotationError: 方法缺少返回类型注解
    """
```

---

## C2. 既有公共 API：**保持不变**

以下条目签名与行为均不改变（FR-009、FR-010a）：

| Symbol | Module |
|--------|--------|
| `UseCaseService` | `nexusx.use_case.business` |
| `BusinessMeta` | `nexusx.use_case.business` |
| `@query` / `@mutation` | `nexusx.use_case.business` |
| `FromContext` | `nexusx.use_case.context` |
| `UseCaseAppConfig` | `nexusx.use_case.types` |
| `create_use_case_router` | `nexusx.use_case.router` |
| `create_jsonrpc_router` | `nexusx.use_case.jsonrpc` |
| `create_use_case_voyager` | `nexusx.voyager.create_voyager` |
| `SelectionError` | `nexusx.use_case.selection`（或既有位置） |

---

## C3. 移除的公共 API（FR-010）

以下条目**不再导出**，导入会抛 `ImportError`（无 shim、无别名）：

| Symbol | 旧路径 | 替代 |
|--------|--------|------|
| `create_use_case_mcp_server` | `nexusx` / `nexusx.use_case` / `nexusx.use_case.server` | `create_use_case_graphql_mcp_server` |
| `create_use_case_flat_server` | `nexusx` / `nexusx.use_case` / `nexusx.use_case.flat_server` | `create_use_case_graphql_mcp_server` |

迁移路径详见 `docs/migrations/2.0-use-case-graphql.md`。

---

## C4. `src/nexusx/__init__.py` 导出契约（2.0 后）

```python
from nexusx.use_case import (
    FromContext,
    SelectionError,
    UseCaseAppConfig,
    UseCaseService,
    create_jsonrpc_router,
    create_use_case_graphql_mcp_server,   # NEW
    create_use_case_router,
    build_compose_schema,                  # NEW
    ComposeSchema,                         # NEW
    ComposeSchemaError,                    # NEW
)
```

被移除的旧导出（与 C3 对应）：
- ~~`create_use_case_mcp_server`~~
- ~~`create_use_case_flat_server`~~

---

## C5. 版本号契约

`pyproject.toml`:
```toml
[project]
version = "2.0.0"
```

`CHANGELOG.md`（如不存在则新建）首条：
```
## 2.0.0 - 2026-XX-XX

### BREAKING
- Removed `create_use_case_mcp_server` (use `create_use_case_graphql_mcp_server`).
- Removed `create_use_case_flat_server` (use `create_use_case_graphql_mcp_server`).
- See docs/migrations/2.0-use-case-graphql.md for migration guide.

### Added
- `create_use_case_graphql_mcp_server` — UseCase GraphQL MCP (4-layer progressive disclosure).
- `build_compose_schema`, `ComposeSchema`, `ComposeSchemaError` — direct schema access.
```
