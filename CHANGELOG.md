# Changelog

## 3.7.0

### New Feature: 自包含 `Application` 类（specs/009-app-self-contained）

引入 `nexusx.mcp.Application` 作为 MCP 体系里"业务应用"的最小可导出单元。一个 `Application` 封装 SQLModel `base` + 数据库连接信息（`url` / `engine` / `session_factory` 三选一或全缺）+ GraphQL 元数据，可作为独立 Python 包发布（`pip install blog-app`），再由合并项目组装到 `create_mcp_server(apps=[...])`——把"业务应用的 schema/连接定义"从"运行它的 MCP server"里彻底解耦出来。

**关键设计：**
- **资源所有权按来源判定**：`url=` 路径下 Application 自造 engine 并拥有，`dispose()` 释放；`engine=` / `session_factory=` 路径下视为外部资源、不拥有，`dispose()` no-op。避免 double-dispose / 错释放外部 engine / 资源泄漏三类坑。
- **三种连接方式互斥**：构造期校验，多传抛 `ValueError("Provide at most one of: url, engine, session_factory")`。
- **schema-only 模式**：完全不传连接参数也可构造，仅做 schema 内省（entity_names / SDL）。这是"应用作为包导出"的关键场景——包作者不知道用户的 DB URL。
- **幂等 dispose**：`if self._disposed: return`，三个触发出口（MCP server lifespan shutdown / `async with Application(...)` / 显式 `await dispose()`)重叠时安全。
- **URL 凭据脱敏**：`__repr__` 和错误消息里的 URL 自动把密码替换为 `***`（借力 SQLAlchemy `make_url().render_as_string(hide_password=True)`）。
- **跨 app 名称冲突在构造期失败**：`MultiAppManager` 在初始化时校验重名 / alias 冲突，比运行期失败好排查。

**用法速览：**

```python
from nexusx.mcp import Application, create_mcp_server

# 单 app 独立使用（schema 内省 + 直接 query）
blog = Application(name="blog", base=BlogBase, url="sqlite+aiosqlite:///blog.db")
print(blog.resources.entity_names)
result = await blog.resources.handler.execute("{ users { id name } }")

# 多 app 合并到 MCP server
mcp = create_mcp_server(apps=[blog, shop], name="Gateway")
mcp.run()  # lifespan 退出时自动 dispose 所有 owned engines
```

**Changes：**
- `src/nexusx/mcp/application.py`: 新增（288 行）—— `Application` 类 + `_redact_url` + `_coerce_to_application` + `lifespan_dispose_hook`
- `src/nexusx/mcp/managers/multi_app_manager.py`: 改为消费 `Application` 对象；dict 输入 transparent 转换 + 警告；构造期校验跨 app 名称冲突
- `src/nexusx/mcp/server.py`: `create_mcp_server` 接线 FastMCP lifespan → `manager.dispose()`
- `src/nexusx/mcp/__init__.py`: 导出 `Application`
- `demo/{auth,blog,multi_app}/mcp_server.py` + `skills/nexusx-4phase/template/src/main.py`: 全部迁移到 `Application` 形式
- `docs/api/api_mcp.{md,zh.md}` + `docs/advanced/mcp_service.{md,zh.md}`: 同步更新
- `tests/mcp/test_application.py` (396) / `test_dict_compat.py` (109) / `test_multi_app_lifespan.py` (92): 新增；`test_multi_app_manager.py`: fixture 迁移

---

### Deprecation: dict-based `AppConfig` 迁移到 `Application`（specs/009-app-self-contained）

旧 dict 形式（`{"name": ..., "base": ..., "url": ...}`）**仍然工作**，但每次构造会抛 `DeprecationWarning`。dict 形式将在 **3.8.0** 移除。

**迁移示例：**

```python
# Before (deprecated)
from nexusx.mcp import create_mcp_server

create_mcp_server(
    apps=[
        {"name": "blog", "base": BlogBase, "url": "sqlite+aiosqlite:///blog.db"},
        {"name": "shop", "base": ShopBase, "url": "sqlite+aiosqlite:///shop.db"},
    ],
    name="Gateway",
)

# After
from nexusx.mcp import Application, create_mcp_server

create_mcp_server(
    apps=[
        Application(name="blog", base=BlogBase, url="sqlite+aiosqlite:///blog.db"),
        Application(name="shop", base=ShopBase, url="sqlite+aiosqlite:///shop.db"),
    ],
    name="Gateway",
)
```

**字段映射：**

| dict key | `Application(...)` 参数 | 说明 |
|---|---|---|
| `name` | `name=` | 必填 |
| `base` | `base=` | 必填 |
| `url` / `engine` / `session_factory` | 同名 | 三选一互斥；全缺则进入 schema-only 模式 |
| `description` | `description=` | 默认 `""` |
| `query_description` | `query_description=` | 可选 |
| `mutation_description` | `mutation_description=` | 可选 |
| `aliases` | `aliases=` | list[str]，不能与自身 `name` 冲突 |

**对现有项目的影响：**
- **行为变化**：所有用 dict 形式声明 app 的代码仍能正常运行（功能不变），每次构造会在 stderr 看到 `DeprecationWarning: Passing AppConfig dict is deprecated; use Application(...)`。
- **零功能破坏**：dict 形式 transparent 转换为 `Application`，行为与新形式完全等价。
- **迁移工作量**：纯机械替换（如上演示），无逻辑变更。
- **抑制警告**（仅限过渡期，不推荐长期使用）：`python -W ignore::DeprecationWarning`。

**兼容窗口：** 3.7.x 全系列保留 dict 形式 + 警告；**3.8.0 移除**。建议现有项目在升级到 3.7.x 后尽快迁移，避免升级 3.8 时一次性破坏。

**Changes：**
- `src/nexusx/mcp/application.py`: `_coerce_to_application` 检测 dict 输入时抛 `DeprecationWarning`
- 警告文案包含迁移目标（`use Application(...)`）和移除版本（`removed in v3.8.0`）

---

### Bug Fix: use_case router 不再把嵌套 `BaseModel` 参数拍平成 dict（#110，修 #107）

`create_router` 生成的 handler 之前用 `body.model_dump()` 把 FastAPI 已校验的 request model 整体拍平成 dict 再传给 service 方法。当方法签名声明 `list[ItemInput]` / `ItemInput` / `ItemInput | None` 等嵌套 BaseModel 参数时，方法体实际收到的是 `list[dict]` / `dict`——签名与运行时类型脱节，访问 `item.text` 直接 `AttributeError`。

改为按字段名从 request model 做属性访问（`getattr(body, name)`）。Pydantic 在校验阶段已构造好的嵌套 BaseModel 实例原样透传给方法体，类型契约不再断链。标量 / `list[scalar]` / `FromContext` / 默认值 / alias 等其他形态行为完全不变，OpenAPI / compose schema 生成路径也不受影响（schema 与 router 是两条正交路径）。

**Changes：**
- `src/nexusx/use_case/router.py`: `_make_handler` 的 body 分支由 `body.model_dump()` 改为 `{p: getattr(body, p) for p in body_params}`
- `tests/test_use_case_router.py`: 新增 `TestNestedBaseModelParams`，覆盖 `list[Model]` / `Model` / `Optional[Model]` / `Optional[list[Model]]` / `list[Optional[Model]]` / 两层嵌套 / 标量回归 / alias

---

### Behavior Change: `route_options` 不再允许覆盖 router 自留键（#111）

承接 #107 的 router 清理。`_make_handler` 抽取公共逻辑、移除一个恒真的死分支与一个未使用参数、并为生成的 handler 闭包设置有意义的 `__name__` / `__qualname__`（改善栈轨迹与 FastAPI 生成的 operation_id）——这些都是内部重构，用户无感。

唯一可观察的变化：`route_options` 里若传入 `endpoint` / `methods` 这两个 router 始终显式设置的键，过去会在路由注册阶段抛令人困惑的 `TypeError: got multiple values for keyword argument`；现在在 `create_router()` 调用时即抛清晰的 `ValueError`。`path` 及其他键仍可正常覆盖。

**Changes：**
- `src/nexusx/use_case/router.py`: 抽取 `_merge_context_params` helper；handler 闭包命名；`route_options` 守护 `_RESERVED_ROUTE_KEYS`（`endpoint` / `methods`）
- `tests/test_use_case_router.py`: 新增 reserved-keys 回归测试

---

## 3.6.2

### Bug Fix: `@query`/`@mutation` 返回裸 scalar 或 `list[scalar]` 不再被包装成 `{"_value": ...}`（#106）

`_serialize_item` 的 fallback 分支原本把所有"非 Pydantic 模型 + 无子选择"的返回值统一塞进 `{"_value": str(item)}`——这是函数还是 entity-only 时代留下的防御性兜底。返回裸 scalar 的常见 mutation 模式（`delete_xxx() -> bool`、`count_xxx() -> int`、`reorder() -> list[UUID]`）因为客户端 query 没有子选择、`field_sel.sub_fields` 为空，全部落到这个分支，结果响应变成 `{"_value": "True"}` / `[{"_value": "..."}]`——既不是 SDL 声明的 `Boolean!` 类型，也不是 JSON 原生值。这是 3.6.0/3.6.1 UUID 链路修复的对称缺口：入参方向修完了，出参方向的方法返回值仍坏着。

**修法：** 把 `{"_value": str(item)}` 这条 fallback 改为调 `_serialize_scalar_value`；后者用 Pydantic 的 `TypeAdapter(type(value)).dump_python(value, mode="json")` 统一处理——`bool` / `int` / `str` 原样返回、`UUID` stringify、`datetime` / `Decimal` / `Enum` / `set` / `tuple` / 嵌套 list 也由 Pydantic 统一负责。Pydantic 模型路径（`model_dump(mode="json")`）不动。`bool` / `int` / `str` / `list[str]` / `list[UUID]` 都自然走通。

**为什么借力 Pydantic 而非手写 isinstance 分派：** 一行代码覆盖所有 Pydantic 已知的类型；测试矩阵可以小步快跑（先钉 UUID/list 这两种最常见模式），未来用户写 `Decimal` / `Enum` 返回值时自动受益、不需要再改代码。代价是 Pydantic 的 dump 自带边角决策（Decimal → float、Enum → value），目前没有专门测试覆盖这些边角，可接受。

**行为变更：** 方法返回裸 scalar 时响应格式从 `{"_value": str(...)}` 变成原值（`true` / `42` / `"hello"` / `["uuid1", "uuid2"]` 等）。严格说是 bug fix——`{"_value": ...}` 这个形状从来没匹配过 SDL 契约，没有真实客户端能依赖它。

**Changes：**
- `src/nexusx/execution/query_executor.py`: 新增 `from pydantic import TypeAdapter` import；`_serialize_item` fallback 分支用 `_serialize_scalar_value(item)` 取代 `{"_value": str(item)}`；新增 `_serialize_scalar_value` 一行 helper（内部调 `TypeAdapter(type(value)).dump_python(value, mode="json")`）
- `tests/test_scalar_return_serialization.py`: 新增端到端测试——`bool` / `int` / `str` / `UUID` 单值返回、`list[UUID]` / `list[str]` 列表返回、对应 SDL floor test（`Boolean!` / `Int!` / `[UUID!]!`）

---

## 3.6.1

### Bug Fix: `list[UUID]` / `list[datetime]` 等参数类型不再原样穿透（#105）

3.6.0 修了单个 UUID 的入参转换，但 `ArgumentBuilder._convert_scalar_value` 对 `list[T]` / `List[T]` 这类泛型 target 类型直接 `return value`——整个 list 原样穿透，元素不被转换。实际表现：`@mutation reorder(cls, ids: list[UUID])` 收到的是 `list[str]`，SQLModel/SQLAlchemy 绑定 UUID 列时同样抛 `AttributeError: 'str' object has no attribute 'hex'`，错误堆栈同样不指向 nexusx。这是 3.6.0 同源 bug 的一层外——单 scalar 修了，list-of-scalar 漏了。

影响范围其实更广：`list[datetime]` / `list[date]` / `list[time]` 参数也都有同样问题，只是项目里暂时没人写过这种签名所以没暴露。本次走通用解，不为 UUID 写特例。

**修法：** 在 `_convert_scalar_value` 头部（`unwrap_optional` 之后、bare scalar 分支之前）加一段 list 递归——`typing.get_origin(target_type) is list` 检测泛型 list，`get_args` 提取元素类型，对每个元素调 `_convert_scalar_value` 自身。空列表自然走通（递归对 `[]` 返回 `[]`），`Optional[list[T]]` 由前置的 `unwrap_optional` 处理后再进 list 分支，元素层的 `Optional[T]` 由递归调用自身的 `unwrap_optional` 处理。所有现有 bare scalar 分支（`datetime`/`date`/`time`/`UUID`）原封不动，只是现在被 list 递归触达。

**Changes：**
- `src/nexusx/execution/argument_builder.py`: 顶部 `typing` import 加 `get_args, get_origin`；`_convert_scalar_value` 头部加 ~4 行 list 递归分支
- `tests/test_uuid_arguments.py`: 新增 `TestUuidListArgumentConversion` / `TestUuidListSDL`——覆盖字面量 list 转换、variables 形式 list 转换、空 list 通过、SDL 渲染 `[UUID!]!`

---

## 3.6.0

### Breaking Change: UUID 升级为真正的 GraphQL UUID scalar（#104）

