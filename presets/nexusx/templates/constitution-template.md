# [PROJECT_NAME] Constitution

> 本 constitution 由 nexusx preset 强制；记录 nexusx 项目的硬规则与 V 型验收治理。所有 spec / plan / tasks 必须符合以下原则，违反需要在 plan 的 Complexity Tracking 中显式记录理由。

## 核心原则

### I. 关系懒加载强制（不可协商）

所有 SQLModel `Relationship` 必须显式声明 `sa_relationship_kwargs={"lazy": "noload"}`。

**理由**：项目通过显式查询 + Resolver DataLoader 加载关系数据，不依赖 ORM lazy-load。`noload` 防止 session 关闭后 `model_validate(entity)` 访问 relationship descriptor 触发 `DetachedInstanceError`。违反即视为 Phase 1 未完成。

### II. 实体层零业务依赖

`models.py` / `models/` 子模块禁止 `import nexusx` 或导入任何 `service/` 模块；实体文件只含字段与关系声明，**不含 `@query` / `@mutation` 方法**。

**理由**：业务方法在 `service/<domain>/methods.py` 中实现，通过 `mount_method()` 延迟挂载。混入会破坏 phase 1 → phase 2 的清晰边界。

### III. 模型与字段的自描述强制

每个 SQLModel 类必须有 docstring 说明业务含义；每个 `Field` 必须有 `description` 参数。

**理由**：description 会传递到 OpenAPI spec 和 Voyager ER 图；缺失会导致自动生成的对外接口文档失去语义。

### IV. Service 切分必须由用户裁定（不可协商）

**禁止模型自行决定 Service 切分方案**。必须在 Phase 0（specify 阶段）向用户提出至少一种候选方案并取得明确选择，否则禁止进入 Phase 1。

**理由**：Service 切分直接影响目录结构、Phase 2 methods.py 粒度、Phase 3 UseCaseService 类划分、MCP / REST 入口组织。自行决定会迫使后续 phase 围绕错误的边界展开。

### V. methods.py 挂载时序与桥接（不可协商）

- `mount_method()` 必须在创建 `GraphQLHandler` 之前调用
- `service/<domain>/methods.py` 中业务方法必须是普通 `async def`（不含 `cls`）
- 挂载桥接函数必须使用 `@functools.wraps(fn)` 保留 docstring

**理由**：`GraphQLHandler` 初始化时扫描 BaseEntity 子类构建 schema，错序会导致 schema 为空；缺失 `wraps` 会导致 SDL 描述丢失。

### VI. DTO 类型纯净性

- DefineSubset DTO 字段必须使用 DTO 类型，禁止直接使用 SQLModel 实体（3.0+ 会抛 `SQLModelInDtoFieldError`）
- DTO 文件禁用 `from __future__ import annotations`（会导致 compose schema 无法检测 `Annotated` 元数据）

**理由**：DTO 是响应契约，混入 ORM 实体会破坏字段选择与序列化语义；字符串化的类型注解在 SubsetMeta 扫描时不可见。

### VII. UseCaseService 返回类型强制

UseCaseService 的每个 `@query` / `@mutation` 方法必须声明返回类型注解（如 `-> list[X]`、`-> X | None`）。

**理由**：3.0 起 compose schema 生成器（`build_compose_schema`）强校验，缺注解的方法在 MCP server 构造时抛 `MissingReturnAnnotationError`；同时 `create_use_case_router()` 也通过 `get_type_hints(method).get("return")` 提取响应类型作为 OpenAPI `response_model`，缺失会让 spec 显示 unknown、Phase 4 TS SDK 无法生成有效类型。

### VIII. REST 路由与 MCP 传输协议（不可协商）

- REST 路由**必须**通过 `create_use_case_router()` 自动生成，禁止手写 `router/`
- MCP `http_app` 必须使用 `transport="streamable-http", stateless_http=True`，并将 MCP lifespan 嵌套进 FastAPI lifespan（`async with mcp_http.lifespan(mcp_http):`）

**理由**：手写路由无法声明 `response_model`，导致 OpenAPI spec 响应类型为 unknown；MCP http_app 缺少正确的传输 / lifespan 配置会抛 `Task group is not initialized`。

## Phase 闸门规则

### V 型验收（贯穿所有 phase）

每个 Phase 必须遵循三段式：

1. **V 降**：进入 Phase 实现之前，先在 `specs/<NNN>-<name>/phaseN.md` 中定义可观察、可操作的验收标准（"GraphiQL 中执行 X query 返回 Y"，而非"代码健壮"）
2. **实现**：按验收标准编写代码
3. **V 升**：逐条对照验收标准，用户确认后才可进入下一 Phase

### Phase 间暂停

每个 Phase 实现完成后**必须暂停**，展示验收结果，等用户明确确认后才进入下一阶段。**禁止**连续执行多个 Phase 不暂停。

### Phase 4 条件触发

Phase 4（TS SDK 生成）**仅当** plan.md 的"是否生成 TS SDK"字段为 `是` 时才执行；默认 `否`。Phase 4 依赖 Phase 3 使用 `create_use_case_router()`，否则 OpenAPI spec 响应类型为 unknown，SDK 类型生成失败。

## 治理

- Constitution 优先级高于 spec / plan / tasks 中的便利性选择；冲突时以本文件为准
- 修改本 constitution 需要在 commit message 中说明理由，并同步更新 `presets/nexusx/templates/constitution-template.md` 源文件
- 复杂度豁免：如果某项原则需要被违反，必须在 plan.md 的 `## Complexity Tracking` 区块中显式记录"违反项 / 为什么需要 / 拒绝的简化方案"，否则视为未通过 Constitution Check

**Version**: 0.1.0 | **Ratified**: 2026-07-01 | **Last Amended**: 2026-07-01
