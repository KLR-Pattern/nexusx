# 功能规格说明：Voyager ER 图 —— Hide Reverse Relationships 连线模式

**功能分支**：`007-voyager-er-pure-fk`

**创建日期**：2026-07-03

**状态**：草稿

**输入**：用户描述："现在 voyager 中 er diagram 的连线比较复杂， 原因是因为 sqlmodel 的定义中， 存在 foreign key 的关联， 以及 back populate 的字段， 两者都存在的时候， 会导致连线过多， 我希望有一个选项， 比如 pure foreign key 之类的名字， 点击之后，只保留 foreign key 的连线， 隐藏其他的连线。"

## 澄清记录

### Session 2026-07-03

- **Q1**: 在 Hide Reverse Relationships 模式下，"其他连线"的精确范围是什么？ → **A（原文）**: 只保留 FK 列约束连线；所有由 `Relationship(...)` 字段产生的连线一律隐藏；M2M 中间表 → 两端实体的 FK 连线仍保留。
  **修订注（Q4 触发）**：本答案基于"当前代码同时画 FK 列约束连线和 Relationship 连线"的前提。后续核查 `er_diagram_dot.py::analysis()` 与第 120 行注释 "Build relationship map per entity (replaces fk_set)" 后确认：当前 ER 图**所有连线均来自 `Relationship(...)` 字段**（用 relationship 字段名作为锚点，如 `Post::fauthor → User::PK`），不存在独立的 FK 列约束连线。本特性的真实语义因此调整为"按 direction 过滤现有 relationship 连线"，详见 Q4。Q1 的"M2M 中间表 FK 连线保留"在代码现实里不适用——M2M 关系当前以"两端实体之间的直接 MANYTOMANY relationship 连线"形式呈现，Q4 中明确这类连线在 Hide Reverse Relationships 模式下保留显示。
- **Q2**: Hide Reverse Relationships 选项的默认初始状态与持久化策略如何设定？ → **A**: 默认关闭（保持现状，对现有用户零侵入），勾选状态写入 localStorage，刷新或下次进入 ER 图时保留用户上次选择。沿用项目内 `better_cluster_display`、`show_module_cluster`、`brief_mode`、`pydantic_resolve_meta` 等已有偏好持久化的模式。
- **Q3**: Hide Reverse Relationships 模式开启时，侧边栏 "Related Entities" tab 内的迷你子图（spec 005 引入、明确"复用主图当前的渲染配置"）是否也跟随 Hide Reverse Relationships 裁剪？ → **A**: 跟随裁剪。子图严格复用主图渲染配置——Hide Reverse Relationships 模式开启时，子图也按 Hide Reverse Relationships 裁剪规则（按 direction 过滤）渲染。语义上 Hide Reverse Relationships 是一项与 show module cluster / show methods / edge length 同级的"主图渲染配置"，spec 005 验收场景 6 已建立"子图跟随主图所有渲染配置"的原则，Hide Reverse Relationships 不例外。
- **Q4**: 经核查当前 ER 图所有连线均来自 `Relationship(...)` 字段（`er_diagram_dot.py::_add_relationship_link` 用 `rel_info.name` 作锚点、`loader/registry.py::RelationshipInfo.fk_field` 仅用于 DataLoader 不画线），不存在独立的"FK 列约束连线"。用户原 spec 描述的"FK 连线 + back_populates 连线 = 3 条"在代码现实里实际是"MANYTOONE + ONETOMANY = 2 条方向相反的 relationship 连线"。那么 Hide Reverse Relationships 模式的真实行为应该是什么？ → **A**: 选项 B——**按 direction 过滤现有 relationship 连线，不改造连线生成方式**。保留 MANYTOONE 方向（持有 FK 字段的实体 → 被引用实体）、隐藏 ONETOMANY 方向（被引用实体的反向镜像）；MANYTOMANY 双向都保留（既不属于 MANYTOONE 也不属于 ONETOMANY、不在 back_populates 反向冗余范围内）。连线锚点、label、视觉样式与现状完全一致（如 `Post::fauthor → User::PK`、label `author\n1→N`），只是数量从 2 条降为 1 条。**功能名 "Pure Foreign Key" 最初沿用用户原始命名**（用户在原始描述中提议"pure foreign key 之类的名字"），但其语义实际是"按方向过滤 relationship 连线、保留持有 FK 一侧"，与字面"显示 FK 列约束连线"不同；改名决策见 Q5。
- **Q5**: 在 Q4 确认 B 模式后，两个待决定的子项：(a) M2M（MANYTOMANY）方向的 relationship 连线在本模式下如何处理？(b) 功能名 "Pure Foreign Key" 已不准确（实际语义是按方向过滤而非显示 FK 列约束），是否改名？ → **A**: (a) **M2M 双方向都保留**——MANYTOMANY 既不属于 MANYTOONE 也不属于 ONETOMANY、不在 back_populates 反向冗余范围内，过度过滤会让用户看不到多对多关系；本模式不裁剪 M2M 连线。(b) **改名为 "Hide Reverse Relationships"**——此名字最贴切描述行为（隐藏 ONETOMANY 反向镜像），不会让用户误以为会看到 FK 列约束连线。spec 主体、checklist 中所有原 "Pure Foreign Key" / "Pure FK" 表述同步替换为 "Hide Reverse Relationships"。**功能分支名 `007-voyager-er-pure-fk`、目录名 `specs/007-voyager-er-pure-fk/` 作为 git/filesystem 标识保留不变**（与 UI 可见 label 解耦）。

