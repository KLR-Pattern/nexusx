# Phase 1: Schema + ER Diagram + mock seed

**目标**: 定义纯实体模型（字段 + 关系声明）、mock seed data，用 ER diagram 可视化供团队讨论。**不含任何业务方法**。

**硬性前提**: Phase 1 必须在 **Python >= 3.12** 的环境中执行。若使用更低版本 Python，`SQLModel + SQLAlchemy + nexusx ErManager` 在 `Relationship(...)`、自引用关系、虚拟实体注册与 Alembic 自动迁移上可能出现兼容问题。

**新增/修改文件**:
- `db.py` — engine + session_factory（不导入 models，避免循环依赖）。**engine URL 由 Phase 0 Step 0-7 的 DB 选型决定**（in-memory sqlite / file sqlite / docker pg / docker mysql / external）
- `models.py` — 纯 SQLModel 实体 + Relationship（仅字段和关系，不含方法，不导入 `nexusx`）。所有 Relationship 必须加 `sa_relationship_kwargs={"lazy": "noload"}`
- `database.py` — 启动 hook（FastAPI lifespan 调用）。**实现策略由 Step 0-7 决定**：
  - in-memory 场景：`init_db()` 做 `SQLModel.metadata.create_all` + mock seed（讨论样本数据）
  - 持久化场景（file sqlite / docker / external）：`init_db()` 改为 no-op（保留函数签名，`main.py` lifespan 和 tests/conftest.py 都 import 它），schema 和数据完全由 alembic + `scripts/load_seed.py` 管
- `main.py` — FastAPI + Voyager（ER diagram 可视化）

**关键模式**:
- Python 解释器必须为 `>= 3.12`，建议在项目目录显式创建 `.venv` 并固定该版本
- SQLModel 实体 + Relationship 声明关系方向，**不包含任何 @query/@mutation 方法**
- 每个 Model 必须有 docstring 说明业务含义，每个 Field 必须有 `description` 说明字段语义
- mock seed data 用于讨论数据样本是否合理（数量、关联关系、边界值）。持久化场景下 seed 数据写到 `var/seed_data.json`，由 `scripts/load_seed.py` 灌入
- Voyager 通过 `create_use_case_voyager(services=[], er_manager=er)` 展示 ER diagram
- Phase 1 无 GraphiQL（无方法可查询），GraphQL 在 Phase 2 方法挂载后可用
- **如果 Phase 0 Step 0-3 选了虚拟实体根**（普通 `pydantic.BaseModel`，不落表）：在 `ErManager(entities=[...])` 创建后、`create_resolver()` 调用**之前**，调用 `er.add_virtual_entities([CurrentUser, Page, ...])` 注册。虚拟实体通过类属性 `__relationships__` 声明关系（不是 SQLAlchemy `Relationship`）。注册后再调 `er.create_resolver()`，否则注册表已冻结会抛 `RuntimeError`。详见 `docs/guide/virtual_entities.md`

**V 降 — 定义验收标准:**
进入 Phase 1 实现之前，在 `specs/<编号>-<需求简述>/phase1.md` 中记录以下验收标准：

| # | 验收项 | 验证方式 |
|---|--------|----------|
| 1 | 每个 Entity 在 Voyager ER 图中正确显示，关系线方向正确 | 浏览器打开 Voyager |
| 2 | `models.py` 中每个 Entity 只包含字段 + Relationship，无任何业务方法 | 检查代码结构 |
| 3 | mock seed 数据样本展示合理的数量、关联关系和边界值 | 编写简单查询验证记录数 |
| 4 | （持久化场景）alembic baseline 迁移生成并 upgrade 成功，DB 中表结构与 models 一致 | `alembic upgrade head` + 查 `alembic_version` 表 |

**实现：**
编写 `db.py` → `models.py`(纯实体，无方法) → `database.py` → `main.py`

**如果 Step 0-7 选了持久化 DB（file sqlite / docker / external），还需要：**

