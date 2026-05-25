# Changelog

## 2.2.0

### Bug Fix: DefineSubset PK/FK 字段处理

修复 DefineSubset 的两个问题：PK 字段不再需要手动声明即可支持 ONETOMANY 关系的隐式 auto-loading；显式声明的 FK 字段不再被强制 `exclude=True`。

**Changes:**
- `src/nexusx/subset.py`: 新增 `_get_pk_field_names()` 自动检测主键字段并注入 SubsetMeta；移除 `_extract_field_infos` 中对所有 FK 字段的 `exclude=True` 标记，显式声明的 FK 字段现在正常出现在序列化输出中
- 新增回归测试覆盖 PK 自动包含、FK 可见性、omit_fields 场景

### Bug Fix: describe_service 类型提示引导

`describe_service` 返回的 methods 信息中增加 hint，引导 LLM 读取 `types` 字段获取完整的 DTO 类型定义，避免 agent 直接从 method signature 推断类型结构。

**Changes:**
- `src/nexusx/use_case/introspector.py`: method description 增加 hint 文本

### Bug Fix: Service 缺失 docstring 时自动摘要

`UseCaseService` 子类未提供 docstring 时，`list_services` 和 `describe_service` 现在自动从方法的 docstring 摘要生成 service 描述。

**Changes:**
- `src/nexusx/use_case/introspector.py`: 新增 `_summarize_from_methods` fallback 逻辑

### Feature: Resource 使用说明书

新增 `Resource` 类的使用说明书，描述如何在 MCP context 中暴露资源供 LLM 使用。

**Changes:**
- 新增 `docs/resource_manual.md`

### Feature: ER Diagram Builder 校验

ER diagram builder 对 `Relationship.target` 为 model-like 类型（SQLModel/Pydantic BaseModel）时进行校验，防止因 target 类型错误导致渲染崩溃。

**Changes:**
- `src/nexusx/er_diagram.py`: 新增 target 类型校验
- 新增回归测试

### Docs: 知乎文章 Demo

新增 `demo/zhihu_article/` 目录，包含完整的订单系统 demo（models/dtos/services/mcp_server）和 MCP-first 定位的知乎文章。

## 2.1.0

### New Feature: UseCase MCP Selection 投影

`call_use_case` 新增 `selection` 参数，允许 AI agent 指定返回哪些字段，优化 MCP 响应 payload 大小。使用类似 GraphQL 的 rootless selection 语法，如 `{ id title owner { name } }`。

**用法：**

```python
# describe_service 返回 selection_usage 元数据和每个方法的 selection_supported / selection_example
# call_use_case 传递 selection 过滤响应
result = await call_use_case(
    app_name="project",
    service_name="SprintService",
    method_name="get_sprint",
    params='{"sprint_id": 1}',
    selection="{ id task_count contributors { name } }",
)
```

**Selection 规则：**
- 仅支持返回 Pydantic BaseModel / list[BaseModel] 的方法
- 嵌套 DTO 字段必须提供子选择
- 标量、dict、Any 字段不可有子选择
- 不支持 GraphQL arguments

**Changes:**
- `use_case/selection.py`: 新增 `SelectionError`、`apply_selection`、`parse_selection`、`build_subset_model` — 解析 selection 字符串并动态构建 Pydantic 子集模型进行投影
- `use_case/introspector.py`: `describe_service` 输出新增 `selection_usage`（format/source/rules）和每个方法的 `selection_supported` / `selection_example`
- `use_case/server.py`: `call_use_case` 新增 `selection` 参数；`describe_service` hint 包含 selection 使用提示；新增 `_get_return_annotation`
- `use_case/__init__.py`、`__init__.py`: 导出 `SelectionError`
- 新增 16 个测试覆盖 selection 投影和错误场景

## 2.0.0
rename to nexusx

## 2.0.1

- fix primitive value in loader relationships

## 1.10.1

