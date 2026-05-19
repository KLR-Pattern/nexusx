---
name: sqlmodel-nexus-4phase
description: 基于 sqlmodel-nexus 的四阶段开发模式，从 Schema 建模到 API 响应组装再到 TS SDK 的完整项目构建流程。
argument-hint: "[项目路径] 创建四阶段项目的目标目录"
---

# sqlmodel-nexus 四阶段开发模式

基于 sqlmodel-nexus 的渐进式开发方法论。项目在一个 `src/` 目录下逐步演进，每个阶段在上一阶段基础上新增代码。

| Phase | 职责 | 产出 |
|-------|------|------|
| **Phase 0** | 需求确认 | 实体 + 关系 + 聚合根 + 用例方法（与用户反复确认） |
| **Phase 1** | Schema + ER Diagram + 聚合根入口 + mock seed | models + db(engine + session) + database(seed) + voyager |
| **Phase 2** | Loader 实现 | models 方法体实现，GraphQL 可查询 |
| **Phase 3** | UseCase 响应组装 + MCP | dtos + services + REST + MCP + Voyager 补充 services |
| **Phase 4** | OpenAPI spec → TS SDK | 端到端 SDK |

## 核心原则

- **需求确认是 Phase 0，必须反复与用户确认后才能进入 Phase 1**（详见下方「Phase 0: 需求确认」）
- 非功能模块与业务模块解耦，业务概念不侵入基础设施层
- **每个 Phase 采用 V 型验收：先定义验收标准（V 降），再实现，最后回查验收（V 升）**
- **每个 Phase 实现完成后必须暂停，展示验收结果，等用户确认后再进入下一阶段**
- Phase 间递进：同一项目目录下逐步丰富，只新增不修改已有代码

### V 型验收模型（贯穿所有 Phase）

每个 Phase 的结构统一为三段：

```
┌──────────────────────────────────────────────┐
│ V 降：定义验收标准                              │
│   "在当前 Phase 开始之前，先定义什么算做完。"      │
│   写入 spec/<phase>.md 的"验收标准"部分            │
└──────────────────────────────────────────────┘
                      ↓
              ┌───────────────┐
              │   实现 Phase   │
              └───────────────┘
                      ↓
┌──────────────────────────────────────────────┐
│ V 升：逐条回查验收                             │
│   "一条一条对照验收标准，通过才可继续。"           │
│   用户逐条确认 → 写入 spec/<phase>.md             │
└──────────────────────────────────────────────┘
```

验收标准必须是**可观察、可操作的**——不写"代码健壮"，写"GraphiQL 中执行 X query 返回 Y"。

## Phase 0: 需求确认（必做）

在写任何代码之前，必须与用户逐项确认以下内容。每一项都需要用户明确认可后才算完成。

### Step 0-1: 术语与实体定义

逐一列出所有业务实体，每个实体说明：

- **业务含义**（一句话，团队无歧义）
- **核心字段**（名称 + 类型 + 语义说明，不需要穷举，但关键属性不能遗漏）
- **字段约束**（唯一、非空、枚举值、联合唯一等）

用表格形式呈现，方便用户逐行确认。

### Step 0-2: 实体关系

用文本 ER 图展示实体间关系，每条关系标明：

- 方向（1:N / N:1 / M:N）
- 业务含义（如「会话包含多条消息」）
- 是否需要中间实体

```
User ──1:N──→ Participant
Conversation ──1:N──→ Message
...
```

**必须与用户确认关系方向和基数是否正确。**

### Step 0-3: 聚合根

明确哪个（或哪些）实体是聚合根。聚合根决定：

- 主要的业务入口（从哪个实体开始查询）
- @query / @mutation 挂在哪些实体上
- Phase 3 的 service 划分依据

### Step 0-4: 业务域划分 + 用例方法

**⚠️ 禁止自行决定 Service 切分方案。必须提出候选方案与用户讨论，由用户最终确认。**

#### Step 0-4a: 提出 Service 切分候选方案

