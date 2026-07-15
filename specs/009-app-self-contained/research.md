# Research：业务应用（Application）自包含数据库连接信息

**功能**：[spec.md](./spec.md) · **计划**：[plan.md](./plan.md)

> Phase 0 产物：记录 5 个核心决策的依据与替代方案，所有 `NEEDS CLARIFICATION` 已在 spec 阶段澄清。

---

## D1：自包含深度——app 持 URL 自己造 engine

**Decision**：app 通过 `DATABASE_URL` 字符串接收连接信息，**自己** `create_async_engine` + `async_sessionmaker`，从而"独立导出" = 子项目 `pip install` 后 import 即可工作。

**Rationale**：
- 用户原始诉求是"几个 nexusx 项目合并到一个网关"——每个 app 自带独立数据库是常态
- pip install → import → 直接用是"独立导出"的核心价值
- engine 创建成本极低（lazy connect），自造不增加启动延迟
- `GraphQLHandler.__init__`（`src/nexusx/handler.py:39-117`）已经设计为接收 `session_factory`——把"造 factory"上移到 `Application` 是自然延伸，不污染核心

**Alternatives considered**：

| 方案 | 评估 |
|---|---|
| **B. app 接收 engine** | 合并项目可统一连接池/事件钩子；但"独立导出"打折扣——子项目 import 后还要等合并项目起 engine |
| **C. 双模式（url 或 engine）** | API 复杂度翻倍；测试矩阵翻倍；YAGNI |
| **D. 仅约定 create_app_config() 工厂，nexusx 不动** | 表面工程；连接逻辑仍散落在子项目；不解决"app 作为一等公民"问题 |

**Source-of-truth**：spec 的"澄清记录 Q1"——用户明确选择深度 A。

---

## D2：类名 `Application`（不叫 `GraphQLApp`）

**Decision**：新类命名为 `Application`。

**Rationale**：
- 用户在 spec 阶段明确指定（"升级，但是名字改成 Application"）
- 名字短、好记、无歧义；与 `MultiAppManager.apps` 字典语义一致
- 与 `create_mcp_server(apps=[...])` 的 `apps` 参数名形成自然对应——每个 element 是一个 `Application`
- 不与 SQLModel/SQLAlchemy 既有术语冲突

**Alternatives considered**：

| 方案 | 评估 |
|---|---|
| `GraphQLApp` | 过于限定到 GraphQL；未来若 mcp 支持其他协议（如 REST），名字有锁死感 |
| `McpApp` | 把抽象绑死到 mcp 传输层；但 app 本身是 GraphQL 业务单元，与 mcp 解耦 |
| `NexusxApp` | 冗余前缀 |
| `App` | 太通用，可能与用户业务模型里的 `App` entity 冲突 |

**Conflict check**：`grep -rn "class Application\|def Application\|Application =" src/nexusx/` 全树零命中。`Application` 在 `nexusx/__init__.py`、`nexusx/mcp/__init__.py` 的 `__all__` 中均未占用。命名安全。

---

## D3：连接信息字段"至多提供一个"（不是"恰好一个"）

**Decision**：`Application.__init__` 的 `url` / `engine` / `session_factory` 三参数遵循**至多提供一个**规则——零个也合法（schema-only 模式）。

**Rationale**：
- **关键约束**：现有 `tests/mcp/test_multi_app_manager.py` 全部 18 个测试使用只含 `name`/`base`/`description` 的 dict（schema-only），强制要求连接信息会一次性打破全部测试，且这些测试的目的就是验证配置校验、AppResources 形态等不依赖数据库的逻辑
- **独立价值**：schema-only 模式对文档生成、SDL 浏览、单元测试场景有独立价值（spec 的"用户故事 2 验收场景 2"）
- `GraphQLHandler.__init__` 第 42 行已经接受 `session_factory: Callable | None = None`，None 是合法值——`Application` 必须镜像这一行为
- 当 session_factory 为 None 时，handler.execute() 会在第一次实际查询时失败（DataLoader 拿不到 session）；schema 内省仍可用，因为 SDLGenerator/IntrospectionGenerator 不需要 session

**Alternatives considered**：

| 方案 | 评估 |
|---|---|
| **强制恰好一个** | 一次性打破全部 18 个测试；破坏 schema-only 价值；拒绝合理用法 |
| **强制至少 url 或 engine** | 同上 |
| **零也合法 + 自动从环境变量读 URL** | 隐式行为；调试困难；与 Python "显式优于隐式" 风格冲突 |

**Source-of-truth**：spec 的"澄清记录 Q3"。

**互斥校验**：当用户提供 ≥2 个字段时（如同时给 url + session_factory），构造期 `ValueError` 明确报错，不静默选择优先级。