### Bug Fix: UseCase MCP 参数类型强转

`call_use_case` 通过 `json.loads()` 解析参数，但 JSON 只产出原生类型（str/int/float/bool/list/dict/None）。当 UseCaseService 方法参数声明为 `uuid.UUID`、`datetime.*`、`Decimal` 或 `BaseModel` 时，值类型不匹配会导致运行时 TypeError。新增 Pydantic TypeAdapter 在调用前自动将 JSON 原生值强转为方法声明的参数类型。

**Changes:**
- `src/nexusx/use_case/server.py`: 新增 `_coerce_value` 和 `_coerce_kwargs`，在 `call_use_case` 中 `json.loads()` 后、方法调用前执行类型强转
- `tests/test_use_case.py`: 新增 `TypeCoercionService` 及 14 个测试用例，覆盖 UUID/datetime/date/time/Decimal/Optional/list/BaseModel/mixed types 场景

## 1.10.0

### Feature: GraphQL DateTime 参数支持与 UTC 归一化

新增 Python `datetime` 到 GraphQL `DateTime` scalar 的映射，并在 GraphQL 参数构建阶段将传入的 timezone-aware DateTime 字符串转换为 UTC aware `datetime`。

**Behavior:**
- 支持 `2026-05-19T10:30:00Z`、`2026-05-19T10:30:00+00:00` 等 UTC 字符串
- 支持 `2026-05-19T18:30:00+08:00` 等带 offset 字符串，并统一归一化为 UTC
- 拒绝 `2026-05-19T10:30:00` 等无时区 naive DateTime 字符串，避免跨时区语义歧义

**Changes:**
- `type_converter.py`: 新增 `datetime -> DateTime` scalar 映射
- `introspection.py`: `__schema` introspection 暴露 `DateTime` scalar
- `execution/argument_builder.py`: 使用 Pydantic `AwareDatetime` 校验 DateTime 参数并归一化到 UTC
- `pyproject.toml`: 显式声明 `pydantic>=2.0`
- 新增 DateTime 参数类型、UTC 归一化和 naive 拒绝的回归测试

## 1.9.3

### Refactoring: Voyager 图布局改为 Service Cluster 模式

将 Voyager 图从「Tags | Routes | Schema」三列布局改为「Services(methods) | Schema」布局。每个 UseCaseService 渲染为一个独立的 cluster，内部直接包含其 methods，不受 show_module 开关影响。选中某个 service 时只显示该 service cluster 及其关联的 schemas。

**Changes:**
- `voyager/render.py`: 新增 `render_service_clusters`，合并原 Tags + Routes 为 service cluster；无选中 tag 时用 Services 外层包裹
- `voyager/use_case_voyager.py`: 重写过滤逻辑 `_filter_by_selected_tags`，按选中 service 做 BFS 过滤可达 schemas；移除不再需要的 `tag_route` links

### Chore: Skill 模板优化（Phase 0~4）

四阶段 skill 模板重大改进：Phase 1 改为纯实体无方法；Phase 2 引入 `_mount()` 桥接 classmethod 协议；Phase 3 改用 `create_use_case_router()` 自动生成路由；Phase 4 改用 `@hey-api/openapi-ts` 生成 SDK。新增 user service 模板、pytest 配置、uv.lock。

**Changes:**
- `skill/skill.md`: Phase 0 新增 Service 切分候选方案讨论流程；Phase 1 移除 @query/@mutation 占位；Phase 2 新增 `_mount()` 模式；Phase 3 改用 `create_use_case_router()`；Phase 4 改用 `@hey-api/openapi-ts`
- `skill/template/src/models.py`: 纯实体定义，方法挂载改为从 methods.py `_mount()`
- `skill/template/src/service/`: 新增 user 模板目录，sprint/task 补充 mutation 方法
- `skill/template/pyproject.toml`: 新增 pytest/pytest-asyncio 可选依赖和配置

