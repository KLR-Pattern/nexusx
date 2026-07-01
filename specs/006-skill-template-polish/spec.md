# 功能规格说明：skill 内容结构与模板优化

**功能分支**: `006-skill-template-polish`

**创建日期**: 2026-07-01

**状态**: Draft

**输入**: 用户原始描述：「我需要优化一下 skills 中的内容，以及代码模版。skill 内容的结构需要更加清晰合理，模版需要更完整一些。目的是让 skill 使用的过程中更加平滑，对用户指令更友好。」

---

## Clarifications

### Session 2026-07-01

- Q: Phase 4（TS SDK 生成）是否在本轮优化范围内？ → A: 仅 Phase 0~3（Python）+ Phase 4 文档对齐；不重写 `fe/` 模板代码（Phase 4 模板是 `openapi-ts` 自动生成的产物，本轮只校准 `phase4.md` 与上游文档的一致性）。
- Q: 测试文件位置统一到哪？ → A: 项目级 `tests/test_<domain>_methods.py`（每个业务域一个文件）。理由：规避 `tests` 导入 `src.models` 与 `models.py` 底部 import service methods 的循环导入，符合 Python 主流布局。模板需要把 `service/<domain>/test.py` 迁移到 `tests/test_<domain>_methods.py`，`phases/phase2.md` 维持现有踩坑分析。
- Q: 本轮优化面向的主要用户是？ → A: 单人独立开发为主，老用户结构迁移为次要；不覆盖团队协作的 CI / 多人分支策略（归 nexusx 主项目或团队规范）。SC-001 测评对象限定为"独立开发者首次使用 skill"，FR-009 迁移指引主要面向"在旧 skill 结构下产出过 specs/ 项目并需要过渡到新结构的老用户"。
- Q: skill 文档中引用的外部 docs 怎么处理？ → A: 关键概念自包含。把虚拟实体、跨层数据流（`ExposeAs`/`SendTo`/`Collector`）、3.0 UseCase GraphQL MCP 迁移等核心概念在对应 phase 文档内提供 10~20 行级别内联摘要；外部 nexusx 包内 docs（`docs/guide/virtual_entities.md` 等）降级为"延伸阅读"，用户不点外链也能完成本阶段决策。
- Q: Phase 0 外置后的内部结构？ → A: 单文件 `phases/phase0.md`，内部按 Step 0-1~0-8 用二级标题分节。Phase 0 是一个连贯的"逐步确认"对话流程，单文件便于连续阅读与检索，不进一步按 Step 拆分多文件。

---

## 用户场景与测试 *(mandatory)*

### 用户故事 1 — 文档与模板自洽 (Priority: P1)

**作为** 一名使用 nexusx-4phase skill 的开发者，
**当我** 按 skill 文档创建项目并对照模板代码学习时，
**我希望** 文档中提到的路径、API 名称、文件位置、版本门槛都与模板代码完全一致，
**以便** 我不会因为"文档说 A、模板做 B"的矛盾而卡住或写出错误代码。

**为何此优先级**：自洽是一切可用性的基础。任何一处文档与模板的矛盾都会让用户对整个 skill 的可信度产生怀疑，且会在每个 phase 反复踩坑。修复成本最低、收益最大。

**独立测试**：随机抽取 5 处 skill 文档中的具体陈述（路径、API、文件名），逐一在模板代码中找到对应实现，全部命中即视为通过。

**验收场景**：

1. **Given** skill 文档中提到的 spec 文件路径，**When** 用户在模板或参考项目中查找该路径，**Then** 实际路径与文档完全一致（不存在 `spec/` 与 `specs/<编号>-*/` 这种单复数或层级差异）。
2. **Given** skill 文档中提到的某个 nexusx API（如 `create_use_case_graphql_mcp_server`），**When** 该 API 在模板 `main.py` 中被使用，**Then** 其调用方式与文档描述完全一致，不出现文档已声明"移除"的旧 API。
3. **Given** 模板中存在的目录或文件（如 `router/`），**When** 用户在文档中查找该目录的说明，**Then** 文档对该目录的存在或不存在有明确陈述，不出现"文档说不需要，模板里却存在"的矛盾。

---

### 用户故事 2 — 一页总览快速上手 (Priority: P1)

**作为** 一名首次接触 nexusx-4phase skill 的开发者，
**当我** 打开 skill 目录时，
**我希望** 先看到一份简明的入口总览（一页可读），覆盖每个阶段的输入、产出、关键 API 与典型坑，
**以便** 我用 5 分钟就能决定从哪里开始读、当前阶段需要做什么，而不必通读全部上千行文档。