## 用户场景与测试 *(必填)*

### 用户故事 1 —— 一键隐藏 back_populates 反向冗余连线，看清持有 FK 的一侧（优先级：P1）

开发者或数据探索者正在 Voyager 的 ER 图 tab 中浏览一个基于 SQLModel 的中等规模 schema。该 schema 的实体类大多通过 `Relationship(back_populates=...)` 定义双向关系，SQLAlchemy 把这种双向关系在内部拆成两条方向相反的 relationship：一条 MANYTOONE（持有 FK 字段的实体 → 被引用实体）+ 一条 ONETOMANY（被引用实体 → 持有 FK 字段的实体，作为反向镜像）。当前 ER 图把这两条 relationship 都画出来，结果是：任意一对双向关联的实体之间出现 2 条方向相反、语义重复的连线（如 `Post::fauthor → User::PK` 与 `User::fposts → Post::PK`），整体画布看上去密集、交叉、难以一眼读懂"数据真正从哪里流向哪里"。用户希望在一个显示选项中勾选 "Hide Reverse Relationships"，让 ER 图立刻**只保留持有 FK 一侧的 MANYTOONE 方向连线**、隐藏 ONETOMANY 反向连线，从而把每对实体之间的连线降到 1 条，专注于"谁持有外键、引用了谁"这一数据流向。

**为什么是这个优先级**：这是本功能的核心价值——消除 `back_populates` 双向关系产生的视觉重复。当前一对实体 2 条反向连线中，ONETOMANY 那一条对"理解数据流向"是冗余的（它只是 ORM 层的反向镜像，数据库层面不增加任何外键信息）。Hide Reverse Relationships 模式能独立交付可感知的价值（即使没有持久化、即使选项位置不理想），因此是 P1。

**独立测试**：在 `demo/enterprise_voyager`（或任意一个定义了 `Relationship(back_populates=...)` 双向关系的 schema）上打开 ER 图，记录勾选前实体 `A` 与 `B` 之间的连线数量（典型为 2 条方向相反的 relationship 连线）；勾选 "Hide Reverse Relationships" 后，验证 `A` 与 `B` 之间的连线下降为 1 条（且该连线对应持有 FK 字段的实体的 MANYTOONE 方向），ONETOMANY 反向连线被隐藏。

**验收场景**：