## 1.9.2

### Bug Fix: 自引用 DTO 导致 `update_forward_refs` 无限递归

修复 `voyager/type_helper.update_forward_refs` 遇到自引用 DTO（如 `parent: Self | None`）时无限递归崩溃的问题。

**根因：** 自引用模型的字段 annotation 指向自身类型，递归遍历时缺少已访问集合，导致循环引用无法终止。

**Changes:**
- `voyager/type_helper.py`: `update_forward_refs` 新增 `_visited: set` 参数，跳过已处理的类型
- `voyager/voyager_context.py`: 补充缺失的 `UseCaseService` 导入
- 新增 `tests/test_voyager_selfref.py`：覆盖自引用 DTO 场景

### Chore: Lint 修复

- 移除未使用的 `mutation` 导入（`demo/use_case/mcp_server.py`）
- 替换可变默认参数 `tags: list[str] = []` → `None`（`tests/test_introspection.py`）
- 清理多余空行、简化 `getattr` 调用、整理 import 顺序

## 1.9.1

### Bug Fix: Inline Literal 参数类型丢失

修复 `ArgumentBuilder._extract_value` 将 GraphQL inline literal 的 `Int` / `Float` 参数转为 `str` 的问题。例如 `query { users(limit: 5) }` 中 `limit` 传入方法时变成了 `"5"` 而非 `5`。

**根因：** graphql-core 的 `IntValueNode.value` 和 `FloatValueNode.value` 属性返回字符串表示。`_extract_value` 对所有带 `.value` 的节点直接返回 `node.value`，未做类型转换。`QueryParser._value_node_to_python` 有正确的 isinstance 分发，但 `ArgumentBuilder` 未复用该逻辑。

**影响范围：** 所有通过 inline literal 传入的 int/float 参数（包括列表和嵌套对象中的值）。通过 GraphQL variables 传入的参数不受影响。

**Changes:**
- `execution/argument_builder.py`: `_extract_value` 改用 `isinstance` 检查 `IntValueNode` / `FloatValueNode` 等类型，与 `QueryParser._value_node_to_python` 保持一致
- 新增 `tests/test_argument_types.py`：10 个测试覆盖 int、float、string、boolean、null、list、nested object 的类型保持，以及 end-to-end 验证

## 1.9.0

### New Feature: UseCaseService 自动生成 FastAPI Router

新增 `create_router()` 函数，从 `UseCaseService` 的 `@query`/`@mutation` 方法自动生成 FastAPI POST 路由，复用 `UseCaseAppConfig` 配置，与 MCP 服务共享同一套业务逻辑。

```python
from nexusx import UseCaseAppConfig, create_use_case_router

router = create_use_case_router(
    UseCaseAppConfig(
        name="project",
        services=[UserService, TaskService],
    )
)
app.include_router(router)
```

**特性：**
- 全部 POST 方法，参数通过 request body 传递
- URL 按 service snake_case 分组：`/api/user_service/list_users`
- `FromContext` 参数通过 `context_extractor(request)` + `Depends` 自动注入
- 支持 `enable_mutation=False` 过滤 mutation 方法
- 支持自定义 `prefix` 和 `url_mapper`
- 完整 OpenAPI 文档（tags、description、response_model）

**新增文件：**
- `use_case/router.py` — `create_router()` 及参数分类、请求模型动态生成、handler 工厂

**Changes：**
- `use_case/router.py`: 新增 `_classify_params`、`_build_request_model`、`_make_handler`、`create_router`
- `use_case/__init__.py`: 导出 `create_router`
- `__init__.py`: 导出 `create_use_case_router`

**Demos：**
- `demo/use_case/fastapi_auto.py` — 自动生成 demo，含 `FromContext` 示例（`ReportService`，`X-User-Id` header 注入）

**Tests：**
- `tests/test_use_case_router.py` — 23 个测试覆盖路由结构、参数处理、FromContext 注入、mutation 过滤、OpenAPI 文档