---

## D4：资源所有权判定——按来源而非引用计数

**Decision**：
- 通过 `url=` 自造的 engine：`Application` **拥有**，`dispose()` 会 `await engine.dispose()`
- 通过 `engine=` 接收的外部 engine：`Application` **不拥有**，`dispose()` 是 no-op
- 通过 `session_factory=` 接收的外部工厂：`Application` **不拥有**，`dispose()` 是 no-op
- `dispose()` **幂等**：第二次调用起 no-op，不抛异常

**Rationale**：
- "按来源判定"是 SQLAlchemy 社区惯例——谁 `create_async_engine`，谁负责 `dispose`
- 引用计数方案（多个 app 共享 engine 时计 ref，归 0 自动 dispose）复杂度高、易出 race；YAGNI
- 调用方共享 engine 的场景（spec 边界情况"共享 engine 的多 app 场景"）：使用方 `async with create_async_engine(...) as engine:` 包住所有 app 的生命周期——简单清晰
- 幂等性来自 FastMCP `_lifespan_manager` 自身就是幂等的（`fastmcp/server/mixins/lifespan.py:139-141`）；同一 manager 被 multiple server 引用时只 dispose 一次

**Alternatives considered**：

| 方案 | 评估 |
|---|---|
| 引用计数共享 engine | 复杂、易 race；社区不推荐 |
| 总是 dispose（不管所有权） | 破坏调用方的 engine 生命周期；反模式 |
| 永不 dispose（让进程退出回收） | 长期运行的网关服务会泄漏连接池；监控不可见 |
| 显式 `owns_engine: bool` 参数 | API 表面积增加；用户容易填错；按来源自动判定更安全 |

**Source-of-truth**：spec 的 FR-006 + FR-007 + 边界情况"资源所有权判定"。

---

## D5：lifespan 自动 dispose 通过 FastMCP `lifespan=` 参数挂接

**Decision**：`create_mcp_server` 在构造 FastMCP 时传入 lifespan async context manager，进入时无操作（资源已 eager 构造），退出时调 `await manager.dispose()`。

**Rationale**：
- 调研 FastMCP 源码（`fastmcp/server/server.py:231`、`fastmcp/server/mixins/lifespan.py:144`、`fastmcp/server/http.py:248,368`）证实：`FastMCP(name, lifespan=...)` 与 transport-level `mcp.http_app().lifespan(...)` **正确组合**——transport lifespan → server lifespan → 用户 lifespan，自动嵌套
- 技能模板 `skills/nexusx-4phase/template/src/main.py:74-76` 已经在用 `mcp_http.lifespan(mcp_http)`——证明这条组合路径在项目里已实战验证
- `Application` 构造完全同步，不需要在 lifespan 进入时做初始化；lifespan 只承担"关闭时清理"职责
- 用户既不需要手动 `await manager.dispose()`（lifespan 自动调），也可以显式调用（高级场景，如脚本/批处理）

**Alternatives considered**：

| 方案 | 评估 |
|---|---|
| 不挂 lifespan，让用户手动 dispose | 大多数用户会忘记；长跑服务泄漏连接池 |
| 把 startup 也放到 lifespan | 不必要——`Application` 构造已是同步 eager；放 lifespan 反而推迟错误暴露（配置错误要到 server 启动才发现） |
| 用 `atexit` 注册清理 | 同步 atexit 不能跑 async dispose；不可行 |

**Source-of-truth**：spec 的 FR-006。

---

## R1：URL 凭据脱敏实现路径

**Decision**：所有面向用户的输出（错误消息、异常字符串、日志、调试信息）中，URL 凭据自动替换为掩码 `***`。

**实现路径**（plan 阶段参考，不是 spec 内容）：
- SQLAlchemy 的 `URL.render_as_string(hide_password=True)` 是社区标准做法
- `Application` 内部统一存储"脱敏后的 URL 字符串"用于日志/错误，原始 URL 仅传递给 `create_async_engine`
- `__repr__`、`__str__` 只输出脱敏形式
- 错误消息（如 `engine.dispose()` 失败、连接超时）必须经过脱敏过滤——通过工具函数 `_redact_url(s: str) -> str` 兜底

**Rationale**：spec FR-013 已锁定。本节记录的是实现细节，便于 tasks.md 分解。

---

## 总结

5 个核心决策（D1-D5）+ 1 个实现参考（R1）全部基于：
- spec 已澄清的用户意图（深度 A、类名、零连接模式）
- 代码勘察确认的现有契约（同步构造、FastMCP lifespan 组合可行）
- 社区惯例（所有权按来源判定、URL 脱敏）

无未解决项。可进入 Phase 1（数据模型 + 契约 + quickstart）。