业务域（Service）按功能边界划分，不按实体划分。Service 切分直接影响：
- 目录结构（`service/<domain>/`）
- Phase 2 的 methods.py 粒度
- Phase 3 的 UseCaseService 类划分
- MCP 和 REST 的入口组织

**必须向用户提出至少一种候选方案**，说明每种方案的切分依据和优劣，由用户选择或修正。

常见的切分策略参考：

| 策略 | 示例 | 适用场景 |
|------|------|----------|
| 按业务功能域 | `auth` / `chat` / `order` | 业务边界清晰，领域间耦合低 |
| 按聚合根 | `user` / `conversation` / `message` | 实体独立性强，CRUD 为主 |
| 混合（功能域 + 独立聚合） | `auth` / `chat`(含 conversation+message) | 部分域跨实体协作 |

**向用户展示的格式：**

```
方案 A：按功能域
  auth/    → register, login
  chat/    → create_conversation, list_messages, send_message
  优势：业务内聚，方法自然归组
  劣势：chat 域可能过大

方案 B：按聚合根
  user/         → register, login
  conversation/ → create_conversation, list_messages
  message/      → send_message
  优势：每个 service 粒度均匀
  劣势：conversation 和 message 强耦合却拆开了
```

**必须等用户明确选择后才能继续。** 如果用户提出自己的分法，按用户的来。

#### Step 0-4b: 按确认的 Service 划分列出用例方法

用户确认 Service 切分后，按每个业务域列出用例方法。每个方法说明：

- **方法名**（动词开头，如 `create_conversation`、`list_messages`）
- **业务意图**（一句话，如「创建群聊并自动将创建者加入为 owner」）
- **挂载实体**（挂在哪个 Entity 的 @query / @mutation 上，供 GraphQL 使用）
- **关键参数**（列出参数名和含义，不需要完整签名）

示例格式：

| 业务域 | 方法名 | 业务意图 | 挂载实体 | 关键参数 |
|--------|--------|----------|----------|----------|
| auth | register | 注册新用户 | User | username, nickname, password |
| auth | login | 登录返回 JWT | User | username, password |
| chat | create_conversation | 创建会话 | Conversation | type, creator_id, name |
| chat | list_messages | 查询会话消息（分页） | Conversation | conversation_id, before_id, limit |

**用例方法不需要实现细节，但必须逻辑自洽**：
- mutation 的参数是否足以完成操作
- 创建类 mutation 是否有遗漏的副作用（如自动创建关联记录）
- 查询类方法是否覆盖了核心场景

### Step 0-5: GraphQL 定位

GraphQL 是辅助开发测试和 AI 测试的接口，不是正式 API。

业务方法的定义和挂载关系：

```
service/<domain>/methods.py  ← 独立定义业务逻辑（核心）
        ↓ 挂载                    ↓ 挂载
  Entity @query/@mutation    UseCaseService @query/@mutation
  (GraphQL 辅助测试)          (REST + MCP 正式接口)
```

- Phase 2：方法体在 `service/<domain>/methods.py` 中实现，`models.py` 通过直接赋值挂载到 Entity
- Phase 3：同一个方法挂载到 UseCaseService（REST/MCP 使用），DTO 转换在 Service 层完成

### Step 0-6: 第三方库确认

列出项目中涉及的非业务功能领域（认证、实时推送、文件存储、数据迁移等），对每个领域：

- **说明候选方案**（推荐成熟第三方库 vs 手写实现）
- **给出推荐理由**（社区活跃度、维护状态、与 FastAPI/SQLModel 的兼容性）
- **必须调查用户提到的第三方库的当前维护状态**（避免选用已停止维护的库）

用表格形式呈现：

| 功能领域 | 推荐方案 | 理由 | 备注 |
|----------|----------|------|------|
| 认证 | ... | ... | ... |
| ... | ... | ... | ... |

**注意事项**：
- 优先使用 FastAPI 生态内的主流方案，减少集成风险
- 如果用户指定了某个库，必须先调查其维护状态和兼容性，发现问题要及时告知用户并提供替代方案
- 对于 sqlmodel-nexus 已覆盖的领域（ORM、GraphQL、MCP），不再重复讨论

**必须与用户确认每个领域的选型后才能继续。**

