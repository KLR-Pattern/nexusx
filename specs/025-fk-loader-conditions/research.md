# Research: 025 FK 关系条件过滤

**日期**: 2026-09-30 | **状态**: 完成（全部决策由 PoC 实验与 clarify 会话的事实支撑，无遗留 unknown）

研究方式说明：本特性的全部技术问题在 spec/clarify 阶段已通过**可运行实验**验证（`/tmp/poc_pj_loader.py` 7 场景、`/tmp/poc_pj_edge_forms.py` 边界形态、`/tmp/poc_pj_behavior.py` 约束行为），而非纸面调研。本文按 Decision / Rationale / Alternatives 记录。

---

## D1: 提取算法——表达式树遍历（非平铺 iterate）

**Decision**: 遍历 `rel.primaryjoin`（M2M 为 `rel.secondaryjoin`，见 D4）的顶层子句：`and_` 的顶层子项逐项考察；每个子项若为"双列等值且匹配 FK 对"则跳过（D2），若为列-常量比较则收集，若为 `or_` / `not_` 等布尔组合则**整体**收集为单一条件。

**Rationale**: PoC 版用 `sqlalchemy.sql.visitors.iterate` 平铺遍历收集全部 `BinaryExpression`——实验（`poc_pj_edge_forms.py` 场景 c）证明这会把 `or_(a, b)` 拆成 a、b 两个独立条件，追加后变成 `AND a AND b`，**静默改写声明语义**（数据正确性事故）。clarify Q1 决策为整体保留。

**Alternatives considered**: ① 平铺 + 检测到 or_ 报错（被 clarify 否决——用户能合法声明的就该尊重）② 正则/字符串解析 primaryjoin（不可行——运行时是编译后的表达式树，不是字符串）③ 让 ORM 自己按 relationship 加载（架构级重写，放弃列裁剪/分页 ROW_NUMBER 既有机制，代价不可接受）。

## D2: FK 等值对的识别——local_remote_pairs 无序签名匹配

**Decision**: 用 `rel.local_remote_pairs`（M2M 用 `rel.secondary_synchronize_pairs`）构造 `(left.table.name, left.key, right.table.name, right.key)` 的双向签名集合；遍历中双列等值子项匹配签名即跳过。

**Rationale**: 实验确认（`poc_pj_behavior.py` 场景 E）：带额外条件的 primaryjoin 中 `local_remote_pairs` 仍只返回 FK 等值对（`{('id','owner_id')}`），常量条件不进 pairs——两者天然可区分。无需自己判断"哪侧是 FK"。

**Alternatives considered**: 用 `foreign_keys` 属性判断（不可靠——多 FK 歧义场景下语义复杂，且 pairs 匹配已充分）。

## D3: 引用列校验——按关系形态限定合法表集合

**Decision**: 提取完成后校验条件引用的全部列：O2M / M2O / O2M_SCALAR 合法集合 = `{target.__table__}`；M2M 合法集合 = `{target.__table__, secondary}`。引用集合外的列 → `ValueError`（含实体名/关系名/列名/支持范围说明）。

**Rationale**: loader 查询只 FROM 这些表（M2M 的 inner 查询 join secondary + target），引用其他表列的 SQL 无法执行——静默忽略等于条件形同虚设（FR-006 诚实失败）。`table is` 身份比较（不是 name 比较）——SQLModel 从 link_model mapper 取的 local_table 与 secondaryjoin 表达式中的是同一 Table 对象（实验确认）。

**Alternatives considered**: name 匹配（跨 schema 同名表会误判，弃用）。

## D4: M2M 的双 join 检查——secondaryjoin 提取 + primaryjoin 额外条件显式报错

**Decision**: M2M 从 `secondaryjoin`（secondary→target 侧）提取额外条件；**同时检查 `primaryjoin`**（source↔secondary 侧）——若其中存在 FK 等值对之外的额外条件（必然引用 source 列），同样启动期 `ValueError`。

**Rationale**: ⚠️ 这是 PoC 的一个**修正点**：PoC 只查 secondaryjoin、静默忽略 primaryjoin 侧的额外条件——违反 FR-006（不支持形态必须报错而非静默）。M2M loader 查询不 join source 表，primaryjoin 侧条件物理上不可执行，报错是唯一诚实行为。

**Alternatives considered**: 支持 primaryjoin 侧条件（需要 loader 查询额外 join source 表，破坏"按 FK 值批查"的 loader 模型，且 source 列对每行父实体值不同——无法作为静态 WHERE，语义上也不成立）。

## D5: 改动位置——registry.py 内聚，factories.py 零改动

**Decision**: 提取器 `_extract_extra_filters` 放 `loader/registry.py`，与 `_extract_sort_field` 等 helper 同层；`_inspect_relationships` 的 4 个分支（M2O / O2M_SCALAR / O2M / M2M）在调工厂处传 `filters=`。

