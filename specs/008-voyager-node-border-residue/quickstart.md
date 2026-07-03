# Quickstart：Voyager 节点高亮边框残留修复 端到端验证

**功能**：[spec.md](./spec.md) · **计划**：[plan.md](./plan.md) · **契约**：[contracts/](./contracts/)

> 本文件是**验证手册**，不是实现指南。具体代码改动见 `tasks.md`（由 `/speckit-tasks` 产出）。

---

## 0. 前置条件

- Python ≥ 3.10、`uv` 已安装
- 现代 Chromium 系浏览器（Chrome / Edge / Brave）或 Firefox
- 工作目录在 `/home/tangkikodo/nexusx/`（nexusx 仓库根）
- demo 数据集 `demo/enterprise_voyager` 可用（含典型双向 `Relationship(back_populates=...)` 关系）
- （可选但推荐）截屏工具，用于像素级对比验证

---

## 1. 修复前 baseline 留档（可选）

> 这一步的目的是记录 bug 当前的视觉表现，方便修复后做"前后对比"。如果你已经熟悉 bug 表现，可以跳过本节。

### 1.1 启动 demo

```bash
uv run uvicorn demo.enterprise_voyager.voyager_demo:app --port 8010
```

打开浏览器访问 `http://localhost:8010`，切换到 `demo/enterprise_voyager` schema，进入 ER-diagram 模式。

### 1.2 重现 bug

1. 找一对有双向 `back_populates` 关系的实体（如 `Employee` 与 `Department`）。
2. 双击 `Employee`——观察 `Employee` 节点的标题背景与外框都变橙色。
3. 单击 `Department`——观察 `Employee` 节点的标题背景橙色消失，**但外框仍有一条淡淡的橙色描边残留**。
4. 截屏保存为 `before-fix.png`。

---

## 2. 端到端人工验证（修复后）

### 2.1 启动 demo（同 §1.1）

### 2.2 Story 1 验收场景 1 —— 双击→单击切换无残留

#### 步骤

1. 找一对有双向 `back_populates` 关系的实体（如 `Employee` 与 `Department`），找一个第三方实体 `C`（如 `Role`，从未被点击过）。
2. 双击 `Employee`，确认标题背景与外框都变橙色。
3. 单击 `Department`。
4. 用 DevTools Elements 面板检查 `Employee` 节点的 outerFrame `<polygon>` 元素的属性。

#### 预期

- `Employee` 标题背景恢复原色（无橙色）。
- `Employee` 外框 `polygon` 的 `stroke` / `stroke-width` / `fill` 属性与 `C`（从未高亮过的同类节点）**完全一致**。
- 截屏对比：将 `Employee` 与 `C` 并排放大比较，肉眼看不到任何描边差异。

#### DevTools 自动检查（可选）

在 Console 里：

```javascript
// 找到 Employee 节点的 outerFrame
const empNode = document.querySelector('g.node[data-name*="Employee"]')
const empOuter = empNode.querySelector('polygon')
const roleNode = document.querySelector('g.node[data-name*="Role"]')
const roleOuter = roleNode.querySelector('polygon')
;['stroke', 'stroke-width', 'fill'].forEach(attr => {
  console.log(`${attr}: Employee=${empOuter.getAttribute(attr)} | Role=${roleOuter.getAttribute(attr)}`)
})
```

三个属性值应该完全一致（或都为 null，回退到默认）。

### 2.3 Story 1 验收场景 2 —— 双击→双击切换无残留

#### 步骤

1. 双击 `Employee`。
2. 双击 `Department`。

#### 预期

- `Employee` 完全还原（标题背景 + 外框），与单击切换路径行为一致。

### 2.4 Story 1 验收场景 3 —— 单击→单击切换无残留

#### 步骤

1. 单击 `Employee`（shallow 高亮：标题背景与外框变橙、单层邻居高亮）。
2. 单击 `Department`。

#### 预期

- `Employee` 外框完全恢复，无橙色残留。

### 2.5 Story 1 验收场景 4 —— 切换 schema 无残留

#### 步骤

1. 在 schema A 双击某节点触发高亮。
2. 切换到 schema B（侧边栏重新打开 / 主图重新生成）。

#### 预期

- 切换后 schema A 的所有节点视觉状态归零（已被整体 SVG 替换）。
- schema B 的所有节点默认状态干净，无任何橙色描边残留。

### 2.6 Story 1 验收场景 5 —— 切换 ER-diagram ↔ voyager 模式

#### 步骤

1. 在 ER-diagram 模式下双击某节点触发高亮。
2. 切换到 voyager 模式（如 use-case 图）。
3. 切回 ER-diagram 模式。

#### 预期

- 切回后所有节点无橙色描边残留。

### 2.7 Story 1 验收场景 7 —— 自引用节点高亮/清除

#### 步骤

1. 找一个含自引用关系的节点（如 `Tree`，如果 demo schema 含）。
2. 双击 `Tree`。
3. 单击其他节点。

#### 预期

- 自环高亮、清除路径同样不残留边框橙色。

### 2.8 Story 1 验收场景 8 / Story 2 验收场景 1 —— 长会话多次切换

#### 步骤

1. 连续切换 20 次以上节点，混合双击与单击（如 A → B → C → D → ... → A → B → ...）。
2. 截屏对比"刚加载完的画布"与"切换 20 次后的画布"（除当前选中节点外）。

#### 预期