### Step 0-7: 检查清单

全部确认后，向用户展示汇总，确保以下问题已回答：

- [ ] 所有实体和字段是否完整，约束是否清晰？
- [ ] 实体关系方向和基数是否正确？
- [ ] 聚合根是否明确？
- [ ] **Service 切分方案是否由用户确认（不是模型自行决定）？**
- [ ] 核心用例是否覆盖主要业务场景，逻辑是否自洽？
- [ ] 第三方库选型是否确认，维护状态是否已调查？
- [ ] 是否有明显的遗漏或边界情况需要讨论？

**全部确认后才能进入 Phase 1。**

## 参考实现

读取本 skill 目录下 `template/` 中的代码作为生成参考。严格遵守 template 中的文件结构、import 风格和命名约定。

## 项目结构

单项目渐进演进，每个 Phase 在上一阶段基础上新增文件：

```
src/
├── models.py       # Phase 1 纯实体 → Phase 2 从 methods 挂载 @query/@mutation
├── db.py           # Phase 1（engine + session factory，不依赖 models）
├── database.py     # Phase 1（mock seed，依赖 db + models）
├── service/        # Phase 2 新增 methods.py，Phase 3 补充 service.py/dtos.py
│   ├── auth/       # 按业务域划分（非按实体）
│   │   ├── methods.py  # Phase 2: 独立业务方法
│   │   ├── dtos.py     # Phase 3: DTO
│   │   ├── service.py  # Phase 3: UseCaseService
│   │   ├── test.py     # Phase 3: unittest, file or folder, depends on complexity
│   │   └── spec.md     # Phase 3: 服务说明
│   └── chat/
│       ├── methods.py
│       ├── dtos.py
│       ├── service.py
│       ├── test.py
│       └── spec.md
├── main.py         # 逐步扩展（voyager → graphql → create_use_case_router → mcp）
fe/                 # Phase 4 前端 SDK
├── openapi-ts.config.ts
├── package.json
└── src/sdk/        # 自动生成的 SDK
    ├── sdk.gen.ts      # SDK class（按 tag 分组）
    ├── types.gen.ts    # TS 类型定义
    └── client/         # HTTP client
```

## 四阶段定义

### Phase 1: Schema + ER Diagram + mock seed

**目标**: 定义纯实体模型（字段 + 关系声明）、mock seed data，用 ER diagram 可视化供团队讨论。**不含任何业务方法**。

**新增/修改文件**:
- `db.py` — aiosqlite engine + session_factory（不导入 models，避免循环依赖）
- `models.py` — 纯 SQLModel 实体 + Relationship（仅字段和关系，不含方法，不导入 `sqlmodel_nexus`）。所有 Relationship 必须加 `sa_relationship_kwargs={"lazy": "noload"}`
- `database.py` — mock seed data（从 `db.py` 导入 engine/session，从 `models.py` 导入实体）
- `main.py` — FastAPI + Voyager（ER diagram 可视化）

**关键模式**:
- SQLModel 实体 + Relationship 声明关系方向，**不包含任何 @query/@mutation 方法**
- 每个 Model 必须有 docstring 说明业务含义，每个 Field 必须有 `description` 说明字段语义
- mock seed data 用于讨论数据样本是否合理（数量、关联关系、边界值）
- Voyager 通过 `create_use_case_voyager(services=[], er_manager=er)` 展示 ER diagram
- Phase 1 无 GraphiQL（无方法可查询），GraphQL 在 Phase 2 方法挂载后可用

**V 降 — 定义验收标准:**
进入 Phase 1 实现之前，在 `spec/phase1.md` 中记录以下验收标准：

| # | 验收项 | 验证方式 |
|---|--------|----------|
| 1 | 每个 Entity 在 Voyager ER 图中正确显示，关系线方向正确 | 浏览器打开 Voyager |
| 2 | `models.py` 中每个 Entity 只包含字段 + Relationship，无任何业务方法 | 检查代码结构 |
| 3 | mock seed 数据样本展示合理的数量、关联关系和边界值 | 编写简单查询验证记录数 |

