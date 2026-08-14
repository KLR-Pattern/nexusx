# Contract — ErManager color 参数与 _member_styling 内部协议

本特性对外暴露 1 个公共 API 变化 + 1 个内部协议；DOT 输出新增 1 个可选属性。

## 1. 公共 API：`ErManager.__init__` 新增 `color`（非 breaking）

```python
ErManager(
    session_factory=...,
    entities=[...],          # 或 base=...
    service_name="blog",     # 既有参数（federation 用），本特性复用为可视化分组名
    color="#E3F2FD",         # 新增：opt-in 可视化颜色，默认 None
)
```

契约要点：

- `color` 为合法 graphviz 颜色字符串（推荐 `#RRGGBB` 浅色）；库不做值校验
- `color` 仅在 Composed 场景经组合体消费；**单体 ErManager 设 color 无任何效果**（不分组、不配色、图输出不变）
- `color` 依赖 `service_name` 生效：设 color 未设 service_name 时 color 被静默忽略，不报错
- `color` 不影响任何查询/加载/分页行为（纯元信息）

## 2. 公共行为：`ComposedErManager` 的 service_name 查重

```python
# 两个 member 设了相同 service_name 时：
ComposedErManager(members=[er_a, er_b])  # er_a/er_b 均 service_name="blog"
# → ValueError: Member service_name 'blog' is used by multiple members; ...
```

构造期 fail-fast（FR-009）。仅查**设了 service_name** 的 member；全部未设名则合法（回落现状分组）。

## 3. 内部协议：`_member_styling`（voyager 消费面探测用）

与 `_fed_registry` 同风格的 duck-typing 协议（非公开 API，面向库内 voyager 消费面）：

```python
# ComposedErManager 上：
@property
def _member_styling(self) -> dict[type, tuple[str, str | None]]:
    """key: member 实体类或 dto_classes 中的 DTO 类
    value: (service_name, color)；仅含设了 service_name 的 member。"""

# 消费面统一探测（单体 ErManager 无此属性 → None → 回落现状）：
styling = getattr(er_manager, "_member_styling", None)
```

消费契约（两个消费面 `er_diagram_dot.py` / `use_case_voyager.py` 一致遵守）：

1. **归属优先级**：`_fed_registry.qualified_of(cls)` 命中 > `_member_styling` 命中 > `cls.__module__`
2. **styling 合并**：`module_color = {**member_colors, **fed_colors, **user_module_color}`（user 最高）
3. member cluster 不进 `federated_modules`（不 dashed）

## 4. DOT 输出契约：cluster 新增可选 `fillcolor`

```dot
// 有颜色的 cluster（member 或 federation service）：
subgraph cluster_module_blog {
    style="rounded,filled"          // federation 远端为 "rounded,dashed,filled"
    pencolor = "#E3F2FD"
    fillcolor = "#E3F2FD"
    ...
}
// 无颜色的 cluster：不输出 fillcolor，style 不含 filled（现状不变）
```

向后兼容：仅新增属性；既有消费方（voyager web 前端 graphviz 渲染、测试断言）不受影响。

## 5. 明确不变项（回归基线）

- 单体 ErManager 的 ER 图 / UseCase 页 DOT 输出与改动前**语义一致**（SC-004）。**已记录的偏离**：实现中顺带修正了 `cluster.j2` 的既有挤行 bug（`trim_blocks` 使 `pencolor` 与后续语句挤在同一行）——属性行现为规范的一行一属性，属空白规范化，节点/边/cluster/颜色均不变
- `ErDiagram.to_mermaid()`（mermaid 路径）不在范围内
- `RemoteService(color=...)` 的 federation 语义不变（本特性使其从"仅边框"升级为"边框+背景"，声明面无变化；DOT 断言相应从 `rounded,dashed` 更新为 `rounded,dashed,filled`）
- Route 节点（UseCaseService 方法）恒按 Python module 分组