Python 的 `uuid.UUID` 此前在两条 GraphQL 路径上**行为分裂且都不正确**：主路径（sdl_generator + TypeConverter）通过 `or "String"` fallback 把 UUID 字段/参数渲染成 `String`；compose 路径（compose_type_mapper）映射到 `ID`。两种处理都偏离了 Python 端明确的 `uuid.UUID` 类型语义。更严重的是主路径上的入参方向：`@query` 方法声明 `id: UUID`、客户端按 SDL 发字符串字面量、ArgumentBuilder 只识别 `datetime`/`date`/`time` 不识别 UUID → 方法运行时拿到的是 `str`，SQLModel/SQLAlchemy 在绑定 UUID 列时调用 `.hex` 抛 `AttributeError: 'str' object has no attribute 'hex'`，错误堆栈完全不指向 nexusx，对用户极其费解。出参方向同样有问题：`_serialize_item` 标量分支直接 `getattr`，UUID 实例未经 stringify 进入响应 dict。

本次把 UUID 提升为两条路径共同的**一等公民 scalar**，与 `DateTime` / `Date` / `Time` 平起平坐：SDL 一致渲染成 `UUID` / `UUID!`，传输层不变（UUID 仍按字符串序列化），introspection 在 `__schema` 里 advertise UUID scalar。

**影响范围（破坏性）：**
- **主路径**：UUID 字段从 `String` 变 `UUID`。`String` 本来就是 fallback bug 而非设计契约，所以主路径用户感知到的是 bug 修复——SDL 类型名变了，但 SQLModel app 的运行时行为从"崩溃"变"正常"。
- **Compose 路径**：UUID 字段从 `ID` 变 `UUID`。这才是真正的破坏性变更——`graphql-codegen` / Apollo 这类消费 SDL 的工具会看到新 scalar 名，需要重新生成类型。Transport 层（字符串序列化）完全不变，纯 SDL 表面变更。
- **不动的事**：主路径 SDL 是否 emit `scalar X` 声明（保持现状，`DateTime`/`Date`/`Time` 也只引用不声明）；`datetime`/`date`/`time` 出参方向的同源序列化缺陷（未钉契约，留给后续）。

**修法：** 改动分布在 scalar 处理的四个站点 + compose 路径对齐，全部 surgical edit：
- `TypeConverter.SCALAR_TYPE_MAP` 注册 `uuid.UUID: "UUID"`，`sdl_generator` 与 `introspection.py` 自动消费。
- `ArgumentBuilder._convert_scalar_value` 在 `time` 分支之后加 UUID 分支，镜像 `date.fromisoformat` / `time.fromisoformat` 的写法调 `uuid.UUID(value)`；非法字符串抛 `ValueError`，被 `query_executor` 的 except 包成 GraphQL 规范的 `{message, path}` 错误响应。
- `QueryExecutor._serialize_item` 标量分支从 `getattr` 改为 `value = getattr(...); if isinstance(value, UUID): value = str(value)`，确保响应 dict 里的 UUID 是字符串。
- `IntrospectionGenerator._build_scalar_types` 硬编码 scalar 列表加 `"UUID"`，否则 Apollo/codegen 会报 unknown type。
- `ComposeTypeMapper._SCALAR_NAMES` 把 `uuid.UUID: "ID"` 改成 `"UUID"`，与主路径对齐；`_SCALAR_DESCRIPTIONS` 同步加 `"UUID"` 描述。

**Changes：**
- `src/nexusx/type_converter.py`: 顶部 `import uuid`；`SCALAR_TYPE_MAP` 加 `uuid.UUID: "UUID"`
- `src/nexusx/execution/argument_builder.py`: 顶部 `import uuid`；`_convert_scalar_value` 加 `uuid.UUID(value)` 分支
- `src/nexusx/execution/query_executor.py`: 顶部 `from uuid import UUID`；`_serialize_item` 标量分支加 UUID → str 归一化
- `src/nexusx/introspection.py:187`: 硬编码 scalars 列表追加 `"UUID"`
- `src/nexusx/use_case/compose_type_mapper.py`: `_SCALAR_NAMES` 把 `uuid.UUID` 从 `"ID"` 改 `"UUID"`；`_SCALAR_DESCRIPTIONS` 加 `"UUID"` 条目
- `tests/test_uuid_arguments.py`: 新增端到端测试——入参方向（字面量/变量/Optional）、出参方向（UUID 实例 → str）、SDL 断言（升级后钉 `UUID!`、负面断言排除 `String`）
- `tests/test_compose_schema.py`: `test_uuid_maps_to_id_scalar` → `test_uuid_maps_to_uuid_scalar`

---

## 3.5.3

### Breaking Change: 移除 UseCase compose query 的 `Op` 包装层

UseCase compose query 原先要求顶层套一层虚拟的 `Op` 字段——`{ Op { UserService { list_users { id } } } }`。这层 wrapper 没有任何业务含义，只是早期实现为了对齐 graphql-core 默认 `Query` 根类型而引入的占位符；每条 compose query 都被迫多写一层缩进、MCP 工具示例与文档也都要解释它的存在，纯粹的认知负担。本次移除后查询直接以 service 开头：`{ UserService { list_users { id } } }`。

**影响范围：**
- `execute_compose_query` / MCP Layer 3 `compose_query` 工具 / GraphiQL 端点全部一致——graphql 层与 mcp 层均不再接受 `Op`。
- 已发布的 compose query 全部需要改写；旧形状会被执行器拒绝，错误消息为 `Service 'Op' not found in app '<name>'. Available: [...]`。
- README / demo / docs / MCP 工具内嵌描述确认无残留 `Op` 示例（仅 specs/ 与历史 plan 文档保留旧语法作为档案，不在此次清理范围）。

**修法：** `_execute_operations` 直接遍历 `selections.items()` 派发到 service，去掉原先"先解一层 root FieldSelection 再迭代 sub_fields"的嵌套循环。QueryParser 仍然按根字段名生成 `FieldSelection`，只是这些 root selection 现在就是 service 名而非 `Op`。`_execute_service_methods` / `_invoke_and_project` / introspection rejection / `compose_introspect` 全部不动——改动只发生在 `_execute_operations` 一个函数内。

**Changes：**
- `src/nexusx/use_case/compose_executor.py`: `_execute_operations` 移除对 `root_sel.sub_fields` 的内层循环，直接遍历 `selections.items()`
- `tests/test_compose_executor.py`: 全部 compose query 字面量去掉 `Op` 包装；新增 `test_wrapper_field_is_rejected` 锁定旧形状被拒绝
- `tests/test_compose_mcp_server.py`: Layer 3 测试同步去 `Op`；新增 `test_wrapper_field_is_rejected`；`test_unknown_app_returns_error_in_errors_array` 同步
- `tests/test_compose_introspect.py`: `_CoercionService` / `_ContextCoercionService` 系列端到端测试同步去 `Op`

---

## 3.5.2

### Bug Fix: Voyager 节点切换后旧节点边框残留橙色描边（#101）

`graph-ui.js::highlightSchemaBanner` 直接用 `setAttribute` 改 outerFrame 与 titleBg 两个 polygon 的 `stroke` / `stroke-width` / `fill`，并通过 `_saveOriginalAttributes` 把原值存到 DOM attribute `data-original-stroke` / `-stroke-width` / `-fill`。但 `clearSchemaBanners` 在清除时只 `removeAttribute` 了这三个数据属性，**没有真正把原值写回 SVG attribute**——它依赖 `graphviz.svg.js::restoreElement` 做还原，而后者的数据源是 jQuery `.data("graphviz.svg.color")`（init 时存的 fill+stroke 快照、不含 stroke-width），与 graph-ui.js 的 DOM attribute 完全独立、互不知道对方的写入。结果：用户双击节点 A、切换到 B 后，A 的标题背景橙色消失（graphviz.svg.js 还原 fill 成功），但**外框残留一条淡淡的橙色描边**——是 stroke-width 被硬编码为 1（不是原值）让原本几乎不可见的描边变粗，加上未被 jQuery data 覆盖的边界情况（如未被 `setupNodesEdges` 处理的元素）留下的橙色 stroke。每次节点切换都触发，长期用户反复感知，是肉眼可见的视觉瑕疵。

**修法：** `clearSchemaBanners` 在调 `gv.highlight()` 之后、`removeAttribute` 之前，对每个 `polygon[data-original-stroke]` 先用 `getAttribute` 读出 `data-original-stroke` / `-stroke-width` / `-fill`、用 `setAttribute` 写回对应 SVG attribute（兜底还原），再删除数据属性。graph-ui.js 成为"最后写入者"，覆盖 graphviz.svg.js 留下的任何不一致。还原语义基于"写回原值"而非"涂改回固定颜色"，未来主题色变更、深色模式都天然兼容。`highlightSchemaBanner` 与 `_saveOriginalAttributes` 的写入路径不动（写入本来就正确，问题在清除路径）；`graphviz.svg.js` 不动（vendored 第三方库，影响面大）；`HIGHLIGHT_COLOR` / `HIGHLIGHT_STROKE_WIDTH` 常量不动（不调色值、不改触发规则）。

**Changes：**
- `src/nexusx/voyager/web/graph-ui.js`: `clearSchemaBanners` 内 `forEach` 循环在 `removeAttribute` 之前新增 ~12 行兜底还原（含 8 行注释）——`getAttribute` 读三个 `data-original-*` 属性、`setAttribute` 写回 `stroke` / `stroke-width` / `fill`

---

## 3.5.1

### Bug Fix: Voyager ER 图切换显示选项后 Related Entities 子图跟随刷新（#100）

`renderErDiagram` 重新渲染主图后不会触发 Related Entities 子图 refetch——`onGenerate` 只 dispatch 到主图路径，子图完全不被触碰。`fetchRelatedEntities` 又有 spec 005 FR-011 引入的 dedup（防快速重复点击同一实体），要求 `selectedSchema === schemaName` 且 dot 还在时直接 return。两条合起来：用户在子图打开时切换任何显示选项 toggle（Hide Reverse Relationships / brief mode / Better Cluster Display / Show Methods / 等），主图按新配置渲染、子图保留旧数据。Pure FK toggle（PR #99）让问题最显眼——连线消失是肉眼可见的——但 bug 影响所有 toggle，是 spec 005 遗留的隐藏问题。

**修法：** `renderErDiagram` 主图渲染完成后，检测 `state.relatedEntities.selectedSchema` 是否非空且 dot 还在；若是，清空 `selectedSchema`（绕过 dedup 守卫）并调 `fetchRelatedEntities(openSubSchema)` 重新拉子图。`buildErDiagramSubgraphPayload` 已经把所有显示选项透传到请求体，refetch 后子图自然按新配置渲染。spec 005 FR-011 防快速点击的 dedup 在没有配置变化时仍正常生效（同一实体连续点击两次、配置不变 → 第二次仍走 dedup 跳过）。

**Changes：**
- `src/nexusx/voyager/web/vue-main.js`: `renderErDiagram` 主图渲染末尾加一段——若 `state.relatedEntities.selectedSchema` 非空且 `dot` 存在，清空 `selectedSchema` 并调 `actions.fetchRelatedEntities(openSubSchema)`

---

## 3.5.0

### New Feature: Voyager ER 图新增 "Hide Reverse Relationships" 开关（#99）

SQLModel 双向关系普遍通过 `Relationship(back_populates=...)` 配置，SQLAlchemy 在内部把它拆成两条方向相反的 relationship——一条 MANYTOONE（持有 FK 字段的实体 → 被引用实体）+ 一条 ONETOMANY（被引用实体的反向镜像）。Voyager ER 图原先把两条都画出来，任意一对双向关联的实体之间都会出现 2 条方向相反、语义重复的连线，整体画布密集、交叉、难以一眼读懂"数据真正从哪里流向哪里"。本次新增 **Hide Reverse Relationships** 开关，开启后只保留 MANYTOONE 方向（持有 FK 一侧）与 MANYTOMANY 方向（不在反向冗余范围内）的连线、隐藏 ONETOMANY 反向镜像，每对实体之间的连线降到 1 条。

**关键设计：**
- 过滤发生在后端 `ErDiagramDotBuilder._add_relationship_link` 入口处——基于 `RelationshipInfo.direction` 字段（SQLAlchemy `inspect()` 已自动反射）早退，**不改造连线锚点 / label 生成逻辑**；surviving edges 视觉上与未开启时完全一致，只是数量减少。
- `self.rel_name_set` 仍记录全部 relationship（包括被过滤掉的 ONETOMANY），Fields tab 字段表内容不受影响——开关只裁剪连线、不裁剪字段展示。
- 子图（spec 005 引入的 Related Entities tab）天然跟随裁剪：`filter_to_neighborhood` 在 `analysis()` 之后调用、消费已过滤的 `self.links`，无需为子图额外实现裁剪逻辑。
- 偏好持久化沿用项目内 `better_cluster_display` / `brief_mode` / `pydantic_resolve_meta` 等已有 toggle 模式：localStorage key `hide_reverse_relationships`、默认未勾选（向后兼容老客户端）、与其他显示选项完全正交。
- Pydantic payload 字段 `hide_reverse_relationships: bool = False` 默认值保证老客户端不传该字段时行为完全一致；响应 shape 不变。

**Changes：**
- `src/nexusx/voyager/er_diagram_dot.py`: `ErDiagramDotBuilder.__init__` 新增 `hide_reverse_relationships: bool = False` 参数；`_add_relationship_link` 入口处按 `rel_info.direction == 'ONETOMANY'` 早退
- `src/nexusx/voyager/create_voyager.py`: `ErDiagramPayload` 与 `ErDiagramSubgraphPayload` 各新增 `hide_reverse_relationships: bool = False` 字段
- `src/nexusx/voyager/voyager_context.py`: 2 处 `ErDiagramDotBuilder(...)` 构造点透传新参数
- `src/nexusx/voyager/web/store.js`: `state.filter.hideReverseRelationships` 字段；`toggleHideReverseRelationships(val, onGenerate)` action（含 localStorage 持久化 + try/catch 降级）；`buildErDiagramPayload` 与 `buildErDiagramSubgraphPayload` 透传字段
- `src/nexusx/voyager/web/vue-main.js`: 初始化时 `loadToggleState("hide_reverse_relationships", false)`；注册 `toggleHideReverseRelationships` action
- `src/nexusx/voyager/web/index.html`: ER-diagram 模式下新增 `<q-toggle>` "Hide Reverse Relationships"（仅在该模式可见，与 Show Methods 同侧）
- `tests/test_voyager_hide_reverse.py`: 新增 10 条 pytest 用例——过滤开/关、M2M 双向保留、单向 MANYTOONE 保留 / ONETOMANY 隐藏、SchemaNode.fields 不变量（FR-007）、端点契约 + 向后兼容、子图跟随裁剪、自引用双向关系

