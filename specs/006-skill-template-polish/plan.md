# 实施计划：skill 内容结构与模板优化

**分支**: `006-skill-template-polish` | **日期**: 2026-07-01 | **Spec**: [spec.md](./spec.md)

**输入**: Feature specification 自 [`/specs/006-skill-template-polish/spec.md`](./spec.md)

**说明**: 本文件由 `/speckit-plan` 命令填充，执行工作流见 `.specify/templates/plan-template.md`。

## 摘要

本轮优化针对 `skill/` 目录中的 nexusx-4phase skill 文档与 `skill/template/` 参考代码模板。核心问题来自上一轮代码评审识别的 P0/P1 共 14 处具体矛盾与缺口：spec 路径不一致、`argument-hint` 非法字段、模板 main.py 与 Phase 3 文档冲突、Phase 0 内联不对称、user service 模板残缺、router 目录残留、Phase 3 出口过载、缺入口总览、版本门槛散落、外部 docs 引用未声明、测试位置说法不一等。

经 `/speckit-clarify` 拍板的 5 条关键决策（详见 [spec.md Clarifications](./spec.md#clarifications)）：
1. 范围限定 Phase 0~3（Python）+ Phase 4 文档对齐，不重写 `fe/` TS SDK 模板
2. 测试位置统一为 `tests/test_<domain>_methods.py`
3. 受众以独立开发者为主、老用户结构迁移为次，不覆盖团队协作
4. 关键概念（虚拟实体 / 跨层数据流 / 3.0 MCP 迁移）自包含到 10~20 行内联摘要
5. Phase 0 外置为单文件 `phases/phase0.md`，按 Step 0-1~0-8 二级标题分节

技术路径：纯文档与模板重组，**不修改 nexusx 框架源码、不引入新依赖**。所有产出物用中文（项目 CLAUDE.md 要求）。

## Technical Context

**Language/Version**: 文档项目（Markdown）+ 模板代码（Python 3.12，与 nexusx 主项目对齐）

**Primary Dependencies**:
- `nexusx >= 3.2`（模板代码引用，假设版本，不修改框架本身）
- Claude Code skill 系统（frontmatter 仅识别 `name` / `description`，无构建依赖）

**Storage**: 文件系统（`skill/` 目录），无运行时存储

**Testing**: 
- 一致性检查：人工 + grep 脚本验证文档陈述与模板代码对齐
- 模板可运行性：`uv sync && uvicorn src.main:app` 启动验证
- 自动化测试：模板自带 `pytest tests/`（迁移到项目级 `tests/` 后）

**Target Platform**: Claude Code skill 用户（Linux / macOS / WSL）；模板运行平台为 Python 3.12+

**Project Type**: developer-tool / skill 文档项目（非编译产物，非 web 服务）

**Performance Goals**: N/A（文档项目无运行时性能指标）

**Constraints**:
- **不修改 nexusx 框架源码**（spec 范围外）
- **不引入新外部依赖**（spec 范围外）
- **不重写 Phase 4 `fe/` TS SDK 模板**（clarify 决策 #1）
- **保持 V 型验收 + Phase 0~4 五阶段方法论不变**（只重组载体）
- **不覆盖团队协作 / CI / 多人分支策略**（clarify 决策 #3）

**Scale/Scope**:
- skill 文档：SKILL.md（约 330 行）+ spec-management.md（约 90 行）+ phases/phase1~4.md（合计约 400 行）
- 模板代码：`skill/template/src/`（约 12 个 Python 文件）+ `pyproject.toml` + `uv.lock`
- 新增文件：`phases/phase0.md`（外置 Phase 0 内容）、可能的入口总览（写入 SKILL.md 顶部）
- 影响范围：仅 `skill/` 子树，不动主项目 `src/`、`docs/`、`tests/`

## Constitution Check

*GATE: 必须在 Phase 0 研究之前通过；Phase 1 设计后再次检查。*

`.specify/memory/constitution.md` 当前为空模板（仅含 `[PRINCIPLE_X_NAME]` 等占位符），未定义可执行的 governance gates。

**处理方式**：
- 视为本项目 constitution 未启用正式 gates，本计划不触发任何 violation
- 项目级约束改为引用 `CLAUDE.md` 与本 spec 的 `## 假设` / `## 范围外（Out of Scope）` 章节
- 如未来 constitution 落地具体原则，需在 Phase 1 末尾再次回查

**隐含 gate**（来自 spec 假设与 CLAUDE.md，本次自检）：
- ✅ 产物全部使用中文（spec-kit 产物要求）
- ✅ 不修改 nexusx 框架源码
- ✅ 不引入新依赖
- ✅ 保持 V 型验收 + 五阶段方法论
- ✅ 不重写 Phase 4 TS SDK 模板

无 violation，不需要 Complexity Tracking 表登记。

## Project Structure

### 本 Feature 的产出文档

```text
specs/006-skill-template-polish/
├── spec.md              # /speckit-specify 输出（已完成，含 Clarifications）
├── plan.md              # 本文件（/speckit-plan 输出）
├── research.md          # Phase 0 输出（决策汇总）
├── data-model.md        # Phase 1 输出（skill 资产清单 + 模板文件树模型）
├── quickstart.md        # Phase 1 输出（验证运行手册）
├── contracts/
│   └── skill-interface.md  # Phase 1 输出（skill 对外接口契约）
├── checklists/
│   └── requirements.md  # /speckit-specify 输出（已完成）
└── tasks.md             # /speckit-tasks 输出（下一步，不在本计划内）
```

### 被修改的源代码（`skill/` 子树）

```text
skill/
├── SKILL.md                  # 瘦身：保留总览 + 入口导航，Phase 0 内容外移
├── spec-management.md        # 校准：路径统一为 specs/<编号>-*/，补中文化声明
├── phases/
│   ├── phase0.md             # 【新增】从 SKILL.md 外置的 Phase 0 内容（Step 0-1~0-8）
│   ├── phase1.md             # 校准：移除 spec/ 单数路径、统一术语
│   ├── phase2.md             # 校准：测试位置声明与模板对齐
│   ├── phase3.md             # 重组：分"推荐默认组合"+"可选扩展"，内联核心概念
│   └── phase4.md             # 校准：术语、路径、版本声明对齐（不重写 fe/）
└── template/
    ├── pyproject.toml        # 校准：packages = ["src"]，alembic/uvicorn/driver 依赖示例
    ├── uv.lock               # 跟随 pyproject.toml 更新
    └── src/
        ├── main.py           # 重组：默认仅 REST + UseCase MCP + Voyager，可选出口注释化
        ├── models.py         # 校准：mount_method() 示例与文档一致
        ├── db.py             # 校准：URL 占位符与 Step 0-7 决策树对齐
        ├── database.py       # 校准：in-memory vs 持久化分支示例
        ├── router/           # 【删除】残留目录（create_use_case_router 取代手写 router）
        └── service/
            ├── user/         # 【补齐】补 dtos.py / service.py / test.py，与其他 service 对等
            ├── sprint/       # 校准：test.py 迁出
            └── task/         # 校准：test.py 迁出
        # test.py 文件统一迁移到↓
tests/                        # 【新增于模板根】test_<domain>_methods.py
├── test_user_methods.py
├── test_sprint_methods.py
└── test_task_methods.py
```

**Structure Decision**:
- **单项目结构**（plan 模板的 Option 1）：本 feature 不新建应用，只重组 `skill/` 子树
- **新增 `phases/phase0.md`**：Phase 0 与 Phase 1~4 文档结构对称
- **新增 `tests/`**：模板根级测试目录（替代 `service/<domain>/test.py`），匹配 clarify 决策 #2
- **删除 `template/src/router/`**：与 phase3.md "不需要手写 router" 一致
- **补齐 `template/src/service/user/`**：使三个示例 service 在文件结构上对等
- **不动 `template/fe/`**：Phase 4 TS SDK 模板不在本轮范围（clarify 决策 #1）

## Complexity Tracking

> 仅当 Constitution Check 存在需论证的 violation 时填写

`.specify/memory/constitution.md` 为空模板，无 violation，本表留空。