**实现：**
编写 `db.py` → `models.py`(纯实体，无方法) → `database.py` → `main.py`

**V 升 — 逐条回查验收:**
按验收标准逐条验证，用户确认后才写入 `spec/phase1.md`：

- [ ] 1. Voyager ER 图：实体节点、关系线、聚合根高亮
- [ ] 2. Entity 纯字段：无 @query/@mutation 方法，无 `sqlmodel_nexus` 导入
- [ ] 3. mock seed：数据量合理、关联关系正确、包含边界用例

### Phase 2: 方法实现 + Entity 挂载

**目标**: 按业务域实现独立方法，挂载到 Entity 的 @query/@mutation，GraphQL 可查询。

**新增/修改文件**:
- `service/<domain>/methods.py` — 独立业务方法实现（核心逻辑，不含 @query/@mutation 装饰器）
- `models.py` — 从 methods 导入并通过 `Entity.method = query(fn)` / `Entity.method = mutation(fn)` 挂载

**关键模式**:
- 业务方法在 `service/<domain>/methods.py` 中定义，为普通 async 函数（不含 `cls` 参数，非 classmethod）
- `models.py` 通过 `_mount()` 辅助函数挂载（桥接 classmethod 协议）：
  ```python
  import functools
  from sqlmodel_nexus import mutation, query
  from src.service.user.methods import list_users, create_user

  def _mount(entity, name, fn, decorator):
      """Wrap a plain async function to accept cls, then apply decorator."""
      @functools.wraps(fn)
      async def wrapper(cls, *args, **kwargs):
          return await fn(*args, **kwargs)
      setattr(entity, name, decorator(wrapper))

  _mount(User, "list_users", list_users, query)
  _mount(User, "create_user", create_user, mutation)
  ```
- `_mount()` 保留原始函数的 docstring，确保 GraphQL SDL 正确生成描述
- GraphQL 作为辅助测试接口，`@query`/`@mutation` 装饰器在挂载时应用
- 挂载代码放在 Entity class 定义之后、ErManager 之前

**V 降 — 定义验收标准:**
进入 Phase 2 编码之前，先与用户确认测试验收集并写入 `spec/phase2.md`：

| # | 方法 | 测试场景 | 预期结果 | 验证方式 |
|---|------|----------|----------|----------|
| 1 | create_user | 正常创建 | 返回新用户对象，含关联关系 | GraphiQL mutation |
| 2 | create_user | 重复邮箱 | 返回错误提示 | GraphiQL mutation |
| 3 | list_users | 分页查询 | 返回正确分页数据 | GraphiQL query |
| ... | ... | ... | ... | ... |

验收标准要求：
- 每个 `@query`/`@mutation` 至少覆盖：**一个正常场景 + 一个边界/异常场景**
- 异常场景的预期结果必须是可观察的（不写"不出错"，写"返回 status: error, message: xx"）
- 验证方式统一通过 GraphQL query/mutation 在 GraphiQL 中执行

**实现：**
编写 `service/<domain>/methods.py` → `models.py` 挂载

**V 升 — 逐条回查验收:**
启动服务，在 GraphiQL 中逐一执行验收表，同时运行自动化测试：

- [ ] 1. create_user（正常）→ 返回新用户数据，关系字段正确
- [ ] 2. create_user（重复）→ 返回预期错误信息
- [ ] 3. list_users（分页）→ 分页参数生效
- [ ] ...（每条对标验收表）
- [ ] 确认 seed 数据仍可查询，Loader 行为符合预期
- [ ] 自动化测试全部通过：`pytest tests/`

### Phase 3: UseCase 响应组装 + MCP

**目标**: 按 API 用例组装响应结构。DefineSubset 隐藏内部字段，UseCaseService 统一业务入口。

**新增/修改文件**:
- `service/<entity>/spec.md` — 服务目的、用途、需求、变更记录
- `service/<entity>/dtos.py` — DefineSubset DTOs
- `service/<entity>/service.py` — UseCaseService
- `main.py` — 用 `create_use_case_router()` 挂载 REST + MCP + Voyager 补充 services