---

## 3.4.2

### Bug Fix: SDL 给 paginated list 字段补回 limit/offset args（#98）

`enable_pagination=True` 时，introspection 路径会给 paginated list 字段渲染 `limit` / `offset` 参数，但 **SDL generator 输出同一字段时不带 args**——两条路径对同一个 schema 给出不一致的描述。GraphQL 规范要求字段可接受的参数必须在 SDL 里声明，否则客户端不允许传：任何走 SDL 而不是 introspection 接 nexusx 的客户端（AI agent / codegen 工具 / GraphiQL 替代品 / 文档生成器）都看不到这些字段能传分页参数，分页功能对它们**实际不可达**。

修法：`SDLGenerator._generate_entity_type` 渲染关系字段时复用已有的 `_is_paginated_relationship` 判定，对带 `page_loader` 的 list 字段输出 `{field}(limit: Int, offset: Int = 0): {Type}Result!`，其它字段不变。`offset` 默认值 `0` 与 introspection 的 `defaultValue: "0"` 对齐。

**Changes：**
- `src/nexusx/sdl_generator.py`: `_generate_entity_type` 渲染关系字段时按 `_is_paginated_relationship` 分支，paginated 字段附加 `(limit: Int, offset: Int = 0)`，non-paginated 字段保持 `{name}: {type}` 不变
- `tests/test_pagination_mixed.py`: 新增 `test_paginated_field_exposes_limit_offset_args` 锁 SDL args 形态；调整 `test_paginated_list_renders_as_result_type` 改为只断言类型后缀（字段名后多出 args 让原断言失效），与 introspection 侧 `test_paginated_field_uses_result_type_with_args` 形成对称覆盖

---

## 3.4.1

### New Feature: Voyager ER 图新增 `Better Cluster Display` 开关（module cluster 专用）

为缓解大型 ER 图在开启 `show module cluster` 时出现的边剧烈绕行与 cluster 内显示不稳定问题，新增一个仅在 **ER Diagram 模式** 且 **Show Module Cluster 已开启** 时可见的增强开关：`Better Cluster Display`。

该开关关闭时保持原始 Graphviz 行为；开启时，仅对 ER 图应用一组更适合 cluster 大图的 Graphviz 路由参数：

- `splines=polyline`
- `newrank=true`
- `compound=true`

同时，该开关位于 `Show Module Cluster` 下方并保持缩进，状态持久化到浏览器 `localStorage`；当 `Show Module Cluster` 关闭时，`Better Cluster Display` 会自动隐藏并重置为关闭状态。

**Changes：**
- `src/nexusx/voyager/web/index.html`: 在 `Show Module Cluster` 下方新增缩进显示的 `Better Cluster Display` toggle（仅 ER Diagram + showModule=true 时可见）
- `src/nexusx/voyager/web/store.js`: 新增 `filter.betterClusterDisplay`、`toggleBetterClusterDisplay()`、`localStorage` 持久化，以及 ER payload / subgraph payload 透传
- `src/nexusx/voyager/web/vue-main.js`: 暴露 `toggleBetterClusterDisplay` 给页面模板，确保点击后可触发重绘
- `src/nexusx/voyager/create_voyager.py`: 为 `ErDiagramPayload` / `ErDiagramSubgraphPayload` 新增 `better_cluster_display` 字段
- `src/nexusx/voyager/voyager_context.py`: 将 `better_cluster_display` 透传给 `ErDiagramDotBuilder`
- `src/nexusx/voyager/er_diagram_dot.py`: 新增 `better_cluster_display` 构造参数并传递给 `DiagramRenderer`
- `src/nexusx/voyager/render.py`: 将 `splines=polyline`、`newrank=true`、`compound=true` 改为由 `better_cluster_display` 条件控制，而非全局默认启用
- `src/nexusx/voyager/templates/dot/er_diagram.j2`: 新增 `newrank` / `compound` 图属性模板输出

## 3.4.0

### New Feature: Voyager ER 图新增 "About" tab（docstring + Mermaid 渲染）& 侧边栏宽度放宽（#95）