## 1.8.0

### Voyager ER Diagram: 关系字段重构

ER diagram 的关系展示方式从「FK 字段出发」改为「relationship name 字段出发」。边从 `owner: User` 这样的 relationship 字段出发连到目标实体，而非从 `user_id` 这样的 FK 字段出发。

**Changes:**
- `voyager/er_diagram_dot.py`: `_get_entity_fields()` 新增 relationship 字段（`name: TargetType`）；`_add_relationship_link()` source anchor 从 `fk_field` 改为 `rel_info.name`；`fk_set` 替换为 `rel_name_set`
- `voyager/templates/dot/link.j2`: 去掉硬编码的 `:e` / `:w` 端口方向，由 Graphviz 自动选择最优端口
- `README.md`: 重写开头，强调"一套模型，四种消费路径"定位；Mermaid 流程图改为星型结构
- `voyager/web/manifest.webmanifest`: 新增 PWA manifest 文件
- `voyager/web/index.html`: manifest 路径改为 static mount 路径；Google Fonts 替换为 `fonts.loli.net` 镜像

## 1.7.0

### Voyager ER Diagram: 关系字段重构（内部版本）

与 1.8.0 内容相同，作为快速迭代版本发布。

## 1.6.0

### New Feature: Voyager 支持 resolve/post/expose/send 元信息显示

Voyager 新增 `Pydantic Resolve Meta` 开关，开启后可在 DTO 字段上显示 `● resolve`、`● post`、`● expose as`、`● send to`、`● collectors` 彩色标记，直观呈现 Core API 模式的数据流设计。

**检测内容：**
- `resolve_*` 方法和 `AutoLoad` 注解 → resolve 标记
- `post_*` 方法 → post 标记
- `ExposeAs` 注解 → expose as 标记
- `SendTo` 注解 → send to 标记
- `Collector` 参数 → collectors 标记

**Changes:**

- `voyager/type_helper.py`: 新增 `analysis_pydantic_resolve_fields()` 函数，修改 `get_pydantic_fields()` 调用它
- `voyager/type.py`: `CoreData` 新增 `show_pydantic_resolve_meta` 字段
- `voyager/use_case_voyager.py`: `render_dot()` 和 `dump_core_data()` 传递 flag 到 Renderer
- `voyager/voyager_context.py`: `get_option_param()` 动态检测元数据；`get_filtered_dot()` / `get_core_data()` / `render_dot_from_core_data()` 传递 flag

## 1.5.0

### Breaking Change: UseCase 方法必须使用 `@query` / `@mutation` 装饰器

`UseCaseService` 的方法不再自动收集裸 `@classmethod`。必须使用 `@query` 或 `@mutation` 装饰器标记方法，才会被 `BusinessMeta` 元类发现并暴露为 MCP 工具。

**迁移：**

```python
# Before (1.4.0)
class UserService(UseCaseService):
    @classmethod
    async def list_users(cls) -> list[UserDTO]:
        ...

# After (1.5.0)
from nexusx import query, mutation

class UserService(UseCaseService):
    @query
    async def list_users(cls) -> list[UserDTO]:
        ...

    @mutation
    async def create_user(cls, name: str) -> UserDTO:
        ...
```

### New Features

- **`@query` / `@mutation` 装饰器** — `UseCaseService` 方法必须显式标记类型，`__use_case_methods__` 存储完整元数据（`method`, `kind`, `description`）
- **`enable_mutation` 参数** — `UseCaseAppConfig` 新增 `enable_mutation: bool = True`，控制 mutation 方法的可见性
- **三层 mutation 过滤** — 当 `enable_mutation=False` 时，`list_services`（方法计数）、`describe_service`（方法列表）、`call_use_case`（执行拦截）均过滤 mutation
- **`kind` 字段** — `describe_service` 输出的方法信息中包含 `kind` 字段（`"query"` 或 `"mutation"`）
- **`description` 属性** — `@query`/`@mutation` 装饰器自动提取 docstring 作为 description

