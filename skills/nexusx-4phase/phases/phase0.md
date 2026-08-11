# Phase 0: 需求确认（必做）

在写业务代码之前完成以下确认。新项目需要与用户确认关键业务决策；现有项目应先从代码、配置和既有 spec 中提取结论，只询问无法安全推断或会改变行为的事项。

### Step 0-1: 术语与实体定义

逐一列出所有业务实体，每个实体说明：

- **业务含义**（一句话，团队无歧义）
- **核心字段**（名称 + 类型 + 语义说明，不需要穷举，但关键属性不能遗漏）
- **字段约束**（唯一、非空、枚举值、联合唯一等）

用表格形式呈现。新项目供用户逐行确认；现有项目同时标注信息来源（model、migration、service 或既有 spec）。

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

新项目必须与用户确认关系方向和基数；现有项目若 ORM 声明和迁移已明确，则记录检测结果，只询问冲突或新增关系。

### Step 0-3: 聚合根

明确哪个（或哪些）实体是聚合根。聚合根决定：

- 主要的业务入口（从哪个实体开始查询）
- @query / @mutation 挂在哪些实体上
- Phase 3 的 service 划分依据

#### 根类型选择（nexusx 6.x）

每个聚合根必须明确是 **SQLModel 实体**还是 **虚拟实体（普通 `pydantic.BaseModel`）**：

| 类型 | 何时选 | 数据持久化 | 例子 |
|------|--------|-----------|------|
| **SQLModel 实体** | 数据需要落库、参与 alembic 迁移、是 GraphQL 实体入口 | ✅ 表 | `User` / `Sprint` / `Conversation` |
| **虚拟实体（BaseModel）** | 响应根不对应ORM表：组装自外部 claims、聚合视图、第三方 SDK DTO | ❌ 不建表 | `CurrentUser`（OIDC claims）、`Page[T]`（分页 wrapper）、第三方 SDK 镜像 |

虚拟实体通过 `ErManager.add_virtual_entities([...])` 在 Phase 1 注册，与 SQLModel 实体在 Resolver / ER / Voyager 中同等对待（详见 `docs/guide/virtual_entities.md`）。

**判断依据**：如果根字段全部来自数据库表 → SQLModel；如果字段来自请求上下文（JWT、headers）或聚合多个源 → 虚拟实体。混合场景（如 `Page[TaskDTO]` 包含真实 task 数据）由 Phase 3 DTO 组合，根本身仍是虚拟实体。

### Step 0-4: 业务域划分 + 用例方法

**不要在缺少依据时自行决定 Service 切分方案。** 新项目应提出候选方案与用户讨论；现有项目优先沿用已有业务域边界，只有新增需求跨越现有边界时再确认。

#### Step 0-4a: 提出 Service 切分候选方案

业务域（Service）按功能边界划分，不按实体划分。Service 切分直接影响：
- 目录结构（`service/<domain>/`）
- Phase 2 的 methods.py 粒度
- Phase 3 的 UseCaseService 类划分
- MCP 和 REST 的入口组织

新项目必须提出至少一种候选方案，说明切分依据和优劣；现有项目仅在现有边界无法容纳需求时提出候选方案。

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

新项目必须等用户明确选择后继续；现有项目若边界已经由目录、服务类和 spec 明确，可记录依据后直接沿用。

#### Step 0-4b: 按确认的 Service 划分列出用例方法

Service 切分经用户确认或由现有项目边界确定后，按每个业务域列出用例方法。每个方法说明：

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

新项目必须确认新增领域的选型后继续；现有项目默认沿用已安装方案，只有新增或替换依赖时需要确认。

### Step 0-7: 数据持久化与迁移策略

DB 类型与迁移策略决定 Phase 1 的 `db.py` / `database.py` 实现方式以及是否引入 alembic。新项目必须由用户确认；现有项目应读取配置、依赖和迁移目录后沿用，禁止擅自切换数据库。