双击 entity 打开的侧边栏原先只有 Fields / Source Code / Related Entities 三个 tab，schema 模型类的 `__doc__` 完全没有入口。本次在最左新增 **About** tab，把类级 docstring 当作 GitHub-Flavored Markdown 渲染——含标题、列表、表格、代码块、引用块、水平线等元素；docstring 中的 ```mermaid 围栏块（`stateDiagram-v2` / `flowchart` / `sequenceDiagram` 等）就地渲染成可视化图表，方便在 docstring 里直接画"实体生命周期 / 状态转移 / 交互流程"。Mermaid 块语法错误时降级为"错误提示 + 默认折叠的原始源码"，方便复制到外部工具调试，且单块失败不影响其它内容。

同时把侧边栏拖拽宽度上限从固定 **800px** 改为 **floor(viewport × 2/3)**，宽屏下也能给宽表格、宽 Mermaid 图、长 Python 行留足空间；视窗缩放时自动 clamp 到新的 2/3 上限，下限 300px 与默认初始宽度不变。

**关键设计：**
- docstring 走独立端点 `POST /docstring`（与 `/source` / `/vscode-link` 对称），不改 SchemaNode、不改 `/source` 契约——避免 er-diagram 初始 payload 膨胀与 service worker 缓存键失效。
- 前端依赖 `marked` / `dompurify` / `mermaid` 走 **CDN**（cdn.jsdelivr.net），匹配现有 Vue/d3/jQuery 模式；三个 URL 加入 sw.js 的 `CDN_ASSETS` 预缓存列表以保证离线可用。
- docstring 经 `DOMPurify.sanitize` 清洗后再注入，所有 `<a>` 强制 `target="_blank" rel="noopener noreferrer"`，且不识别"实体引用"格式——About tab 与 Related Entities 子图一样**只读**。
- 切换实体保留当前激活 tab（沿用 spec 005 FR-012 的策略，对四个 tab 一视同仁）；About tab 在 tab 栏最左，但侧边栏首次打开默认激活 Fields 不变。

**Changes：**
- `src/nexusx/voyager/voyager_context.py`: 新增 `get_docstring(schema_name)` 方法，复用 `_resolve_object`、返回 `{"docstring": obj.__doc__ or ""}`
- `src/nexusx/voyager/create_voyager.py`: 新增 `POST /docstring` 路由，状态码映射与 `/source` 一致
- `src/nexusx/voyager/web/component/about-display.js`: 新建组件，渲染管线 = marked → DOMPurify → innerHTML → 链接硬化 → mermaid.run（per-block try/catch + 错误降级）
- `src/nexusx/voyager/web/component/schema-code-display.js`: 加 `showAbout` prop；tab 栏最左加 About；content 区挂载 `<about-display>`
- `src/nexusx/voyager/web/vue-main.js`: 引入 AboutDisplay 全局组件；`mermaid.initialize({ startOnLoad: false, theme: "default" })`；`startDragDrawer` clamp 改为 `Math.max(300, Math.min(floor(innerWidth × 2/3), ...))`；`onMounted` 注册 `window.resize` 监听器，超出新上限时主动压缩
- `src/nexusx/voyager/web/index.html`: 引入 marked / dompurify / mermaid 三个 `<script>`；`<schema-code-display>` 加 `:show-about="store.state.mode === 'er-diagram'"`
- `src/nexusx/voyager/web/sw.js`: `CDN_ASSETS` 预缓存列表追加三个 CDN URL
- `tests/test_voyager_docstring.py`: 新增 5 条 pytest 用例（happy / 空 docstring / 非法格式 / module 缺失 / class 缺失）
- `demo/enterprise_voyager/models.py`: 给 `Employee` 加 docstring，覆盖 FR-003 全部 Markdown 元素 + FR-004 三种 Mermaid 类型，便于人工验证

---

## 3.3.1

### Bug Fix: Voyager ER-diagram 侧边栏补回字段描述

`ErDiagramDotBuilder._get_entity_fields` 构造 `FieldInfo` 时**两类字段都漏传 `desc`**：普通 `model_fields` 字段没读 `v.description`，关系字段（`CustomRelationship`）的 `description` 又因为在转换成 `RelationshipInfo` 时被丢弃而无从透出。结果是 ER-diagram 模式下双击 entity 打开的侧边栏 Fields 表格，Description 列**永远是空的**——即使 schema 上明确写了 `Field(description=...)` 或 `__relationships__=[CustomRelationship(description=...)]`。同类的 DTO 路径（`get_pydantic_fields`）一直是对的，所以非 ER-diagram 视图不受影响，这也让 bug 更隐蔽。

**修法：**
- 普通字段：`er_diagram_dot.py` 构造 `FieldInfo` 时补 `desc=getattr(v, 'description', None) or ''`，和 `type_helper.py:223` 的写法对齐
- 关系字段：给 `RelationshipInfo` 加 `description: str | None = None` 字段；`_build_custom_relationship_info` 把 `Relationship.description` 透传过来；`er_diagram_dot.py` 构造关系 `FieldInfo` 时同样补 `desc=rel_info.description or ''`

ORM 自动发现的普通关系（MANYTOONE / ONETOMANY / MANYTOMANY）没有 description 来源，仍为空——这是预期行为；只有用户显式写了 description 的字段/关系才会进入表格。

**Changes：**
- `src/nexusx/voyager/er_diagram_dot.py`: `_get_entity_fields` 的两处 `FieldInfo(...)` 各补一个 `desc=` 参数
- `src/nexusx/loader/registry.py`: `RelationshipInfo` 新增 `description` 字段；`_build_custom_relationship_info` 透传 `Relationship.description`

---

## 3.3.0

### New Feature: Voyager ER 图新增 "Related Entities" 聚焦子图 tab（#93）

`demo/enterprise_voyager` 这类 30+ 实体的大 schema 里，"单击高亮一层邻居"虽然有用，但相关节点被图布局散布到画布各处，肉眼很难一眼看全某个实体的直接关联。本次在双击打开的侧边栏里新增第三个 tab **Related Entities**，渲染一张**只读的迷你 ER 子图**——只包含所选实体 + 直接邻居 + 它们之间的边——作为主图高亮邻域在侧边栏内的聚焦视图。

**行为：**
- 子图复用主图当前的渲染配置（show module cluster / show methods / edge length 的 Small / Middle / Large），随主图配置或所选实体的变化自动重新渲染；子图本身**不暴露任何配置项**。
- 视觉管线与主图同构：后端返回 DOT，前端用独立 d3-graphviz 实例渲染成 SVG。独立实例保证主图与子图的缩放/平移/布局状态互不干扰。
- 只读：不在子图内绑定实体 click/dblclick（不会把主图选区切走），但保留 pan/zoom 这些纯视图操作。
- 孤立实体（无任何关系）：子图渲染该实体自身一个孤立节点 + 居中提示"该实体没有直接关联实体"，与"加载中" / "出错"视觉可区分。

**Changes：**
- `src/nexusx/voyager/er_diagram_dot.py`: `ErDiagramDotBuilder` 新增 `filter_to_neighborhood(schema_name)` —— 在 `analysis()` 之后把 nodes / links 收窄到一层邻域；保留自引用与平行边
- `src/nexusx/voyager/voyager_context.py`: 新增 `get_er_diagram_subgraph(payload)`，响应结构与 `get_er_diagram_data` 完全一致；未知 schema 短路为空
- `src/nexusx/voyager/create_voyager.py`: 新增 `ErDiagramSubgraphPayload` + `POST /er-diagram-subgraph` 端点
- `src/nexusx/voyager/web/component/related-entities-display.js`（新）: `RelatedEntitiesDisplay` Vue 组件，独立 d3-graphviz 实例 + 四态（加载 / 正常 / 孤立节点 + 文案 / 错误）+ 只读 pan/zoom + schemaName / filter 响应式 refetch
- `src/nexusx/voyager/web/component/schema-code-display.js`: 模板追加第三个 `<q-tab name="related">`（由 `showRelatedEntities` prop 门控，仅 ER-diagram 模式显示）
- `src/nexusx/voyager/web/store.js`: 新增 `relatedEntities` 状态 + `fetchRelatedEntities` / `clearRelatedEntities` actions + `buildErDiagramSubgraphPayload` helper
- `tests/test_voyager_subgraph.py`（新）: 11 个测试覆盖邻域精确性、孤立实体、自引用 / 平行边、配置透传、端点契约、边方向一致性

---

### Bug Fix: 侧边栏跟随画布选择 + 空白点击与拖拽手势分离（#93）

做 Related Entities tab 的过程中发现一组侧边栏响应性问题：(1) 双击打开侧边栏后，画布上**单击**其他 entity 侧边栏内容不跟随更新（只有双击才更新，违反直觉）；(2) 画布空白处点击会关侧边栏，但**拖拽平移视图**也会误关。本次顺手修掉，并把已注释但无保护的 tab 跨实体保留行为加上防回归注释。

**修法：**
- 单击路径在 `nodes.on("click")` 末尾，当侧边栏已打开（新增 `isSidebarOpen` getter 从 store 同步）时额外触发 `onSchemaClick` —— 与现有双击路径幂等
- 空白点击关闭逻辑加 mousedown/mouseup 位移阈值（5px）：纯点击关闭侧边栏，拖拽（平移 / 框选）保持不变；复用画布现有的 mousedown/mouseup 事件，不引入新的手势判定机制
- `schema-code-display.js` 的 `resetState()` 中 `tab.value = "fields"` 保持注释状态，加 protective comment 说明"切换实体时不得重置 tab"

**Changes：**
- `src/nexusx/voyager/web/graph-ui.js`: `GraphUI` 加 `_bgMouseDownPos` mousedown 追踪；node click 末尾按 `sidebarOpen` 条件触发 `onSchemaClick`；document-level click handler 加 5px drag 阈值
- `src/nexusx/voyager/web/vue-main.js`: `GraphUI` 构造时传 `isSidebarOpen` getter
- `src/nexusx/voyager/web/component/schema-code-display.js`: `resetState()` 加 FR-012 protective comment

---

## 3.2.3

### Bug Fix: Voyager 源码定位支持非 service module 的全限定类名

`VoyagerContext._resolve_object` 之前在处理 `module.ClassName` 形态的 schema 名时，会先把模块名限制在 `services` 所在 module 范围内。Voyager / ER UI 实际传回的节点名却可能是图分析阶段收集到的**任意已加载类型**，例如 DTO、entity、loader 或测试里的辅助 schema；这些类型经常并不定义在 service module 下。结果是像 `tests.test_voyager_security._LocalSchema` 这类结构完全合法、而且运行时已加载的名称，会被误判，进一步在 `get_source_code` / `get_vscode_link` 上表现为“格式非法”或无法跳转。

**修法：** 去掉 service-module 白名单限制，优先从 `sys.modules` 解析已经加载的模块，仅在未加载时再尝试导入；导入失败则安全返回 `None`。这样既保留了原有的 `Service.method` 解析路径，也让 Voyager 能正确处理图里出现的非 service-module 类型名。

**Changes：**
- `src/nexusx/voyager/voyager_context.py`: `_resolve_object` 移除 `_allowed_modules` 限制，新增 `sys.modules` 优先解析与 `ImportError` 兜底
- `tests/test_voyager_security.py`: 重写分辨率测试，覆盖未知 service、非 service module 全限定类名、`get_source_code`、VS Code link，以及内建对象无源码时的回退行为

---

## 3.2.2

### Bug Fix: 自引用 / 互引用 DTO 不再让 schema 构建栈溢出（#91）

`ComposeTypeMapper._register_object` / `_register_input_object` 之前在**遍历完所有字段之后**才把 `TypeInfo` 写入 `_registry` 和 `_by_python_id` memo。当 DTO 出现自引用（`parent: Self | None`、`children: list[Self]`）或互引用（`A.b: B` + `B.a: A`）时，递归走到自引用字段时 memo 还没写入，无法短路， recursion 一路到底直到 `RecursionError`——`build_compose_schema` 直接崩溃，应用启动失败。同样的形态曾在 note-tool 的 `TagTreeItem` 启动时踩到。

**修法：** 遍历字段**之前**先往两个 memo 里写一个 `fields=()` 的 stub `TypeInfo`，让自/互引用的重入命中 memo 提前返回 name。字段遍历完成后用 `dataclasses.replace(stub, fields=...)` 把真实字段填回去——`TypeInfo` 是 frozen dataclass，所以必须 replace 而非原地改。`TypeRef` 是 name-based，下游消费者看到的始终是 finalize 之后的版本。

**Changes：**
- `src/nexusx/use_case/compose_type_mapper.py`: `_register_object` 和 `_register_input_object` 改为先 stub 后 finalize，新增 `import dataclasses`
- 回归测试：自引用（`TreeNode`）、互引用（`NodeA` / `NodeB`）、`INPUT_OBJECT` 自引用（`TreeFilter.children: list[Self]`）三个场景

---

### Bug Fix: SQLModel `date` / `time` 字段在 GraphQL 端到端原生支持（#92）

SQLModel 实体声明 `when: date` / `start_time: time` 时，整条 GraphQL 链路把它当作字符串处理——SDL 误报成 `String!`，突变调用时字符串原样穿透到 SQLModel 触发 `TypeError: SQLite Date type only accepts Python date objects`，GraphiQL introspection 里 `Date` / `Time` scalar 压根不出现，客户端无从知晓。child-calendar 项目踩到这个坑。三处局部修复，让 `date` / `time` 走与既有 `datetime` 一致的处理路径。

**修法：**
- `TypeConverter.SCALAR_TYPE_MAP` 增加 `date → "Date"`、`time → "Time"`——SDL 和 introspection 通过 `get_scalar_type_name(...) or "String"` 自动停止回落到 `String`，`sdl_generator` 无需改动
- `ArgumentBuilder._convert_scalar_value` 增加 `date` / `time` 分支，用标准库 `date.fromisoformat` / `time.fromisoformat` 把 GraphQL 字符串字面量（含变量）parse 回 Python 原生对象
- `IntrospectionGenerator._build_scalar_types` 的硬编码 scalar 列表加入 `"Date"` / `"Time"`，让 GraphiQL 能 discover

**Changes：**
- `src/nexusx/type_converter.py`: `SCALAR_TYPE_MAP` 加 2 项
- `src/nexusx/execution/argument_builder.py`: `_convert_scalar_value` 加 `date` / `time` 两个 `isinstance(value, str)` 分支
- `src/nexusx/introspection.py`: `_build_scalar_types` 的 scalars 列表加 `"Date"` / `"Time"`
- `tests/test_date_time_arguments.py`: 新增 16 个测试，覆盖 TypeConverter 标量映射、SDL 发射、ArgumentBuilder 字符串→对象转换、Introspection 标量列表、端到端 SQLite 落库五层

---

## 3.2.1

### Bug Fix: `serialize_result` 改用 JSON 模式 + dict 递归序列化（#90）

移植 pydantic-resolve v5.10.4 的同名修复。`use_case/serialization.py:serialize_result` 是 JSON-RPC（`jsonrpc.py:280`）和 CLI（`cli.py:83`）组装响应时唯一会走的序列化路径，但三个细节让它对 `UUID` / `datetime` / `Decimal` 这类非 JSON 原生类型完全失效——尤其是当 use case 方法返回**包含这些类型的 `dict` payload** 时：

1. `BaseModel.model_dump()` 用默认 `mode="python"`，UUID / datetime / Decimal 仍然是 Python 对象。
2. `dict` 直接 `return result` **不递归**，嵌套在 dict 里的 UUID / BaseModel 被原样泄露。
3. 兜底 `return result`（任何带 `model_dump` 或其他类型）也绕开 JSON 转换。

最终症状：调用方走到 `json.dumps(...)` 时抛 `TypeError: Object of type UUID is not JSON serializable`——错误指向 `json.dumps` 那一行而不是 `serialize_result`，定位困难。

**修法：** 全部走 Pydantic 的 JSON 模式：
- `model_dump(mode="json")` 替换两处 `model_dump()`
- dict 改成 `{k: serialize_result(v) for k, v in result.items()}` 递归
- 兜底改用 `TypeAdapter(type(result)).dump_python(result, mode="json")`

完全对齐上游 commit `6ecf965`。

**Changes：**
- `src/nexusx/use_case/serialization.py`: 重写 `serialize_result`，4 处分支调整（BaseModel / dict 递归 / `model_dump` fall-through / 兜底 TypeAdapter）
- `tests/test_use_case_serialization.py`: 新增 12 个测试——该函数**此前完全没有单元测试**。覆盖 UUID/datetime/Decimal 标量、嵌套 BaseModel、dict-with-UUID（修复核心回归点）、嵌套 dict 中的 UUID、dict 中的 BaseModel 值、端到端 `json.dumps(payload)` 不抛错、None/scalar passthrough

---

## 3.2.0

### New Feature: 非 SQLModel 根对象（虚拟实体）— #87

让普通 `pydantic.BaseModel` 子类作为 NexusX 解析与 ER 可视化的一等公民，无需继承 SQLModel 也无需底层表。三项能力同步落地。

**动机：** 之前 `DefineSubset` 强制要求 SQLModel 源。FastAPI 端点用 `CurrentUser`（OIDC claims 组装）/ page wrapper / 第三方 SDK DTO 这类**非 ORM 根**做响应根时，只能 hack `_subset_registry`，没有官方路径。本特性把这一场景从 workaround 提升为 first-class。

#### `ErManager.add_virtual_entities([...])` —— 虚拟实体注册

注册普通 BaseModel 子类到 ER 图，作为 SQLModel 实体的对等参与者。注册后可：

- 作为 `Resolver().resolve(root)` 的合法根
- 声明 `__relationships__`（与 SQLModel 实体同一语法）
- 参与 ExposeAs / SendTo / Collector 跨层数据流
- 在 ER / Voyager 渲染为视觉区分的虚拟节点

**生命周期约束：** 必须在第一次 `create_resolver()` **之前**调用——之后注册表冻结，再调抛 `RuntimeError`。ErManager 是 startup-once，所有实体注册（SQLModel 走 `__init__`，虚拟走 `add_virtual_entities`）都在请求服务前完成。

**校验矩阵：**

| 输入 | 结果 |
|------|------|
| `[A, B]`（普通 BaseModel，未注册过） | 两者都注册 |
| `[]`（空列表） | 无操作 |
| `[42]` / `[int]`（非类） | `TypeError` |
| `[SomeRandomClass]`（非 BaseModel） | `TypeError` |
| `[User]`（`SQLModel` 子类） | `TypeError`——SQLModel 必须走 `__init__` 的 `entities=` / `base=` |
| `[A, A]`（同次或跨次重复） | `ValueError` |
| 在 `create_resolver()` 之后调用 | `RuntimeError`（"registry is frozen"） |

#### `DefineSubset.__subset__` 源拓宽到任意 BaseModel

源从 `type[SQLModel]` 拓宽到 `type[BaseModel]`——SQLModel 与普通 BaseModel 均被接受。"subset" 的语义是 **schema 子集**（从 `model_fields` 选字段），与数据来源无关：SQLModel 源走 ORM 自动投递（`_orm_to_dto`），BaseModel 源由用户直接构造 DTO 实例，框架不参与。

两个 API 正交：一个 BaseModel 类可以 (a) 只注册为虚拟实体、(b) 只作为 DefineSubset 源、(c) 两者都用、(d) 两者都不用。

#### ER / Voyager 虚拟节点视觉区分

混合 SQLModel + 虚拟实体的项目，ER 图不再崩溃；虚拟实体渲染为视觉上明确区分的节点（FR-009）：

| 属性 | SQLModel 实体 | 虚拟实体 |
|------|--------------|---------|
| 形状 | `shape=plain`（HTML label）| `shape=plain`（同上）|
| 表头底色 | 主题色（teal）| 浅黄 `#FFF9C4` |
| Label | `{ClassName}` | `«virtual»\n{ClassName}` |
| Cluster | 按模块路径 | 独立 `cluster_virtual`（虚线边框）|

**为什么不用 `shape=note`：** 现有 renderer 对所有节点用 HTML label + `shape=plain`，给虚拟节点单独换 shape 会破坏 HTML 渲染。视觉区分改由 **填色 + 衍型标签 + 独立 cluster** 三个信号共同承载，黑白打印也可读。

**两个入口：**

- `ErDiagram.from_er_manager(er)` —— 数据 API，返回 `ErDiagram` 数据类，可调 `.to_mermaid()`
- `ErDiagramDotBuilder(er).render_dot()` —— DOT 路径，Voyager 实际使用的入口

零虚拟实体时 DOT 输出与 baseline 字节一致（虚拟 cluster 被完全省略）。

#### Resolver 源解析统一 + Edge Case B 报错

`_resolve_source()` 作为单一辅助函数，统一三种根的源查找逻辑：

1. DefineSubset DTO → `_subset_registry` 拿源
2. 虚拟实体（已注册 BaseModel）→ `_registry.has_entity()` 命中自身
3. 未注册的 BaseModel → 看 `__relationships__`：有则抛 `RuntimeError` 指向 `add_virtual_entities`，无则返回 None 跳过 auto-load

之前未注册的 BaseModel 即使声明了 `__relationships__` 也会被静默跳过，用户不知道为什么关系字段不加载。现在改成清晰报错（spec Edge Case B）。

#### CUSTOM 关系 loader 输出自动投影到声明 DTO 类型

CUSTOM 关系的 loader 返回值与字段声明的 DTO 类型不一致时（如字段 `list[AgentDTO]`，loader 返回 `_Agent` SQLModel 实例），Resolver 现在按 `isinstance(r, dto_cls)` 判断而非之前的 `isinstance(r, BaseModel)`——后者会把所有 BaseModel（包括 SQLModel 实体）当作"已转换"，静默跳过投影，导致字段实际持有错误的类型。`test_loader_output_converted_to_declared_dto_type` 锁定该修复。

#### DefineSubset 自动包含 `__relationships__` fk 字段

BaseModel 源没有 SQLAlchemy 元数据，FK 字段名只能从 `Relationship(fk="...")` 读取。`_resolve_subset_info` 现在扫源类的 `__relationships__` 自动把 fk 字段加进 DTO（`exclude=True`、`Optional`、`default=None`），与 SQLModel 源的 FK auto-include 对称。否则 DTO 排除 fk 字段时关系加载会静默失败（`getattr(dto, fk, None)` 返 None，loader 永不触发）。

#### 迁移路径

老 hack `_subset_registry[X] = Y` 改为：

- Y 有 `__relationships__` 或需要 ER 可见 → `er.add_virtual_entities([Y])`
- X 是 Y schema 的子集 → `class X(DefineSubset): __subset__ = (Y, ("fields",))`（Y 现在可以是 BaseModel）
- X 就是 Y 自身 → 让 X 成为普通 BaseModel + `er.add_virtual_entities([X])`

