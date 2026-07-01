# 契约：侧边栏宽度 clamp 逻辑

**功能**：[spec.md](../spec.md) · **数据模型**：[data-model.md](../data-model.md) §4.3 · **公式决策**：[research.md](../research.md) 决策 5

**位置**：`src/nexusx/voyager/web/vue-main.js`（修改 `startDragDrawer` + 新增 resize 监听）

---

## 现状（修改前）

```js
// vue-main.js:263-285
function startDragDrawer(e) {
  const startX = e.clientX
  const startWidth = store.state.rightDrawer.width

  function onMouseMove(moveEvent) {
    const deltaX = startX - moveEvent.clientX
    const newWidth = Math.max(300, Math.min(800, startWidth + deltaX))  // ← 800 是死上限
    store.state.rightDrawer.width = newWidth
  }
  // ... mouseup cleanup
}
```

问题：上限固定 800px，在 1920px+ 视窗上仍偏窄（spec Story 3 痛点）。

---

## 修改后

### 1. 抽取常量与上限函数（文件顶部 setup 内）

```js
const RIGHT_DRAWER_MIN = 300
const rightDrawerMax = () => Math.floor(window.innerWidth * 2 / 3)
```

- **MIN 维持 300**（spec 假设 + Session：拖拽下限不动）。
- **MAX 是函数**，每次调用时从 `window.innerWidth` 实时取——避免缓存导致视窗缩放后值陈旧。

### 2. 拖拽 clamp（`startDragDrawer` 内）

```js
function onMouseMove(moveEvent) {
  const deltaX = startX - moveEvent.clientX
  const newWidth = Math.max(
    RIGHT_DRAWER_MIN,
    Math.min(rightDrawerMax(), startWidth + deltaX)
  )
  store.state.rightDrawer.width = newWidth
}
```

### 3. 视窗 resize 时的 clamp（新增 watch 或事件监听）

在 `setup()` 内（与其它事件监听并列）：

```js
function onWindowResize() {
  const max = rightDrawerMax()
  if (store.state.rightDrawer.width > max) {
    store.state.rightDrawer.width = max
  }
  // 注意：不主动把 width 撑到 max——只在超出时压回，避免"视窗变大时侧边栏自动变宽"的怪异行为
}

window.addEventListener('resize', onWindowResize)

// 在组件 onUnmounted 中清理：
//   window.removeEventListener('resize', onWindowResize)
```

### 4. 侧边栏首次打开时的 clamp

`store.state.rightDrawer.width` 初值是 `300`（spec 假设 + 现有 store 默认）；如果未来引入 localStorage 持久化，hydrate 时必须：

```js
// 在 store 初始化或 app mount 后：
store.state.rightDrawer.width = Math.min(
  store.state.rightDrawer.width,
  rightDrawerMax()
)
```

本期 store 没有 localStorage 持久化（`store.js` 未引入持久层），因此这一步**当前不需要**——但留作未来兼容点。

---

## 行为契约

### 拖拽时（FR-013、FR-014）

| 输入 | 输出 width |
|------|-----------|
| `startWidth + deltaX` 在 `[300, floor(W×2/3)]` 内 | 取该值 |
| `startWidth + deltaX` < 300 | `300` |
| `startWidth + deltaX` > `floor(W×2/3)` | `floor(W×2/3)` |

### 视窗 resize 时（FR-015）

| 触发 | 当前 width | 操作 |
|------|-----------|------|
| resize → 新 `floor(W×2/3)` 仍 ≥ 当前 width | 任意 | **不动** |
| resize → 新 `floor(W×2/3)` < 当前 width | 任意 | 把 width 压到新的 `floor(W×2/3)` |

**关键不变量**：resize 监听**只在 width 超出时压缩**，从不在 width 内于上限内主动扩展——否则"用户拖到 600 后视窗变大，侧边栏自动跳到 800"会非常怪异。

### 不变行为（FR-016）

- 默认初始 width 维持 `300`（store.js 现状，不改）。
- 折叠/展开（`rightDrawer.drawer`）逻辑不改。
- 侧边栏内容渲染、tabs 切换、所有非宽度相关交互不改。

---

## 验收映射

| spec 验收场景 | 本契约对应行为 |
|--------------|---------------|
| Story 3 #1（不超过 `floor(W×2/3)`） | §拖拽 clamp 表第 3 行 |
| Story 3 #2（1920px → ~1280px） | `floor(1920 × 2/3) = 1280`，自然成立 |
| Story 3 #3（下限不破坏可用性） | `RIGHT_DRAWER_MIN = 300` 不动 |
| Story 3 #4（视窗缩小时自动 clamp） | §视窗 resize 时第 2 行 |
| Story 3 #5（刷新后 clamp） | §侧边栏首次打开时的 clamp（未来兼容点） |
| Story 3 #6（不主动拖拽时行为不变） | §不变行为 |
