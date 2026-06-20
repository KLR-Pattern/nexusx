# Feature Specification: UseCase Service → GraphQL → MCP

**Feature Branch**: `001-usecase-graphql-mcp`

**Created**: 2026-06-20

**Status**: Draft

**Input**: User description: "参考 ~/pydantic-resolve 项目中 use case graphql 和 mcp 的实现方式，在 nexusx 中也引入：1) 由 UseCaseService 自动生成 GraphQL schema/接口的能力；2) 基于该 GraphQL 构建 MCP 服务。同时评估是否需要移除 nexusx 当前的 use_case MCP（create_use_case_mcp_server / create_flat_mcp_server / create_use_case_router / create_use_case_voyager）。"

> Note (analyze H2 remediation 2026-06-20): the actual legacy flat-MCP entry is named `create_use_case_flat_server` (see `src/nexusx/__init__.py`); the original input paragraph abbreviated it. FR-010 and User Story 3 use the correct name throughout.

## Background

nexusx 现在有两套**互不依赖**的对外能力：

1. **GraphQL 模式**（`src/nexusx/handler.py` + `src/nexusx/mcp/`）：从 SQLModel 实体自动生成 GraphQL schema（SDL + 内省），并提供基于该 schema 的 MCP 服务。执行链：`GraphQLHandler.execute()` 是单一执行入口。
2. **UseCase 模式**（`src/nexusx/use_case/`）：开发者用 `UseCaseService` + `@query`/`@mutation` 声明业务方法，由 `BusinessMeta` 元类收集，`ServiceIntrospector` 生成"SDL 风格"字符串用于人类阅读。配套的 `create_use_case_mcp_server` 等 4 个工厂函数提供 MCP / FastAPI / Voyager 入口。**这条链不经过任何真正的 GraphQL schema** —— 它的 MCP Layer 3（`call_use_case`）直接用 JSON 参数调用 Python 方法。

参考实现 `~/pydantic-resolve` 给出了第三条路（`pydantic_resolve/use_case/compose_schema.py` + `mcp_server.py` 的 `create_use_case_graphql_mcp_server`）：

- 由 `UseCaseService` 自动生成**真正的 GraphQL schema**，固定三层结构：`Query → {Service}Query → 方法字段`。
- MCP Layer 3（`compose_query`）接收**标准 GraphQL 查询字符串**，落到生成的 schema 上执行，从而获得字段选择、嵌套投影、类型校验等 GraphQL 原生能力，同时保留 UseCase 的服务/方法边界。
- 内省查询被 Layer 3 拒绝（用 Layer 1/2 的描述工具代替），以保持 MCP 响应紧凑。

本特性要把这条路引入 nexusx，并明确老 use_case MCP 的去留。

## Clarifications

### Session 2026-06-20

- Q: 新 UseCase GraphQL 执行链是否自动套用 Resolver 处理 DTO 上的 `resolve_*` / `post_*` / AutoLoad？ → A: **否**。service 方法内部已经显式调用 `Resolver().resolve(dtos)`（见 `demo/use_case/mcp_server.py` 的既有写法），Resolver 的调用时机与方式由 service 方法自行决定。GraphQL 执行层只负责调用 service 方法、对返回值做字段选择/类型校验，**不**在外面再套一层 Resolver（否则会重复处理）。
- Q: 新 UseCase GraphQL MCP 的工具响应 shape 走 GraphQL 标准 `{data, errors}` 还是现有 `mcp/` 模块的 `{success, data, error, error_type}` 信封？ → A: **分层**。Layer 3（`compose_query` 执行工具）返回 GraphQL 标准 `{data, errors}`；Layer 0–2（应用发现 / schema 总览 / 方法详情，都是 meta 描述工具而非 GraphQL 执行）继续用现有 `{success, data}` 信封，与 `mcp/` 模块一致。理由：Layer 3 是 GraphQL 原生执行入口，返回 `{data, errors}` 让 AI agent 与 GraphQL 客户端能直接解读；前 3 层不是 GraphQL 执行，用 success 信封更自然且与既有 MCP 模块一致。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 由 UseCaseService 自动获得真正的 GraphQL API (Priority: P1)