### Changes

- `decorator.py`: `query()` / `mutation()` 增加 `_graphql_query_description` / `_graphql_mutation_description` 属性
- `use_case/business.py`: `BusinessMeta` 只收集有装饰器标记的方法，`__use_case_methods__` 值类型从 `dict[str, Any]` 变为 `dict[str, dict[str, Any]]`
- `use_case/types.py`: `UseCaseAppConfig` 新增 `enable_mutation` 字段
- `use_case/manager.py`: `UseCaseResources` 新增 `enable_mutation` 字段并从 config 传递
- `use_case/introspector.py`: `describe_service()` 方法信息增加 `kind` 字段
- `use_case/server.py`: 三层 `enable_mutation` 过滤逻辑

## 1.4.0

### Breaking Change: Remove `RpcServiceConfig`

`RpcServiceConfig` TypedDict is removed. `create_rpc_mcp_server` and `create_rpc_voyager` now accept a plain list of `RpcService` subclasses instead of config dicts.

- Service name is derived from `cls.__name__` (e.g. `TaskService` → `"TaskService"`)
- Service description is derived from `cls.__doc__`

**Migration:**

```python
# Before
from nexusx import RpcServiceConfig, create_rpc_mcp_server

mcp = create_rpc_mcp_server(
    services=[
        RpcServiceConfig(name="task", service=TaskService, description="..."),
        RpcServiceConfig(name="sprint", service=SprintService, description="..."),
    ],
)

# After
from nexusx import create_rpc_mcp_server

mcp = create_rpc_mcp_server(
    services=[TaskService, SprintService],
)
```

## 1.3.3

### Breaking Change: Remove `Loader(str)` Support

Remove the string-based `Loader('relationship_name')` pattern that performed ErManager lookup at resolve time. Only `Loader(DataLoaderClass)` and `Loader(async_callable)` are now supported.

**Migration:**

```python
# Before
def resolve_owner(self, loader=Loader("owner")):
    return loader.load(self.owner_id)

# After — use DataLoader class or async callable
def resolve_owner(self, loader=Loader(UserLoader)):
    return loader.load(self.owner_id)
```

Note: Implicit auto-loading (field name matches relationship + compatible type) already handles the common case without any `resolve_*` method.

**Changes:**
- Remove `isinstance(dep_val, str)` branch from `Resolver._resolve_dependency`
- Remove string-based examples from `Loader` docstring
- Remove `TestLoaderWithStringName`, `TestResolverLoader`, `TestCustomRelationshipResolve` test classes
- Update `TestClassMetaCache` to use async callable instead of string dependency

## 1.3.2

### Bug Fix: Introspection defaultValue Format

Fix `IntrospectionGenerator` default value serialization from Python `repr()` to JSON format (`json.dumps`), ensuring valid GraphQL literals in introspection results. Previously, `buildClientSchema` from graphql-js (used by GraphiQL) would fail with syntax errors due to Python-formatted strings like `'planning'` (single quotes) and `None` instead of `"planning"` and `null`.

| Before (`repr`) | After (`json.dumps`) |
|------------------|----------------------|
| `'default'` | `"default"` |
| `None` | `null` |
| `True` | `true` |
| `False` | `false` |
| `5` | `5` |

- Add `_format_default_value` static method to `IntrospectionGenerator`
- Add `TestDefaultValueFormat` test class with 10 tests covering string, None, int, float, bool, list defaults and end-to-end `buildClientSchema` validation

### Documentation

- Update `llms-full.txt` to reflect current v1.3.1 API surface, including Core API, RPC + Voyager mode documentation

## 1.3.1

### Refactoring: Constant Extraction

Replace magic strings with named constants across the codebase.

