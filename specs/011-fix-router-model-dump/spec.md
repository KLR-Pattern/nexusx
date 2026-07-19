# Feature Specification: 修复 UseCase Router 把嵌套 BaseModel 参数拍平成 dict 的 Bug

**Feature Branch**: `011-fix-router-model-dump`

**Created**: 2026-07-19

**Status**: Draft

**Input**: User description: "根据我说的， 移除 model_dump 的方式来修复当前的 issue"

**关联 Issue**: KLR-Pattern/nexusx#107

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 按签名声明使用嵌套 BaseModel 列表参数（Priority: P1）

作为一个使用 nexusx 构建 AI/MCP 接口的开发者，我希望在 `@mutation` / `@query` 方法上声明 `List[SomeBaseModel]`（或单层嵌套 `SomeBaseModel`、`Optional[SomeBaseModel]`）类型的参数时，方法体收到的对象与签名声明完全一致（即 `ItemInput` 实例而非 `dict`），这样我就能直接用 `it.text` 而不是 `it["text"]`，签名变成可信的类型契约。

**Why this priority**: 这是 issue #107 的核心痛点。当前实现里 router 调用 `body.model_dump()` 把 Pydantic 已构造好的 BaseModel 实例递归降级成 dict，签名说谎、IDE 类型提示无效、开发者被迫写 `isinstance(it, dict)` 双分支防御代码。这是 nexusx"签名即真相"卖点的直接破坏。

**Independent Test**: 给一个声明了 `items: List[ItemInput]` 的 `@mutation` 方法发 POST 请求，方法体内直接调用 `items[0].text`，应当返回正常结果而不是抛 `AttributeError: 'dict' object has no attribute 'text'`。

**Acceptance Scenarios**:

1. **Given** 一个 `@mutation` 方法声明 `items: List[ItemInput]`，**When** 客户端 POST `/api/<service>/<method>` 携带 `{"items": [{"text": "a"}, {"text": "b"}]}`，**Then** 方法体收到的 `items` 是 `List[ItemInput]`，每个元素都是 `ItemInput` 实例，`items[0].text == "a"` 成立，方法正常返回。
2. **Given** 一个 `@mutation` 方法声明 `item: ItemInput`（单层嵌套，非列表），**When** 客户端 POST 携带 `{"item": {"text": "a"}}`，**Then** 方法体收到的 `item` 是 `ItemInput` 实例。
3. **Given** 一个 `@mutation` 方法声明 `item: Optional[ItemInput] = None`，**When** 客户端 POST 携带 `{"item": {"text": "a"}}`，**Then** 方法体收到 `ItemInput` 实例；**When** 携带 `{"item": null}` 或省略字段，**Then** 方法体收到 `None`。

---

### User Story 2 - 标量参数、FromContext 参数与默认值行为完全保持原状（Priority: P2）

作为开发者，我希望修复只针对"嵌套 BaseModel 被拍平"这一具体问题，**不要引入其他行为变化**：标量参数（`UUID`/`str`/`int`/`bool`/`datetime` 等）依然按原值传递，`FromContext` 参数依然按 context_extractor 注入，方法默认值依然生效，request model 的字段 `alias` / validators 依然按 Pydantic 语义执行。

**Why this priority**: 修复必须是无副作用的。router 是所有 use case 请求的必经路径，任何对其他参数形态的行为偏移都会引发更广的回归。这条故事本质是回归保护。

**Independent Test**: 用一组覆盖标量、FromContext、默认值、alias 的现有用例对修复后的 router 跑一遍，断言全部通过；同时新增针对这些场景的显式回归测试。

**Acceptance Scenarios**:

1. **Given** 一个方法声明 `owner_id: UUID` 标量参数，**When** 客户端 POST UUID 字符串，**Then** 方法体收到的 `owner_id` 仍是 `UUID` 实例（修复前 `model_dump()` 也保留 UUID，本条用于锁定行为不退化）。
2. **Given** 一个方法声明 `count: int = 10` 带默认值，**When** 客户端省略 `count` 字段，**Then** 方法体收到 `count == 10`；**When** 客户端显式传 `"count": 42`，**Then** 方法体收到 `count == 42`。
3. **Given** 一个方法声明 `user_id: Annotated[UUID, FromContext("user_id")]`，**When** `context_extractor` 返回 `{"user_id": <UUID>}`，**Then** 方法体收到的 `user_id` 来自 context 而非 body，且与修复前行为一致。
4. **Given** 一个方法声明 `tags: List[str]`（标量列表），**When** 客户端 POST `{"tags": ["a", "b"]}`，**Then** 方法体收到 `["a", "b"]`，类型不变。

---

### User Story 3 - Schema 生成阶段不受 router 实现影响（Priority: P3）

作为开发者，我希望修复 router 后，OpenAPI / GraphQL compose / MCP tool 的 schema 生成保持完全一致：嵌套 BaseModel 参数仍然注册成 INPUT_OBJECT，标量参数仍然按原映射规则生成。

**Why this priority**: schema 生成和 router 是两条独立路径，修复 router 不应触碰 schema。这条是被动保证——只要不改 `compose_type_mapper` 就成立，但需要在测试中显式断言，防止后续误改。

**Independent Test**: 跑现有 schema/compose 测试套件，确认修复前后输出 diff 为空。

**Acceptance Scenarios**:

1. **Given** 一个声明 `items: List[ItemInput]` 的方法，**When** 生成 compose schema，**Then** `ItemInput` 注册为 `INPUT_OBJECT`，SDL 输出与修复前一致。
2. **Given** 修复已合并，**When** 跑全套现有 router / compose / OpenAPI 测试，**Then** 全部通过。

---

### Edge Cases

- 当 service 方法签名里**同时**包含嵌套 BaseModel 参数和 FromContext 参数（Case 1）时，FromContext 注入路径不能因 router 改动而错位。
- 当 request model 字段使用了 `Field(alias="...")` 时（service 参数注解为 `Annotated[T, Field(alias="x")]`），客户端按 alias 提交 JSON，方法体收到的 Python 字段值应当是构造好的 BaseModel 实例。
- 当 service 方法体把入参原样返回（如 `def echo(cls, item: ItemInput) -> ItemInput: return item`）时，FastAPI 的 `response_model` 序列化路径应当正常工作，最终 JSON 与修复前一致。
- 当请求体非常大或包含深嵌套结构（如 `List[NestedLevel1]`，每层都有 BaseModel）时，修复后不能引入明显的性能退化（应反而略快，因为去掉了递归 dump）。
- 当参数注解为 `Any` 或拿不到 hint 时（fallback 成 `Any`），方法体收到的应当是 Pydantic 原样保留的 JSON 值（dict / list / 标量），与修复前一致。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Router 在调用 `@query` / `@mutation` 方法时 MUST 把请求参数按 service 方法签名声明的类型传递，不得在 router 层把任何嵌套 BaseModel 实例递归降级为 dict。
- **FR-002**: 实现 MUST 通过去掉 `body.model_dump()` 调用、改为按字段名从已校验的 request model 上直接取值（Python 属性访问）的方式达成 FR-001，避免引入"先 dump 再 validate"的二次校验路径。
- **FR-003**: 标量类型参数（`int` / `float` / `str` / `bool` / `UUID` / `datetime` / `date` / `time`）MUST 保持修复前的行为，即按 Pydantic 已构造的 Python 对象传递（如 `UUID` 实例，不是字符串）。
- **FR-004**: `FromContext` 注入路径 MUST 与修复前完全一致——context 参数仍由 `context_extractor` 提供，不经过 body 字段映射。
- **FR-005**: 方法默认值 MUST 在客户端省略字段时生效，与修复前一致。
- **FR-006**: Router handler 闭包 MUST 在所有四个 case（body only / body + ctx / ctx only / no params）下都正确工作；其中 ctx only 和 no params 两个 case 因不涉及 body 取值，行为 MUST 完全不变。
- **FR-007**: 修复 MUST 不触碰 `compose_type_mapper`、`compose_schema`、`introspector` 等 schema 生成模块——schema 路径与 router 路径相互正交。
- **FR-008**: 修复 MUST 同步更新任何因行为变化而失效的现有测试（如断言 handler 收到 dict 形态的 mock 测试），并为新增行为补回归测试。
- **FR-009**: 修复 MUST 在 CHANGELOG / Release Notes 中显式声明行为变化：嵌套 BaseModel 参数现在以 BaseModel 实例形态传入方法体，而不是 dict。