**关键模式**:
- `DefineSubset` + `SubsetConfig` 定义响应 DTO（字段选择、FK 隐藏）
- `ErManager` + `Resolver` 自动加载关系（implicit auto-load）
- `UseCaseService` 统一业务逻辑入口（同时服务 MCP 和 FastAPI）
- `@query` / `@mutation` 装饰器标记服务方法
- **UseCaseService 方法必须声明返回类型注解**（如 `-> list[ChatSummary]`、`-> ChatSummary | None`），`create_use_case_router()` 从中提取 `response_model`，使 OpenAPI spec 正确反映 DTO 结构
- **UseCaseService 复用 `service/<domain>/methods.py` 中的核心逻辑，不重新实现**：
  - **query 方法（list）**：调用 methods.py 拿 `list[Model]` → `[DtoType.model_validate(m) for m in models]` → `Resolver().resolve(dtos)`
  - **query 方法（get 单条）**：调用 methods.py 拿 `Model | None` → `DtoType.model_validate(entity)` → `Resolver().resolve(dto)`
  - **mutation 方法**：同 get 单条模式，调用 methods.py 获取 Model 后转换
  - **service.py 不直接操作数据库**（无 `build_dto_select`、`async_session`）
- **`create_use_case_router()` 自动生成 REST 路由** — 从 UseCaseAppConfig 生成 POST 路由，自动提取 `response_model`、构建 request body model、注册路由。不需要手写 `router/` 目录
  ```python
  from sqlmodel_nexus import UseCaseAppConfig, create_use_case_router
  use_case_router = create_use_case_router(
      UseCaseAppConfig(
          name="project",
          services=[WorkspaceService, AgentService, ChatService],
      ),
  )
  app.include_router(use_case_router)
  ```
- `create_use_case_voyager()` 可视化服务结构
- `create_use_case_mcp_server()` + `UseCaseAppConfig` 暴露给 AI agent
- MCP http_app 必须使用 `transport="streamable-http", stateless_http=True`
- MCP http_app 的 lifespan 必须在 FastAPI lifespan 中通过 `async with mcp_http.lifespan(mcp_http)` 嵌套启动
- MCP http_app 对象必须在 lifespan 函数定义之前创建，以便引用

**V 降 — 定义验收标准:**
进入 Phase 3 编码之前，先与用户确认以下验收项并写入 `spec/phase3.md`：

| # | 验收项 | 验证方式 |
|---|--------|----------|
| 1 | 每个 REST 端点返回的响应字段符合 DTO 定义（FK 字段隐藏、关系字段包含） | curl POST endpoint |
| 2 | Voyager 中 service 树展示完整（每个服务的方法可见） | 浏览器打开 Voyager |
| 3 | MCP 四层渐进式披露完整：discover → inspect → execute | MCP 客户端调用 |
| 4 | POST body 参数校验生效（参数缺少返回 422） | curl 发送非法请求 |

**实现：**
编写 `dtos.py` → `service.py` → `router/` → `main.py` 挂载

**V 升 — 逐条回查验收:**

- [ ] 1. REST 响应：`curl /api/sprint_service/list_sprints -X POST` 返回字段符合 DTO
- [ ] 2. FK 隐藏：返回数据中不包含 FK 字段（如 `owner_id`）
- [ ] 3. Voyager：service 节点和 method 方法都可见
- [ ] 4. MCP：依次调用 list_apps → list_services → describe_service → call_use_case
- [ ] 5. 参数校验：缺少必填参数返回 422

### Phase 4: OpenAPI → TS SDK

**目标**: 从 FastAPI OpenAPI spec 生成 TypeScript SDK（callable classes + types）。

**前提**: Phase 3 必须使用 `create_use_case_router()` 生成 REST 路由（而非手写 router），才能在 OpenAPI spec 中正确暴露 `response_model`。

**V 降 — 定义验收标准:**
确认后写入 `spec/phase4.md`：

| # | 验收项 | 验证方式 |
|---|--------|----------|
| 1 | 每个 DTO 字段都有对应 TS 类型 | 检查 types.gen.ts |
| 2 | 后端字段名（snake_case）原样映射到 TS 类型 | 检查类型字段名 |
| 3 | 嵌套关系在 TS 类型中有正确的递归结构 | 检查嵌套类型定义 |

