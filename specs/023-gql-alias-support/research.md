# Research: GraphQL Alias 支持（specs/023）

Phase 0 产出。Spec 无遗留 NEEDS CLARIFICATION（4 项决策已在 clarify 确认），本文记录实现层设计决策及其备选方案，全部结论来自对当前代码（6.1.2，commit 5d03777 之后）的直接验证。

## D1: `sub_fields` 的 key 语义——`alias or field_name`，查找一律走 `FieldSelection.name`

- **Decision**: 字典 key 即响应键（`alias or field_name`）；方法/字段解析查找一律用 `FieldSelection.name`（原始名）。
- **Rationale**: 最小传染——迭代式消费方（compose executor、build_model）改为 `sel.name` 查找即可，按 key 取响应的路径天然正确；dict 保序保证声明顺序（mutation 串行序）。
- **Alternatives**:
  - (a) `sub_fields` 改 `list[FieldSelection]`——语义最彻底，但所有 `.get(name)`/`.items()` 消费全变线性扫描或需重建索引，13 个测试文件大范围重写， rejected；
  - (b) 双 dict（by_name + by_key）——内存翻倍、两份结构一致性维护，仅省一次 `name` 属性访问，rejected。

## D2: 同层响应键冲突检测放 parser 层

- **Decision**: 在 `_parse_selection_set` 构建 dict 时检测重复 key，抛出带位置的错误（含别名重复、别名撞字段名、无别名同名字段重复三种形态，见 clarify Q2/Q4）。
- **Rationale**: fail earliest——两条执行路径（compose/entity-first）共享同一拦截点，错误在任何方法调用前产生。
- **Alternatives**: executor 层各自检测——两份实现、拦截时机更晚（部分方法可能已执行），rejected。

## D3: mutation 三态反馈的响应呈现

- **Decision**: 失败或被跳过的别名在 `data` 中对应键为 `null`；`errors` 条目带 `path`（定位到别名）与 `extensions.code` 区分三态：`MUTATION_FAILED`（该调用抛异常）/ `SKIPPED_PRIOR_FAILURE`（因前序失败未执行）。已成功的别名正常携带结果。
- **Rationale**: 贴 GraphQL 规范的 data/errors 分工（失败字段在 data 为 null），`extensions.code` 是生态惯用的机器可读标注，MCP agent 可据此精确重试。
- **Alternatives**: 失败键从 data 中整个省略——破坏"查询里出现过的键必在 data 中"的直觉契约，agent 无法区分"没执行"与"执行了但序列化丢键"，rejected。

## D4: entity-first 移除 `group_failed` 整组作废

- **Decision**: `_execute_entity_group` 的 `group_failed → return None` 机制改为逐字段收集（失败字段 null + errors 条目），与 compose 路径对齐（clarify Q1）。
- **Rationale**: FR-005 要求两路径一致；组级作废在批量场景抹掉已成功副作用，正是 Issue #140 报告的危险模式。
- **Alternatives**: 仅 compose 改、entity-first 保留组级 null——两路径行为分叉需永久文档化，且存量组级语义本是 v1 简化（docstring 自述），rejected。
- **回归风险**: 依赖整组 null 的既有测试需同步更新；串行执行顺序（DataLoader store-then-read 去重不变量）不受影响，仅错误粒度变化。

## D5: `validate_no_aliases` 的退场方式——保留原语义，仅移除库内调用

- **Decision**: 函数保留（仍拒绝 alias，供外部自定义防线使用），`handler.py:324` 的内部调用移除；docstring 更新为"可选的用户侧校验工具"。
- **Rationale**: 公共 API 不破坏（feedback 公约）；它的语义（检测并拒绝）本身没有过时，过时的只是"nexusx 自身不支持 alias"这一前提。
- **Alternatives**: 改为 no-op + deprecation——语义突变且无必要（外部用它的人仍想要拒绝行为），rejected。

## D6: federation 渲染出口剥 alias（边界闸门）

