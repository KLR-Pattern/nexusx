# 数据模型：skill 资产清单与依赖关系

**Feature**: 006-skill-template-polish
**说明**: 本 feature 是 skill 文档/模板优化项目，无运行时数据库。本文件将优化对象建模为"文档资产 + 模板文件"的实体清单与依赖图，作为 Phase 1 设计契约。

---

## 实体清单

### 实体 1：Skill 主文档（SKILL.md）

- **业务含义**：skill 入口，被 Claude Code 加载时第一个读到的文件
- **关键属性**：
  - `frontmatter`: dict — YAML 头部，只允许 `name` / `description` 两个字段（移除非法 `argument-hint`）
  - `overview`: 入口总览章节，覆盖 Phase 0~4 的输入/产出/关键 API/典型坑
  - `version_gate`: 适用版本声明（`nexusx >= 3.2`）
  - `navigation`: 指向 `phases/phaseN.md` 与 `spec-management.md` 的导航链接
- **关系**：1:N → Phase 文档；1:1 → spec-management.md
- **本轮变更**：瘦身（删除内联的 Phase 0 内容约 200 行）；新增入口总览；移除 `argument-hint`

### 实体 2：Phase 文档（phases/phaseN.md，N ∈ {0, 1, 2, 3, 4}）

- **业务含义**：单阶段的详细实施指令，独立可读
- **关键属性**：
  - `goal`: 本阶段目标（一句话）
  - `new_files`: 新增/修改文件清单
  - `key_patterns`: 关键模式（含 10~20 行内联摘要，外部 docs 降级为延伸阅读）
  - `acceptance_criteria_v_drop`: V 降阶段定义的可观察验收标准
  - `implementation_steps`: 实现步骤
  - `acceptance_criteria_v_raise`: V 升阶段逐条回查清单
  - `pitfalls`: 踩坑经验列表
- **关系**：N:1 → SKILL.md（被导航）；N:N → 模板代码示例
- **本轮变更**：
  - `phase0.md`：**新增**（从 SKILL.md 外置，Step 0-1~0-8 二级标题分节）
  - `phase1.md` / `phase2.md`：校准路径与术语（`spec/` → `specs/<编号>-*/`）
  - `phase3.md`：重组"推荐默认出口"+"可选扩展"，内联虚拟实体 / 跨层数据流 / 3.0 MCP 迁移摘要
  - `phase4.md`：校准术语、路径、版本声明（不重写 fe/ 模板）

### 实体 3：Spec 管理工作流（spec-management.md）

- **业务含义**：spec 目录命名、文件格式、写入时机、交付校验的规则集
- **关键属性**：
  - `directory_naming`: `specs/<编号>-<需求简述>/`
  - `file_format`: `phaseN.md` 三段式（需求说明 / 验收标准 / 实现描述）
  - `write_timing`: 每个 phaseN.md 的 V 降 / V 升写入时机
  - `iteration_rules`: 增量迭代时的 spec 处理规则
  - `delivery_check`: 交付前 `wc -l` 完整性检查
  - `language_requirement`: 【新增】中文撰写要求
  - `migration_guide`: 【新增】从旧结构（`spec/` 单数路径、Phase 0 内联）迁移的指引
- **关系**：1:1 → SKILL.md
- **本轮变更**：路径统一为 `specs/<编号>-*/`；新增 `## 语言要求` 章节；新增 `## 从旧结构迁移` 章节

### 实体 4：模板项目（template/）