作为 nexusx 的使用者，我已经按现有约定写了一组 `UseCaseService` 子类（带 `@query`/`@mutation` 的 async classmethod），我希望**不写任何额外 schema**，就能拿到一个标准 GraphQL schema：可以打印 SDL、可以通过内省喂给 GraphiQL、可以接收并执行合法的 GraphQL 查询。Schema 的结构遵循"Query → {Service}Query → 方法字段"的固定三层，方法参数（去掉 `cls` 和 `FromContext` 标注的）自动成为 GraphQL 参数，Pydantic DTO（含可达的嵌套 DTO/枚举）自动成为 GraphQL 输出类型。

**Why this priority**：这是整个特性的价值锚点。没有"真正的 GraphQL schema"，后面的 MCP 就只是把老的直接调用换个名字。只要这一条做出来，nexusx 就已经在 GraphQL 客户端/工具生态里可用，独立交付价值。

**Independent Test**：定义 3 个 service（含 list 返回、单实例返回、带参数方法、带嵌套 DTO 返回），调用一次"生成 schema"入口，断言：(a) 生成的 SDL 通过 graphql-core 校验；(b) 至少 3 条查询（每 service 一条）能成功执行并返回正确数据。

**Acceptance Scenarios**:

1. **Given** 一个仅返回标量列表的简单 service，**When** 调用 schema 生成器，**Then** 得到的 SDL 含 `type Query { XService: XServiceQuery! }` 和 `type XServiceQuery { list_x: [Int!]! }` 形态，且能通过 graphql-core 的 `build_schema` 校验。
2. **Given** 一个方法返回嵌套两层 DTO（如 `SprintSummary.tasks: list[TaskSummary]`），**When** 生成 schema，**Then** SDL 中 `SprintSummary`、`TaskSummary` 两个类型都被注册，字段类型正确，引用关系闭合。
3. **Given** 一个方法签名带 `FromContext` 标注的参数，**When** 生成 schema，**Then** 该参数**不**出现在 GraphQL 参数列表中（仅普通参数成为 GraphQL 参数）。
4. **Given** 一个生成的 schema 实例，**When** 对它执行一次 GraphQL 查询并请求子集字段（例如只要 `id`、`title`），**Then** 响应里只包含请求的字段，不包含未请求的字段。
5. **Given** 一个 service 同时声明了 `@query` 和 `@mutation` 方法，**When** 生成 schema，**Then** Mutation 类型与 Query 类型分别含对应字段，结构正确。

---

### User Story 2 - 基于 UseCase GraphQL 的 MCP 服务 (Priority: P2)

作为 MCP 消费方（Claude / Cursor / 其它 agent），我希望连接到一个"UseCase GraphQL MCP"服务，按渐进式披露逐层探索：先列出应用 → 看每个应用有哪些 service 和方法 → 看某个方法的参数/返回类型/SDL → 用一段标准 GraphQL 查询实际调用。最后一层的工具接收 GraphQL 字符串而非 JSON 参数表，让我能用字段选择控制返回大小，用查询组合表达更复杂的需求。

**Why this priority**：在 P1 之后，MCP 是把 GraphQL 能力交付到 AI agent 手里的关键通道。pydantic-resolve 已经证明这条路可行；nexusx 需要给出对等的入口。

**Independent Test**：启动一个新 MCP server（一个应用、3 个 service），按 Layer 0→1→2→3 的顺序调用四个工具，断言：每一层输出形态符合约定；Layer 3 接受标准 GraphQL 查询字符串并返回数据；Layer 3 对内省查询（`__schema` 等）返回明确拒绝而非完整内省结果。

**Acceptance Scenarios**:

1. **Given** 一个配置了 2 个应用的 MCP server，**When** 调用应用发现工具，**Then** 返回 2 个应用的名称、描述、service 数量。
2. **Given** 已知某应用，**When** 调用"schema 总览"工具，**Then** 返回该应用下所有 service 和方法的紧凑列表（名称、类型 query/mutation、说明），**不**包含参数和返回类型（保持紧凑）。
3. **Given** 已知某 service 和方法，**When** 调用"方法详情"工具，**Then** 返回该方法的参数表（名称/类型/默认值）、返回类型，以及一段完整的 SDL 片段（方法签名 + 所有可达 DTO）。
4. **Given** 用户想真正拉数据，**When** 调用执行工具并传一段标准 GraphQL 查询字符串，**Then** 返回该查询的执行结果（data / errors）。
5. **Given** 同上，**When** 查询里包含 `__schema` 或 `__type` 内省字段，**Then** 执行工具返回明确的"内省请用 Layer 1/2"错误，而不是把完整内省结果塞回来。
6. **Given** 一个方法依赖 `FromContext` 参数，**When** MCP context 提取器返回相应上下文，**Then** 执行该方法时上下文被正确注入，方法体内能拿到对应值。

---

### User Story 3 - 老 use_case MCP 的明确去留与迁移指引 (Priority: P3)

作为 nexusx 的现有用户（已经在用老的 `create_use_case_mcp_server` / `create_use_case_flat_server`），我希望升级到带 GraphQL 模式的版本后，**清楚地知道**老的 MCP 入口会被**移除**，并且有可操作的迁移文档，不会出现"升级后悄悄坏掉"或"老代码不知所踪"的情况。**注意**：与 MCP 无关的 `create_use_case_router`（FastAPI REST）和 `create_use_case_voyager`（可视化）不在本特性移除范围内，仍按既有方式工作。

**Why this priority**：用户明确要求"评估老的 use_case service mcp 是否需要被移除"。这条不解决，前两条会让生态里出现两个互相竞争的 MCP 实现，给用户和维护者都带来困惑。

**Independent Test**：以一个使用老 `create_use_case_mcp_server` 的最小 demo 升级到新版本，按迁移文档逐步替换为新 GraphQL MCP 入口，断言：(a) 老 MCP 入口的导入失败信息清晰；(b) 新 MCP 入口能复现老 demo 的全部查询；(c) 老 `create_use_case_router` / `create_use_case_voyager` demo 不受影响、继续工作。

**Acceptance Scenarios**:

1. **Given** 用户升级到含本特性的版本，**When** 尝试 `from nexusx import create_use_case_mcp_server` 或 `from nexusx import create_use_case_flat_server`，**Then** 导入**失败**，且错误信息（`ImportError` 消息或包装函数 docstring）明确指向新的 GraphQL MCP 入口。
2. **Given** 旧的 demo/测试代码引用了老 MCP 入口，**When** 用户阅读迁移指南，**Then** 文档对**每一个**老 MCP 入口给出"它过去做什么 → 新 GraphQL MCP 如何做同样的事 → 改造步骤"三件事，并标注本特性引入的版本号。
3. **Given** 维护者执行 `grep -rn "create_use_case_mcp_server\|create_use_case_flat_server" src/`，**When** 检查 src 树，**Then** 没有任何残留定义（默认不引入兼容 shim）。
4. **Given** 新特性的 demo 与测试套件，**When** 用新 GraphQL MCP 入口重新实现老 demo 的全部查询场景，**Then** 所有原查询能力都能通过新入口复现（参数透传、DTO 返回、context 注入、列表/单实例查询），证明移除不带来功能损失。
5. **Given** 现有使用 `create_use_case_router`（REST）或 `create_use_case_voyager`（可视化）的代码，**When** 升级到含本特性的版本，**Then** 两者**继续正常工作**，行为与升级前一致（不发出 warning、不改变签名、不改变返回结构）。

---

### User Story 4 - 复用既有基础设施，避免并行实现 (Priority: P3)

