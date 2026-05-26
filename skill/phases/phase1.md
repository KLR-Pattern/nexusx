# Phase 1: Schema + ER Diagram + mock seed

**目标**: 定义纯实体模型（字段 + 关系声明）、mock seed data，用 ER diagram 可视化供团队讨论。**不含任何业务方法**。

**新增/修改文件**:
- `db.py` — aiosqlite engine + session_factory（不导入 models，避免循环依赖）
- `models.py` — 纯 SQLModel 实体 + Relationship（仅字段和关系，不含方法，不导入 `nexusx`）。所有 Relationship 必须加 `sa_relationship_kwargs={"lazy": "noload"}`
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
- [ ] 2. Entity 纯字段：无 @query/@mutation 方法，无 `nexusx` 导入
- [ ] 3. mock seed：数据量合理、关联关系正确、包含边界用例

## 踩坑经验

1. **engine/session 必须独立为 `db.py`** — `models.py` 需要 `async_session`，`database.py` 需要 models，放在同一文件会导致循环导入。`db.py` 只放 engine + session_factory，不导入任何 model
2. **`pyproject.toml` 必须配置 `packages = ["src"]`** — hatchling 默认按项目名找目录，`src/` 布局需要显式指定 `[tool.hatch.build.targets.wheel]`
3. **目录命名不能以数字开头** — Python 模块名限制
4. **每个 Model 必须有 docstring，每个 Field 必须有 description** — Phase 1 就要确保语义清晰，description 会传递到 OpenAPI spec
5. **所有 Relationship 加 `sa_relationship_kwargs={"lazy": "noload"}`** — 项目通过显式查询 + Resolver DataLoader 加载关系数据，不依赖 ORM lazy-load。`noload` 使 relationship 属性直接返回默认值（`None`/`[]`），避免 session 关闭后 `model_validate(entity)` 访问 relationship descriptor 触发 DetachedInstanceError