详见 `docs/guide/virtual_entities.md` 与 `docs/reference/migration.md`。

### Spec 工件

完整 speckit 工件位于 `specs/004-non-sqlmodel-roots/`：spec / plan / research / data-model / contracts / quickstart / tasks / checklists。

### Changes

- `src/nexusx/loader/registry.py`: 新增 `ErManager.add_virtual_entities()` / `has_entity()` / `frozen` 属性 / `_frozen` flag；`_registry` 类型拓宽为 `dict[type, ...]`；`create_resolver()` 顶部置 `_frozen = True`
- `src/nexusx/subset.py`: `_resolve_subset_info` 源校验从 `issubclass(SQLModel)` 拓宽到 `issubclass(BaseModel)`；新增 `_get_relationship_fk_field_names()` 自动注入 BaseModel 源的 fk 字段；`_subset_registry` 类型拓宽为 `dict[type[BaseModel], type[BaseModel]]`
- `src/nexusx/relationship.py`: `get_custom_relationships(entity)` 签名拓宽到任意 `type`；新增 `is_virtual_entity()` 规范 helper（er_diagram / voyager 共用，避免漂移）
- `src/nexusx/resolver.py`: 新增 `_resolve_source()` 统一源解析（被 `_get_loader` 和 `_scan_auto_load_fields` 共用）；`_orm_to_dto` docstring 重写为"loader 输出投影"语义；`_batch_auto_load` CUSTOM 分支改用 `isinstance(r, dto_cls)`；Edge Case B `RuntimeError` 报错路径
- `src/nexusx/er_diagram.py`: 新增 `from_er_manager()` 入口；`_build()` 按 `registry_relationships` flag 分叉关系数据源；`EntityInfo.is_virtual` 字段
- `src/nexusx/voyager/er_diagram_dot.py`: `SchemaNode.is_virtual` 标记，通过 `is_virtual_entity()` 判定
- `src/nexusx/voyager/render.py`: `render_schema_label` 虚拟节点黄底 + `«virtual»` 衍型；`render_dot` 把虚拟节点分组进 `cluster_virtual`
- `src/nexusx/voyager/render_style.py`: `ColorScheme.virtual_fill` (`#FFF9C4`) / `virtual_cluster`
- `src/nexusx/voyager/type.py`: `SchemaNode.is_virtual` 字段
- `tests/test_virtual_entities.py`: Layer 1 API 契约 + Layer 2 能力对等 + Layer 3 不变量
- `tests/test_definesubset_basemodel.py`: BaseModel 源子集化 + fk auto-include + 自定义关系自动投影
- `tests/test_virtual_entities_er.py`: ER/Voyager 渲染 + 视觉区分信号 + 零虚拟 baseline 等价回归

### Docs

- 新增 `docs/guide/virtual_entities.md` + `.zh.md`：完整使用指南（API 契约、迁移、可视化规则）
- `docs/api/api_core.md` + `.zh.md`：ErManager 方法表新增 `add_virtual_entities`，DefineSubset 段补 BaseModel 源 tip
- `docs/reference/migration.md` + `.zh.md`：新增 `_subset_registry` → 官方 API 迁移表
- `docs/reference/changelog.md` + `.zh.md`：本版本摘要
- `docs/index.md` + `.zh.md`：guide 表格新增 Virtual Entities 行

### 版本同步

- `pyproject.toml`: 3.1.3 → 3.2.0
- `uv.lock`: nexusx 3.1.3 → 3.2.0（**无镜像源引入**，仍指向 `pypi.org`，符合 CLAUDE.md 约定——本地用 `uv lock` 同步即可）

---

## 3.1.3

### Bug Fix: 分页 `has_more` off-by-one（#86）

分页 loader 在"当前页之后**恰好**还剩 1 行"时报告 `has_more=False`，导致客户端误以为没有下一页而停止翻页，最后一行被静默吞掉。

**根因：** `factories.py` M2O/M2M 两条路径都用 `has_next_page = total_count > offset + 1 + effective_limit`，把 SQL peek-by-1 多 fetch 的那一行算进了"已返回"。标准分页语义应该是 `total_count > offset + effective_limit`（"剩余 ≥ 1 行就 True"）。

实测 `total=5, offset=0`：

| limit | 修复前 has_more | 修复后 has_more |
|---|---|---|
| 1 | True  | True |
| 2 | True  | True |
| 3 | True  | True |
| 4 | **False** ❌ | True |
| 5 | False | False |

**修法：** 直接利用 SQL 已经 fetch 出来的 peek 行——`has_next_page = len(grouped[fk]) > effective_limit`。peek-by-1 设计本就是为了回答这个问题，原来绕了一圈用 total_count 反推反而引入了 off-by-one。`total_count` 现在只用于响应 payload，不参与 boolean 决策。

**Changes：**
- `src/nexusx/loader/factories.py`: M2O (`:432`) 和 M2M (`:559`) 的 `has_next_page` 都改成 `len(grouped.get(cmd.fk_value, [])) > effective_limit`
- `tests/test_loader_pagination.py`: `test_basic_pagination`（M2O + M2M 两个版本）原本断言 `has_more is False` —— 那是 bug 行为，翻成 `True`，注释同步更新。其他三个 `has_more is False` 测试（offset=1 / offset 超出 total）的数学在新旧公式下都给 False，保持不变
- `tests/test_pagination_mixed.py::TestExecutionMixedPagination`: 把单一 `limit=1` 断言扩展成 `limit ∈ {1, 2, 3}` 的循环，锁定 `total=3` 边界：limit=1/2 → True，limit=3 → False

---

### Behavior Change: `enable_pagination` 改为 warn-skip，不再 all-or-nothing 阻塞启动（#83）

之前 `ErManager(enable_pagination=True)` 要求**所有** ORM list 关系都配置 `order_by`，否则 startup 抛 `ValueError`。审计日志、append-only 事件流、配置字典这类没有自然排序键的 list 被迫加 `order_by="id"` 占位，或干脆放弃全局分页。

**新行为：** startup 改成对每个缺 `order_by` 的 list 关系打一条 WARNING，列出被跳过的 `Entity.field`，然后正常启动。被跳过的关系走 regular loader，SDL/introspection 自动把它们渲染成 `[T]!` 而非 `Result<T>`——这些路径本来就是 per-relationship 看 `page_loader is not None` 判断的，零下游改动。

**为什么是 warning 而不是 silent：** issue 作者列的场景是"主动不想分页"，但仍然希望 startup 能看到"哪些 list 被跳过了"，避免"以为开了分页实际某些 list 没"的错觉。WARNING 既不阻塞启动，又能用 logging filter 主动静音。

**未做（YAGNI）：** 没加 `strict_pagination=True` opt-in，也没加显式 opt-out 入口（`__nexusx_no_paginate__` / SQLAlchemy `info` dict）。等真有人抱怨 warning 噪音再叠加。

**Changes：**
- `src/nexusx/loader/registry.py`: `_validate_pagination` 从 `raise ValueError` 改成 `logger.warning`；docstring 同步
- `tests/test_loader_registry.py`: 删除原本名实不符的 `test_pagination_validation_raises_on_missing_order_by`（fixture 都有 `order_by`，根本没测到 fail path），换成真正验证 warn-skip 行为的 `_PagParent/_PagChild` 集成测试；`TestPaginationValidation` 里两个 mock 测试同步翻转断言；新增 `test_no_warning_when_all_list_relationships_have_order_by` sanity test
- `tests/test_pagination_mixed.py`: 新增端到端测试，用一个 parent 同时挂"有 order_by"和"无 order_by"两条 list 关系，分别验证 SDL 渲染（`Result<T>` vs `[T!]!`、`Result` 类型只对分页目标生成）、introspection 字段形状（args 只挂在分页字段上）、execution（page_loader 返回 Result dict，regular loader 返回 `list[T]`）

---

## 3.1.2

Port of pydantic-resolve v5.10.2 (`commit 184886d`) — three INPUT_OBJECT correctness fixes for the UseCase compose surface. Before this release, nexusx registered every Pydantic `BaseModel` as a GraphQL `OBJECT` regardless of whether it appeared as a method return or a method argument. That violated the GraphQL spec (input types must be `INPUT_OBJECT`) and crashed with `DuplicateTypeError` when the same class was used as both return and arg.

### Bug Fix: BaseModel 方法参数现在注册为 INPUT_OBJECT（US1）

`@mutation create_task(payload: CreateTaskInput)` 之前在 schema 里把 `CreateTaskInput` 登记成 `OBJECT`，违反 GraphQL spec（field arg 必须是 `INPUT_OBJECT`）。GraphiQL 拒绝渲染，`graphql.build_client_schema` 校验失败。

**行为：**
- 新增 `ComposeTypeMapper.map_python_type_as_input(py_type)` 公共入口；`_build_method_arguments` 改走这条路径
- `_map_leaf` 根据 `is_input` 把 BaseModel 叶子分派到新加的 `_register_input_object`（产出 `kind=INPUT_OBJECT` + 填充 `input_fields`）
- 每个 input field 的 `default_value` 来自 pydantic field default，渲染成 GraphQL literal（`5` / `null` / `"hi"` / `true`），与现有 method-arg default 序列化路径一致
- mutable defaults（`default_factory=...`）依然不支持，按"无静态字面量"处理

**Changes：**
- `src/nexusx/use_case/compose_type_mapper.py`: 新增 `map_python_type_as_input` / `_register_input_object` / `_build_input_field_info`；`_map` / `_map_optional` / `_map_list` / `_map_leaf` 全链路加 `is_input` 关键字参数；import `ArgumentInfo` + `pydantic_core.PydanticUndefined`
- `src/nexusx/use_case/compose_schema.py`: `_build_method_arguments` 改调 `map_python_type_as_input`
- `tests/test_compose_introspection.py::TestInputTypeEdgeCasesUS1`: 4 个新测试覆盖基本登记、默认值字面量、Optional/list 字段 nullability

### Bug Fix: 同一 BaseModel 同时作为返回和参数不再崩溃（US2）

`upsert_task(patch: TaskDTO) -> TaskDTO` 之前直接 `DuplicateTypeError` 崩掉（class name 已被 return 侧占住）。GraphQL spec 禁止一个类型同时是 OBJECT 和 INPUT_OBJECT。

**行为：**
- `build_compose_schema` 重构成两阶段：先跨所有 service 登记所有 return 侧 OBJECT，再跨所有 service 登记所有 arg 侧 INPUT_OBJECT。phase 顺序 load-bearing —— 只有 OBJECT 先占住 bare class name，input 侧重命名分支才能正确触发
- `_register_input_object` 在 bare name 已被 OBJECT 占住且 `python_class is cls` 时，自动重命名为 `{Name}Input`（例如 `TaskDTO` → `TaskDTOInput`）
- distinct-class 同名（不同 Python 类共享 `__name__`）依然 `DuplicateTypeError`，原有 guard 不变
- 嵌套 input 闭包一致性：`OuterInput.inner: InnerInput` 这种字段也走 `map_python_type_as_input`，嵌套的 `InnerInput` 自动登记为 INPUT_OBJECT；如果 `InnerInput` 也被用作 return，则 leaf name 一致地重命名为 `InnerInputInput`

**Changes：**
- `src/nexusx/use_case/compose_schema.py`: `build_compose_schema` 整体重构成 pass-1 收集元数据 + phase-A 登记返回 + phase-B 登记 args + phase-C 装配 FieldInfo；删除旧的 `_build_service_fields` 单遍实现
- `src/nexusx/use_case/compose_type_mapper.py`: `_register_input_object` 加 rename-on-conflict 分支；幂等性检查改扫描式（不再依赖 `_by_python_id`，避免 OBJECT 和 INPUT_OBJECT 互相覆盖）
- `tests/test_compose_introspection.py::TestInputTypeEdgeCasesUS2`: 2 个新测试覆盖同名冲突 + 嵌套 input

### Bug Fix: 方法级 SDL 现在展开 INPUT_OBJECT 类型（US3）

`render_method_sdl(service, method)` 之前只收集返回类型的闭包，且 `_collect_closure` 把 INPUT_OBJECT 当叶节点不递归。结果 SDL 里引用了 `input CreateTaskInput { ... }` 却从不定义它 —— AI agent / 文档读者看到的 SDL 是残缺的。

**行为：**
- `_collect_closure` 增加 INPUT_OBJECT 分支：递归走 `input_fields[*].type_ref`
- `_render_method_sdl` 同时从返回 type_ref 和每个 arg 的 type_ref 起步收集闭包
- `_emit_type_sdl` 对 `kind=INPUT_OBJECT` 改读 `t.input_fields`（之前无条件读 `t.fields`），并渲染 `name: Type = literal` 默认子句

**Changes：**
- `src/nexusx/use_case/compose_schema.py`: `_collect_closure` / `_render_method_sdl` / `_emit_type_sdl` 三处扩展
- `tests/test_compose_introspection.py::TestInputTypeEdgeCasesUS3`: 1 个新测试验证 SDL 含 `input MDLInput { ... }` 块及字段展开

### Spec-Compliance Gate: GraphiQL canonical introspection round-trip

`tests/test_compose_introspection.py::TestGraphiQLCompatibility::test_canonical_graphiql_introspection_query_works` —— 把 GraphiQL 启动时发送的标准 introspection query 喂给 `compose_introspect`，再把结果交给 `graphql.build_client_schema`。这是 FR-008 / SC-002 的硬性闸：任何一个 spec 违规（INPUT_OBJECT 字段错放在 OBJECT 上、dangling type ref、malformed default）都会让 `build_client_schema` 抛错。

