# 文档质量与跨文档一致性 Checklist：skill 内容结构与模板优化

**Purpose**: 校验本 feature 的 spec / plan / tasks / research / data-model / contracts 各产物中关于"文档质量与跨文档一致性"的需求陈述是否清晰、完整、一致、可测。**不**校验实现是否做到——那是 `quickstart.md` 的职责。
**Created**: 2026-07-01
**Feature**: [spec.md](../spec.md)

**说明**: 本 checklist 由 `/speckit-checklist` 生成，聚焦 documentation domain（Q1=A），标准 review 深度（Q2=B），含跨 story 一致性（Q3=A）。

---

## Requirement Completeness（文档相关需求是否齐全）

- [ ] CHK001 - spec 是否列出所有需要校准路径的文档文件（SKILL.md / phases/phase1~4.md / spec-management.md）？  [Completeness, Spec §FR-001]
- [ ] CHK002 - 是否有需求明确"模板代码与 phase 文档双向对齐"（而非仅文档侧改）？  [Completeness, Gap]
- [ ] CHK003 - FR-009（老用户迁移指引）是否定义了"迁移指引应覆盖哪些具体场景"（路径变化 / Phase 0 外置 / 测试位置变更）？  [Completeness, Spec §FR-009]
- [ ] CHK004 - 是否有需求规定 phase0.md 外置后 SKILL.md 中如何"指向"它（链接位置 / 链接文本）？  [Completeness, Spec §FR-002 + FR-003]
- [ ] CHK005 - FR-011（核心概念自包含）是否列全了需要内联摘要的概念清单（虚拟实体 / 跨层数据流 / 3.0 MCP 迁移——是否还有遗漏）？  [Completeness, Spec §FR-011]

## Requirement Clarity（"自洽 / 平滑 / 完整"等模糊词是否量化）

- [ ] CHK006 - "文档与模板自洽"（US1 标题）是否在 spec 中被量化为可观察的检查（如 grep 命中数 = 0）？  [Clarity, Spec §US1 + SC-002]
- [ ] CHK007 - "使用过程更平滑"（用户原话）是否被翻译为可测的 SC-001（≤30 分钟）和 SC-004（≥80% 理解度）？  [Clarity, Spec §SC-001 + SC-004]
- [ ] CHK008 - "对用户指令更友好"是否在 spec 中转化为具体需求项（FR-002 入口总览 / FR-005 决策引导）？  [Clarity, Spec §FR-002 + FR-005]
- [ ] CHK009 - "模板更完整"（用户原话）是否被具体化为"三个 service 文件结构对等"（FR-004）？  [Clarity, Spec §FR-004]
- [ ] CHK010 - "10~20 行内联摘要"（FR-011）的范围是否清晰——是行数下限、上限、还是区间？  [Clarity, Spec §FR-011]

## Requirement Consistency（spec ↔ plan ↔ tasks ↔ contracts 之间不冲突）

- [ ] CHK011 - spec §FR-004（Phase 0~3 Python + Phase 4 文档对齐）与 plan §Project Structure（不动 `fe/`）是否一致？  [Consistency, Spec §FR-004 vs Plan §Project Structure]
- [ ] CHK012 - spec §FR-006（`tests/test_<domain>_methods.py`）与 tasks T021（迁移 sprint/task 测试）+ T022（新建 user 测试）的文件路径是否完全对齐？  [Consistency, Spec §FR-006 vs Tasks §T021/T022]
- [ ] CHK013 - spec §FR-010（默认出口组合）与 contracts §接口面 5（REST + UseCase MCP + Voyager + GraphQL HTTP）与 tasks T014（main.py 重组）三处描述是否一致？  [Consistency, Spec §FR-010 vs Contracts §接口面 5 vs Tasks §T014]
- [ ] CHK014 - research §S-03（保留 `create_mcp_server` 加注释）与 contracts §接口面 5（默认出口表未列 `create_mcp_server`）之间是否有显式说明两者关系？  [Consistency, Research §S-03 vs Contracts §接口面 5]
- [ ] CHK015 - spec §FR-007（版本门槛集中声明）与 research §S-06（"phaseN.md 不再散落版本门槛"）是否一致？phase3.md 内联摘要里提到的"3.0+ MCP"是否违反这一规则？  [Consistency, Spec §FR-007 vs Research §S-06]

## Acceptance Criteria Quality（SC 是否可测）