**为何此优先级**：当前的 phase 文档单篇都很长（Phase 0 内联 200+ 行，Phase 3 接近 200 行），新人没有入口地图，容易迷路。这是阻碍 skill 被广泛使用的最大障碍。

**独立测试**：找一名未接触过 nexusx 的开发者，给他 5 分钟阅读入口总览，要求他口述"四阶段每阶段做什么、产出什么"，能 80% 准确复述即视为通过。

**验收场景**：

1. **Given** 一名未读过 skill 的开发者，**When** 他打开 skill 入口（SKILL.md 顶部或独立的 README），**Then** 在一屏内能看到一张覆盖 Phase 0~4 的总览表，列出每阶段的输入、产出文件、关键 API。
2. **Given** 开发者想深入了解某个阶段，**When** 他在总览中点击/跳转到对应 phase 文档，**Then** 该文档独立可读，无需先读其他 phase 也能理解本阶段任务。
3. **Given** Phase 0（需求确认）当前内联在 SKILL.md，**When** 用户查看目录结构，**Then** Phase 0 与 Phase 1~4 一样有独立的 `phases/phase0.md` 文件，结构对称。

---

### 用户故事 3 — 完整模板覆盖全程 (Priority: P2)

**作为** 一名按 skill 实施项目的开发者，
**当我** 进入某个 phase 并需要参考成熟写法时，
**我希望** 模板项目包含每个 phase、每个示例 service 的完整文件（含 `dtos.py` / `service.py` / `test.py` / `spec.md`），
**以便** 我直接对照模板就能写出符合规范的代码，不需要自己脑补缺失的部分。

**为何此优先级**：当前模板中 `service/user/` 只有 `methods.py` + `spec.md`，缺 `dtos.py`/`service.py`/`test.py`，而 sprint/task 都齐全。这种"残缺"会让用户怀疑是不是 user service 故意省略有特殊原因，或者直接照着缺失模板写出不完整代码。

**独立测试**：模板项目按 phase 顺序逐阶段运行（Phase 1 建表 → Phase 2 挂方法 → Phase 3 出 REST/MCP → Phase 4 生成 SDK），每个阶段都能直接运行通过，不需要补任何文件。

**验收场景**：

1. **Given** 模板项目 `template/src/service/`，**When** 列出每个 service 子目录的文件，**Then** 所有 service 都包含完整的 `__init__.py` / `methods.py` / `dtos.py` / `service.py` / `test.py` / `spec.md`（或文档明确说明某文件按 phase 渐进出现的位置）。
2. **Given** 模板项目根目录，**When** 执行 `uvicorn src.main:app --reload`，**Then** 服务能启动且 `/voyager`、`/graphql`、REST 端点、MCP 端点全部可用，无需任何修改。
3. **Given** 模板项目的测试，**When** 执行全部测试，**Then** 测试全部通过，覆盖至少一个正常场景和一个边界场景。

---

### 用户故事 4 — 决策引导清晰 (Priority: P3)

**作为** 一名进入 Phase 3 的开发者，
**当我** 面对多种出口形态（REST / JSON-RPC / GraphQL HTTP / MCP / CLI / Voyager）选择时，
**我希望** skill 给我明确的"推荐默认组合"和"何时选什么扩展"的决策引导，
**以便** 我不需要把 6 种方案都读完才能做决定。

**为何此优先级**：当前 Phase 3 文档把 6 种出口并列展开，信息密度过高。新手难以判断"先做哪个、哪些可选"。优先级低于前三个，因为信息虽然过载但内容是齐全的。

**独立测试**：阅读 Phase 3 文档的"出口决策"部分后，能在 1 分钟内回答"如果我要给 AI agent 用，应该选哪个组合？如果要给传统 HTTP 客户端用呢？"。

**验收场景**：

1. **Given** Phase 3 文档，**When** 用户查看出口形态相关章节，**Then** 首先看到"推荐默认组合"的明确陈述（如 REST + UseCase MCP + Voyager），其次才是"可选扩展"的小节。
2. **Given** 模板 `main.py`，**When** 用户阅读其挂载代码，**Then** 默认只演示推荐组合，可选扩展以注释或独立示例的形式提供，不会让用户误以为所有出口都必须启用。

---

### Edge Cases