1. **给定** ER 图已加载一个含 `Relationship(back_populates=...)` 双向关系的 schema，**当** 用户在显示选项中勾选 "Hide Reverse Relationships"，**那么** ER 图立即重新渲染，画布上只保留 MANYTOONE 方向（持有 FK 字段的实体指向被引用实体）的 relationship 连线，所有 ONETOMANY 方向（被引用实体反向持有 relationship）的连线被隐藏。
2. **给定** `Post.author = Relationship(back_populates="posts")`（MANYTOONE 方向、`Post` 持有 `user_id` FK）与 `User.posts = Relationship(back_populates="author")`（ONETOMANY 方向、`User` 不持有 FK）同时存在，**当** Hide Reverse Relationships 模式开启，**那么** `Post` 与 `User` 之间只保留 `Post::fauthor → User::PK` 这条 MANYTOONE 方向连线（label `author\n1→N`）；`User::fposts → Post::PK` 这条 ONETOMANY 反向连线被隐藏。
3. **给定** Hide Reverse Relationships 模式已开启，**当** 用户取消勾选 "Hide Reverse Relationships"，**那么** ER 图立即重新渲染，恢复显示全部 relationship 连线（含 ONETOMANY 反向），状态与开启前一致。
4. **给定** Hide Reverse Relationships 模式已开启，**当** 用户在 ER 图中切换到另一个 schema 或重新生成图，**那么** 新生成的 ER 图仍按 Hide Reverse Relationships 模式渲染（模式状态不被重置）。
5. **给定** 一对实体之间**仅**存在 ONETOMANY 方向 relationship、对应的 MANYTOONE 反向未定义（罕见但合法——只在被引用实体上写了 `Relationship(...)` 但持有 FK 的实体没有写反向），**当** Hide Reverse Relationships 模式开启，**那么** 这对实体之间不画任何连线（这是 Hide Reverse Relationships 模式按"仅保留 MANYTOONE 方向"规则的预期行为，不视为缺陷）。
6. **给定** 一个含多对多关系的 schema（如 `User.posts ↔ PostTag ↔ Post`，两端实体通过 `Relationship(secondary=...)` 或类似机制配置），**当** Hide Reverse Relationships 模式开启，**那么** 两端实体之间的 MANYTOMANY 方向 relationship 连线**仍保留显示**（双方向都保留），因为 MANYTOMANY 既不属于 MANYTOONE 也不属于 ONETOMANY、不在 back_populates 反向冗余范围内；Hide Reverse Relationships 模式不裁剪 M2M 连线。
7. **给定** Hide Reverse Relationships 模式开启时与其他显示选项（cluster display / brief mode / show fields 等）同时启用，**当** ER 图渲染，**那么** 各选项效果独立叠加、互不干扰——Hide Reverse Relationships 只决定"按方向过滤哪些 relationship 连线"，不影响字段展示、聚类、简短模式等其他维度。
8. **给定** Hide Reverse Relationships 模式开启期间用户双击实体打开侧边栏，**当** 用户查看 Fields / Source Code / About 各 tab，**那么** 这些 tab 的内容不受 Hide Reverse Relationships 模式影响——Fields 仍展示完整的 Relationship 字段列表（含 ONETOMANY 方向字段）、Source Code 仍展示完整源码、About 仍展示完整 docstring；仅主画布的 ONETOMANY 连线被裁剪。
9. **给定** Hide Reverse Relationships 模式开启期间用户双击实体 `X` 并切换到 "Related Entities" tab，**当** 子图渲染，**那么** 子图按 Hide Reverse Relationships 模式裁剪——仅渲染 `X` 与其 MANYTOONE 方向邻居（含"`X` 持有 FK 指向他者"与"他者持有 FK 指向 `X`"两类）之间的连线，以及 MANYTOMANY 邻居之间的连线；纯 ONETOMANY 方向邻居（即 `X` 不持有 FK、对方也未持有 FK 指向 `X`、仅由 `X` 反向引用）既不画连线、对应节点也不被渲染（沿用 spec 005"子图只渲染与 X 有可见边的邻居"逻辑）。
10. **给定** Hide Reverse Relationships 模式开启、Related Entities 子图已按 Hide Reverse Relationships 裁剪渲染，**当** 用户取消勾选 "Hide Reverse Relationships"，**那么** 子图立即重新渲染，恢复显示 `X` 与全部直接关系邻居（含 ONETOMANY 反向邻居）及其连线，状态与主画布一致。

---

### 用户故事 2 —— 偏好持久化：下次进入 ER 图沿用上次的 Hide Reverse Relationships 选择（优先级：P2）