作为 nexusx 的维护者，我希望新特性尽量复用现有的类型转换（`type_converter.py`）、查询解析（`query_parser.py`）、响应构建（`response_builder.py`）等基础设施，而不是在 `use_case/` 下平行再造一套同义逻辑。同时，若复用确实带来语义冲突（例如现有 `GraphQLHandler` 强依赖 SQLModel 实体发现，不适合 service 驱动），则明确**新写**一个独立的 schema 构建器，并在代码或文档里说明为什么不复用。

**Why this priority**：pydantic-resolve 的 `compose_schema.py` 是独立写的，nexusx 也大概率需要独立 builder；但要避免重复造 type mapping 这种细碎又容易出错的逻辑。这条是工程内务，但决定了长期可维护性。

**Independent Test**：在新模块的 plan / 代码注释里，对每一个"复用 / 不复用"的决策给出依据。对一个三类方法的 service 生成 schema 时，确认 Python → GraphQL 的类型映射规则与现有 `type_converter.py` 行为一致（除非有明确差异并记录原因）。

**Acceptance Scenarios**:

1. **Given** 已有的标量/容器类型映射规则（`int`→`Int`、`list[T]`→`[T!]!` 等），**When** 用新 builder 生成 schema，**Then** 同样的 Python 类型产生同样的 GraphQL 类型名。
2. **Given** 现有 `FieldSelection` 抽象，**When** 新 builder 执行 GraphQL 查询，**Then** 字段投影逻辑复用同一抽象（或明确说明为什么另起）。
3. **Given** plan 阶段产出，**When** 审阅者读 plan/代码，**Then** 每一个"新建 vs 复用"的决策都有显式理由（plan.md 或代码注释里写明）。

---

### Edge Cases