**Regression invariants** (`TestRegressionInvariants`): 显式断言"没有 BaseModel 参数的 app 不会引入任何 INPUT_OBJECT TypeInfo" + "SCALAR/ENUM 的 TypeInfo 永远不带 `python_class`"，把 FR-009 / SC-003 的不变量钉死，防止未来重构意外把 OBJECT 翻成 INPUT_OBJECT。

---

## 3.1.1

### Bug Fix: `_orm_to_dto` 保留 DB NULL（修复 BUG_1_2）

`Resolver._orm_to_dto` 在把 ORM 实例转换为 DefineSubset DTO 时，过滤掉 `None` 值导致 DB NULL 被静默替换成 DTO 字段的 `Field(default=...)` 默认值。NULL 和"显式默认值"在 API 响应里无法区分——评分场景下 "未评分" 与 "评分为零" 同样是 0；时间戳场景下 NULL 被替换成 `default_factory=datetime.now` 完全失去语义。

**行为：**
- `_orm_to_dto` 直接透传字段值（含 None）给 DTO 构造器
- 若 DTO 字段类型不允许 None（非 `Optional[...]`），Pydantic validation 会抛错——这是正确的 schema 不匹配信号，强制用户在 schema 上声明 `Optional`
- 仅影响 auto-load 路径（`_orm_to_dto`）。直接 `DTO.model_validate(orm)` 不受影响

**Changes：**
- `src/nexusx/resolver.py:680`: 去掉 `if v is not None` filter，改为 `{f: getattr(orm_instance, f, None) for f in subset_fields}`
- `tests/test_resolver.py::TestOrmToDto`: 新增 2 个测试——`test_orm_to_dto_preserves_null_for_optional_field`（NULL 必须保留为 None）+ `test_orm_to_dto_preserves_explicit_zero`（counter-test，明确 0 不被误判）

### Bug Fix: QueryExecutor per-field 异常现在写日志（修复 BUG_1_3）

`QueryExecutor` 在 resolver 抛错时（如 `@query` 方法内部的 `AttributeError`）只把异常 message 塞进 response `errors` 列表，**不写任何日志**——整个 `query_executor.py` 连 `import logging` 都没有。server bug 完全不可见：Sentry/Loki/CloudWatch 这些基于日志的告警系统收不到信号，运维无法定位生产事故。

**行为：**
- per-field except 仍把异常塞进 response（保持 GraphQL-spec 兼容的 `{message, path}`）
- 额外调用 `logger.exception("Resolver error in field %s", field_name)`，让 traceback + exception type + line number 进入服务端日志
- response shape 不变

**实测对比：**

| 异常来源 | 修复前日志 | 修复后日志 |
|---|---|---|
| 顶层语法错误（handler.py 兜底） | ✅ 完整 traceback | ✅ 完整 traceback（不变） |
| Resolver 抛 AttributeError | ❌ 完全空 | ✅ 完整 traceback + exception type |

**Changes：**
- `src/nexusx/execution/query_executor.py`: 顶部加 `import logging` + `logger = logging.getLogger(__name__)`；per-field except 加 `logger.exception(...)` 调用
- `tests/test_query_executor.py::TestQueryExecutorBasic`: 新增 `test_execute_handles_exception_in_method_logs_traceback`——用 `caplog` 验证 logger 收到 exception type、Traceback、message

### Bug Fix: `post_default_handler` + `default_handler` 字段冲突检测（修复 BUG_1_6）

`post_default_handler` 是保留字（作为 finalizer 跑在所有 `post_*` 之后，不自动绑定字段）。但 `post_<field>` 命名约定强烈暗示 `post_default_handler` 会填充名为 `default_handler` 的字段。用户同时定义两者时，方法返回值被静默丢弃、字段保持默认值——零警告。常量 `POST_DEFAULT_HANDLER` 也没在 `nexusx.__init__` 导出，保留字完全不可发现。

**行为：**
- 仅 `post_default_handler` 方法存在时：保持原 finalizer 行为不变（backward compat）
- 仅 `default_handler` 字段存在时：当作普通字段（无副作用）
- **同时**定义两者时：`_build_class_meta` 抛 `ValueError`，错误信息附 3 种修复路径（rename method / drop field / 手动赋值）

**Changes：**
- `src/nexusx/resolver.py:_build_class_meta`: 在 `post_default_handler` 分支检测 `kls.model_fields` 是否含 `default_handler`，若是则 raise
- `tests/test_resolver.py::TestResolverPostDefaultHandler`: 新增 3 个测试——`test_conflict_when_default_handler_field_also_exists`（冲突必须 raise）+ 2 个 counter-test（仅 method / 仅 field 各自的行为）

### Docs: CLAUDE.md 精简为纯行为约束

CLAUDE.md 此前包含技术栈、目录结构、公共 API 列表、开发命令、核心约定、常见陷阱等 200 行技术细节，与 `pyproject.toml` / `__init__.py` / 源码本身重复且容易脱节（review 发现版本号、目录、API 列表均已过时 2 个大版本）。

**行为：**
- CLAUDE.md 简化为只保留"开发注意事项"段（uv.lock 镜像源约束）+ SPECKIT 工具自动管理段
- 所有技术细节改为以源码 / pyproject.toml 为单一来源（`grep` / `find` 即可获取）
- CLAUDE.md 加入 `.gitignore`，避免再次脱节

**Changes：**
- `CLAUDE.md`: 从 ~200 行简化为 17 行
- `.gitignore`: 加入 `CLAUDE.md`

### Chore: Review 测试基础设施

review 期间为校验 finding 写的 failing-test 文件 `tests/test_review_findings.py` 已移至 `review/test_review_findings.py`（不进 git，pytest 默认不发现），与 `review/review_result.md` 一并 gitignore。

---

## 3.1.0

### New Feature: Resolver `loader_instances` 参数

移植 pydantic-resolve 的 `Resolver(loader_instances=...)` API 到 nexusx。调用方可传入预创建（通常已 prime）的 DataLoader 实例，按 class 匹配，用于跳过已知 key 的冗余 batch 调用。

**行为：**
- `Resolver(loader_registry=..., context=..., loader_instances={LoaderClass: instance})` 接受预创建的 DataLoader 实例字典
- 当 `resolve_*` 方法声明 `loader=Loader(Cls)` 且 `Cls` 在字典中时，Resolver 返回调用方提供的实例；否则按原逻辑创建新实例（行为不变）
- 构造期校验：key 必须是 `aiodataloader.DataLoader` 子类，value 必须是 key 的实例。不合规输入在构造期抛 `TypeError`，绝不进入 traversal
- 提供的实例按引用使用（不复制），`Resolver.resolve()` 不会清理它们——caller 拥有生命周期，需要 per-request 隔离的场景请每次构造新实例
- `ErManager.create_resolver()` 工厂将 `loader_instances` 透传到底层 Resolver

**范围限定（关键）：** 仅影响显式 `Loader(Cls)` Depends 路径。auto-load 路径——无论是 `__relationships__` 自定义关系还是 ORM 原生 SQLModel 关系——一律不变，因为他们走 ErManager 的按名字查找，根本不查询 `_loader_instances`。决策记录在 `specs/002-resolver-loader-instances/spec.md`（Clarifications 2026-06-23）。

**与 pydantic-resolve 的差异：** 无——严格等价移植，class-keyed API；唯一区别是错误类型选用更地道的 `TypeError`（pydantic-resolve 用 `AttributeError`）。

**示例：**

```python
from aiodataloader import DataLoader
from nexusx import ErManager

class UserLoader(DataLoader):
    async def batch_load_fn(self, keys):
        return [await fetch_user(k) for k in keys]

# 已知当前用户，跳过 DB 往返
loader = UserLoader()
loader.prime(current_user.id, current_user_dto)

er = ErManager(base=SQLModel, session_factory=async_session)
Resolver = er.create_resolver()
resolver = Resolver(
    context={"user_id": current_user.id},
    loader_instances={UserLoader: loader},
)
result = await resolver.resolve(dtos)
```

**Changes：**
- `src/nexusx/resolver.py`: `Resolver.__init__` 新增 `loader_instances` 参数；新增 `_validate_loader_instances` 静态方法（构造期 `TypeError`）；`_get_or_create_loader` 先查 `_loader_instances` 再 fallback 到 `_loader_cache`；类 docstring 更新参数说明与生命周期语义
- `src/nexusx/loader/registry.py`: `ErManager.create_resolver()` 返回的 `BoundResolver.__init__` 透传 `loader_instances`
- `tests/test_resolver.py`: 新增 `TestLoaderInstances`（3 个测试覆盖 US1 pre-prime、US2 by-reference、US3 校验失败）
- `tests/test_loader_registry.py`: 新增 `test_create_resolver_forwards_loader_instances`（FR-005 工厂透传）
- `specs/002-resolver-loader-instances/`: 完整 speckit 工件（spec / plan / research / data-model / contracts / quickstart / tasks）

### Chore: 全树 ruff --fix + uv.lock 同步

PR #82 顺手做的代码树清理：

- `ruff check --fix` 清理 49 个 lint issue，主要是 `benchmarks/`、`demo/`、`tests/` 中冗余的 inline `from typing import Annotated`（顶层已 import）
- `uv.lock`: nexusx 3.0.0 → 3.0.1 同步（`face1aa` 把 `pyproject.toml` bump 到 3.0.1 时 lock 文件漏同步；本次 PR 的 `uv run` 顺手补上。**无镜像源引入**，仍指向 `pypi.org`，符合 CLAUDE.md 约定）
- `tests/` 中仍有 16 个 `Optional[X] → X | None` 的 ruff 提示（需要 `--unsafe-fixes`），本次未处理

**版本同步：**
- `pyproject.toml`: 3.0.1 → 3.1.0
- `uv.lock`: nexusx 3.0.1 → 3.1.0

## 3.0.1

### Bug Fix: `use_case.cli` 不再在 import 时强制要求 `typer`

`use_case/cli.py` 原本在模块顶部 `try: import typer except ImportError: raise`，导致只要 `import nexusx`（更准确说，触发 `nexusx.use_case` 包加载）就会 eager 拉起 `typer`，即使从没碰过 CLI 入口。这与 `nexusx.mcp` 处理 `fastmcp` 的方式不一致——后者用 `TYPE_CHECKING` 守卫 type-only import、runtime 在函数体内 lazy import。

**行为：**
- `import nexusx` 不再 eager 加载 `typer`；用户不必装 `nexusx[cli]` extra 也能调用 `create_simple_mcp_server` / `create_use_case_graphql_mcp_server` / `create_router` / `create_jsonrpc_router` 等所有非 CLI 入口
- `create_use_case_cli()` 行为不变；首次调用时才在函数体内 `import typer`，未装时由 typer 自身抛 `ImportError`（移除了自定义错误信息）
- 公共 API 表面完全不变；`create_use_case_cli` 仍是 `nexusx` 顶层导出符号

**Changes：**
- `src/nexusx/use_case/cli.py`: 删掉顶部 `try: import typer except ImportError: raise` 块；改用 `if TYPE_CHECKING: import typer`；`_build_command` 和 `create_use_case_cli` 函数体内分别加局部 `import typer`

**版本同步：**
- `pyproject.toml`: 3.0.0 → 3.0.1

## 3.0.0

### BREAKING: 移除老的直接调用式 UseCase MCP 入口

引入由 `UseCaseService` 自动生成**真正的 GraphQL schema**、并基于此构建 MCP 服务的新执行链（参考 `pydantic-resolve` 的 compose 实现）。配套**硬移除**两个老的直接调用式 use_case MCP 入口（调用 Python 方法 + JSON 参数的范式）。与 GraphQL/MCP 正交的 `create_use_case_router`（FastAPI REST）与 `create_use_case_voyager`（Voyager 可视化）**保持不变**。

**移除：**

| 入口 | 替代 |
|------|------|
| `create_use_case_mcp_server`（4 层渐进披露 MCP，Layer 3 是 `call_use_case` 直接方法调用） | `create_use_case_graphql_mcp_server`（4 层渐进披露，Layer 3 是 `compose_query` 接收 GraphQL 字符串） |
| `create_use_case_flat_server`（一方法一 tool 的扁平 MCP） | `create_use_case_graphql_mcp_server`（同上；如需扁平 tool-per-method 范式可基于 `build_compose_schema` 自建） |
| `ServiceIntrospector`（内部类，仅生成 SDL 风格字符串） | `ComposeSchema`（生成真正的 GraphQL schema：introspection JSON + SDL） |

迁移指南：[`docs/migrations/3.0-use-case-graphql.md`](./docs/migrations/3.0-use-case-graphql.md)

### New Feature: UseCase GraphQL + 4 层 MCP

**新增公共 API：**

| 函数 / 类 | 用途 |
|----------|------|
| `create_use_case_graphql_mcp_server(apps, name)` | 4 层渐进披露 MCP server：`list_apps` → `describe_compose_schema` → `describe_compose_method` → `compose_query` |
| `build_compose_schema(app) -> ComposeSchema` | 直接访问生成的 schema（可用于自建 GraphiQL / 嵌入其它入口） |
| `ComposeSchema` | 产物类，提供 `render_introspection()` / `render_sdl()` / `render_method_sdl(service, method)` |
| `compose_introspect(schema, query)` | 处理 GraphiQL 风格的 introspection 查询（`__schema` / `__type` / `__typename`），返回 `{data, errors}` 信封。与 MCP Layer 3（拒绝内省）成对：MCP 走渐进披露，HTTP GraphiQL 走完整内省 |
| `ComposeSchemaError` 及子类 | schema 生成期错误：`DuplicateServiceError` / `DuplicateMethodError` / `DuplicateTypeError` / `UnsupportedTypeError` / `SQLModelInDtoFieldError` / `MissingReturnAnnotationError` |