- 当老用户已经在用旧的 skill 结构（如已写过 `spec/phase1.md` 单数路径的项目）时，新结构是否提供迁移指引？
- 当 skill 在多人团队中共享时，文档与模板的"单一信息源"原则如何避免再次出现分歧（即未来修改一处忘记同步另一处）？
- 当 nexusx 框架本身版本升级（如 3.2 → 3.3）引入新 API 时，skill 文档如何快速同步而不破坏既有结构？
- 当用户跳过 Phase 0 直接进入 Phase 1（如老用户做小迭代）时，依赖 `spec-management.md` 已有的"迭代功能的处理"章节（Phase 0 快速确认 = 只确认变更部分，不变的部分不重复讨论）。**判定标准**（FR-012）：① 仅新增字段 / 方法 / 关系 → 可跳过 Step 0-1~0-3 的完整重过，只确认 delta；② 涉及聚合根变更、新业务域、DB 选型切换 → MUST 重做 Phase 0 对应 Step。skill 文档 MUST 在 `phases/phase0.md` 与 `spec-management.md` 的"迭代功能的处理"之间建立双向交叉引用，让用户在两处都能找到此判定标准。

---

## 需求 *(mandatory)*

### Functional Requirements

- **FR-001**: skill 文档中关于路径、API 名称、文件位置、版本门槛的所有具体陈述，MUST 与 `template/` 代码自洽，不存在互相矛盾。
- **FR-002**: skill MUST 提供一份入口总览文档（SKILL.md 顶部或独立 README），用一页表格覆盖 Phase 0~4 的输入、产出文件、关键 API 与典型坑，作为用户进入 skill 的第一站。
- **FR-003**: Phase 0（需求确认）内容 MUST 与 Phase 1~4 采用相同的组织方式，外置到独立的 `phases/phase0.md`（单文件），内部按 Step 0-1~0-8 用二级标题分节，与 SKILL.md 主文档解耦。
- **FR-004**: 模板项目 MUST 覆盖 Phase 0~3 的完整 Python 代码示例，所有示例 service（user / sprint / task 等）在文件结构上保持对等，不出现"某些 service 缺文件"的残缺。Phase 4 的 `fe/` TypeScript SDK 模板不在本轮重写范围内（属工具自动生成产物），但 `phase4.md` 文档 MUST 与 Phase 0~3 的术语、路径、版本门槛对齐。
- **FR-005**: Phase 3 文档 MUST 区分"推荐默认出口组合"与"可选扩展"，并给出基于场景的决策引导（如"AI agent 用 MCP、传统 HTTP 用 REST"）。
- **FR-006**: skill MUST 明确测试文件位置为**项目级 `tests/test_<domain>_methods.py`**（每个业务域一个文件），且与模板实际放置位置一致。模板现有的 `service/<domain>/test.py` MUST 迁移到该位置。
- **FR-007**: skill 文档 MUST 在显眼位置（推荐入口总览）声明所假设的 nexusx 最低版本门槛，正文不再散落"3.0 起 / 3.2+"等零散版本声明。
- **FR-008**: skill 文档 MUST 显式声明所有 spec-kit 产物（包括 `phaseN.md`）使用中文撰写，与项目 CLAUDE.md 的中文化要求保持一致。
- **FR-009**: skill MUST 提供一份从旧结构到新结构的迁移指引（哪怕是简短一段），覆盖路径变化、文件外置等破坏性调整，方便老用户过渡。**迁移时 MUST 保留 spec 编号**：旧项目目录 `specs/<旧编号>-<旧描述>/` 重命名为 `specs/<旧编号>-<新描述>/`，编号（如 `003`）禁止变更，以保证 git 历史连续与外部引用不断裂；只有描述部分可更新。
- **FR-010**: 模板 `main.py` MUST 默认只演示推荐出口组合，可选出口以注释或独立示例文件提供，避免给用户"必须全部启用"的错觉。
- **FR-011**: skill 文档中关于**虚拟实体**（Phase 0 决策）、**跨层数据流** `ExposeAs`/`SendTo`/`Collector`（Phase 3）、**3.0 UseCase GraphQL MCP 迁移**（Phase 3）等核心概念 MUST 在对应 phase 文档内提供 10~20 行级别的内联摘要，使用户不点外部链接也能完成本阶段决策；nexusx 包内 `docs/guide/*`、`docs/api/*`、`docs/migrations/*` 等外部引用降级为"延伸阅读"标注。
- **FR-012**: skill 文档 MUST 在 `phases/phase0.md` 与 `spec-management.md` 的"迭代功能的处理"章节之间建立**双向交叉引用**，并显式记录"何时可跳过 Phase 0 / 何时必须重做"的判定标准（仅新增字段方法 → 可跳过；聚合根 / 业务域 / DB 选型变更 → 必须重做）。