- 方法**没有返回类型注解**（或注解为 `None`）：生成的 schema 字段类型如何处理？默认行为是报错（schema 生成期），还是允许作为 `Void`？
- 方法返回的 DTO 字段**引用了 SQLModel 实体类型**（违反 nexusx 既有约定：DTO 字段必须是 DTO 类型）：schema 生成是报错还是尝试映射？默认应当报错，并给出清晰提示。
- 两个 service **同名**（跨应用）/ 两个方法**同名**（同 service）：schema 生成期报错，还是允许？默认报错。
- 同一 DTO 在多个 service 返回类型里出现：schema 里**只注册一次**，引用闭合。
- 方法参数带默认值：GraphQL 参数也带 `defaultValue`；可选参数 vs 必填参数的语义保持一致。
- `@mutation` 方法返回与某 `@query` 相同的 DTO：DTO 类型在 Mutation 和 Query 两边共享同一份定义。
- 列表返回（`list[XDTO]`）：schema 字段类型为 `[XDTO!]!`（与 pydantic-resolve 对齐）。
- 方法抛出业务异常：MCP 执行工具把异常映射成结构化错误响应（errors 数组），而非 500。
- 调用方传入非法 GraphQL 字符串：返回可读的解析错误，不崩溃。
- AI agent 在 Layer 3 走"先内省再查询"：被规则拒绝并提示用 Layer 1/2（避免大响应）。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 能从一个或多个 `UseCaseService` 子类自动派生出一份真正的 GraphQL schema（graphql-core 可校验、可执行），无需用户手写 schema。
- **FR-002**: 生成的 schema MUST 遵循固定的三层结构：顶层 `Query` 的每个字段对应一个 service；每个 `{Service}Query` 类型的每个字段对应 service 的一个 `@query` 方法；若存在任何 `@mutation` 方法，则同样生成对应的 `{Service}Mutation` 类型并挂到顶层 `Mutation`。
- **FR-003**: 系统 MUST 把方法的普通参数（**排除** `cls` 以及任何被 `FromContext` 标注的参数）转成 GraphQL 字段参数，参数类型与默认值保持一致。
- **FR-004**: 系统 MUST 把方法的返回类型（含 `list[T]`、`Optional[T]`、嵌套 Pydantic DTO、枚举）转换为对应的 GraphQL 输出类型，并递归注册所有可达类型，使引用关系闭合、同一 DTO 只注册一次。
- **FR-004a**: GraphQL 执行层 MUST NOT 在 service 方法返回值外面再自动套用一层 `Resolver`。`Resolver` 的调用时机与方式由 service 方法自行决定（既有 `UseCaseService` 实践是方法体内显式 `Resolver().resolve(dtos)`，本特性沿用此约定）。GraphQL 执行层只负责：调用 service 方法 → 对方法返回的（已 Resolver 处理过的）DTO 做字段选择与类型校验 → 序列化响应。这样保证 Resolver 不会被重复触发，且与既有 `create_use_case_router` / `create_use_case_voyager` 出口行为一致。
- **FR-005**: 系统 MUST 能导出标准 SDL 字符串与 graphql-core 兼容的内省结果，使 GraphiQL 等标准客户端可直接消费。
- **FR-006**: 系统 MUST 提供一个 MCP server 工厂，遵循四层渐进式披露：应用发现 → schema 总览（service+方法名/类型/说明，**不含**参数和返回类型）→ 方法详情（参数表+返回类型+SDL 片段）→ GraphQL 查询执行。
- **FR-007**: MCP server 的"执行"工具（Layer 3）MUST 接收标准 GraphQL 查询字符串作为输入（而非 JSON 形态的方法名+参数表），并返回 GraphQL 标准 `{data, errors}` 结构的执行结果。前 3 层 meta 工具（应用发现 / schema 总览 / 方法详情）MUST 沿用现有 `mcp/` 模块的 `{success, data}` 信封（成功）与 `{success, error, error_type}` 信封（失败），保持模块间一致性。Layer 3 不套 success 信封，直接返回 GraphQL 原生结果。
- **FR-008**: MCP server 的"执行"工具 MUST 拒绝内省型查询（包含 `__schema` / `__type` 等），返回明确的"请用 Layer 1/2"提示，避免向 agent 回灌完整内省。
- **FR-009**: 新特性 MUST 不破坏现有 `@query` / `@mutation` / `UseCaseService` / `BusinessMeta` / `FromContext` / `UseCaseAppConfig` 的既有语义（向后兼容）。
- **FR-010**: 系统 MUST **立即移除**老的直接调用式 use_case **MCP** 入口（且仅这两个）：`create_use_case_mcp_server`（4 层渐进式披露 MCP）、`create_use_case_flat_server`（扁平 MCP，一方法一 tool），以及只为它们存在、不被其它入口共享的内部支撑代码（典型为 `use_case/server.py`、`use_case/manager.py` 中只服务于 MCP 的部分）。移除必须是"硬移除"——重新导入这两个名字必须失败，并给出指向新 GraphQL MCP 入口的错误信息，而不是悄悄退化或留作别名。同时 MUST 提供一份迁移指南（README 或独立 `docs/` 页面），逐个老 MCP 入口写明"它解决什么 → 新特性如何解决 → 改造步骤"。
- **FR-010a**: 系统 MUST **保留**与 GraphQL/MCP 正交的既有 use_case 出口：`create_use_case_router`（FastAPI REST 路由）与 `create_use_case_voyager`（Voyager 可视化）。这两个出口**不在本特性的移除范围内**，因为它们解决的不是"MCP 暴露给 agent"这个问题，本特性不引入替代品。若后续需要为 GraphQL 模式提供 REST 路由或可视化，那是另一个独立特性。
- **FR-011**: 新模块 MUST 在"复用既有基础设施"与"独立新建"之间做出有据决策：对每一个新建/复用选择，在 plan 或代码注释中显式说明理由（特别是类型映射与字段投影这两块）。
- **FR-012**: 新特性 MUST 配套至少一个可运行的 demo（含 service 定义 + schema 生成 + MCP 启动），以及覆盖以下场景的测试：(a) 标量/容器/嵌套 DTO 类型映射；(b) `FromContext` 参数被正确过滤；(c) MCP 四层工具的 happy path；(d) 内省查询被 Layer 3 拒绝；(e) 老入口的处置策略生效（如废弃则验证 warning）。