用户在某个工作会话中勾选了 "Hide Reverse Relationships" 以专注于"持有 FK 一侧的数据流向"视图，刷新页面、重启 Voyager、或下次再回到 ER 图 tab 时，希望该偏好被**自动保留**，无需每次重新勾选；同时希望取消勾选后的"显示全部 relationship 连线"状态也同样被保留。这一行为应与项目内已有的偏好（`better_cluster_display`、`brief_mode`、`pydantic_resolve_meta` 等）一致——用户的显示偏好属于个人工作习惯，跨会话延续是合理预期。

**为什么是这个优先级**：偏好持久化能避免"每次都要重新勾选"的反复操作，提升长期使用体验，但即使不做持久化，Hide Reverse Relationships 模式本身的 P1 价值也已交付，因此 P2。

**独立测试**：在 ER 图中勾选 "Hide Reverse Relationships"，刷新浏览器页面，再次进入 ER 图 tab；验证 "Hide Reverse Relationships" 复选框仍为勾选状态，且 ER 图按 Hide Reverse Relationships 模式渲染（仅 MANYTOONE 与 M2M 方向连线）。取消勾选后再刷新，验证状态恢复为未勾选、ER 图显示全部 relationship 连线。

**验收场景**：

1. **给定** 用户在 ER 图中勾选了 "Hide Reverse Relationships"，**当** 用户刷新浏览器页面或重新进入 ER 图 tab，**那么** "Hide Reverse Relationships" 复选框仍为勾选状态，ER 图按 Hide Reverse Relationships 模式渲染（仅 MANYTOONE 与 M2M 方向连线）。
2. **给定** 用户在 ER 图中取消勾选 "Hide Reverse Relationships"，**当** 用户刷新浏览器页面，**那么** "Hide Reverse Relationships" 复选框为未勾选状态，ER 图显示全部 relationship 连线（含 ONETOMANY 反向）。
3. **给定** 用户从未勾选过 "Hide Reverse Relationships"（首次使用 / localStorage 中无对应记录），**当** 用户首次进入 ER 图，**那么** "Hide Reverse Relationships" 默认未勾选，ER 图显示全部 relationship 连线（保持现状，对现有用户零侵入）。
4. **给定** 浏览器禁用或不可写 localStorage（如隐私模式），**当** 用户在 ER 图中切换 "Hide Reverse Relationships" 勾选状态，**那么** 当前会话内 Hide Reverse Relationships 模式仍正常生效、可来回切换；不抛错、不阻塞 UI；只是不持久化，刷新后回到默认（未勾选）。
5. **给定** localStorage 中已存在该偏好的旧值（例如版本升级后字段含义变更），**当** 读取到无法解析或类型异常的值，**那么** 安全降级为默认（未勾选），不抛错、不阻塞 ER 图渲染。

### 边界情况

