# Quickstart：Voyager Hide Reverse Relationships 连线模式 端到端验证

**功能**：[spec.md](./spec.md) · **计划**：[plan.md](./plan.md) · **契约**：[contracts/](./contracts/)

> 本文件是**验证手册**，不是实现指南。具体代码改动见 `tasks.md`（由 `/speckit-tasks` 产出）。

---

## 0. 前置条件

- Python ≥ 3.10、`uv` 已安装
- 现代 Chromium 系浏览器（Chrome / Edge / Brave）或 Firefox
- 工作目录在 `/home/tangkikodo/nexusx/`（nexusx 仓库根）
- demo 数据集 `demo/enterprise_voyager` 可用（含典型 `Relationship(back_populates=...)` 双向关系）

---

## 1. 后端单元测试（pytest）

### 1.1 运行测试

```bash
uv run pytest tests/test_voyager_hide_reverse.py -v
```

### 1.2 预期通过的测试用例

| 用例 | 描述 | 预期断言 |
|------|------|---------|
| `test_filter_off_keeps_all_directions` | `hide_reverse_relationships=False` 下，双向 `back_populates` 关系生成 2 条 Link（MANYTOONE + ONETOMANY） | `len(builder.links) == 2` |
| `test_filter_on_hides_onetomany` | `hide_reverse_relationships=True` 下，同一对实体的 ONETOMANY Link 缺失 | `len(builder.links) == 1` 且方向为 MANYTOONE |
| `test_m2m_preserved_when_filter_on` | M2M（`secondary="..."`）在 `hide_reverse_relationships=True` 下双方向都保留 | `len(builder.links) == 2`（两端各一条） |
| `test_manytoone_unirectional_preserved` | 单向 MANYTOONE（无 `back_populates`）在 Pure FK 模式下保留 | `len(builder.links) == 1` |
| `test_onetomany_unirectional_hidden` | 单向 ONETOMANY（无 `back_populates`）在 Pure FK 模式下隐藏 | `len(builder.links) == 0` |
| `test_fields_table_unchanged` | Pure FK 模式开关下，`SchemaNode.fields` 列表完全一致（含 ONETOMANY 方向 relationship 字段） | 两种模式下 `node.fields` 深度相等 |
| `test_endpoint_with_filter_on` | `POST /er-diagram` 带 `hide_reverse_relationships: true`，响应 dot 字符串不含 ONETOMANY 边 | dot 中 ONETOMANY 关系对应行缺失 |
| `test_endpoint_default_omits_field` | `POST /er-diagram` 不带该字段，行为与现状一致 | 响应 dot 与本期改动前完全一致 |
| `test_subgraph_follows_filter` | `POST /er-diagram-subgraph` 带 `hide_reverse_relationships: true`，子图按 Pure FK 模式裁剪 | 子图 dot 中 ONETOMANY 边缺失 |
| `test_self_referential_back_populates` | 自引用双向关系（`Tree.parent` ↔ `Tree.children`）在 Pure FK 模式下保留 `parent`、隐藏 `children` | `len(builder.links) == 1` 且方向为 MANYTOONE |

如果所有用例通过，后端契约满足 spec FR-005 / FR-006 / FR-007 / FR-008 / Story 1 验收场景 1-6 / Story 2 验收场景 1-3。

---

## 2. 端到端人工验证（浏览器）

### 2.1 启动 voyager

```bash
uv run python -m nexusx.voyager  # 或项目实际启动命令
```

打开浏览器访问 `http://localhost:<port>`，切换到 `demo/enterprise_voyager` schema，进入 ER-diagram 模式。

### 2.2 验证 Story 1（P1）—— Pure FK 模式裁剪反向镜像

#### 步骤

1. 在 ER-diagram 画布上找到一对有双向 `back_populates` 关系的实体（如 `Post` 与 `User`：`Post.author ↔ User.posts`）。
2. 记录勾选前 `Post` 与 `User` 之间的连线数量（预期 2 条：`Post::fauthor → User::PK` 与 `User::fposts → Post::PK`）。
3. 在显示选项面板勾选 **"Hide Reverse Relationships"**。
4. 观察 ER 图立即重新渲染。
5. 记录勾选后 `Post` 与 `User` 之间的连线数量。

#### 预期

- 勾选前：2 条方向相反的连线（如验收场景 2 所述）。
- 勾选后：1 条 MANYTOONE 方向连线（`Post::fauthor → User::PK`，label `author\n1→N`），ONETOMANY 反向连线（`User::fposts → Post::PK`）被隐藏。
- 连线锚点、label、视觉样式与勾选前完全一致——只是数量减少。