### Key Entities *(include if feature involves data)*

- **UseCaseService**：业务服务基类（既有），作为 schema 生成的输入。每个子类对应 schema 中一个 `{Service}Query`（和/或 `{Service}Mutation`）类型。
- **UseCaseAppConfig**：应用配置（既有，可能需要扩展），把若干 service 与描述、context 提取器打包成一个应用。
- **ComposeSchema**（新概念，名字仅作占位）：从一组 `UseCaseService` 派生出的 GraphQL schema 产物，承载 SDL 生成、内省、查询执行三项能力。
- **UseCaseGraphQLMCP**（新概念，名字仅作占位）：基于 ComposeSchema 的 MCP server，提供四层渐进式披露工具。
- **MigrationGuide**（新概念）：面向既有用户的迁移指引文档，说明老入口处置策略与替换路径。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 一位熟悉 nexusx 的开发者，从零定义 3 个 service（覆盖 list 返回、单实例返回、带参数、嵌套 DTO）到拿到一个可被 GraphiQL 打开、可被标准 GraphQL 客户端查询的 schema + MCP server，可在数分钟内完成，无需手写任何 schema 片段。
- **SC-002**: 在新特性的测试套件中，所有生成的 schema 都能通过 graphql-core 的 `build_schema`/`validate_schema` 校验；至少 5 条代表性的 GraphQL 查询（含字段选择、嵌套投影、参数透传）能成功执行并返回与 DTO 字段一致的结果。
- **SC-003**: 对同一个 use case，AI agent 通过新 MCP 完成一次"探索 → 调用 → 解读"的完整往返所需的工具调用次数和返回 token 数，**不多于**通过老直接调用式 MCP 完成同任务所需的次数/token（理想情况下因字段选择而更少）。
- **SC-004**: 升级到含本特性的版本后，未使用被处置老入口的用户**不感知任何变化**；使用了老入口的用户在首次调用时**立即**看到与 FR-010 一致的处置信号（warning / 失败 / 文档提示，取决于最终策略）。
- **SC-005**: 新模块与既有 `mcp/` 模块的代码重复点在 plan.md 中被显式列出并说明处置（共享 / 容忍 / 抽公共）；不允许"明显应该共享却平行实现且无说明"的情况进入 main。

## Assumptions

- 新特性在 `src/nexusx/use_case/` 目录下扩展（新增子模块或同层新模块），保持"UseCase 模式"作为一个整体对外；不把它打散到 `mcp/` 里。
- 新特性的执行链独立于现有 `GraphQLHandler`（后者强耦合 SQLModel 实体发现）；schema 构建器**新建**，但类型映射、字段投影这类细粒度能力尽量复用现有 `type_converter.py` / `query_parser.py`。
- `UseCaseService` / `@query` / `@mutation` / `FromContext` / `UseCaseAppConfig` 的既有语义保持不变；如有必要的扩展字段（例如应用级的 context 提取器），以**向后兼容**方式添加。
- 老 use_case MCP 的处置策略**已确定为"立即移除"**（FR-010）：移除范围仅限两个老 **MCP** 入口（`create_use_case_mcp_server`、`create_use_case_flat_server`）及其专属支撑代码。`create_use_case_router`（FastAPI REST）与 `create_use_case_voyager`（可视化）**不移除**（FR-010a），因为它们与 GraphQL/MCP 是正交出口。本特性版本号建议打 minor 或 major bump（具体由 plan 决定）以反映 breaking change。
- MCP server 继续基于 `fastmcp`（与现有 `mcp/` 和 `use_case/server.py` 一致），不引入新的 MCP SDK。
- 本特性聚焦 Python 库的公共 API；FastAPI 路由 / Voyager 可视化是否同步提供"GraphQL 版本"留到 plan 阶段决定（默认 v1 只交付 MCP + schema 生成器）。
- 老 `mcp/` 模块（基于 SQLModel 实体的 GraphQL MCP）**不在本特性范围内**，保持原状不动。
