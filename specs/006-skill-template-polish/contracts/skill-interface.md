# Skill 对外接口契约

**Feature**: 006-skill-template-polish
**说明**: 本 feature 优化对象是 Claude Code skill 文档与模板，"对外接口"指 skill 被 Claude Code 加载和被用户调用时暴露的契约面。本文件作为 Phase 1 设计产物，定义 skill 与外部（Claude Code runtime、用户、其他 phase 文档）之间的稳定契约。

---

## 接口面 1：Skill Frontmatter（YAML 头部）

Skill 通过 SKILL.md 顶部的 YAML frontmatter 被 Claude Code skill 系统识别。

### 字段契约

| 字段 | 类型 | 必填 | 本轮变更 | 说明 |
|---|---|---|---|---|
| `name` | string | ✅ | 不变 | skill 唯一标识，kebab-case。当前值：`nexusx-4phase` |
| `description` | string | ✅ | 不变 | 一句话用途说明，Claude Code 用于决定何时调用本 skill |
| ~~`argument-hint`~~ | — | ❌ | **删除** | Claude Code 不识别此字段，保留会让用户误以为生效 |

### 校验规则

- frontmatter 必须以 `---` 开始和结束
- 只允许 `name` 和 `description` 两个字段；多余字段必须删除
- `name` 全小写、kebab-case、≤ 64 字符
- `description` 中文或英文均可，必须包含触发场景的关键词（"nexusx"、"四阶段"、"Schema"、"API"等）

### 反例（必须避免）

```yaml
---
name: nexusx-4phase
description: 基于 nexusx 的四阶段开发模式...
argument-hint: "[项目路径] 创建四阶段项目的目标目录"   # ❌ 无效字段
---
```

### 正例

```yaml
---
name: nexusx-4phase
description: 基于 nexusx 的四阶段开发模式，从 Schema 建模到 API 响应组装再到 TS SDK 的完整项目构建流程。
---
```

---

## 接口面 2：Skill 调用约定（运行时入口）

调用约定的说明必须放在 SKILL.md 正文（替代被删除的 `argument-hint`）。

### 用户调用方式

```
/nexusx-4phase [项目目录路径]
```

- 参数：可选的目标目录路径（相对或绝对）
- 缺省行为：未提供路径时，skill 引导用户在当前位置或指定路径下创建项目

### Claude Code 加载时序

1. Claude Code 读 `SKILL.md` frontmatter → 注册 skill
2. 用户触发（显式 `/nexusx-4phase` 或描述匹配触发条件）→ Claude Code 加载 SKILL.md 全文
3. SKILL.md 正文引导 Claude / 用户进入 Phase 0 → 读取 `phases/phase0.md`
4. Phase 0 完成后依次读取 `phases/phase1.md` ~ `phases/phase4.md`

### 隐含契约

- SKILL.md 必须自包含"调用约定"+"入口总览"+"Phase 导航"三段，使用户不需要先读 phase 文档就能开始
- 每个 `phases/phaseN.md` 必须独立可读，不依赖兄弟 phase 文档的上下文

---

## 接口面 3：Phase 文件命名与结构契约

### 文件命名

```
phases/phase0.md   # Phase 0：需求确认（本轮新增）
phases/phase1.md   # Phase 1：Schema + ER Diagram + mock seed
phases/phase2.md   # Phase 2：方法实现 + Entity 挂载
phases/phase3.md   # Phase 3：UseCase 响应组装 + MCP
phases/phase4.md   # Phase 4：OpenAPI → TS SDK
```

- 文件名固定为 `phase<N>.md`，N ∈ {0, 1, 2, 3, 4}
- 不允许 `phase0/`（子目录）或 `phase-0.md`（连字符）等变体

### 文件结构契约

每个 `phaseN.md` 必须包含以下章节（顺序固定）：

```markdown
# Phase N: <阶段标题>

**目标**: <一句话>

**新增/修改文件**: <清单>

**关键模式**: <含 10~20 行内联摘要，外部 docs 仅作延伸阅读>

**V 降 — 定义验收标准**:
<可观察、可操作的验收表>

**实现**: <步骤>

**V 升 — 逐条回查验收**:
<checkbox 清单>

## 踩坑经验
<编号列表>
```

### SKILL.md 引用契约

SKILL.md 必须通过以下方式引用 phase 文件：

```markdown
Phase 0 完成并确认后，读取当前阶段的详细指令：
- **Phase 1**: 读取 `phases/phase1.md`
- **Phase 2**: 读取 `phases/phase2.md`
- **Phase 3**: 读取 `phases/phase3.md`
- **Phase 4**: 读取 `phases/phase4.md`
```

不允许在 SKILL.md 中复制 phase 文档正文（避免双份维护）。

---

## 接口面 4：Spec 工作流契约（spec-management.md）

### 目录命名契约

```
specs/<编号>-<需求简述>/
```

- `<编号>`：三位序号（001、002、…），按项目递增
- `<需求简述>`：英文短横线连接

### 文件结构契约

```
specs/<编号>-<需求简述>/
├── story.md
├── phase0.md
├── phase1.md
├── phase2.md
├── phase3.md
└── phase4.md
```

- 所有 phase 文件平铺在 spec 目录下，不允许嵌套
- 每个 phase 文件必须包含三段：**需求说明 / 验收标准 / 实现描述**

### 语言契约（本轮新增）

- 所有 spec-kit 产物（`story.md`、`phaseN.md`、`spec.md`、`plan.md`、`tasks.md`、`checklists/*` 等）必须使用中文撰写
- 英文术语（框架名、API 名、代码标识符）保留原文

---

## 接口面 5：模板项目契约（template/）

### 模板可运行性契约

```bash
cd skill/template
uv sync
uvicorn src.main:app --reload
```

- 启动后必须能访问 `/voyager`、`/graphql`（含 GraphiQL）、REST 端点、`/mcp-usecase` MCP 端点
- 不需要任何手工修改即可启动

### 文件结构对等契约

`template/src/service/` 下所有示例 service 子目录的文件列表必须对等：

```
service/<domain>/
├── __init__.py
├── methods.py
├── dtos.py        # Phase 3
├── service.py     # Phase 3
└── spec.md
```

- 当前 sprint / task 已满足，user 必须补齐
- 测试文件统一外置到 `template/tests/test_<domain>_methods.py`，service 子目录内不放测试

### 默认出口组合契约

`template/src/main.py` 默认仅演示以下出口：

| 出口 | 入口 API | 必须 |
|---|---|---|
| REST | `create_use_case_router(app_config)` | ✅ |
| UseCase GraphQL MCP | `create_use_case_graphql_mcp_server(apps=[...])` | ✅ |
| Voyager | `create_use_case_voyager(services=..., er_manager=...)` | ✅ |
| GraphQL HTTP | `GraphQLHandler` + `/graphql` 路由 | ✅（开发期辅助） |

其余出口（JSON-RPC / CLI）必须以注释形式保留，不在默认启动中加载。

---

## 契约违反的后果

| 违反点 | 后果 | 检测时机 |
|---|---|---|
| `argument-hint` 残留 | Claude Code 无效字段，用户混淆 | grep 检查 |
| `phases/phase0.md` 缺失 | Phase 0 流程无法进入（SKILL.md 不应再内联 Phase 0） | 文件存在性检查 |
| service 文件结构不对等 | 用户照 sprint 写 user 时缺文件参考 | 目录列表比较 |
| 模板无法直接启动 | SC-003 失败 | `uv sync && uvicorn` 实测 |
| 默认出口全开 | FR-010 违反，用户错觉"必须全启" | main.py 阅读检查 |