| Constant | Used in |
|----------|---------|
| `QUERY_META_PARAM` | `introspection`, `sdl_generator` |
| `RELATIONSHIPS_ATTR` | `relationship` |
| `RESOLVE_PREFIX` / `POST_PREFIX` | `resolver`, `subset` |
| `RPC_METHODS_ATTR` | `rpc/business`, `rpc/introspector`, `rpc/server` |

### Demo Restructure

Consolidate all demo applications under `demo/` with domain-based sub-packages:

| Before | After |
|--------|-------|
| `auth_demo/` | `demo/auth/` |
| `demo/app.py` | `demo/blog/app.py` |
| `demo_multiple_app/` | `demo/multi_app/` |
| `demo/rpc_*.py` | `demo/rpc/` |

- Add `@query` / `@mutation` methods for User and Task entities in `demo/blog/models.py`
- Update all import paths to match new structure

### Voyager Enhancements

- **ER Diagram method discovery**: `@query` / `@mutation` methods are now shown on entity SchemaNodes
- **DefineSubset source tracking**: Voyager generates subset → source entity links for DTOs
- **RPC method source resolution**: `get_source_code` / `get_vscode_link` support `service.method` format in addition to `module.ClassName`

### Documentation

- Rewrite README tagline to emphasize progressive framework positioning and `DefineSubset` declarative capabilities
- Add mermaid flowchart illustrating P1 (ER Diagram) → P2 (GraphQL API) → P3 (Declarative Assembly) progression

## 1.3.0

### New Feature: Voyager Visualization

Migrated fastapi-voyager's interactive visualization into nexusx, decoupled from FastAPI route introspection. Visualizes RPC service structure and ER diagrams from ErManager.

**New package `nexusx.voyager`:**

| Export | Purpose |
|--------|---------|
| `create_rpc_voyager` | Create a FastAPI ASGI sub-app for interactive visualization |

**Voyager features:**
- RPC service graph: Service→Tag, Method→Route, DTO→SchemaNode mapping
- ER diagram: renders entities and relationships from ErManager
- DOT graph rendering via Jinja2 templates + Graphviz WASM frontend
- REST endpoints: `/dot`, `/dot-search`, `/er-diagram`, `/source`, `/vscode-link`
- Configurable: module colors, field visibility, theme color, initial page policy
- GZip middleware support

**ErManager new public methods:**
- `get_all_entities()` — return all registered entity classes
- `get_all_relationships()` — return full relationship registry

**Public API:**
- `create_rpc_voyager` accepts `list[RpcServiceConfig]` (reusable with `create_rpc_mcp_server`)

### Demos

- **`demo/rpc_voyager_demo.py`** — Voyager UI mounted on FastAPI, with 8 entities and 12 relationships (port 8008)
- Demo entities expanded: Project, Sprint, Task, User, Comment, Label, TaskLabel, Tag
- Update `start_all.sh` with RPC Voyager (port 8008)

### Dependencies

- Add `jinja2>=3.0` for DOT template rendering

## 1.2.0

### New Feature: RPC Services

Business service classes with auto-discovery, SDL introspection, and dual serving via MCP and web frameworks.

**New package `nexusx.rpc`:**

| Export | Purpose |
|--------|---------|
| `RpcService` | Base class — subclasses declare `async classmethod`s, auto-discovered by `BusinessMeta` metaclass |
| `create_rpc_mcp_server` | Create an independent FastMCP server exposing services as progressive-disclosure tools |
| `RpcServiceConfig` | Service registration config (name, service class, description) |

**RpcService features:**
- `BusinessMeta` metaclass scans for public `async classmethod`s, excludes `_`-prefixed and `get_tag_name`
- `get_tag_name()` returns OpenAPI-compatible tag name (`SprintService` → `"sprint"`)
- `ServiceIntrospector` generates SDL-style method signatures and DTO type definitions
- FK fields from `DefineSubset` DTOs are hidden from SDL output
- `_type_to_sdl_name()` converts Python type annotations to SDL types (`list[int]` → `[Int!]!`, `X | None` → `X`)

