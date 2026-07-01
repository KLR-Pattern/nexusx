# Quickstart：Voyager About Tab & 侧边栏宽度放宽 端到端验证

**功能**：[spec.md](./spec.md) · **计划**：[plan.md](./plan.md) · **契约**：[contracts/](./contracts/)

> 本文件是**验证手册**，不是实现指南。具体代码改动见 `tasks.md`（由 `/speckit-tasks` 产出）。

---

## 0. 前置条件

- Python ≥ 3.10、`uv` 已安装
- 现代 Chromium 系浏览器（Chrome / Edge / Brave）或 Firefox；mermaid 在 IE 上不支持（nexusx 也不支持 IE）
- 视窗宽度 ≥ 1280px 的桌面环境（用于 Story 3 的拖拽验证；移动端不在本期范围）
- 工作目录在 `/home/tangkikodo/nexusx/`（nexusx 仓库根）

---

## 1. 准备 demo 数据（给至少一个实体加 docstring）

`demo/enterprise_voyager/models.py` 现有 38 个实体类，**目前都没有 docstring**——为了让 About tab 有内容可渲染，先给 `Employee` 加一段含 mermaid 的 docstring：

```python
class Employee(SQLModel, table=True):
    """员工实体。

    表示系统中的一个**在职**或**离职**员工。一个员工从属于一个 `Department`，
    并通过 `Team` 关联到具体的协作小组。

    ## 状态机

    以下状态机描述了员工的生命周期：

    ```mermaid
    stateDiagram-v2
        [*] --> Onboarding
        Onboarding --> Active: 完成入职
        Active --> OnLeave: 请假
        OnLeave --> Active: 假期结束
        Active --> Offboarding: 提交离职
        Offboarding --> [*]: 完成离职
        OnLeave --> Offboarding: 假期中离职
    ```

    ## 字段说明

    | 字段 | 类型 | 说明 |
    |------|------|------|
    | `full_name` | `str` | 全名 |
    | `department_id` | `int` | 所属部门 |

    注意：本实体的 [审计日志](#) 由独立的 `AuditLog` 实体维护。
    """
    id: int | None = Field(default=None, primary_key=True)
    full_name: str
    # ...其余字段保持原样
```

> 提示：上面这段 docstring 故意覆盖了**标题 / 段落 / 加粗 / 行内代码 / 围栏代码块（mermaid + 表格）/ 表格 / 链接**——对应 FR-003 的所有元素；同时 mermaid 块用于验证 FR-004；最后的 `[审计日志](#)` 链接用于验证 FR-017（应可点击但不导航实体）。

---

## 2. 启动 voyager

```bash
uv run uvicorn demo.enterprise_voyager.voyager_demo:app --port 8010
```

浏览器打开：<http://localhost:8010/voyager>

预期：看到 ER-diagram 默认 tab；30+ 个实体节点可见。

---

## 3. 验证路径

### 路径 A —— Story 1：Markdown 渲染（P1）

1. 在 ER 图上**双击** `Employee` 节点 → 侧边栏打开，默认在 Fields tab。
2. 点击最左的 **About** tab → 应在 ~100ms 内看到：
   - 一级标题"员工实体。"（H1 字号最大）
   - 段落正文，加粗的"在职"/"离职"
   - 二级标题"状态机"、"字段说明"
   - 一个表格（字段 / 类型 / 说明 三列）
   - 行内代码（`Department`、`Team`、`full_name` 等）以等宽字体背景色显示
   - 末尾"审计日志"是一个可点击样式的链接（鼠标悬浮显示手指光标）