- 实体之间仅存在 ONETOMANY 方向 relationship、无 MANYTOONE 反向：Hide Reverse Relationships 模式下两者无连线（见 Story 1 验收场景 5）。
- 自引用双向关系（如 `Tree.parent = Relationship(back_populates="children")` 与 `Tree.children = Relationship(back_populates="parent")`）：MANYTOONE 方向（`parent`）保留、ONETOMANY 方向（`children`）隐藏，与其他双向关系一致；自环在画布上呈现为单条 MANYTOONE 自连线。
- 单向 Relationship（无 `back_populates`）：按其 SQLAlchemy `direction` 字段判定——MANYTOONE 单向保留、ONETOMANY 单向隐藏、MANYTOMANY 单向保留。
- 多对多关系（MANYTOMANY）：Hide Reverse Relationships 模式下双方向都保留显示，不参与方向过滤；这与"M2M 没有 back_populates 反向冗余"的语义一致。
- 复合外键 / 多列 FK：在 Hide Reverse Relationships 模式下不引入新行为——只要对应 relationship 存在且方向是 MANYTOONE，连线照常保留；是否实际为复合 FK 不影响裁剪规则。
- 同一对实体之间同时存在多条 MANYTOONE relationship（罕见，如多个角色外键）：Hide Reverse Relationships 模式下多条 MANYTOONE 连线均保留显示，与方向过滤规则一致。
- Hide Reverse Relationships 模式开启时切换 ER 图布局算法（如 dot / fdp / neato）：模式仍生效，仅 MANYTOONE 与 M2M 方向连线显示。
- Hide Reverse Relationships 模式与 cluster display 同时开启：聚类边界按 cluster display 规则绘制，连线按 Hide Reverse Relationships 规则裁剪，二者不冲突。
- 用户在 Hide Reverse Relationships 模式开启期间通过 URL 参数分享 ER 图给他人：模式属于本地显示偏好，不进入 URL；接收方按自己的 localStorage 偏好渲染（默认未勾选，除非接收方自己也开启过）。
- localStorage 配额满或被禁用：当前会话内 Hide Reverse Relationships 模式仍可切换，仅持久化失败；写入失败应在控制台 warn 但不阻塞 UI（沿用项目内 `console.warn("Failed to save ...")` 模式）。
- 后端在某条 relationship 上无法判定 direction（理论不应发生，`RelationshipInfo.direction` 已由 SQLAlchemy `inspect()` 提供）：默认按 ONETOMANY 处理（即 Hide Reverse Relationships 模式下隐藏），偏向"宁可不画也不要画错"。
- Hide Reverse Relationships 模式开启时，用户双击实体 X 打开 Related Entities 子图，若 X 的某些邻居仅通过 ONETOMANY 反向 relationship 关联（无 MANYTOONE 反向、非 M2M），则这些邻居节点既不画连线、也不被渲染进子图——这是 Hide Reverse Relationships 模式按"主图渲染配置"传递给子图的预期结果，不应视为 spec 005 子图功能的回归。

## 需求 *(必填)*

### 功能需求

#### 选项可见性与交互

- **FR-001**：Voyager ER 图必须提供一个名为 "Hide Reverse Relationships" 的可勾选显示选项；该选项在 ER-diagram 模式下可见，与项目内已有的显示选项（cluster display / brief mode / show fields 等）位于同一交互区域，便于用户在一次扫视中找到。
- **FR-002**："Hide Reverse Relationships" 选项的默认初始状态必须为**未勾选**，确保现有用户首次升级后看到的 ER 图与之前一致（保持现状，零侵入）。
- **FR-003**：用户勾选或取消勾选 "Hide Reverse Relationships" 后，ER 图必须**立即重新渲染**，不需要用户额外点击"应用"或"刷新"——沿用项目内 `toggle*` 显示选项的"勾选即生效"模式。
- **FR-004**："Hide Reverse Relationships" 选项的勾选/取消操作必须键盘可达、有清晰视觉反馈（聚焦态、勾选态可辨），不依赖鼠标。

#### 连线裁剪规则

- **FR-005**：当 "Hide Reverse Relationships" 被勾选时，ER 图必须**只保留 MANYTOONE 方向的 relationship 连线**（即持有 FK 字段的实体指向被引用实体的那条）；所有 ONETOMANY 方向的 relationship 连线（即被引用实体反向持有 relationship 的那一侧，通常是 `back_populates` 双向关系的反向镜像）必须被隐藏。连线本身的锚点、label、视觉样式**与未开启 Hide Reverse Relationships 时完全一致**（仍是 `Post::fauthor → User::PK`、label `author\n1→N`），Hide Reverse Relationships 只决定"哪些方向的关系被画出来"，不改造连线生成方式。
- **FR-006**：多对多（MANYTOMANY）方向的 relationship 连线在 Hide Reverse Relationships 模式下**仍保留显示**（双方向都保留），因为 M2M 既不属于 MANYTOONE 也不属于 ONETOMANY、不在 back_populates 反向冗余范围内。Hide Reverse Relationships 模式不裁剪 M2M 连线。
- **FR-007**：Hide Reverse Relationships 模式的裁剪作用范围限定为**连线渲染**，且同时作用于主画布与侧边栏 "Related Entities" tab 内的迷你子图（spec 005 已确立"子图复用主图所有渲染配置"原则，Hide Reverse Relationships 同样适用——见 Story 1 验收场景 9、10）。Hide Reverse Relationships 模式**不**改变实体节点的字段展示、不隐藏实体节点本身、不影响侧边栏 Fields / Source Code / About 各 tab 的内容——这三个 tab 仍完整展示全部 Relationship 字段信息（含 ONETOMANY 方向）、源码、docstring。
- **FR-008**：当一对实体之间仅存在 ONETOMANY 方向 relationship、对应的 MANYTOONE 反向未定义时，Hide Reverse Relationships 模式下两者之间不画连线；这是预期行为，UI 不需要额外提示。