**MCP server — three-layer progressive disclosure:**

| Tool | Purpose |
|------|---------|
| `list_services()` | Discover available services and method counts |
| `describe_service(service_name)` | Method signatures (SDL) + DTO type definitions |
| `call_rpc(service_name, method_name, params)` | Execute a method with JSON params |

**Web framework integration:**
- Same `RpcService` classes serve both MCP and FastAPI routes
- Routes are thin wrappers calling service classmethods
- OpenAPI tags derived from `get_tag_name()` for automatic grouping in `/docs`

### Demos

- **`demo/rpc_mcp_server.py`** — RPC MCP server with UserService, TaskService, SprintService (stdio + HTTP)
- **`demo/rpc_fastapi.py`** — FastAPI routes calling the same RPC services, demonstrating dual-serving pattern
- Update `start_all.sh` with RPC MCP (port 8006) and RPC FastAPI (port 8007)

### Tests

- Add `tests/test_rpc.py` — 41 tests covering `BusinessMeta` discovery, SDL type conversion, `ServiceIntrospector`, MCP tool integration

### Documentation

- Add "RPC Services" section to README with service definition, MCP exposure, and web framework embedding examples
- Update README quick start table and reading order


## 1.1.1

### New Features

- **`build_dto_select`** — new public function that generates a `select(*columns)` statement from a DefineSubset DTO, querying only the scalar columns the DTO needs. Relationship field names are filtered automatically. Accepts an optional `where` parameter for SQLAlchemy filter expressions.

### Documentation & Demos

- Simplify Core API demo endpoints to use `build_dto_select` + `dict(row._mapping)` pattern instead of manual field-by-field DTO construction.

## 1.1.0

### New Features

- **`Relationship.target` supports `list[Entity]`** — one-to-many relationships can now use `target=list[Entity]` instead of the separate `is_list=True` flag. The `is_list` attribute becomes a computed property derived from the target type. A new `target_entity` property extracts the bare entity class, stripping the `list[...]` wrapper.
- **Many-to-many relationship support** — added `Article`/`Reader` many-to-many test fixtures in `conftest.py` and comprehensive loader factory tests covering `create_many_to_many_loader` and `create_page_many_to_many_loader`.
- **MCP supports `session_factory`** — `AppConfig` and `SingleAppManager` now accept an optional `session_factory` parameter, which is forwarded to `GraphQLHandler` to enable DataLoader relationship loading in MCP services.

### Bug Fixes

- **Many-to-many loader queries use `session.execute()`** — replaced `session.exec()` with `session.execute()` for raw `Table` and subquery/aggregate queries in `create_many_to_many_loader` and `create_page_many_to_many_loader`. `exec()` unwraps multi-column rows into scalars, which loses column data needed for join table resolution.

### Documentation & Demos

- Add `CLAUDE.md` and `llms-full.txt` for project-level AI context.
- Add paginated GraphQL demo application (`demo/app_paginated.py`).
- Update `start_all.sh` to include the new paginated demo service.


## 1.0.0

### New Public API: Core API Mode

nexusx now provides a complete Core API mode alongside GraphQL, enabling DTO-first response assembly for REST endpoints and service layers.

**New exports from `nexusx`:**

| Export | Purpose |
|--------|---------|
| `ErManager` | Central hub — discovers entities from SQLModel base, manages relationships, produces Resolvers |
| `Loader` | Declare DataLoader dependencies in `resolve_*` method signatures |
| `DefineSubset`, `SubsetConfig` | Create independent DTO models from SQLModel entities |
| `ExposeAs`, `SendTo`, `Collector` | Cross-layer data flow (parent→descendant and descendant→ancestor) |
| `Relationship`, `ErDiagram` | Custom non-ORM relationships and Mermaid ER diagram generation |