- **Decision**: `_render_selection`（`remote_loader.py:247`）改用 `child.name` 渲染字段名，不透传 dict key；`build_gql_query` 的其余部分不变。member 端零改动。
- **Rationale**: 渲染出口唯一（β `_RemoteLoader` / γ `_DtoRemoteLoader` / `_PaginatedRemoteLoader` 三类 loader 全走它）；spec FR-008 的 wire 边界在此一处置防。
- **Alternatives**: 在 parser 层为 federation 单独建一棵"剥 alias 的树"——多一份结构副本、两处维护，rejected（机造查询本就由 `child.name` 重建，天然无别名）。

## D7: 同方法同参数不去重（FR-011）

- **Decision**: mutation 逐个独立执行（禁执行级去重）；query 亦逐个独立调用，性能由数据层既有 DataLoader 批量/缓存提供（同 selection 同参数 → 同 type_key → 同实例 → key 缓存命中，同一节点只发一次 member 请求）。
- **Rationale**: 去重隐含方法纯度假设；graphql-core/Apollo 均不做字段级去重；"正确性在方法层、性能在数据层"分层清晰。
- **Alternatives**: request 级 memoization（按 (method, args) 缓存）——留作将来透明优化，不改契约，v1 不做。

## D8: 版本策略——minor 6.2.0

- **Decision**: 次版本递增 + changelog 显著条目（说明 key 语义变更与 entity-first 错误粒度变更）。
- **Rationale**: `sub_fields` 类型签名不变仅 key 含义变（语义 breaking），但存量不存在正确使用别名的代码（此前要么被拒要么被吞），实际兼容影响为零；entity-first 错误粒度变更是行为改进方向（null 组 → 精确三态）。
- **Alternatives**: major 7.0.0——过度保守，无真实破坏面，rejected（spec Assumptions 已确认）。

## 验证记录（决策依据的代码事实）

| 事实 | 位置 | 验证方式 |
|---|---|---|
| dict 覆盖根因 | `query_parser.py:121` | 静态阅读 + Issue #140 复现 |
| entity-first 放开后 N 次全执行、key 覆盖、投影串用 | `query_executor.py:183/207/268` | monkeypatch 实验（2026-08-30，CALL_LOG 证据） |
| 关系解析缓存实例级隔离 | `query_executor.py:57` `(id(entity), field)` | 静态阅读 |
| federation loader 按 selection/params 拆实例 | `remote_loader.py:100-111`（type_key + force_split）、`registry.py:728-766`（params_key） | 静态阅读，注释明言防并发竞争 |
| wire 纯读无 mutation | `remote_loader.py` 全文 grep | 零命中 |
| compose 无 alias 校验 | `compose_executor.py:107` | 静态阅读 + Issue 报告 |

## 实现期新增发现（D6 修正）

- **`FieldSelection.name` 在手工构建树上语义不统一**：`Resolver._build_nested_selection`（resolver.py:1352）把 `name` 用作**目标类型名**（如 `MTComment`），而 parser 生成的树上 `name` 是原始字段名。联邦渲染闸门最初无条件用 `child.name` 渲染，导致机造查询输出类型名、member 报 unknown field（deep_chain/materialized 两测试抓出）。**修正规则**（`_wire_render_name`）：仅 `alias is not None` 的节点用 `name` 渲染（parser 树保证其为原始字段名），无 alias 节点一律渲染 key——兼容手工树。
- **entity-first 的序列化走 `response_builder` 而非 `core_builder.build_model`**（评估阶段"response_builder dormant"的判断有误——它在 entity-first `_serialize` 路径上活跃）。嵌套别名检测因此落在 `_validate_method_selection`（执行前、有 path），`core_builder` 的检测作为 compose 投影路径的兜底。
- **query 失败隔离语义**：执行期异常（方法体抛错、参数 coerce 失败、FromContext 缺失）统一 per-field（键 null + `QUERY_FAILED`）；规划期错误（unknown service/method、enable_mutation、parse、键冲突）保持 fail-fast——贴 GraphQL 的 field error 语义，也是 5 个存量断言更新的依据。