1. **`pyproject.toml` 加 `alembic>=1.13` 依赖**，按 DB 类型加 async driver（postgresql → `asyncpg`；mysql → `aiomysql`）
2. **`alembic init alembic`**
3. **改 `alembic/env.py`**：
   - 顶部加 `import os`、`from sqlmodel import SQLModel`、`import src.models  # noqa: F401`（**关键：不导入则 SQLModel.metadata 为空，autogenerate 会生成空迁移**）
   - `target_metadata = SQLModel.metadata`
   - URL 从 env var 读，与 app 用同一文件但走 **sync 驱动**（alembic 默认 sync 连接）：
     ```python
     sync_url = os.getenv("DATABASE_URL_SYNC", "sqlite:///./var/<name>.db")
     config.set_main_option("sqlalchemy.url", sync_url)
     ```
   - SQLite 场景在 offline / online 两个 `context.configure(...)` 都加 `render_as_batch=True`（SQLite 不支持大多数 ALTER，必须 batch）
4. **改 `alembic/script.py.mako`** 加 `import sqlmodel`（SQLModel 的 `AutoString` 类型在生成的迁移里会被引用，缺这个 import 会 NameError）
5. **`alembic.ini` 的 `sqlalchemy.url =` 留空**，env.py 覆盖
6. **`.gitignore` 加 `var/`**（file sqlite 场景）
7. **`alembic revision --autogenerate -m "init schema"`** → 打开生成的迁移文件检查表结构正确（特别是自引用 FK）→ **`alembic upgrade head`**
8. **（可选）`scripts/load_seed.py`**：一次性把 mock seed 数据灌入文件 DB，保留 ID 和时间戳

**踩坑预警：**
- ❌ `alembic revision --autogenerate` 给出空 `upgrade()`：`env.py` 漏了 `import src.models`
- ❌ `alembic upgrade` 报 `NameError: name 'sqlmodel' is not defined`：`script.py.mako` 漏了 `import sqlmodel`
- ❌ uvicorn `--reload` 模式下，改 `db.py` URL 后会立即 reload，老的 `init_db()` 可能跑了一次 create_all 把表建到新文件里 → 后续 autogenerate 看到表已存在生成空迁移。**解决**：先 dump 数据 → 删 DB 文件 → 改代码 → autogenerate → upgrade → load_seed

**V 升 — 逐条回查验收:**
按验收标准逐条验证，用户确认后才写入 `specs/<编号>-<需求简述>/phase1.md`：

- [ ] 1. Voyager ER 图：实体节点、关系线、聚合根高亮
- [ ] 2. Entity 纯字段：无 @query/@mutation 方法，无 `nexusx` 导入
- [ ] 3. mock seed：数据量合理、关联关系正确、包含边界用例
- [ ] 4. （持久化场景）alembic baseline 已 upgrade，`alembic_version` 表记录了 revision id

## 踩坑经验

1. **engine/session 必须独立为 `db.py`** — `models.py` 需要 `async_session`，`database.py` 需要 models，放在同一文件会导致循环导入。`db.py` 只放 engine + session_factory，不导入任何 model
2. **`pyproject.toml` 必须配置 `packages = ["src"]`** — hatchling 默认按项目名找目录，`src/` 布局需要显式指定 `[tool.hatch.build.targets.wheel]`
3. **目录命名不能以数字开头** — Python 模块名限制
4. **每个 Model 必须有 docstring，每个 Field 必须有 description** — Phase 1 就要确保语义清晰，description 会传递到 OpenAPI spec
5. **所有 Relationship 加 `sa_relationship_kwargs={"lazy": "noload"}`** — 项目通过显式查询 + Resolver DataLoader 加载关系数据，不依赖 ORM lazy-load。`noload` 使 relationship 属性直接返回默认值（`None`/`[]`），避免 session 关闭后 `model_validate(entity)` 访问 relationship descriptor 触发 DetachedInstanceError
6. **in-memory SQLite 是进程级的，跨进程连不上** — uvicorn 跑起来后内存数据只活在那一个进程里，重启即丢。如果中途想从 in-memory 切到 file sqlite，必须**先通过 MCP/HTTP 接口把当前数据 dump 出来**（写 `var/seed_data.json`），再改 `db.py` URL 和引入 alembic，最后用 `scripts/load_seed.py` 灌回。直接连内存库 dump 是不可能的
7. **uvicorn `--reload` 模式下编辑代码会立即重启** — 在做 DB 迁移这类需要"先 dump 再改代码"的操作时，必须 Phase A（dump）和 Phase B+（改代码）严格分开：dump 落盘确认之前不要碰任何 `*.py`/`*.toml`/`*.ini` 文件，否则进程一重启数据就没了
