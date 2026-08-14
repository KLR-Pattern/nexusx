# Implementation Plan: Voyager 的 ComposedErManager 分组与配色

**Branch**: `022-voyager-composed-clusters` | **Date**: 2026-08-14 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/022-voyager-composed-clusters/spec.md`

## Summary

ComposedErManager 组合多 engine 时，Voyager 的 ER 图与 UseCase 页按 member 分 cluster（标签 = member `service_name`），member 可在 `ErManager(color=...)` opt-in 声明颜色使 cluster 获得背景填充。技术路径是**复用 federation 已验证的 styling 管道**（节点 `module` 字段改写 + `module_color` 前缀匹配 + cluster dashed/rounded），唯一的新渲染能力是 cluster `fillcolor`。单体 ErManager 场景零变化（非 breaking）。补上 spec 019 research "Unknown 4" 的遗留。

## Technical Context

**Language/Version**: Python 3.10+（pyproject `requires-python >=3.10`）

**Primary Dependencies**: FastAPI（voyager ASGI 子应用）、SQLModel/pydantic（实体与 DTO）、jinja2（DOT 模板）。graphviz 仅作为 DOT 文本消费方，库自身不依赖 graphviz 二进制。

**Storage**: N/A（纯可视化特性，无持久化）

**Testing**: pytest（现有 1511 tests；ER 图断言直接检查 DOT 字符串，仿 `tests/test_federation_voyager.py` 的 opt-in 断言模式）

**Target Platform**: Linux/macOS/Windows（库，任何能跑 FastAPI 的环境）

**Project Type**: library

**Performance Goals**: ER 图生成走懒分析（请求时构建），member 分组为 O(entities) dict 查找，无可感知开销。

**Constraints**: 非 breaking（FR-008）；DOT 输出对既有消费方（voyager web 前端、测试断言）保持向后兼容——新增属性（fillcolor）不删改既有属性。

**Scale/Scope**: 触点 6 个源文件 + 1 模板 + demo + 双语文档；预计新增测试 ~10 个。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` 为未实例化的空模板，无具体 gate。沿用项目既有纪律自检：

- ✅ 库优先、公共 API 非 breaking（`color` 为新增可选参数，默认 None）
- ✅ 测试先行可行（DOT 字符串断言，无需图形渲染环境）
- ✅ 与 020/021 的"声明在 member、消费方读取"精神一致（color 声明在 ErManager，Voyager 读取）

## Project Structure

### Documentation (this feature)

```text
specs/022-voyager-composed-clusters/
├── plan.md              # 本文件
├── research.md          # Phase 0：unknown 决策记录
├── data-model.md        # Phase 1：member 分组映射结构
├── quickstart.md        # Phase 1：端到端验证指南
├── contracts/
│   └── voyager-member-styling.md  # Phase 1：ErManager color 参数 + _member_styling 内部协议
└── tasks.md             # Phase 2（/speckit-tasks 生成）
```

### Source Code (repository root)

```text
src/nexusx/
├── loader/
│   ├── registry.py        # ErManager.__init__ 加 color 参数（FR-001）
│   └── composed.py        # _member_styling 聚合 + service_name 重名校验（FR-002/FR-009）
├── voyager/
│   ├── er_diagram_dot.py  # ER 图节点归属优先级 + styling 合并（FR-003/FR-004/FR-007）
│   ├── use_case_voyager.py# UseCase 页 DTO 归属 + styling 合并（FR-005）
│   ├── voyager_context.py # _get_voyager 透传 member_styling
│   ├── render.py          # DiagramRenderer cluster fillcolor 支持（FR-004）
│   └── templates/dot/cluster.j2  # fillcolor/filled 模板扩展
demo/composed_er_manager/
├── app.py                 # blog_er/shop_er 加 service_name+color；挂 /voyager
tests/
└── test_composed_voyager.py  # 新增测试套件
docs/advanced/
├── composed_er_manager.md / .zh.md   # 双语补"Voyager 分组与配色"节
└── voyager.md / .zh.md               # 提及 member 分组
```

**Structure Decision**: 单项目布局（库 + demo + tests），无新顶层目录。

## Complexity Tracking

> 无 Constitution Check 违规，无需填。