- 画布视觉状态与刚加载时一致，无累积、无半褪色。
- 当前选中节点正确高亮（标题背景 + 外框）。

### 2.9 Story 2 验收场景 2 —— 刷新页面后画布干净

#### 步

1. 在 ER-diagram 模式下双击某节点触发高亮。
2. 刷新浏览器（F5 / Cmd+R）。

#### 预期

- 重新加载后画布无任何橙色描边残留。

### 2.10 Story 2 验收场景 3 —— 切换显示选项 toggle 无残留

#### 步骤

1. 双击节点 A 触发高亮。
2. 切换显示选项 toggle（如勾选 / 取消勾选 "Hide Reverse Relationships"、"Better Cluster Display"、"Brief Mode"）触发主图重渲染。

#### 预期

- 重渲染后无任何橙色描边残留（高亮状态随重渲染归零）。

---

## 3. 回归检查

### 3.1 现有交互行为不变

| 行为 | 预期 |
|------|------|
| 双击节点打开侧边栏 | 标题背景 + 外框 + 邻居 + 边都被正确高亮（橙色） |
| 单击节点切换选中 | shallow 高亮（含直接邻居）正确显示 |
| 关闭侧边栏 | 现有"是否清高亮"行为不变（本特性不强制改变） |
| 邻居高亮（dim 效果） | 非邻居节点 dim 显示正常、清除后还原正常 |
| 边的高亮（连线、箭头） | 不受影响 |
| Related Entities 子图（spec 005） | 子图渲染、跟随主图配置（spec 007 后）行为不变 |
| About / Fields / Source Code 各 tab（spec 006） | 不受影响 |

### 3.2 其他 toggle 不受影响

依次切换以下 toggle，确认各自行为不变：

- Show Module Cluster
- Better Cluster Display
- Brief Mode
- Show Methods
- Hide Reverse Relationships（spec 007）
- Pydantic Resolve Meta
- Edge Minlen

### 3.3 schema 切换、模式切换、刷新

依次执行，确认无回归：

- 切换 schema（主图重新加载）
- 切换 ER-diagram → voyager → ER-diagram
- 浏览器刷新

---

## 4. 失败排查

| 现象 | 可能原因 | 排查步骤 |
|------|---------|---------|
| 修复后仍有橙色描边残留 | 浏览器缓存了旧 JS 文件 | DevTools Network → Disable cache + 硬刷新（Cmd+Shift+R / Ctrl+Shift+R） |
| 修复后所有节点外框都消失 | `data-original-stroke` 写回空字符串、原 stroke 本就为空 | DevTools 检查从未高亮过的节点的 outerFrame.stroke，确认 Graphviz 输出是否真有 stroke 属性 |
| 双击节点不再有橙色高亮 | 修复意外破坏了 highlightSchemaBanner 写入路径 | 检查 highlightSchemaBanner 是否未被改动；检查 GraphUI.HIGHLIGHT_COLOR 常量 |
| 邻居高亮 / dim 效果消失 | gv.highlight() 调用被意外删除 | 确认 clearSchemaBanners 第一行 `if (this.gv) { this.gv.highlight() }` 仍存在 |
| Console 报错 `Cannot read property 'getAttribute' of null` | querySelector 选择器或 polygon 结构变化 | 检查 polygon[data-original-stroke] 选择器是否返回有效元素；查 Graphviz 输出格式是否变化 |

---

## 5. 验收场景覆盖矩阵

| spec 验收场景 | quickstart 步骤 | 验证方式 |
|--------------|----------------|---------|
| Story 1 - 场景 1（双击→单击切换） | 2.2 | 截屏 + DevTools 属性对比 |
| Story 1 - 场景 2（双击→双击切换） | 2.3 | 截屏 |
| Story 1 - 场景 3（单击→单击切换） | 2.4 | 截屏 |
| Story 1 - 场景 4（切换 schema） | 2.5 | 视觉检查 |
| Story 1 - 场景 5（切换 ER-diagram ↔ voyager） | 2.6 | 视觉检查 |
| Story 1 - 场景 6（关闭侧边栏） | 不强制（沿用现有行为） | 视觉检查 |
| Story 1 - 场景 7（自引用节点） | 2.7 | 视觉检查 |
| Story 1 - 场景 8（快速连续点击） | 2.8 | 视觉检查 |
| Story 2 - 场景 1（长会话不累积） | 2.8 | 截屏对比 |
| Story 2 - 场景 2（刷新后画布干净） | 2.9 | 视觉检查 |
| Story 2 - 场景 3（toggle 触发重渲染） | 2.10 | 视觉检查 |

---

## 6. 验证完成检查清单

- [ ] §2.2 双击→单击切换无残留（核心修复点）
- [ ] §2.3 双击→双击切换无残留
- [ ] §2.4 单击→单击切换无残留
- [ ] §2.5 切换 schema 无残留
- [ ] §2.6 切换 ER-diagram ↔ voyager 无残留
- [ ] §2.7 自引用节点高亮/清除正确
- [ ] §2.8 长会话 20+ 次切换无累积
- [ ] §2.9 刷新页面画布干净
- [ ] §2.10 切换显示选项 toggle 无残留
- [ ] §3.1 现有交互行为不变（无回归）
- [ ] §3.2 其他 toggle 不受影响
- [ ] §3.3 schema 切换、模式切换、刷新无回归

所有项打勾后，本期修复可交付。