### 2.3 验证 Story 1 验收场景 3 —— 取消勾选恢复

#### 步骤

1. 在 Pure FK 模式开启状态下，取消勾选 "Hide Reverse Relationships"。
2. 观察画布。

#### 预期

- ER 图立即重新渲染。
- 恢复显示全部 relationship 连线（含 ONETOMANY 反向），状态与首次开启 Pure FK 之前一致。

### 2.4 验证 Story 1 验收场景 4 —— 切换 schema 不重置模式

#### 步骤

1. Pure FK 模式开启状态下，切换到另一个 schema（如 `demo/simple_voyager` 或其他可用 schema）。
2. 观察新 schema 的 ER 图。

#### 预期

- "Hide Reverse Relationships" 复选框仍为勾选状态。
- 新 schema 的 ER 图按 Pure FK 模式渲染（仅 MANYTOONE + M2M 方向连线）。

### 2.5 验证 Story 1 验收场景 6 —— M2M 双方向都保留

#### 步骤

1. 在 Pure FK 模式开启状态下，找到含多对多关系的实体对（如 `User` 与 `Role` 通过 `UserRole` 中间表，且 `User.roles ↔ Role.users` 配置 `secondary`）。
2. 观察 `User` 与 `Role` 之间的连线。

#### 预期

- 两端实体之间的 MANYTOMANY 方向 relationship 连线**仍保留显示**（双方向都保留）。
- 不应被 Pure FK 模式隐藏（M2M 不在 back_populates 反向冗余范围）。

### 2.6 验证 Story 1 验收场景 8 —— Fields / Source Code / About 不受影响

#### 步骤

1. Pure FK 模式开启状态下，双击实体 `Post` 打开侧边栏。
2. 切换到 Fields / Source Code / About 各 tab。
3. 取消勾选 Pure FK，重新打开同一实体的侧边栏，比较内容。

#### 预期

- Fields tab：仍展示完整的字段列表（含 `author` 这个 MANYTOONE 方向 relationship 字段）。
- Source Code tab：仍展示 `Post` 类的完整源码。
- About tab（spec 006）：仍展示 `Post` 类的 docstring。
- Pure FK 开关不影响这三个 tab 的内容（仅裁剪主画布连线）。

### 2.7 验证 Story 1 验收场景 9-10 —— Related Entities 子图跟随裁剪

#### 步骤

1. Pure FK 模式开启状态下，双击实体 `Post`，切换到 "Related Entities" tab。
2. 观察子图渲染。
3. 取消勾选 Pure FK，观察子图重新渲染。

#### 预期（Pure FK 开启）

- 子图按 Pure FK 模式裁剪：仅渲染 `Post` 与其 MANYTOONE 方向邻居（如 `User`，通过 `Post.author`）之间的连线，以及 MANYTOMANY 邻居（如 `Tag`，通过 M2M 关系）之间的连线。
- 纯 ONETOMANY 方向邻居（如某些仅在 `Post.xxx_set` 反向引用 `Post` 的实体）既不画连线、对应节点也不被渲染进子图。

#### 预期（取消勾选后）

- 子图立即重新渲染，恢复显示 `Post` 与全部直接关系邻居（含 ONETOMANY 反向）及其连线。

### 2.8 验证 Story 2 —— 偏好持久化

#### 步骤

1. 在 Pure FK 模式开启状态下，刷新浏览器页面（F5 / Cmd+R）。
2. 再次进入 ER-diagram 模式。
3. 观察 "Hide Reverse Relationships" 复选框状态。

#### 预期

- 复选框仍为勾选状态（localStorage 持久化生效）。
- ER 图按 Pure FK 模式渲染（仅 MANYTOONE + M2M 连线）。

#### 反向验证

1. 取消勾选 "Hide Reverse Relationships"。
2. 刷新浏览器。
3. 观察。

预期：复选框为未勾选状态，ER 图显示全部 relationship 连线。

### 2.9 验证边界情况 —— localStorage 不可用降级

#### 步骤

1. 打开浏览器 DevTools → Application → Storage，禁用 localStorage（或在隐私模式下打开）。
2. 切换 "Hide Reverse Relationships" 勾选状态。

#### 预期

- 当前会话内 Pure FK 模式仍正常生效、可来回切换、ER 图正确渲染。
- 不抛错、不阻塞 UI。
- 控制台可能出现 `console.warn("Failed to save hide_reverse_relationships to localStorage", ...)` 警告（沿用项目模式）。
- 刷新后回到默认（未勾选）。