### Key Entities *(include if feature involves data)*

- **Request Model**: nexusx 在 `create_router()` 时为每个 use case 方法动态构造的 Pydantic 模型（命名形如 `<Service><MethodName>Request`），承载客户端 JSON 经 `model_validate` 后的强类型结果。本修复的关键是：方法体收到的参数应当直接来自该模型的字段访问，而不是它的 `model_dump()` 输出。
- **Service Method 参数**: `@query` / `@mutation` 装饰的方法签名参数。参数被 `_classify_params` 分为 body 参数（来自 JSON）与 context 参数（来自 `context_extractor`），router handler 闭包负责把它们组合后传给方法。
- **Body Params**: 进入 request model 的参数名列表，由 `_classify_params` 在 `create_router()` 时计算并传给 `_make_handler()`。本修复需要在 handler 闭包里捕获这份列表以支持按字段名取值。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Issue #107 的复现代码（声明 `items: List[ItemInput]` 并在方法体内调用 `it.text`）在修复后端到端跑通，HTTP 200 返回，无 `AttributeError`。
- **SC-002**: 修复后 router 对一个覆盖"嵌套 BaseModel / 嵌套 List[BaseModel] / Optional[BaseModel] / 标量 / List[标量] / FromContext / 默认值"的回归测试套件全部通过；该套件在修复前应当至少有一条嵌套 BaseModel 用例失败、其余通过。
- **SC-003**: 现有 nexusx 全量测试套件在修复后零回归（与修复前 master 上的通过集合相比，不新增失败项）。
- **SC-004**: 修复前后对同一组 service 定义生成的 OpenAPI schema / compose SDL 输出二进制一致（diff 为空），证明 schema 路径未受影响。
- **SC-005**: 修复后无需服务开发者编写 `isinstance(it, dict)` 双分支防御代码——服务方法可以完全依赖签名类型，按"签名即真相"模式编写。

## Assumptions

- 假设修复仅触及 `src/nexusx/use_case/router.py` 中 `_make_handler` 的四个 case 与必要的辅助函数（如向 handler 闭包传入 `body_params`）；不修改 `_build_request_model`、`_classify_params`、`create_router` 的外部接口。
- 假设 FastAPI 已在 request model 阶段完成 JSON → BaseModel 的递归构造与 validator 执行，router 只需取已构造的字段值，无需重新校验。
- 假设 `body.model_dump()` 的任何"副作用"（如对 computed_field、field_serializer 的处理）都不适用于动态生成的 request model，因为这些只能定义在用户编写的 BaseModel 类体上，而 request model 由 `pydantic.create_model` 动态拼装——因此去掉 `model_dump()` 不会丢失任何业务语义。
- 假设现有测试中若存在依赖 handler 收到 dict 形态的断言，会在同一个 PR 中更新为新的 BaseModel 形态；这是预期回归而非破坏。
- 假设修复不引入新的依赖，也不修改 `nexusx` 公共 API（`UseCaseService` / `@query` / `@mutation` / `create_router` / `UseCaseAppConfig`）的签名。
- 假设修复在 Python 3.13 + Pydantic 2.x 环境下完成，与 issue #107 报告环境一致。
