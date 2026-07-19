# Specification Quality Checklist: 修复 Router 把嵌套 BaseModel 拍平成 dict 的 Bug

**Purpose**: 在进入 plan 阶段前，校验规格说明书的完整性与质量。
**Created**: 2026-07-19
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] 规格说明书未泄露实现细节（具体语言 / 框架 / API 设计）
- [x] 聚焦于用户价值与业务诉求
- [x] 可被非技术干系人理解
- [x] 所有 mandatory section 已填写

**注**：本特性是 bug 修复，"用户"是 nexusx 的开发者；FR-002 在描述修复手法时提到了 "去掉 `body.model_dump()`"——这一条是 issue #107 提出且用户明确要求的修复路径，属于规格层面的"约束"，而非实现细节泄露。如果后续 plan 阶段需要探索其他等价方案，可在 plan 阶段放宽此约束。

## Requirement Completeness

- [x] 规格说明书内不再残留 `[NEEDS CLARIFICATION]` 标记
- [x] 所有 Functional Requirement 可测、无歧义
- [x] Success Criteria 可度量
- [x] Success Criteria 未引入实现细节（无框架、语言、数据库、工具）
- [x] 所有验收场景已定义
- [x] 边缘情况（Edge Cases）已识别
- [x] 范围边界清晰（修复仅触及 router.py 的 handler 闭包，不触碰 schema 路径）
- [x] 依赖与假设已在 Assumptions 章节列出

## Feature Readiness

- [x] 所有 Functional Requirement 都有清晰的验收路径（在 User Story 的 Acceptance Scenarios 中可追溯）
- [x] User Story 覆盖主流程（嵌套 BaseModel 修复）+ 回归流程（标量 / FromContext / 默认值不变）+ 防御流程（schema 路径不变）
- [x] 本特性可达成 Success Criteria 中定义的可度量结果
- [x] 实现细节未泄露到规格中（除 FR-002 一处用户显式指定的修复约束）

## Notes

- 本特性的"用户"是 nexusx 库的开发者，因此 User Story 以开发者视角撰写，而非终端用户视角。
- `SUCCESS Criteria SC-004`（schema 输出二进制一致）是强约束，可在 plan 阶段通过"对一组 service 定义先 dump schema、修复后再 dump、diff 为空"的脚本化方式验证。
- 若 plan 阶段发现 FR-002（强制去掉 `model_dump()`）与某些 Pydantic 边角特性冲突，可在 plan 阶段提出替代实现（如 `TypeAdapter` 二次校验），但需在 plan.md 中显式记录权衡理由。
- 进入下一阶段建议先跑 `/speckit-clarify`（若仍有歧义）或直接 `/speckit-plan`。
