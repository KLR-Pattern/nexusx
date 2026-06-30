# 研究与决策记录：skill 内容结构与模板优化

**Feature**: 006-skill-template-polish
**日期**: 2026-07-01
**输入**: [spec.md Clarifications](./spec.md#clarifications) + 上一轮代码评审识别的 14 处 P0/P1/P2 问题

## 用途

本文件汇总 `/speckit-clarify` 已拍板的 5 条核心决策，以及落地阶段需要回答的子决策。所有 NEEDS CLARIFICATION 在 clarify 阶段已闭环；本文件不再引入新澄清，只补充"如何执行"的依据。

---

## 核心决策（来自 clarify）

### D-01 Phase 4 范围

- **决策**：仅 Phase 0~3（Python）+ Phase 4 文档对齐；不重写 `fe/` TS SDK 模板代码
- **理由**：Phase 4 模板是 `@hey-api/openapi-ts` 自动生成产物，人工重写收益低；上一轮识别的所有 P0 矛盾都在 Phase 0~3 范围
- **替代方案（已否）**：① 全量覆盖 Phase 0~4 + 重写 fe/（工作量翻倍，收益边际）；② 完全跳过 Phase 4（会使 phase4.md 与新结构脱节）
- **落地约束**：`phase4.md` 仍需校准术语、路径、版本声明与 Phase 0~3 一致

### D-02 测试文件位置

- **决策**：项目级 `tests/test_<domain>_methods.py`，每个业务域一个文件
- **理由**：规避 `tests` 导入 `src.models`、`models.py` 底部 import service methods 的循环导入（phase2.md 踩坑 #6 已分析）；符合 Python 主流布局
- **替代方案（已否）**：① `service/<domain>/test.py`（结构紧凑但循环导入需要 conftest 绕弯）；② 混合分层（增加心智负担）
- **落地约束**：模板把 `template/src/service/{user,sprint,task}/test.py` 迁移到 `template/tests/test_<domain>_methods.py`；删除原位置 `test.py`

### D-03 目标用户

- **决策**：单人独立开发者为主，老用户结构迁移为次；不覆盖团队协作 / CI / 多人分支策略
- **理由**：模板与 skill 现有设计是"单项目渐进演进"，团队场景归 nexusx 主项目或团队规范
- **替代方案（已否）**：① 单人 + 团队并重（扩大范围，FR 数量翻倍）；② 仅新人（删除 FR-009 迁移指引会让老用户卡住）
- **落地约束**：SC-001 测评对象限定"独立开发者首次使用 skill"；FR-009 迁移指引聚焦"老 specs/ 项目如何过渡到新 skill 结构"

### D-04 外部 docs 引用处理

- **决策**：关键概念自包含（虚拟实体 / 跨层数据流 / 3.0 MCP 迁移）
- **理由**：用户原话强调"使用过程更平滑"，读 skill 中途跳出去找 nexusx 包内 docs 是高频打断点
- **替代方案（已否）**：① 仅声明 docs 位置（改善有限）；② 镜像 docs（双份维护负担）
- **落地约束**：phase0.md / phase3.md 内每处引用 `docs/guide/*`、`docs/api/*`、`docs/migrations/*` 前补 10~20 行摘要；外部 docs 标注为"延伸阅读"

### D-05 Phase 0 外置结构

- **决策**：单文件 `phases/phase0.md`，内部按 Step 0-1~0-8 二级标题分节
- **理由**：Phase 0 是连贯对话流程，单文件便于连续阅读
- **替代方案（已否）**：① 子目录多文件（8 个 Step 文件管理成本超过收益）；② 维持内联（与 FR-003 冲突）
- **落地约束**：SKILL.md 顶部改为入口总览 + Phase 0~4 导航，正文移除 200+ 行 Phase 0 内容

---

## 落地阶段子决策（执行层面）

### S-01 入口总览放在哪里？

- **选项 A**：写入 SKILL.md 顶部（在 Phase 0 表格之上）
- **选项 B**：独立 `skill/README.md`，SKILL.md 顶部加链接
- **选项 C**：两者都做（README 给仓库访客，SKILL.md 顶部给 Claude Code 加载时）

**决策**：选 A。Claude Code 加载 skill 时只读 SKILL.md，独立 README 不会被自动加载；总览必须在 SKILL.md 内才能起到"一页地图"作用。仓库根的 nexusx/README.md 是另一个层级，不在本轮范围。

### S-02 `argument-hint` 字段怎么处理？

- Claude Code skill frontmatter 只识别 `name` / `description`，`argument-hint` 是无效字段
- **决策**：删除 `argument-hint`，把调用约定说明移到 SKILL.md 正文（"调用时传入目标目录路径作为参数"）
- **替代方案（已否）**：保留但加注释（无效字段留作用户混淆源）

### S-03 模板 main.py 默认出口组合选什么？

- phase3.md 列出 6 种出口（MCP / GraphQL HTTP / REST / JSON-RPC / CLI / Voyager）
- **决策**：默认演示 **REST + UseCase GraphQL MCP + Voyager**，其余（GraphQL HTTP / JSON-RPC / CLI）以注释形式保留
- **理由**：REST 是 OpenAPI/SDK 链路必经；UseCase MCP 是 nexusx 3.0+ 的主推 MCP 入口；Voyager 是 ER/服务结构可视化必备；其余是可选扩展
- **替代方案（已否）**：① 默认仅 REST（缺 MCP/可视化让模板失色）；② 全部启用（与 FR-010 冲突，造成"必须全开"错觉）
- **额外清理**：模板现有 `create_mcp_server`（base 实体 MCP，老入口）是否保留？— **保留**作为对比示例但加注释说明它属于"base 实体层"而非"UseCase 层"，避免与 phase3.md "3.0 起 UseCase MCP 只有 GraphQL 模式"陈述冲突

### S-04 spec-management.md 与 SKILL.md 路径统一为？

- 当前矛盾：SKILL.md 写 `spec/phase0.md`（单数），spec-management.md 写 `specs/<编号>-*/phaseN.md`（复数 + 子目录）
- **决策**：统一为 `specs/<编号>-<需求简述>/phaseN.md`（与现有 specs/001~005 实际位置一致）
- **落地操作**：grep SKILL.md / phases/phase1~4.md 全部 `spec/phase` 出现位置，替换为 `specs/<编号>-<需求简述>/phaseN.md` 或上下文相关的具体引用

### S-05 迁移指引（FR-009）形式？

- **选项 A**：写进 `spec-management.md` 一个新章节 `## 从旧结构迁移`
- **选项 B**：独立 `skill/migrations/` 目录
- **决策**：选 A。迁移指引本质是 spec 工作流的一部分（涉及 specs/ 目录命名与文件位置），与 spec-management.md 同源；独立目录会让 spec 工作流被拆成多处

### S-06 版本门槛（FR-007）声明放哪？

- **决策**：SKILL.md 顶部入口总览下方加一行 `**适用版本**：nexusx >= 3.2`，并在此处链接到 nexusx 版本与特性对照（虚拟实体=3.2+，UseCase GraphQL MCP=3.0+）
- **正文清理**：删除 phase1.md / phase3.md 中散落的"3.0 起"、"3.2+"等零散门槛，改为"参见 SKILL.md 适用版本"

### S-07 中文化要求（FR-008）声明位置？

- **决策**：spec-management.md 文件开头加一段 `## 语言要求`，声明所有 spec-kit 产物（含 phaseN.md）使用中文，引用项目 CLAUDE.md

---

## 上一轮评审 P0/P1/P2 问题对账

| 编号 | 问题 | 对应决策 | 落地位置 |
|---|---|---|---|
| P0-1 | `spec/` vs `specs/<编号>-*/` 路径不一致 | S-04 | SKILL.md / phases/phase1~4.md |
| P0-2 | `argument-hint` 非有效字段 | S-02 | SKILL.md frontmatter |
| P0-3 | 模板 main.py 与 Phase 3 文档冲突 | S-03 | template/src/main.py |
| P0-4 | Phase 0 内联，结构不对称 | D-05 | phases/phase0.md（新增） |
| P0-5 | user service 模板残缺 | FR-004 | template/src/service/user/ |
| P0-6 | router 目录残留 | D-04 落地 | template/src/router/ 删除 |
| P1-7 | Phase 3 文档过载 | S-03 | phases/phase3.md 重组 |
| P1-8 | 缺入口总览 | S-01 | SKILL.md 顶部 |
| P1-9 | 版本门槛散落 | S-06 | SKILL.md + phases/* |
| P1-10 | 外部 docs 引用未声明 | D-04 | phase0.md / phase3.md 内联摘要 |
| P2-11 | Phase 4 验收过简 | D-01 | phase4.md 校准 |
| P2-12 | 测试位置说法不一 | D-02 | phases/phase2.md + 模板迁移 |
| P2-13 | 中文化要求未显式 | S-07 | spec-management.md |
| P2-14 | 缺迁移 / 升级说明 | S-05 | spec-management.md 新章节 |

所有 P0/P1/P2 均已闭环到具体决策与落地位置，无遗留 NEEDS CLARIFICATION。