**Core API usage:**

```python
from sqlmodel import SQLModel
from nexusx import DefineSubset, ErManager, Loader

er = ErManager(base=SQLModel, session_factory=async_session)
Resolver = er.create_resolver()
result = await Resolver(context={"user_id": 1}).resolve(dtos)
```

### New Features

- **`ErManager`** — replaces internal `LoaderRegistry`. Accepts `base` (auto-discovers all `table=True` SQLModel subclasses) or `entities` (explicit list). Provides `create_resolver()` which returns a Resolver **class** bound to the entity graph.
- **Implicit auto-loading** — DTO fields matching ORM relationship names are loaded automatically via DataLoader. No annotation needed; the framework checks field name match + type compatibility with `is_compatible_type`.
- **`is_compatible_type`** — validates that a DTO type is compatible with the relationship's target entity before auto-loading, preventing silent type mismatches at runtime.
- **Resolver metadata caching** — `_ClassMeta` cache avoids repeated `dir()` + `inspect.signature()` calls. Method parameters are analyzed once per class, reused across all instances.
- **`scan_expose_fields` / `scan_send_to_fields` caching** — module-level caches for field metadata scanning.
- **`_node_collectors` cleanup** — per-node collector entries are released immediately after traversal, preventing memory growth during large tree resolution.
- **`_extract_sort_field` supports `desc()` / `asc()`** — handles SQLAlchemy `UnaryExpression` in `order_by` clauses.
- **`get_loader_by_name` ambiguity warning** — logs a warning when multiple entities share the same relationship name.
- **FK field lookup from registry** — `query_meta` uses actual FK field names from `ErManager` instead of assuming `{relationship_name}_id` convention.
- **DataLoader factories use closures** — cleaner pattern; configuration captured in closure scope instead of class attributes.

### Removed from Public API

| Removed | Replacement |
|---------|-------------|
| `AutoLoad` | Implicit auto-loading (field name matches relationship + compatible type) |
| `LoaderRegistry` | `ErManager` (alias `LoaderRegistry = ErManager` kept for internal compat) |
| `Resolver` (direct export) | `er.create_resolver()` returns a bound Resolver class |

### Migration from 0.14.0

The 0.14.0 Core API exports were not yet part of a stable release. If you used them from the feature branch:

```python
# Before (0.14.0 feature branch)
from nexusx import LoaderRegistry, Resolver, AutoLoad
registry = LoaderRegistry(entities=[User, Task], session_factory=sf)
result = await Resolver(registry).resolve(dtos)

# After (1.0.0)
from nexusx import ErManager
er = ErManager(base=SQLModel, session_factory=sf)
Resolver = er.create_resolver()
result = await Resolver().resolve(dtos)
```

`AutoLoad()` annotations can be removed — implicit auto-loading handles it when field names match relationships.

### GraphQL Mode

No breaking changes. All existing `GraphQLHandler` usage works unchanged.


## 0.13.0

- Add `AutoQueryConfig` for auto-generating `by_id` and `by_filter` queries for SQLModel entities
- `by_id`: find a single entity by primary key
- `by_filter`: filter entities by field values with auto-generated `FilterInput` type
- Pass `auto_query_config` to `GraphQLHandler` to enable; handler discovers all entity subclasses automatically
- Update README.md with Auto-Generated Standard Queries documentation

## 0.12.0
- migrate from mcp to fastmcp

## 0.11.0

- Update README.md to emphasize rapid development of minimum viable systems
- Add 30-Second Quick Start section for quick onboarding
- Embed GraphiQL HTML template into the library
- Add `get_graphiql_html()` method to `GraphQLHandler` with configurable `endpoint` parameter

## 0.10.0

- add `allow_mutation` option to `create_mcp_server` to enable mutation support in the generated GraphQL server. This allows clients to perform create, update, and delete operations on the data models defined in the SQLModel schema.
