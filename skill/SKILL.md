---
name: nexusx-4phase
description: 基于 nexusx 的四阶段开发模式，从 Schema 建模到 API 响应组装再到 TS SDK 的完整项目构建流程。
argument-hint: "[项目路径] 创建四阶段项目的目标目录"
---

# nexusx 四阶段开发模式

基于 nexusx 的渐进式开发方法论。项目在一个 `src/` 目录下逐步演进，每个阶段在上一阶段基础上新增代码。

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

## 阶段实现

Phase 0（需求确认）完整包含在本文件中。

Phase 0 完成并确认后，读取当前阶段的详细指令：
- **Phase 1**: 读取 `phases/phase1.md`
- **Phase 2**: 读取 `phases/phase2.md`
- **Phase 3**: 读取 `phases/phase3.md`
- **Phase 4**: 读取 `phases/phase4.md`

每个阶段完成后，继续进行下一阶段之前暂停并等待用户确认。

对于 Spec 管理工作流（目录命名、文件格式、迭代规则、交付验证），读取 `spec-management.md`。

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

- Phase 2：方法体在 `service/<domain>/methods.py` 中实现，`models.py` 的 `mount_method()` 函数挂载到 Entity，`main.py` 显式调用
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
- 对于 nexusx 已覆盖的领域（ORM、GraphQL、MCP），不再重复讨论

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

## 阶段间变化对照

| 方面 | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|------|---------|---------|---------|---------|
| 实体 | 纯字段 + Relationship + docstring + mock seed | methods.py 实现 + `mount_method()` 挂载到 Entity | 继承 Phase 2 | - |
| 关系 | Relationship 声明 | DataLoader 实现 | DefineSubset 隐藏 FK | - |
| 查询 | 无方法 | methods.py + `mount_method()` 挂载 | UseCaseService 封装（复用 methods.py） | - |
| API | Voyager(ER diagram) | GraphiQL | GraphQL + REST + Voyager(+services) + MCP | TS SDK |
| 响应 | N/A | 完整实体 | DefineSubset DTO | OpenAPI spec |
