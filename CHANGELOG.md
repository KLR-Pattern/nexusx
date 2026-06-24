# Changelog

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