#### 持久化与会话

- **FR-009**："Hide Reverse Relationships" 的勾选状态必须持久化到浏览器 localStorage，沿用项目内已有偏好持久化模式（如 `better_cluster_display`、`brief_mode`、`pydantic_resolve_meta`）；具体的 localStorage key 命名属于实现决策，建议沿用项目内 snake_case 习惯。
- **FR-010**：刷新页面或重新进入 ER 图 tab 时，必须从 localStorage 读取上次勾选状态并应用到 "Hide Reverse Relationships" 选项；若 localStorage 中无对应记录，按未勾选处理（FR-002）。
- **FR-011**：当 localStorage 不可用、写入失败、或读取到无法解析的值时，必须优雅降级——当前会话内 Hide Reverse Relationships 模式仍可正常切换、不抛错、不阻塞 ER 图渲染；仅持久化失效。控制台可 warn（沿用项目内 `console.warn("Failed to save ...")` 模式），但 UI 不向用户报错。
- **FR-012**：Hide Reverse Relationships 模式的状态属于本地显示偏好，**不进入 URL 参数**——避免分享 URL 时把个人偏好强加给接收方。

#### 与其他选项的正交性

- **FR-013**："Hide Reverse Relationships" 必须与其他显示选项（cluster display / brief mode / show fields / pydantic resolve meta 等）**正交**——任一组合的渲染结果等于各选项独立效果的叠加，Hide Reverse Relationships 只决定"按方向过滤哪些 relationship 连线"，不干涉其他维度的渲染。
- **FR-014**：Hide Reverse Relationships 模式开启期间，用户切换 schema、重新生成 ER 图、或切换布局算法时，模式状态必须保持生效，不被这些操作重置。

### 关键实体

- **MANYTOONE 方向 relationship 连线**：SQLModel/SQLAlchemy 中由 `Relationship(...)` 字段在 ORM 层面形成的关系映射，其 SQLAlchemy `direction` 字段取值为 `MANYTOONE`——即当前实体持有 FK 列、指向被引用实体。在 ER 图中表现为 `Source::frel_name → Target::PK` 的端到端连线，锚点用 relationship 字段名（如 `Post::fauthor → User::PK`）。这是 Hide Reverse Relationships 模式下**保留**的连线类型。
- **ONETOMANY 方向 relationship 连线**：`Relationship(...)` 字段对应 SQLAlchemy `direction` 取值为 `ONETOMANY`——即被引用实体的反向镜像（通常是 `back_populates` 双向关系的另一侧），当前实体不持有 FK、只是 ORM 层的反向引用。在 ER 图中同样表现为 `Source::frel_name → Target::PK` 连线（如 `User::fposts → Post::PK`）。这是 Hide Reverse Relationships 模式下**隐藏**的连线类型。
- **MANYTOMANY 方向 relationship 连线**：`Relationship(...)` 字段对应 SQLAlchemy `direction` 取值为 `MANYTOMANY`——通过中间表关联两端实体，两端实体本身都不直接持有 FK（FK 在中间表上）。在 ER 图中同样表现为 `Source::frel_name → Target::PK` 连线。Hide Reverse Relationships 模式下**保留显示**，不参与方向过滤。
- **Hide Reverse Relationships 显示模式**：Voyager ER 图的一个本地显示偏好状态，开启后只渲染 MANYTOONE 方向与 MANYTOMANY 方向的 relationship 连线、隐藏 ONETOMANY 反向连线，目的是消除 `back_populates` 双向关系产生的视觉重复，让用户专注于"谁持有外键、引用了谁"的数据流向。功能名 "Hide Reverse Relationships" 沿用用户原始命名；其实际语义是"按 direction 过滤 relationship 连线"，与字面"显示 FK 列约束连线"不同（当前代码不画 FK 列约束连线）。

## 成功标准 *(必填)*

### 可衡量结果