- **业务含义**：参考代码，所有 phase 实现的"金标准"
- **关键属性**：每个文件对应一个 nexusx API 用法示例
- **结构**（优化后）：
  ```
  template/
  ├── pyproject.toml            # packages = ["src"]，依赖示例（uvicorn / aiosqlite / asyncpg / alembic）
  ├── uv.lock
  ├── src/
  │   ├── __init__.py
  │   ├── main.py               # 默认 REST + UseCase GraphQL MCP + Voyager；其余出口注释化
  │   ├── models.py             # 含 mount_method() 示例
  │   ├── db.py
  │   ├── database.py
  │   └── service/
  │       ├── user/             # 补齐 dtos.py / service.py
  │       ├── sprint/           # 原位校准
  │       └── task/             # 原位校准
  ├── tests/                    # 【新增】test_<domain>_methods.py
  │   ├── test_user_methods.py
  │   ├── test_sprint_methods.py
  │   └── test_task_methods.py
  └── fe/                       # Phase 4 TS SDK（本轮不动）
  ```
- **关系**：N:N → phase 文档（每个 phase 引用对应模板代码段）
- **本轮变更**：
  - 删除 `template/src/router/`（与"不需要手写 router"一致）
  - 补齐 `template/src/service/user/{dtos.py, service.py}`
  - 把 `template/src/service/<domain>/test.py` 迁移到 `template/tests/test_<domain>_methods.py`
  - `template/src/main.py`：默认仅 REST + UseCase MCP + Voyager；GraphQL HTTP / JSON-RPC / CLI 注释化；为保留的 `create_mcp_server` 加注释说明属"base 实体层"
  - `template/pyproject.toml`：补 `packages = ["src"]`、`uvicorn`、async driver、`alembic>=1.13`（持久化场景）示例

---

## 关系图（文本 ER）

```
SKILL.md ──1:N──→ phases/phaseN.md  (N ∈ {0, 1, 2, 3, 4})
SKILL.md ──1:1──→ spec-management.md
phases/phaseN.md ──N:N──→ template/src/<file>  (文档引用代码示例)

phases/phase0.md 【新增】 ──1:1──→ SKILL.md  (内容来源：从 SKILL.md 外置)
template/tests/test_<domain>_methods.py 【新增】 ──N:1──→ template/src/service/<domain>/methods.py
template/src/service/user/{dtos,service}.py 【新增】 ──1:1──→ template/src/service/sprint/{dtos,service}.py (结构对齐)
template/src/router/ 【删除】
```

---

## 验证规则（从需求映射）

| 规则 | 来源 FR | 验证方式 |
|---|---|---|
| 文档中 `spec/` 单数路径出现次数 = 0 | FR-001 | `grep -rn "spec/phase" skill/`（除 `specs/` 外不应有命中） |
| `argument-hint` 出现次数 = 0 | S-02 | `grep -n "argument-hint" skill/SKILL.md` |
| `phases/phase0.md` 存在且非空 | FR-003 | `wc -l skill/phases/phase0.md` ≥ 100 |
| 三个示例 service 文件结构对等 | FR-004 | `ls skill/template/src/service/*/` 三个目录文件列表相同 |
| `template/src/router/` 不存在 | D-04 落地 | `test ! -d skill/template/src/router/` |
| `template/tests/test_*_methods.py` 存在 | FR-006 | `ls skill/template/tests/` |
| `template/src/service/<domain>/test.py` 不存在 | FR-006 | `find skill/template/src/service -name test.py` 应为空 |
| SKILL.md 顶部含入口总览 | FR-002 | 人工 + `grep -n "## .*总览\|## 入口\|## Overview" skill/SKILL.md` |
| SKILL.md 含 `nexusx >= 3.2` 适用版本 | FR-007 | `grep -n "nexusx >= 3.2" skill/SKILL.md` |
| Phase 3 文档"推荐默认组合"在"可选扩展"之前 | FR-005 | 人工阅读 phase3.md 章节顺序 |
| Phase 4 文档不含 `spec/phase4`（单数） | FR-001 | `grep -n "spec/phase4" skill/phases/phase4.md` 应为空 |

---

## 状态转换

文档资产无运行时状态机。模板代码的"状态"通过 git 提交历史表达：

```
draft (本 feature 分支) → review (PR) → merged (master)
```

每个 phase 文档的"V 降 → 实现 → V 升"是 spec-management.md 定义的写作时序，不影响文档资产本身的实体结构。