### Key Entities *(include if feature involves data)*

- **skill 主文档（SKILL.md）**：skill 的入口，描述方法论与阶段总览。优化后应瘦身，主要承载总览与导航。
- **phase 文档（phases/phaseN.md）**：每阶段的详细指令。优化后所有 phase（含 0）结构对称、独立可读。
- **spec-management 工作流（spec-management.md）**：spec 目录命名、文件格式、写入时机、交付校验的规则集。
- **模板项目（template/）**：参考代码，所有 phase 实现的"金标准"。优化后覆盖完整、可直接运行。
- **入口总览**：新增的一页快速参考，连接 SKILL.md 与各 phase 文档。

---

## 成功标准 *(mandatory)*

### Measurable Outcomes

- **SC-001**: 一名具有 FastAPI / SQLModel 基础但未接触过 nexusx 的开发者，从打开 skill 到产出第一个可运行的 Phase 1 项目，总耗时 ≤ 30 分钟。
- **SC-002**: 对 skill 文档与模板代码执行一致性检查（路径、API、文件名、版本声明），矛盾点数量为 0。
- **SC-003**: 模板项目在干净的 venv 中 `uv sync && uvicorn src.main:app` 能直接启动，所有端点（`/voyager` / `/graphql` / REST / MCP）可访问，无需任何手工修改。
- **SC-004**: 每个 phase 文档（phase0.md ~ phase4.md）独立阅读理解度 ≥ 80%，即不读其他 phase 文档也能正确理解本阶段任务并开始动手。**评测方法**：随机抽一份 phase 文档（如 `phase2.md`），让评审者只读该文件后回答 5 个理解度问题（目标是什么 / 新增哪些文件 / 关键调用点 / V 降验收形式 / 至少 2 个踩坑），答对 ≥4 题即通过（详见 [quickstart.md 检查 7](./quickstart.md#检查-7人工评测对应-sc-001sc-004)）。
- **SC-005**: Phase 3 出口决策时间 ≤ 1 分钟——开发者读完决策引导后能立刻选定适合自己场景的出口组合。
- **SC-006**: 模板项目的全部自动化测试通过率 100%，至少覆盖每个 service 一个正常场景 + 一个边界场景。

---

## 假设

- 目标用户是具备 FastAPI / SQLModel / Python 异步基础的开发者；不具备这些前置技能的用户不在目标范围内。本轮优化以**单人独立开发者**为首要受众，**老用户结构迁移**为次要受众；团队协作场景（CI、多人分支策略、模板版本对齐流程）不在本轮范围。
- 本次优化的范围限定在 skill 文档（`skill/` 目录）与模板代码（`skill/template/`），**不修改 nexusx 框架本身的代码**。任何对框架 API 的引用都以现状为准。
- 保持 skill 现有的核心方法论不变：V 型验收模型、Phase 0~4 五阶段递进、spec 工作流。
- 不引入新的外部依赖或新的工具链；优化聚焦于"现有内容的重组、补齐、对齐"。
- nexusx 当前主版本为 3.x，本 skill 文档假设用户使用 ≥ 3.2 版本（含虚拟实体等特性）。**框架升级同步策略**（针对未来 4.0 等破坏性变更）：① 升级后立即跑一遍 `quickstart.md` 全部 7 组检查，定位失效项；② 更新 SKILL.md `## 适用版本` 章节，同步特性-版本对照表；③ 重大 API 变更（如装饰器名、handler 签名变化）MUST 新建独立 spec（如 `specs/0XX-skill-nexusx-4-sync/`）走完整四阶段流程，不在本 feature 内热修。
- 用户已通过项目 CLAUDE.md 知晓 spec-kit 产物中文化要求；本 spec 及其后续 plan / tasks / checklists 全部使用中文。

## 范围外（Out of Scope）

- **Phase 4 的 `fe/` TypeScript SDK 模板代码不重写**：Phase 4 模板是 `@hey-api/openapi-ts` 自动生成的产物，重写收益低；本轮只校准 `phase4.md` 文档与上游 Phase 0~3 的一致性（路径、术语、版本声明）。
- 不修改 nexusx 框架本身的源码或 API。
- 不引入新的工具链或新的依赖。
- 不重写 V 型验收 / 五阶段递进的核心方法论，只重组其文档载体。