- **SC-001**：在一个含典型 `Relationship(back_populates=...)` 双向关系的中等规模 schema（如 `demo/enterprise_voyager`）上，用户勾选 "Hide Reverse Relationships" 后，画布上肉眼可见的连线数量**显著下降**——任意一对双向关联实体之间的连线由 2 条降为 1 条（仅剩 MANYTOONE 方向），整体视觉密度大幅降低。
- **SC-002**：用户勾选 "Hide Reverse Relationships" 后刷新浏览器或重新进入 ER 图 tab，模式状态被自动保留，无需重新勾选；取消勾选后再刷新，状态恢复为未勾选，与项目内 `better_cluster_display`、`brief_mode` 等已有偏好的持久化体验一致。
- **SC-003**：Hide Reverse Relationships 模式与 cluster display / brief mode / show fields 等其他显示选项同时开启时，渲染结果与各选项独立效果的叠加一致，无相互干扰或意外覆盖。
- **SC-004**：Hide Reverse Relationships 模式开启时，用户能完整看到该 schema 在 ORM 层面所有"持有 FK 一侧"的 relationship——所有 MANYTOONE 方向连线均保留可见，所有 MANYTOMANY 方向连线也保留可见（不丢失多对多关系信息），仅 ONETOMANY 反向镜像被裁剪。
- **SC-005**：Hide Reverse Relationships 模式只裁剪**连线**（同时作用于主画布与 Related Entities 子图），不改变实体节点、字段展示；用户在 Hide Reverse Relationships 模式下双击实体后，侧边栏 Fields / Source Code / About 各 tab 仍能完整查看该实体的全部 Relationship 字段（含 ONETOMANY 反向字段）、源码、docstring（与未开启 Hide Reverse Relationships 时一致），从而在"看清持有 FK 一侧的数据流向"与"查看完整 ORM 关系定义"之间无缝切换。

## 假设

- 选项命名：见上方 Q5 决议——已从用户原始描述的 "Pure Foreign Key" 改名为 "Hide Reverse Relationships"；中文界面内可附加简短说明如"仅保留持有外键一侧的关系连线，隐藏反向"，便于用户理解作用。
- 选项位置：见 FR-001（与现有显示选项面板同侧）；具体 UI 布局细节（顺序、分组、icon）属于 plan 阶段的实现决策，本假设不重复固化。
- localStorage key 沿用项目现有 snake_case 习惯，具体命名（如 `pure_fk_edges`）属于实现决策，本规格不固化。
- 后端在生成 ER 图时**已具备**判定 relationship 方向的能力——`RelationshipInfo.direction` 字段（取值 `MANYTOONE` / `ONETOMANY` / `MANYTOMANY`）由 SQLAlchemy `inspect()` 自动反射，已存在于 `loader/registry.py`。Hide Reverse Relationships 模式的实现路径是"在 `er_diagram_dot.py::_add_relationship_link` 或其调用点按 `direction` 过滤"，不需要新增 FK 元数据反射逻辑、也不需要改造连线锚点或 label 生成方式。
- Hide Reverse Relationships 模式作用于 ER-diagram 模式下的主画布连线，以及侧边栏 "Related Entities" tab 内的迷你子图连线（spec 005 已确立子图复用主图所有渲染配置的原则，Hide Reverse Relationships 同样适用）；其他模式（如 use-case 图）不受影响。
- Hide Reverse Relationships 模式不影响侧边栏 Fields / Source Code / About 三个 tab 的内容——这些 tab 与连线渲染无关，始终展示完整的字段定义、源码、docstring。
- Hide Reverse Relationships 模式开启时，对于无法判定 direction 的 relationship（理论不应发生），默认按 ONETOMANY 处理（即隐藏），偏向"宁可不画也不要画错"。
- Hide Reverse Relationships 模式状态属于本地显示偏好，不进入 URL、不进入导出的 schema 元数据；用户之间分享 ER 图（URL）时接收方按自己 localStorage 偏好渲染。
- 本规格不引入"Hide Reverse Relationships 与全部 relationship 视图之间平滑过渡动画"等增强体验——切换是即时的，与现有显示选项（如勾选 cluster display）的即时行为一致。