**Schema 结构（固定三层）：**

```graphql
type Query {
  TaskService: TaskServiceQuery!
  UserService: UserServiceQuery!
}
type TaskServiceQuery {
  list_tasks: [TaskSummary!]!
  get_task(task_id: Int!): TaskSummary
}
```

**4 层 MCP 工具响应 shape：**

| Layer | 工具 | 响应信封 |
|-------|------|---------|
| 0 | `list_apps` | `{success, data}` |
| 1 | `describe_compose_schema` | `{success, data}` |
| 2 | `describe_compose_method` | `{success, data}` |
| 3 | `compose_query` | `{data, errors}`（GraphQL 标准） |

Layer 3 接收标准 GraphQL 字符串；**拒绝内省查询**（`__schema` / `__type` / `__typename`），返回 `{data: null, errors: [...]}` 引导用 Layer 1/2 探索 schema。

**执行边界（关键）：** GraphQL 执行层**不**在 service 方法返回值外再套一层 `Resolver`。service 方法内部已经显式 `Resolver().resolve(dtos)`，外层只做：调方法 → 字段投影（基于 `subset.build_subset_model`） → 序列化。

**版本号策略：** 严格 semver —— 公共 API 移除 = major bump（2.10.1 → 3.0.0）。

### Preserved (Unchanged)

以下公共 API 签名与行为均保持不变：

- `UseCaseService` / `BusinessMeta` / `@query` / `@mutation` / `FromContext` / `UseCaseAppConfig`
- `create_use_case_router`（FastAPI REST 自动路由）
- `create_jsonrpc_router`（JSON-RPC over HTTP）
- `create_use_case_voyager`（Voyager 可视化）
- GraphQL 模式全部能力（`GraphQLHandler` / `SDLGenerator` / 既有 `mcp/` 模块）

## 2.10.1

### Bug Fix: scalar-list 自定义关系字段支持隐式 auto-load

修复 DTO 字段类型为 scalar（如 `list[int]` / `str`）且字段名匹配一个 `Relationship(target=list[int])` / `Relationship(target=str)` 形式的 CUSTOM 自定义关系时，隐式 auto-load 被静默跳过的问题。此前 `_scan_auto_load_fields` 强制要求字段类型为 BaseModel 子类（DTO），导致 scalar 类型字段即使匹配关系也不会自动加载，必须手写 `resolve_*` 才行。

**行为：**
- DTO 字段类型为 BaseModel DTO → 走原有路径（兼容性用 `is_compatible_type(dto_cls, target_entity)` 校验）
- DTO 字段类型为 scalar primitive → 仅当对应关系方向为 `CUSTOM` 且字段 annotation 与关系原始 `target`（按 `is_list` 重建 `list[target_entity]` 或 `target_entity`）兼容时，加入 auto-load 列表
- ORM 关系（MANYTOONE / ONETOMANY / MANYTOMANY）target 是 SQLModel 实体，scalar 字段不会误匹配
- 下游 `_batch_auto_load` 在 `dto_cls=None` 时已能正确处理（跳过 ORM→DTO 转换、跳过子节点 BFS 追加），本次修复无需改动加载链路

**Changes：**
- `src/nexusx/resolver.py`: `_scan_auto_load_fields` 把 `rel_info` 查询提到 `dto_cls` 判空之前，新增 scalar 分支调用 `_is_scalar_rel_field`；新增 `_is_scalar_rel_field` 静态方法（按 `is_list` 重建 raw target 并复用 `is_compatible_type`）
- `tests/test_autoload.py`: 新增 `TestAutoLoadScalarListField`（2 个测试覆盖 scalar-list 隐式 auto-load + 显式 `resolve_*` 回退路径）

### Docs: skill Phase 0/1 增加 DB 选型与 alembic 迁移策略

skill 4-phase 开发模式文档增强：Phase 0 新增 Step 0-7「数据持久化与迁移策略」，列出 in-memory sqlite / file sqlite / docker pg / docker mysql / external DB 五种选型的对比表，并明确 alembic 引入条件、`init_db()` 实现策略、`scripts/load_seed.py` 一次性灌种等下游影响；Phase 1 `db.py` / `database.py` 实现描述与 Phase 0 决策挂钩，新增 alembic baseline 验证步骤。

**Changes：**
- `skill/SKILL.md`: Step 0-7 数据持久化决策表 + alembic 引入清单 + 目录结构调整（alembic / scripts / var）
- `skill/phases/phase1.md`: db.py URL 来源、database.py 双策略（in-memory create_all+seed vs 持久化 no-op+alembic）、alembic baseline 验证
- `skill/spec-management.md`: 配套字段更新

**版本同步：**
- `pyproject.toml`: 2.10.0 → 2.10.1
- `uv.lock`: 同步 nexusx 包版本（v2.10.0 发布时漏同步的 2.9.2→2.10.0 一并修正至 2.10.1）

## 2.10.0

### New Feature: Resolver `post_default_handler` 收尾钩子

新增保留方法 `post_default_handler(self)`，在该节点所有 `post_*` 方法执行完毕后运行，用于跨多个 `post_*` 字段的聚合 / 收尾计算（如根据多个计数算 completion_rate、拼接 summary）。语义对齐 pydantic-resolve 的同名特性。

**行为：**
- 固定方法名 `post_default_handler`（非 `post_<field>`，不绑定到某个字段）
- 在同节点所有 `post_*` 完成后执行（可安全读取它们写入的字段）
- **不自动赋值**：返回值被忽略，方法体内手动 `self.xxx = ...`（可一次写多个字段）
- 支持与 `post_*` 相同的参数注入：`context` / `parent` / `ancestor_context` / `Loader` / `Collector`，可为 `async`
- 由于 BFS 递归先于 `post_*` 阶段，`post_default_handler` 能读到后代 `SendTo` 已经收集进祖先 Collector 的值

**与 pydantic-resolve 的差异：** nexusx 额外允许在 `post_default_handler` 中使用 `Loader`（pydantic-resolve 显式禁用），保持与 `post_*` 内部一致。

**示例：**

```python
class SprintView(BaseModel):
    total_tasks: int = 0
    completed_tasks: int = 0
    completion_rate: float = 0.0
    summary: str = ""

    def post_total_tasks(self):
        return len(self.tasks)

    def post_completed_tasks(self):
        return len([t for t in self.tasks if t.status == "done"])

    def post_default_handler(self):
        # runs after post_total_tasks / post_completed_tasks
        self.completion_rate = (
            self.completed_tasks / self.total_tasks
            if self.total_tasks else 0.0
        )
        self.summary = f"{self.completion_rate:.0%} complete"
```

**Changes：**
- `src/nexusx/resolver.py`: 新增 `POST_DEFAULT_HANDLER` 常量；`_ClassMeta` 增加 `post_default_handler` 字段；`_build_class_meta` 优先识别保留名（避免被 `post_*` 前缀分支误当成 `default_handler` 字段）；`_compute_should_traverse` 计入该方法（否则仅含该钩子的子节点不会被遍历）；`_execute_posts` 末尾追加一轮调用（不 setattr）
- `tests/test_resolver.py`: 新增 `TestResolverPostDefaultHandler`（9 个测试覆盖执行顺序、返回值忽略、async、Collector、context、parent、ancestor_context、仅含 handler 的子节点遍历、多兄弟节点）
- `CLAUDE.md`: 更新 Resolver 执行顺序（新增第 4 步）与常见陷阱（保留方法名）

## 2.9.2

### New Feature: DefineSubset FK 字段自动注入

FK 字段自动注入到 DTO（`model_fields`），供 Resolver 用作 DataLoader key 加载关系。与 PK auto-include 机制对称：字段存在但 `exclude=True`，不出现在 `model_dump()` 序列化输出中。`build_dto_select()` 自动排除这些字段，不生成多余的 SELECT 列。

**行为：**
- 未在 `__subset__` 中声明的 FK 字段自动注入，annotation 改为 `Optional`（`default=None`），`exclude=True`
- 显式声明在 `__subset__` 中的 FK 字段保持原样，不受影响
- `SubsetConfig(omit_fields=["owner_id"])` 可阻止 auto-include，但如果 DTO 同时声明了对应的关系字段（如 `owner: OwnerDTO`），会抛出 `ValueError`

**Changes：**
- `src/nexusx/subset.py`: 新增 `_get_fk_field_names()`；`_resolve_subset_fields` FK auto-include（尊重 `omit_fields`）；`_build_field_definitions` 对 auto-included FK 设 `Optional + default=None + exclude=True`；`_create_subset_class` 存 `__subset_auto_excluded__`；`build_dto_select` 排除 auto-excluded 字段；新增 `_validate_omitted_fk_not_needed()` 校验 omit FK 与关系字段冲突
- 修正旧测试适配新行为；新增 2 个测试覆盖 omit FK 场景

## 2.9.1

### Bug Fix: `list[T] | None` 和 `list[T | None]` 类型转换错误

修复 `_python_type_to_graphql` 中 Optional 与 list 组合类型的 GraphQL SDL 生成错误。

**根因：** `_python_type_to_graphql` 先检查 `origin is list`，再检查 Optional。对于 `list[str] | None`，`get_origin()` 返回 `UnionType` 而非 `list`，list 检查被跳过。Optional 分支 unwrap 后调用 `_python_type_to_graphql_inner`，而 `_inner` 不处理 list 类型，fallback 为 `String`。同理，`list[Entity | None]` 的元素类型也因 `_inner` 不处理 Optional 而 fallback 为 `String`。

**影响：**
- `list[str] | None` 参数/返回值 → SDL 中生成 `String` 而非 `[String!]`
- `list[int] | None` 参数/返回值 → SDL 中生成 `String` 而非 `[Int!]`
- `list[Entity | None]` 参数/返回值 → SDL 中元素类型丢失，fallback 为 `String`

**Changes：**
- `src/nexusx/sdl_generator.py`: Optional 分支改为递归调用 `_python_type_to_graphql`（而非 `_inner`），使 list 检查能再次命中；list 分支先 unwrap 元素的 Optional，再传给 `_inner`
- 修正 `tests/test_sdl_generator.py::test_list_optional_int` 的错误期望（`[String]!` → `[Int]!`）
- 新增 `tests/test_optional_list_param.py`：9 个测试覆盖 `list[str] | None`、`Optional[list[str]]`、`list[int] | None`、`list[str]`、`list[Entity | None]`、`list[str | None]` 及完整 SDL 生成

## 2.9.0

### Bug Fix: 自定义关系在全局分页下无法查询

`enable_pagination=True` 时，自定义关系（`direction="CUSTOM"`）因缺少 `page_loader` 被 `_validate_pagination` 拦截并报错。自定义关系使用用户提供的 loader callable，无法像 ORM 关系那样在 SQL 层做分页。

**Changes：**
- `src/nexusx/loader/registry.py`: `_validate_pagination` 跳过 CUSTOM 方向的关系，使其在全局分页下用普通 loader 正常查询（不分页）
- 新增 E2E 测试验证 `enable_pagination=True` 时自定义关系通过普通 loader 返回完整结果

### Refactoring: 公共 API 精简

精简顶层导出，移除内部实现细节和命名不规范的符号。

**移除的导出（内部路径不变）：**

| 符号 | 内部路径 |
|------|---------|
| `SDLGenerator` | `nexusx.sdl_generator.SDLGenerator` |
| `QueryParser` | `nexusx.query_parser.QueryParser` |
| `FieldSelection` | `nexusx.query_parser.FieldSelection` |
| `get_return_type` | `nexusx.use_case.business.get_return_type` |

**重命名：**

| 旧名 | 新名 |
|------|------|
| `create_cli` | `create_use_case_cli` |
| `create_flat_mcp_server` | `create_use_case_flat_server` |

**Changes：**
- `src/nexusx/__init__.py`: 移除 `SDLGenerator`、`QueryParser`、`FieldSelection`、`get_return_type` 导入和 `__all__` 条目；导入改为新名称
- `src/nexusx/use_case/cli.py`: `create_cli` → `create_use_case_cli`
- `src/nexusx/use_case/flat_server.py`: `create_flat_mcp_server` → `create_use_case_flat_server`
- `demo/`、`tests/`、`skill/` 同步更新

## 2.8.0

### Bug Fix: 分页 limit 参数未传递到 QueryExecutor

修复 GraphQL 分页查询中 `limit` 参数被静默丢弃的问题。`tasks(limit: 1)` 等查询实际返回全部数据。

**根因：** `_build_field_jobs` 在处理分页关系时将 `child_sel` 替换为 `items_sel`（items 子选择），但 `_FieldJob` 只保存了替换后的选择。`_load_field_paginated` 从 `child_sel.arguments` 提取分页参数，而 `limit` 存在于原始的 tasks 字段选择上，items 子选择没有 arguments，导致 limit 丢失。

**Changes：**
- `src/nexusx/execution/query_executor.py`: `_FieldJob` 新增 `original_sel` 字段；`_build_field_jobs` 在替换为 items_sel 时保存原始选择；`_load_field_paginated` 从 `original_sel` 提取分页参数

### Bug Fix: 分页 has_next_page 差一错误 & Resolver 缓存泄漏

- `pagination.py`: 修复 `has_next_page` 在 `end == total_count` 时错误返回 True 的 off-by-one 问题
- `resolver.py`: 修复 `_ClassMeta` 缓存和 `scan_expose_fields` / `scan_send_to_fields` 模块级缓存未清理导致的内存泄漏

### Performance: BFS 跳过纯数据子树

Resolver BFS 遍历新增优化：当子树中没有 `resolve_*`、`post_*`、`ExposeAs`、`SendTo` 等需要执行的方法时，跳过 BFS 下沉，直接返回。纯数据 DTO（只有标量字段）不再进入遍历队列。