**实现：**
在项目根目录创建 `fe/` 子目录，使用 `@hey-api/openapi-ts` 生成 SDK：

1. 创建 `fe/openapi-ts.config.ts`：
```typescript
import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  input: 'http://localhost:8000/openapi.json',
  output: {
    fileName: { suffix: '.gen' },
    path: 'src/sdk',
    header: ['// @ts-nocheck'],
  },
  plugins: [
    '@hey-api/client-fetch',
    '@hey-api/typescript',
    { name: '@hey-api/sdk', operations: { strategy: 'byTags' } },
  ],
});
```

2. 创建 `fe/package.json`，添加依赖和脚本：
```json
{
  "scripts": { "generate-client": "openapi-ts" },
  "devDependencies": { "@hey-api/openapi-ts": "^0.97" }
}
```

3. 安装依赖并生成：
```bash
cd fe && npm install && npm run generate-client
```

**生成产物**:
- `fe/src/sdk/sdk.gen.ts` — 按 tag 分组的 SDK class（如 `WorkspaceService`、`ChatService`）
- `fe/src/sdk/types.gen.ts` — 完整 TS 类型（含嵌套关系）
- `fe/src/sdk/client/` — HTTP client 基础设施

**V 升 — 逐条回查验收:**

- [ ] 1. TS 类型覆盖：所有 UseCaseService 的返回类型都有对应定义
- [ ] 2. 字段名一致：snake_case 字段名与后端一致
- [ ] 3. 嵌套结构：DTO 的关系字段推导为正确的嵌套 TS 类型

## 阶段间变化对照

| 方面 | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|------|---------|---------|---------|---------|
| 实体 | 纯字段 + Relationship + docstring + mock seed | methods.py 实现 + `_mount()` 挂载到 Entity | 继承 Phase 2 | - |
| 关系 | Relationship 声明 | DataLoader 实现 | DefineSubset 隐藏 FK | - |
| 查询 | 无方法 | methods.py + `_mount()` 挂载 | UseCaseService 封装（复用 methods.py） | - |
| API | Voyager(ER diagram) | GraphiQL | GraphQL + REST + Voyager(+services) + MCP | TS SDK |
| 响应 | N/A | 完整实体 | DefineSubset DTO | OpenAPI spec |

## 踩坑经验

