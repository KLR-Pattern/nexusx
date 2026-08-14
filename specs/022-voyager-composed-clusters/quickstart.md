# Quickstart — 022 Voyager Composed 分组与配色 验证指南

端到端验证本特性生效的三个场景：自动化测试（主路径）、demo 目测（视觉确认）、单体回归（非 breaking 确认）。

## 前置

```bash
uv sync --all-extras          # 依赖就绪（含 fastapi/uvicorn）
```

## 场景 1：自动化测试（P1/P2/P3/P4 全覆盖）

```bash
# 本特性新套件
uv run pytest tests/test_composed_voyager.py -v

# 相邻回归（federation styling 不变 + composed 核心不变）
uv run pytest tests/test_federation_voyager.py tests/test_composed_er_manager.py -v

# 全量
uv run pytest
```

**预期**：全部通过。新套件关键断言（对应 contracts/voyager-member-styling.md）：

| 断言 | 验证点 |
|---|---|
| `label = "blog"` / `label = "shop"` 两个 cluster 出现 | US1 分组 |
| 跨边界边两端的 cluster 不同 | US1 |
| `fillcolor = "#..."` 仅出现在有色 member 的 cluster | US2 opt-in |
| 无色 member 的 cluster 无 `fillcolor` | US2 |
| UseCase 页注册 DTO 落在 member cluster | US3 |
| 邻域子图保留两 cluster 及颜色 | US4 |
| 单体 ErManager 的 DOT 与改动前逐字一致 | FR-008 |
| 同 service_name 两 member 构造 `ValueError` | FR-009 |

## 场景 2：demo 目测（视觉确认）

```bash
uv run uvicorn demo.composed_er_manager.app:app --port 8030
```

打开 `http://localhost:8030/voyager/`：

1. **ER 图 tab**：blog 与 shop 实体各在一个带背景色的 cluster 中（service_name 为标签）；`CmUser → CmOrder` 跨 engine 边横跨两个 cluster
2. **Related Entities**：点选 `CmUser`，邻域子图仍显示两个 cluster
3. 若 demo 同时挂 UseCase 页：注册进 `dto_classes` 的 DTO 落在对应 member cluster

**预期视觉**：两个浅色背景块（如 blog 淡蓝、shop 淡橙），节点表头继承同色调；无色配置的 member（若有）为白底。

## 场景 3：单体回归（非 breaking）

```bash
uv run pytest tests/test_voyager_er_diagram_custom_scalar.py tests/test_voyager_subgraph.py tests/test_voyager_selfref.py tests/test_voyager_hide_reverse.py -v
```

**预期**：全部通过（单体场景输出未变）。

## 关键参考

- 分组映射结构：[data-model.md](data-model.md)
- API 契约与不变项：[contracts/voyager-member-styling.md](contracts/voyager-member-styling.md)
- 决策依据：[research.md](research.md)