### 2.10 验证边界情况 —— 与其他显示选项正交

#### 步骤

1. 同时勾选 "Hide Reverse Relationships" + "Better Cluster Display" + "Brief Mode"。
2. 观察画布。

#### 预期

- 三个选项效果独立叠加：
  - Pure FK：仅 MANYTOONE + M2M 连线
  - Better Cluster Display：聚类显示按其规则
  - Brief Mode：仅 tag → schema 简短模式
- 无相互干扰或意外覆盖。

---

## 3. 验收场景覆盖矩阵

| spec 验收场景 | quickstart 步骤 | 自动化 / 人工 |
|--------------|----------------|---------------|
| Story 1 - 场景 1（开启后只保留 MANYTOONE） | 2.2 | 人工 + 后端单测（test_filter_on_hides_onetomany） |
| Story 1 - 场景 2（Post↔User 双向关系） | 2.2 | 人工 + 后端单测 |
| Story 1 - 场景 3（取消勾选恢复） | 2.3 | 人工 |
| Story 1 - 场景 4（切换 schema 不重置） | 2.4 | 人工 |
| Story 1 - 场景 5（单向 ONETOMANY 无连线） | 后端单测 | test_onetomany_unirectional_hidden |
| Story 1 - 场景 6（M2M 双向保留） | 2.5 | 人工 + 后端单测（test_m2m_preserved_when_filter_on） |
| Story 1 - 场景 7（与其他选项正交） | 2.10 | 人工 |
| Story 1 - 场景 8（Fields/Source/About 不受影响） | 2.6 | 人工 + 后端单测（test_fields_table_unchanged） |
| Story 1 - 场景 9（子图跟随裁剪） | 2.7 | 人工 + 后端单测（test_subgraph_follows_filter） |
| Story 1 - 场景 10（取消后子图恢复） | 2.7 | 人工 |
| Story 2 - 场景 1（刷新保留勾选） | 2.8 | 人工 |
| Story 2 - 场景 2（取消后刷新恢复） | 2.8 反向 | 人工 |
| Story 2 - 场景 3（首次默认未勾选） | 2.2 前置 | 人工 |
| Story 2 - 场景 4（localStorage 不可用降级） | 2.9 | 人工 |
| Story 2 - 场景 5（异常值安全降级） | 后端单测 + loadToggleState 既有覆盖 | 自动化 |

---

## 4. 失败排查

| 现象 | 可能原因 | 排查步骤 |
|------|---------|---------|
| 勾选后连线数量不变 | 后端未生效（Payload 字段未透传 / ErDiagramDotBuilder 未收到参数） | DevTools Network 检查 `/er-diagram` 请求 body 是否含 `hide_reverse_relationships: true`；后端日志检查 |
| 勾选后画布空白 | `_add_relationship_link` 早退条件过严（误过滤 MANYTOONE / M2M） | 检查后端单测是否通过；调试时打印 `rel_info.direction` 与判定结果 |
| 刷新后状态丢失 | toggle 函数未写 localStorage / 初始化时未读 localStorage | DevTools Application → Local Storage 检查 `hide_reverse_relationships` 键是否存在 |
| 子图未跟随裁剪 | `ErDiagramSubgraphPayload` 未加字段 / `related-entities-display.js` 未透传 | DevTools Network 检查 `/er-diagram-subgraph` 请求 body |
| Fields tab 字段缺失 | `_add_relationship_link` 早退影响了 `self.rel_name_set`（不应该） | 检查 `analysis()` 第 121-125 行是否独立构建 `rel_name_set` |
| 与 cluster display 冲突 | 实现意外耦合（不应该） | 后端单测组合两种 toggle |

---

## 5. 验证完成检查清单

- [ ] 后端单元测试全部通过（10 个用例）
- [ ] 人工验证 Story 1（核心裁剪行为）—— 步骤 2.2
- [ ] 人工验证 Story 2（持久化）—— 步骤 2.8
- [ ] 人工验证子图跟随（spec 005 兼容性）—— 步骤 2.7
- [ ] 人工验证 M2M 边界（spec FR-006）—— 步骤 2.5
- [ ] 人工验证与其他选项正交（spec FR-013）—— 步骤 2.10
- [ ] 人工验证 localStorage 降级（spec FR-011）—— 步骤 2.9
- [ ] 无回归：现有 toggle（cluster display / brief mode / show methods / pydantic resolve meta）行为不变

所有项打勾后，本期功能可交付。