1. **engine/session 必须独立为 `db.py`** — `models.py` 需要 `async_session`，`database.py` 需要 models，放在同一文件会导致循环导入。`db.py` 只放 engine + session_factory，不导入任何 model
2. **`pyproject.toml` 必须配置 `packages = ["src"]`** — hatchling 默认按项目名找目录，`src/` 布局需要显式指定 `[tool.hatch.build.targets.wheel]`
3. **不要在 DefineSubset 文件中使用 `from __future__ import annotations`** — 会使类型注解变字符串，SubsetMeta 无法检测 Annotated 元数据
4. **DTO 字段类型必须用 DTO 类型** — 不能直接用 SQLModel 实体，否则 TypeError
5. **列表关系需要 order_by** — 分页功能要求 `sa_relationship_kwargs={"order_by": "Entity.column"}`
6. **ErManager base 和 entities 互斥** — 不能同时提供
7. **目录命名不能以数字开头** — Python 模块名限制
8. **UseCaseService 只有被 @query/@mutation 装饰的 async classmethod 会被发现** — 普通方法不会暴露
9. **build_dto_select → dict(row._mapping) → DTO 构造** — 这是 Core API 的标准查询模式
10. **每个 Model 必须有 docstring，每个 Field 必须有 description** — Phase 1 就要确保语义清晰，description 会传递到 OpenAPI spec
11. **每个 service 子目录必须包含 spec.md** — 记录服务目的、用途、方法需求、DTO 说明和变更记录，方便团队理解服务边界
12. **fastmcp>=3.2.4 挂载到 FastAPI 需要 lifespan 合并** — `app.mount("/mcp", mcp.http_app(path="/"))` 会报 `Task group is not initialized`。必须：(1) 使用 `transport="streamable-http", stateless_http=True`；(2) 在 lifespan 函数定义之前创建 MCP http_app 对象；(3) 将 MCP http_app 的 lifespan 嵌套到 FastAPI lifespan 中（`async with mcp_http.lifespan(mcp_http):`）
13. **methods.py 函数需通过 `_mount()` 桥接 classmethod 协议** — `query()`/`mutation()` 返回 `classmethod`，会自动注入 `cls` 参数。methods.py 中的独立函数不含 `cls`，直接用 `query(fn)` 挂载到 Entity 后调用会 TypeError。使用 `_mount()` 辅助函数包装一层 `async def wrapper(cls, *args, **kwargs): return await fn(*args, **kwargs)` 来桥接。`@functools.wraps(fn)` 保留 docstring，确保 GraphQL SDL 正确生成描述
14. **测试需 monkey-patch 每个 methods 模块的 `async_session`** — methods.py 执行 `from src.db import async_session` 时已绑定原始值，运行时 patch `src.db.async_session` 不会影响已导入的局部绑定。必须同时 patch `src.db` 和每个 methods 模块：`monkeypatch.setattr(mod, "async_session", test_factory)`
15. **测试放在项目级 `tests/` 目录** — 不放在 `service/*/` 子目录，避免循环导入（tests 导入 src.models，而 models.py 底部导入 service methods）。每个业务域一个 `test_<domain>_methods.py` 文件
16. **Use `create_use_case_router()` 而非手写路由** — 手写路由无法声明 `response_model`，导致 OpenAPI spec 中响应类型为空（`unknown`），TS SDK 无法生成有效类型。`create_use_case_router()` 从 UseCaseService 方法的返回类型注解（如 `-> list[ChatSummary]`）自动提取 `response_model`，使 FastAPI 在 OpenAPI spec 中正确描述响应结构
17. **UseCaseService 方法必须声明返回类型注解** — `create_use_case_router()` 通过 `get_type_hints(method).get("return")` 提取返回类型作为 `response_model`。缺少返回注解的方法，其响应类型在 OpenAPI spec 中为空
18. **`@hey-api/sdk` 的 `asClass` 已废弃** — v0.97+ 使用 `operations: { strategy: 'byTags' }` 替代 `asClass: true`，按 OpenAPI tags 分组生成 SDK class
19. **所有 Relationship 加 `sa_relationship_kwargs={"lazy": "noload"}`** — 项目通过显式查询 + Resolver DataLoader 加载关系数据，不依赖 ORM lazy-load。`noload` 使 relationship 属性直接返回默认值（`None`/`[]`），避免 session 关闭后 `model_validate(entity)` 访问 relationship descriptor 触发 DetachedInstanceError
20. **methods.py 返回 Model，service.py 负责 DTO 转换** — methods.py 是纯业务逻辑层，所有方法（query + mutation）返回 ORM Model 实体。service.py 统一调用 methods.py，DTO 转换在 service.py 中进行：(1) list 方法调 methods 拿 `list[Model]` → `[DtoType.model_validate(m) for m in models]` → `Resolver().resolve(dtos)`；(2) 单条 get 方法调 methods 拿 `Model | None` → `DtoType.model_validate(entity)` → `Resolver().resolve(dto)`；(3) mutation 方法同单条 get。service.py 不直接操作数据库（无 `build_dto_select`、`async_session`）

## 需求文档管理

每次使用 skill 时，必须在项目根目录下创建 `spec/` 目录，按以下规则组织需求文档：

### 目录命名

```
spec/<编号>-<需求简述>/
```

- **编号格式**: `YY-MM-DD` + 两位序号，如 `250510-01`
- **需求简述**: 英文短横线连接，如 `chat-demo`

示例: `spec/250510-01-chat-demo/`

### 文件结构

```
spec/<编号>-<需求简述>/
├── story.md        # 用户原始需求 + Overview Design
├── phase0.md       # 需求确认
├── phase1.md       # Schema + ER Diagram
├── phase2.md       # Loader 实现
├── phase3.md       # UseCase + MCP
└── phase4.md       # TS SDK
```