#### 选型决策表

| 选项 | async DB URL | 持久化 | Alembic | 额外依赖 | 适用场景 |
|------|-------------|--------|---------|---------|---------|
| **In-memory SQLite** | `sqlite+aiosqlite://` | ❌ 进程退出即丢 | ❌ 不需要 | `aiosqlite` | 纯原型/Demo/团队讨论数据样本，不关心数据保留 |
| **File-backed SQLite** | `sqlite+aiosqlite:///./var/<name>.db` | ✅ 文件 | ✅ 必须 | `aiosqlite` | 本地开发、单人项目、轻量持久化 |
| **Docker PostgreSQL** | `postgresql+asyncpg://user:pwd@localhost:5432/db` | ✅ 容器卷 | ✅ 必须 | `asyncpg` + docker-compose | 团队开发、生产前演练 |
| **Docker MySQL** | `mysql+aiomysql://user:pwd@localhost:3306/db` | ✅ 容器卷 | ✅ 必须 | `aiomysql` + docker-compose | 同上，团队偏好 MySQL |
| **External DB** | 各种 | ✅ | ✅ 必须 | 视驱动 | 已有 DB 基础设施 |

#### 决策影响（下游 Phase 必须遵守）

- **Phase 1 `db.py`**：engine URL 取决于此决策
- **Phase 1 `database.py`**：
  - **in-memory**：`init_db()` 做 `create_all` + mock seed（每次重启自动恢复，讨论用样本数据）
  - **持久化（file / docker / external）**：`init_db()` 改为 no-op，schema 由 alembic 管，seed 改为一次性 `scripts/load_seed.py`（保留 ID）
- **Phase 1 引入 alembic**（持久化场景必须）：
  - `alembic init alembic`
  - `env.py`：`import src.models` 注册表 + `target_metadata = SQLModel.metadata` + 同步 URL（app 用 async，alembic 用 sync）
  - SQLite 必须 `render_as_batch=True`；PostgreSQL / MySQL 不需要
  - `script.py.mako` 模板加 `import sqlmodel`（SQLModel 的 `AutoString` 类型需要）
  - `pyproject.toml` 加 `alembic>=1.13`
  - 生成 baseline：`alembic revision --autogenerate -m "init schema"` → 检查 → `alembic upgrade head`
  - `.gitignore` 加 `var/`（file sqlite 场景）

#### 必须记录的明确结论（写入当前需求目录的 `phase0.md`）

```
DB 选型：[in-memory sqlite / file sqlite / docker pg / docker mysql / external ___]
async DATABASE_URL：________________
sync DATABASE_URL_SYNC（alembic + load_seed 用）：________________
是否引入 alembic：[是 / 否]
是否需要 docker-compose：[是 / 否]
init_db() 策略：[create_all+seed / no-op+alembic / 其他]
```

新项目未明确选定前禁止进入 Phase 1；现有项目能从仓库确认时，将检测结果写入 phase0.md 即可。

### Step 0-8: 检查清单

全部确认后，向用户展示汇总，确保以下问题已回答：

- [ ] 所有实体和字段是否完整，约束是否清晰？
- [ ] 实体关系方向和基数是否正确？
- [ ] 聚合根是否明确？
- [ ] **每个聚合根的类型是否确认：SQLModel（落表）还是虚拟实体（BaseModel，不落表）？**
- [ ] **Service 切分方案是否由用户确认，或有现有代码/spec 作为依据？**
- [ ] 核心用例是否覆盖主要业务场景，逻辑是否自洽？
- [ ] 第三方库选型是否确认，维护状态是否已调查？
- [ ] **DB 选型 + 迁移策略是否由用户确认，或已从现有配置和迁移目录中确认（Step 0-7）？**
- [ ] 是否有明显的遗漏或边界情况需要讨论？

**全部确认后才能进入 Phase 1。**