3. **通过判据**：内容与 `Employee.__doc__` 字面一致；排版层级清晰；没有原始 Markdown 标记（如 `##`、`**`、`` ` ``）泄露到屏幕上。

### 路径 B —— Story 2：Mermaid 图渲染（P2）

1. 紧接路径 A，**滚动** About tab 内容到"状态机"小节。
2. 应看到一张**可视化状态图**：7 个状态节点（`[*]`、`Onboarding`、`Active`、`OnLeave`、`Offboarding`）+ 6 条带标签的转移箭头（"完成入职"、"请假"等）。
3. **不是**原始的 `stateDiagram-v2 ...` 源码。
4. 表格、段落等其它元素保持正常渲染（不被 mermaid 干扰）。
5. **通过判据**：节点不重叠到不可读；转移标签可见；整张图视觉一致。

### 路径 C —— Mermaid 错误降级（FR-010）

1. 编辑 `Employee.__doc__`，把 `stateDiagram-v2` 改成 `stateDiagram-v2` 但引入一处语法错误（例如删掉某个 `-->` 的尖括号、或加一行 `Active ->` 不写目标）：
   ```python
   Active -> Offboarding: 提交离职   # 故意用单箭头 -> 触发语法错
   ```
2. 重启服务（uvicorn 不会自动热重载 docstring；Ctrl+C 后重新 `uv run uvicorn ...`），刷新浏览器。
3. 重新打开 `Employee` 的 About tab → 应看到：
   - 一段红色或灰色错误提示，类似"该 Mermaid 图渲染失败：..."
   - 下面有一个折叠的"查看源码"小三角，点击后**展开**显示原始 mermaid 源码（可复制到 <https://mermaid.live> 调试）
   - docstring 的其它部分（标题、表格、链接）**仍正常渲染**
4. **通过判据**：单块 mermaid 失败不污染其它内容；折叠默认收起；错误信息明确（不是空白、不是页面崩溃）。

### 路径 D —— 空 docstring / 错误状态（FR-005、FR-006、FR-007）

1. **空 docstring**：双击任意一个**没有** docstring 的实体（例如 `Organization`，默认就空）→ 切到 About tab → 应看到"该实体暂无 docstring。"文案，**不是**空白。
2. **错误状态**：在浏览器 DevTools 的 Network 面板，把 `/docstring` 请求改为"Block request domain"再切换实体 → 应看到红色错误文案（不是空白、不是"加载中"假象）。
3. **加载指示**：在 DevTools 给 `/docstring` 加 "Slow 3G" 节流 → 切换实体 → 应在内容上方看到一条 indeterminate 进度条。
4. **通过判据**：三态（空/错/加载）视觉可区分。

### 路径 E —— Story 3：侧边栏宽度放宽（P2）

1. 把浏览器视窗拉到 **1920px 宽**（或用 DevTools 设备工具栏精确设定）。
2. 双击 `Employee` 打开侧边栏 → 默认宽度 ~300px。
3. **按住**侧边栏左边缘的拖拽手柄向左拖 → 应能拖到 **~1280px** 宽（=`floor(1920 × 2/3)`），不再被旧的 800px 上限卡住。
4. 拖到极限后，About tab 中的表格、Mermaid 图应能完整展示，**无需横向滚动**。
5. **向右**拖回 → 应能拖到下限 ~300px，不能更小。
6. **视窗缩放 clamp**：把视窗从 1920px 缩到 **1200px** → 侧边栏宽度应自动从 1280px 收缩到 ~800px（=`floor(1200 × 2/3)`），不会出现"侧边栏比画布还宽"的破损布局。
7. **通过判据**：上限跟随视窗动态变化；下限稳定；resize 后布局完整。

### 路径 F —— 切换实体保留激活 tab（FR-008）

1. 当前在 `Employee` 的 About tab。
2. 在画布上**单击**（注意：侧边栏已打开，单击即可触发）另一个实体 `Department`。
3. **通过判据**：
   - 侧边栏停留在 About tab（不会跳回 Fields）
   - About tab 内容刷新为 `Department` 的 docstring（如果 Department 也没有 docstring，则显示空状态文案）
   - 主画布高亮切换到 `Department` 的相关实体

### 路径 G —— 链接不导航实体（FR-017）

1. 回到 `Employee` 的 About tab，滚到底部的 `[审计日志](#)` 链接。
2. 点击该链接。
3. **通过判据**：
   - 不触发对 `AuditLog` 实体的跳转
   - 主画布选中状态仍是 `Employee`
   - 侧边栏仍是 `Employee` 的 About tab
   - 由于 href 是 `#`，浏览器可能在 URL 末尾加 `#`——这是可接受的

---

## 4. 后端单测（可选但推荐）

```bash
uv run pytest tests/test_voyager_docstring.py -v
```

预期：5 条用例全绿（happy path / 空 docstring / 非法 schema_name / module not found / class not found），详见 [contracts/docstring-endpoint.md](./contracts/docstring-endpoint.md) §测试覆盖。

---

## 5. 故障排查

| 现象 | 可能原因 | 处理 |
|------|---------|------|
| About tab 不显示 | `showAbout` prop 未传 true | 检查 `index.html` 中 `<schema-code-display :show-about="store.state.mode === 'er-diagram'">` 是否生效 |
| Markdown 渲染但 mermaid 不渲染 | `mermaid.initialize` 未调用 / `startOnLoad` 未关 | 看浏览器 console，应有 mermaid 的告警；确认 `vue-main.js` 中 `mermaid.initialize({ startOnLoad: false, theme: 'default' })` 已执行 |
| 整个 About tab 空白 + console 报 XSS | DOMPurify 配置过严，剥离了 mermaid 需要的属性 | 在 `DOMPurify.sanitize` 配置 `ADD_ATTR: ['class','target','rel','href']` |
| 拖拽仍卡在 800px | 浏览器缓存了旧 `vue-main.js` | DevTools → Application → Service Workers → Unregister；或硬刷新（Ctrl+Shift+R） |
| 视窗缩放后侧边栏比画布还宽 | resize 监听未挂载 | 检查 `vue-main.js` 是否新增了 `window.addEventListener('resize', onWindowResize)`；确认 `onWindowResize` 内只压缩不扩展 |
| docstring 显示原始 `__doc__`，缩进很怪 | 后端做了 `inspect.cleandoc` 或前端 marked 未配置 | 后端**不**做 cleandoc；前端依赖 marked 默认行为；若仍异常，前端在 parse 前 `docstring.replace(/^\s+/gm, '')` 试验性修复 |

---

## 6. 通过判据汇总

如果上述路径 A–G 全部通过、后端单测全绿，则本功能视为**端到端验证完成**，可进入 `/speckit-tasks` 拆分实现任务，或直接交付实现。