- [ ] CHK016 - SC-001（≤30 分钟）是否定义了"从哪个动作开始计时 / 到哪个动作停止"的边界？  [Measurability, Spec §SC-001]
- [ ] CHK017 - SC-002（矛盾点 = 0）是否定义了"矛盾点"的判定规则（同一陈述在三处出现 ≠ 矛盾；陈述与模板冲突 = 矛盾）？  [Measurability, Spec §SC-002]
- [ ] CHK018 - SC-004（≥80% 理解度）是否定义了"理解度"的评测脚本（5 题答对 4 题）？此脚本在 spec 中是否给出？  [Measurability, Spec §SC-004 + Gap]
- [ ] CHK019 - SC-005（决策 ≤1 分钟）是否有可重复的评测方法（读哪段、问什么题）？  [Measurability, Spec §SC-005]

## Scenario Coverage（4 个 user story 是否覆盖全部文档资产）

- [ ] CHK020 - US1（自洽）是否覆盖了所有 4 项需要路径校准的 phase 文档（phase1/2/3/4），而非仅举例？  [Coverage, Spec §US1]
- [ ] CHK021 - US4（决策引导）是否仅聚焦 phase3.md，还是也包括 SKILL.md 顶部总览的"适用场景"引导？  [Coverage, Spec §US4 vs FR-002]
- [ ] CHK022 - 跳过 Phase 0 的场景（spec Edge Cases 第 4 条"老用户小迭代"）是否在 tasks 中有对应处理（如 spec-management.md 的"迭代功能处理"是否覆盖）？  [Coverage, Spec §Edge Cases + Spec-management §迭代功能的处理]

## Edge Case Coverage（边界是否定义）

- [ ] CHK023 - nexusx 框架升级（4.0 破坏性变更）场景，spec 是否定义了 skill 文档的同步策略？  [Edge Case, Gap, Spec §假设]
- [ ] CHK024 - 老用户 spec 项目使用旧 `spec/` 单数路径时，迁移到 `specs/<编号>-*/` 的 ID 是否保留（避免 git 历史断裂）？  [Edge Case, Spec §FR-009 + Gap]

## Ambiguities & Conflicts（跨 story 共享文件冲突检查 — Q3=A）

- [ ] CHK025 - tasks 是否显式标注 SKILL.md 被 US1（T004/T005）和 US2（T017）共享修改的串行依赖？  [Conflict, Tasks §Phase Dependencies]
- [ ] CHK026 - tasks 是否标注 `template/src/main.py` 被 US1（T014 默认出口）和 US3（T024 注册 UserService）共享修改的串行依赖？  [Conflict, Tasks §T014 vs T024]
- [ ] CHK027 - tasks 是否标注 `phases/phase3.md` 被 US1（T013 路径校准）和 US4（T026~T028 重组与内联）共享修改的串行依赖？  [Conflict, Tasks §T013 vs T026]
- [ ] CHK028 - spec §FR-001（自洽）与 FR-011（自包含摘要）在 phase3.md 上的修改顺序是否定义（先重组再内联 vs 反之）？  [Ambiguity, Spec §FR-001 vs FR-011]

## Notes

- 项目以 `- [ ]` 起始；通过后改为 `- [x]`
- 任意一项不通过 → 回到 spec.md / plan.md 走变更流程，**不要**直接在 tasks.md 加任务
- traceability 引用约定：`Spec §FR-XXX` / `Spec §SC-XXX` / `Spec §US N` / `Plan §<章节>` / `Tasks §T<NNN>` / `Research §<S-XX 或 D-XX>` / `Contracts §<接口面 N>` / `Spec-management §<章节>`
- 与已有 `checklists/requirements.md`（specify 阶段的规格质量校验）不重叠——后者校验 spec 整体写作质量，本文件专门校验 documentation domain

## Pre-Implementation Gap 闭环记录（2026-07-01）

下列 5 项识别为 Gap 的检查项已在 implementation 前闭环，[Gap] 标记转为可验证的 traceability 引用：

| CHK | 原状态 | 闭环动作 | 现状 |
|---|---|---|---|
| CHK018 | SC-004 评测方法未具体化 | spec.md §SC-004 补"5 题答对 4 题"评测脚本，引用 quickstart.md 检查 7 | 可验证 |
| CHK022 | "跳过 Phase 0"判定标准未定义 | spec.md §Edge Cases 改陈述句 + 新增 FR-012 + tasks.md 新增 T038 | 已需求化 |
| CHK023 | nexusx 4.0 同步策略未定义 | spec.md §假设 扩展为 3 步同步策略（跑 quickstart / 更新版本声明 / 新建独立 spec） | 已需求化 |
| CHK024 | 迁移时 spec ID 保留规则未定义 | spec.md §FR-009 补"编号 MUST 保留，只允许改描述部分" | 已需求化 |
| CHK028 | phase3.md 在 US1/US4 间修改顺序未定义 | tasks.md §Phase Dependencies + §Parallel Opportunities 显式串行（T013 → T026 → T027 → T028） | 已串行化 |

PR 评审时这 5 项可直接通过；其余 23 项仍需在实施过程中逐项验证。