### 文件内容格式

每个 phase 文件分三个部分：

```markdown
# Phase N: <阶段标题>

## 需求说明

（记录用户在对话中提出的原始需求、约束条件和确认结论）

## 验收标准

（V 降阶段定义的验收标准表格，每项标注验证方式）

## 实现描述

（记录该阶段的具体技术实现方案、产出文件和关键决策，以及 V 升的逐条回查结果）
```

### 写入时机

| 文件 | 写入时机 |
|------|----------|
| story.md | 用户首次描述需求时记录原始表述；Phase 0 确认后补充 Overview Design（见下方说明） |
| phase0.md | Phase 0 全部确认后，进入 Phase 1 之前 |
| phase1.md | V 降写入验收标准 → 实现 → V 升回查全部通过后写入完整内容 |
| phase2.md | V 降写入验收标准 → 实现 → V 升回查全部通过后写入完整内容 |
| phase3.md | V 降写入验收标准 → 实现 → V 升回查全部通过后写入完整内容 |
| phase4.md | V 降写入验收标准 → 实现 → V 升回查全部通过后写入完整内容 |

## 执行步骤

当用户要求创建四阶段项目时：

1. **创建 spec 目录**: 用户首次描述需求时，在项目根目录创建 `spec/<编号>-<需求简述>/`，将用户原始需求写入 `story.md`，预建 phase0 ~ phase4 空文件
2. **Phase 0 需求确认**: 按 Step 0-1 ~ 0-6 逐步与用户确认实体、关系、聚合根、用例方法、第三方库 → 确认后写入 `phase0.md` → **补充 `story.md` 的 Overview Design 部分** → **用户全部确认后才继续**
3. **创建项目结构**: 目录 + pyproject.toml（依赖 sqlmodel-nexus）
4. **Phase 1**:
   - **V 降**: 与用户确认验收标准表并写入 `spec/phase1.md#验收标准`
   - **实现**: 生成 db.py + models.py(纯实体，无方法) + database.py(mock seed) + main.py(voyager)
   - **V 升**: 逐条回查验收标准 → 通过后写入 `phase1.md` 完整内容 → **暂停等用户确认**
5. **Phase 2**:
   - **V 降**: 与用户确认测试验收集（正常场景 + 边界异常）并写入 `spec/phase2.md#验收标准`
   - **实现**: 编写 service/<domain>/methods.py → models.py 挂载 → tests/ 自动化测试
   - **V 升**: 运行 `pytest tests/` + 在 GraphiQL 中逐一执行验收表 → 通过后写入 `phase2.md` → **暂停等用户确认**
6. **Phase 3**:
   - **V 降**: 与用户确认 REST 端点、DTO 字段、MCP 分层的验收标准并写入 `spec/phase3.md#验收标准`
   - **实现**: 新增 dtos.py + services.py → main.py 用 `create_use_case_router()` 挂载 REST
   - **V 升**: 测试 REST 响应结构 + Voyager 可视化 + MCP 调用链 → 通过后写入 `phase3.md` → **暂停等用户确认**
7. **Phase 4**:
   - **V 降**: 确认 TS 类型覆盖、字段名一致性、嵌套结构等验收项并写入 `spec/phase4.md#验收标准`
   - **实现**: 创建 `fe/` 目录，配置 `@hey-api/openapi-ts`，执行 `npm run generate-client`
   - **V 升**: 检查生成的 sdk.gen.ts + types.gen.ts → 通过后写入 `phase4.md` → **暂停等用户确认**

### story.md 的 Overview Design 部分

Phase 0 全部确认后、进入 Phase 1 之前，在 `story.md` 中补充 `## Overview Design` 部分，内容包含：

- **业务流程**：核心用户操作路径（用文本流程图）
- **实体关系**：ER 图（文本格式）
- **聚合根**：明确入口实体
- **关键设计决策**：第三方库选型、分页策略、幂等策略等（表格形式）
- **四阶段产出**：每个 Phase 的预期交付物概要

目的：让团队在进入 Phase 1 之前对系统全貌有清晰共识。