**Changes：**
- `src/nexusx/resolver.py`: 新增 `_has_work` 检查，`_process_level` 在入队前过滤无工作子树

### Chore: 测试覆盖率体系建立 + 核心模块测试补充

新增 `pytest-cov` 到 dev 依赖，配置 `--cov-report=term-missing` 和排除规则（`TYPE_CHECKING`、`NotImplementedError`）。新增 75 个测试覆盖 loader 分页加载器、query_executor、response_builder、sdl_generator。

**覆盖率变化：**

| 模块 | 2.7.0 | 2.8.0 |
|------|-------|-------|
| `loader/factories.py` | 50% | 90% |
| `loader/pagination.py` | 52% | 98% |
| `execution/query_executor.py` | 73% | 98% |
| `response_builder.py` | 74% | 90% |
| `sdl_generator.py` | 82% | 88% |
| 总体 | 75% | 79% |

**新增文件：**
- `tests/test_loader_pagination.py` — 29 个测试（分页 O2M/M2M loader、PageArgs、create_result_type）

**新增测试（追加到已有文件）：**
- `tests/test_query_executor.py` — +16 个测试（分页 e2e、边界条件、序列化）
- `tests/test_response_builder.py` — +23 个测试（forward ref、annotation 提取、scalar model）
- `tests/test_sdl_generator.py` — +8 个测试（分页类型、默认参数、类型转换）

**Changes：**
- `pyproject.toml`: 新增 `pytest-cov>=6.0.0`、`[tool.coverage.run]`、`[tool.coverage.report]` 配置

## 2.7.0

### Chore: Collector/SendTo 测试覆盖率提升（+8 测试，12→20）

从 pydantic-resolve 迁移 Collector/SendTo 测试场景，补充 nexusx Core API 的跨层数据流测试覆盖。测试按 nexusx BFS Resolver 的实际行为编写，覆盖了 Collector 从所有后代节点聚合、同节点同 alias 共享 Collector 实例、Loader-resolved 字段不触发 SendTo 等行为边界。

**新增测试：**
- `TestCollectorLevelByLevel`: 3 层树中 Collector 的层级隔离——子节点声明同名 Collector 会覆盖祖先实例
- `TestMultipleCollectSource`: B 和 C 同时 SendTo 同一 alias，祖先 Collector 从所有后代聚合
- `TestCollectorFlatNest`: `flat=True` 展平列表值 vs `flat=False` 保持嵌套结构（拆分为两个独立测试）
- `TestMultiFieldSendTo`: 同一节点多个字段发送到同一个 Collector
- `TestSubsetConfigSendTo`: `SubsetConfig.send_to` 参数等价于 `SendTo` 注解
- `TestPostLoaderCollectorLimitation`: `resolve_*` 通过 Loader 加载的子节点不会触发 SendTo 收集
- `TestCollectorIdentity`: 同一 `post_*` 中相同 alias 的两个 Collector 参数返回同一实例

## 2.6.0

### Performance: BFS 并发加载替代 DFS 串行递归（GraphQL QueryExecutor）

将 `QueryExecutor` 的关系字段加载从逐 field 串行递归 DFS 改为 level-by-level BFS，同层多个关系字段通过 `asyncio.gather` 并发加载。

**根因：** DFS 的 `_resolve_relationships` 对 `field_sel.sub_fields` 做 for 循环 + `await`，每个字段必须等上一个字段及其全部子节点加载完毕后才开始。当查询包含同级多个关系字段（如 `users { posts { comments } comments { post } }`），4 轮 SQL 往返串行执行。BFS 将同层字段并发加载，将 4 轮串行减少为 2 轮并发。

**MySQL benchmark（Large: 50 users, 1000 tasks）：**

| 场景 | DFS | BFS | 变化 |
|------|-----|-----|------|
| Q1: 1-level | 12.07ms | 11.74ms | -3% |
| Q2: 2-level | 14.60ms | 15.16ms | +4% |
| Q3: wide | 11.07ms | 9.13ms | **-18%** |
| Q4: deep+wide | 117.39ms | 18.39ms | **-84%** |

**Changes：**
- `src/nexusx/execution/query_executor.py`: 新增 `_FieldJob` 数据类和 `_bfs_resolve` 循环，替代 `_resolve_relationships` + `_load_batch` + `_load_paginated` 的递归模式。新增 `_build_field_jobs` 从 `field_sel.sub_fields` 提取关系字段构造 FieldJob 列表；`_load_field` / `_load_field_batch` / `_load_field_paginated` 只做加载+存储，不递归下沉。序列化层完全不变
- `benchmarks/bench_graphql.py`: 新增 GraphQL QueryExecutor benchmark，支持 SQLite（默认）和 MySQL（`--mysql`），4 个场景 × 3 个数据规模

## 2.5.2

### New Feature: 公共函数 `get_return_type`

将内部函数 `_get_return_type` / `_get_return_annotation` 提取为公共 API `get_return_type()`，用于从 UseCaseService 方法中提取返回类型注解。手动编写 FastAPI 路由时可直接用作 `response_model` 参数，无需重复声明类型。

**Changes：**
- `src/nexusx/use_case/business.py`: 新增公共函数 `get_return_type(method)`，支持 classmethod unwrap + `get_type_hints` + `inspect.signature` fallback
- `src/nexusx/use_case/server.py`: 替换 `_get_return_annotation` → `get_return_type`
- `src/nexusx/use_case/flat_server.py`: 同上
- `src/nexusx/use_case/router.py`: 替换 `_get_return_type` → `get_return_type`，删除旧私有函数
- `src/nexusx/__init__.py`: 导出 `get_return_type`

### Documentation: 全站文档结构优化

以 FastAPI 文档风格（渐进式 Q&A、Step 1/2/3、问题驱动）重构全部 guide 和 advanced 页面。消除 `er_diagram.md` 与 `custom_relationship.md` 的内容重叠。`use_case_service.md` 新增 FastAPI 自动路由（`create_use_case_router`）说明，`use_case_fastapi.md` 改用 `get_return_type` 示例。

**Changes：**
- `docs/guide/`: 重构 `quick_start`、`er_diagram`、`graphql_mode`、`graphql_pagination`、`graphql_auto_query`、`core_api`、`core_api_advanced`、`custom_relationship`、`er_diagram_visual` 共 9 个页面
- `docs/advanced/`: 重构 `mcp_service`、`use_case_service`、`use_case_fastapi`、`voyager` 共 4 个页面
- `docs/guide/er_diagram.md`: 精简 Step 2，消除与 `custom_relationship.md` 的内容重复

## 2.5.0

### Refactoring: 依赖清理 — 移除 uvicorn 和 greenlet 默认依赖

`uvicorn`（ASGI 服务器）和 `greenlet`（async/sync 桥接）不再是默认安装依赖。用户按需在项目中自行添加。

**Changes：**
- `pyproject.toml`: 从 `dependencies` 移除 `uvicorn>=0.41.0` 和 `greenlet>=3.3.2`，两者已在 `dev` 和 `demo` 可选依赖组中覆盖

### Docs: Clean Architecture 框架对比文章

新增 nexusx 与主流 Python 框架（Litestar、Django+DRF、Strawberry、FastAPI+SQLModel、Ariadne、Tartiflette、Temporalio）的 Clean Architecture 对比分析。

**Changes：**
- 新增 `docs/clean-architecture-comparison.md`

### Chore: Skill 渐进披露重构

将 643 行的 SKILL.md 拆分为多文件按需加载架构，每次调用上下文占用减少 50-75%。踩坑经验重新编号并按阶段归入对应文件。

**Changes：**
- `skill/SKILL.md`: 重构为轻量入口（概述 + Phase 0 + 调度指令）
- `skill/phases/phase1.md` ~ `phase4.md`: 各阶段详细指令 + 踩坑经验
- `skill/spec-management.md`: Spec 管理与工作流

## 2.4.1

### Chore: 测试覆盖率提升（+46 测试，678→724）

核心模块覆盖率显著提升，新增测试覆盖 P0（公共 API 校验）和 P1（边缘场景）盲区。

**覆盖率变化：**

| 模块 | 2.4.0 | 2.4.1 |
|---|---|---|
| `loader/registry.py` | 88% | 95% |
| `resolver.py` | 95% | 96% |
| `subset.py` | 86% | 90% |
| `utils/type_compat.py` | 68% | 92% |
| `use_case/selection.py` | 77% | 89% |

**新增测试：**
- `resolver.py`: post_* 中 Loader + Collector 组合注入、`_orm_to_dto` 无 `__subset_fields__` 分支、`_do_extract_dto_cls` 边界类型（字符串注解、Optional、非 BaseModel）
- `subset.py`: `__subset__` 类型校验（dict、错误长度 tuple）、PK 自动注入 + omit 排除、FK 字段显式包含/排除
- `loader/registry.py`: ErManager 初始化校验（base/entities 互斥、都不提供）、base 模式 EntityDiscovery、`create_resolver()` BoundResolver 绑定、分页校验（空 order_by、多列排序、缺少 order_by）
- `type_compat.py`: `is_compatible_type` 完整覆盖（Optional 解包、list 兼容、Union 拒绝、subset 链、子类检查）
- `selection.py`: 解析错误路径（空选择、带参数、空白）+ `_infer_runtime_annotation` 推断（混合类型列表、全 None、空列表）

## 2.4.0

### Performance: BFS Traversal replaces DFS in Resolver

将 Resolver 遍历引擎从 DFS 替换为 BFS，实现 DataLoader 的全量批量加载。

**根因：** DFS 逐节点串行调用 resolve_*，DataLoader 每个 tick 只能收集一个 key，无法发挥批量加载优势。BFS 将同一层所有 resolve_* 方法通过 `asyncio.gather` 并发执行，DataLoader 在单个 tick 内收集所有 key，一次性发出批量查询。

**Changes:**
- `src/nexusx/resolver.py`: 重写遍历引擎为 BFS `_process_level`，5 阶段流水线：Phase 0 元数据准备 → Phase 1 resolve_* 并行执行 → Phase 2 递归子层 → Phase 3 post_* 执行 → Phase 4 SendTo 收集
- `_batch_auto_load`: 新增批量 auto-load，按关系分组收集 FK 值，使用 `load_many` 一次性加载
- `Resolver.resolve()` 移除 `mode` 参数，统一使用 BFS
- 新增 `_WorkItem` 数据结构传递节点 + 父级上下文 + collector 快照

### Bug Fix: Auto-load 子节点重复遍历

修复 `_batch_auto_load` 设置字段后，existing-fields scan 再次拾取这些字段导致子节点被加入 `next_level` 两次的问题。auto-load + SendTo 组合场景下 Collector 会收集重复值。

**Changes:**
- `src/nexusx/resolver.py`: `_batch_auto_load` 返回已加载的 `(id(node), field_name)` 集合，existing-fields scan 跳过这些字段
- 新增测试覆盖 auto-load + SendTo 去重、resolve_* ancestor_context、SendTo 多 Collector、空列表/非 BaseModel/tuple/混合列表输入、resolve_* 返回 tuple

### Chore: Benchmark 精简

移除 raw dict benchmark（`bench_raw_*`），仅保留 Pydantic DTO vs nexusx DefineSubset 对比。

## 2.3.1

### Bug Fix: Python 3.14 (PEP 649/749) DefineSubset extra fields 丢失

修复 `DefineSubset` 在 Python 3.14+ 上类体中声明的 extra fields（关系字段、派生字段）全部丢失的问题。

**根因：** Python 3.14 实现 PEP 649/749，类体 namespace 中 `__annotations__` 变为 `None`，注解延迟存储在 `__annotate_func__` 中。`_extract_extra_fields` 读到空 dict，导致所有 extra fields 被忽略。

**Changes:**
- `src/nexusx/subset.py`: 新增 `_get_namespace_annotations()` compat helper，3.14+ 从 `__annotate_func__(1)` 获取 annotations dict，低版本继续用 `__annotations__`
- 新增 `tests/test_py314_compat.py`: 6 个测试覆盖 scalar / relationship / derived / roundtrip / excluded 场景

## 2.3.0

### New Feature: Flat MCP Server

新增 `create_flat_mcp_server()` — 扁平化 MCP 服务器，每个 `@query`/`@mutation` 方法直接注册为独立 MCP tool，替代 4 层渐进披露模式。适合方法数量较少的场景，LLM 可一步到位调用。

**用法：**

```python
from nexusx import UseCaseAppConfig, create_flat_mcp_server

mcp = create_flat_mcp_server(
    apps=[
        UseCaseAppConfig(
            name="order_system",
            services=[OrderService, CustomerService, ProductService],
        ),
    ],
)
mcp.run()
```

**特性：**
- 每个 `@query`/`@mutation` 方法注册为独立 tool，命名 `{ServiceName}_{method_name}`
- 方法参数从 Python 签名直接映射（排除 `cls` 和 `FromContext`），支持 `selection` 投影
- 每个 app 一个 MCP resource（`nexusx://{app_name}`），包含所有 service 的方法签名 + SDL 类型定义
- `enable_mutation=False` 过滤 mutation tools
- Tool 碰撞时自动加 app 前缀

**新增文件：**
- `src/nexusx/use_case/flat_server.py` — `create_flat_mcp_server` 及 tool/resource 注册

**Changes：**
- `use_case/__init__.py`、`__init__.py`: 导出 `create_flat_mcp_server`
- `CLAUDE.md`: 更新公共 API 列表

## 2.2.1

### Bug Fix: Merge v2.1.0 Selection 投影功能到 master

v2.1.0（UseCase MCP Selection 投影）此前未正确 merge 到 master，导致 selection 功能缺失。本次合并将 selection 功能与 v2.2.0 的 PK/FK 修复统一到 master 分支。

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