**Rationale**: 5 个工厂的 `filters` 参数与 `_apply_filters` 管道**既存**（含分页 count fallback 的 `_apply_filters(count_q, filters)`，`factories.py:452/611`），PoC 证实传入即生效、分页 total_count 语义自动正确。提取器唯一调用方是关系扫描现场，无跨模块复用。

**Alternatives considered**: 提取器独立模块 `loader/conditions.py`（过度设计——单一调用方）；在 factories 层反射 rel（层次错位——工厂不知道关系上下文）。

## D6: viewonly 不强制、back_populates 兼容

**Decision**: 不要求、不校验 viewonly；文档建议声明（表达写入侧只读语义）。

**Rationale**: 实验（`poc_pj_behavior.py` A/B/C）：SQLAlchemy 2.0.50 对常量额外条件完全放行——无 viewonly 也无 warning；viewonly + back_populates 双向允许。nexusx 只走读路径，行为零差异（FR-007）。

## D7: 错误类型与报错风格

**Decision**: `ValueError`，信息含"实体名.关系名 + 被引用列 + 支持范围说明"。

**Rationale**: 与 ErManager 既有生成期校验同风格（如 `__pagination_orders__` 的 fail-fast、#154 非法 Literal 生成期抛错）。存量惯例，无新异常类型。

## D8: 列对象的判定与兼容

**Decision**: `isinstance(x, ColumnClause)` 判定"是列"（含 `AnnotatedColumn`——其动态类多继承原类，实验 repr 与 isinstance 均确认）；常量侧为 BindParameter（enum 值、None、bool 均实验确认可提取）。

**Rationale**: 直接可用，无兼容性问题。

## D9: SQLModel 声明面坑清单（文档/quickstart 必须覆盖）

**Decision**: 以下为 SQLAlchemy/SQLModel 原生约束（非本特性引入），进用户文档：

1. `link_model` 必须传 SQLModel link **类**——传原生 `Table` 对象会在 SQLModel 类构造时 `bool(Table)` 触发 ClauseElement `__bool__` raise（`TypeError`）。
2. 注解用 `Optional["X"]`——`"X | None"` 字符串注解 + `sa_relationship_kwargs` 组合在 mapper 解析时失败（`InvalidRequestError: 'X | None' failed to locate`）。
3. primaryjoin **字符串形式**的 eval 命名空间只有实体类注册表：enum 类、Table 对象不可见 → enum 值条件、引用 secondary 表列的 secondaryjoin 必须用 **lambda** 形式声明（实验确认 lambda 可用）。
4. 类名含下划线（如 `Comment_and`）在字符串声明解析时被 registry 分词拆散（`'Comment' failed to locate`）——业务实体命名实践中罕见，遇到时同样以 lambda 规避。

**Rationale**: 全部为实验复现的原生行为；写进文档可避免用户踩坑后归因于 nexusx。

## D10: 提取出的表达式对象跨查询复用安全性

**Decision**: 提取条件直接作为列表传给工厂闭包捕获，多处 stmt `.where(*filters)` 复用同一表达式对象。

**Rationale**: SQLAlchemy 表达式不可变、跨语句复用是文档支持的模式（PoC 7 场景在同一进程内多 loader/多批次调用无异常）。BindParameter 自动命名在单语句内无冲突（每条 loader 语句只引用一次同一条件）。

## D11: 测试策略

**Decision**: 新增 `tests/test_loader_conditions.py`，走 **ErManager 真实路径**（构造 ErManager → 取 `RelationshipInfo.loader/page_loader` → 断言加载结果），不 mock 提取器；提取器边界（报错形态）用独立用例直接调 `_extract_extra_filters` 断言异常信息。矩阵：4 US 场景 × {O2M, M2O, O2M_SCALAR, M2M(目标列), M2M(link 列), 分页 O2M, 分页 M2M} × {eq, IS NULL, or_ 组合, enum} + 3 个非法形态报错 + 存量零变化对照。

**Rationale**: PoC 已验证"真实路径可测"（`poc_pj_loader.py` 即此模式）；FakeTransport/单元 mock 会掩盖路径问题（历史教训：page_by 分桶类型 gap 正是被单元 mock 掩盖）。全量回归（1751 基线）作为 FR-005 证据。

---

## 附：PoC 与最终实现的差异清单（实现阶段注意）

| # | PoC 行为 | 最终实现 | 依据 |
|---|----------|----------|------|
| 1 | 平铺 iterate 收集 BinaryExpression | 表达式树：and_ 顶层拆分、or_/not_ 整体保留 | D1（or_ 语义破坏实验） |
| 2 | M2M 静默忽略 primaryjoin 侧额外条件 | primaryjoin 侧存在额外条件 → 启动期报错 | D4（FR-006 诚实失败） |
| 3 | M2M 校验仅 target 表 | 合法集合 = target + secondary（link 表列支持） | clarify Q3-B |
| 4 | 未覆盖 or_/IS NULL/enum 提取 | 全部纳入支持与测试矩阵 | poc_pj_edge_forms.py |
