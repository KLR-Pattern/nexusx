# Data Model: GraphQL Alias 支持（specs/023）

Phase 1 产出。本 feature 无新增持久化实体；数据模型变更集中在**查询解析树的键语义**与**响应信封的错误结构**两处契约。

## 1. FieldSelection（既有结构，键语义变更）

```text
FieldSelection
├── name: str                # 查找键（不变）——方法/字段解析一律用它
├── alias: str | None        # 别名（不变，既有字段）
├── arguments: dict          # 参数（不变）
└── sub_fields: dict[str, FieldSelection]
                             # ⚠ 语义变更：key = alias or name（响应键）
                             #   旧语义：key = name（同名字段互相覆盖 → Issue #140 根因）
```

### 键的两种用途（本次变更的核心区分）

| 用途 | 用哪个 | 消费方示例 |
|---|---|---|
| **查找**（这个字段是什么/方法在哪） | `FieldSelection.name` | 方法表查找、DTO 字段解析、联邦渲染 |
| **响应组装**（结果挂在哪个键下） | `sub_fields` 的 dict key | `entity_data[key]`、`results[key]` |

### 同层响应键冲突检测（新增不变量）

`_parse_selection_set` 构建 `sub_fields` 时，同层出现重复 key 即抛错（三种形态等价处理）：

- `a: f` 出现两次（别名重复）
- `a: f` 与 `a: g`（别名撞其他字段名）
- `f { x }` 与 `f { y }`（无别名同名字段重复——不做字段合并，clarify Q2 决策）

顶层（operation 的 entity group / service 名）同名字段重复同族处理。

## 2. 响应信封（mutation 三态，entity-first 与 compose 统一）

```text
{
  "data": {
    "<Service|Entity>": {
      "<响应键>": <结果>        # 已成功：正常值
                                # 失败/跳过：null
    }
  },
  "errors": [
    {
      "message": "<人类可读>",
      "path": ["<Service|Entity>", "<响应键>"],
      "extensions": { "code": "<错误码>" }
    }
  ]
}
```

### 错误码（extensions.code）

| code | 含义 | 触发场景 |
|---|---|---|
| `ALIAS_CONFLICT` | 同层响应键重复 | parser 冲突检测（D2） |
| `MUTATION_FAILED` | 该调用自身抛异常 | mutation 串行执行中（FR-005） |
| `SKIPPED_PRIOR_FAILURE` | 因前序失败未执行 | fail-stop 跳过（FR-006） |
| `RESOLVER_ERROR` | 既有码，保留 | 查询解析器异常（沿用） |

### 不变量

- 查询中出现过的响应键，在 `data` 中必存在（成功为值，失败/跳过为 null）——D3 决策
- mutation 按声明顺序串行；首个 `MUTATION_FAILED` 之后的所有调用为 `SKIPPED_PRIOR_FAILURE`
- query 无 fail-stop：各别名独立成败（失败别名 null + 错误条目，成功别名正常返回）

## 3. 联邦 wire 契约（不变式，非新结构）

mounter 发往 member 的机造查询**永不含别名**——由渲染出口用 `FieldSelection.name` 重建保证（D6）。member 端数据结构零变更。

## 4. 状态迁移

无持久化状态迁移。行为状态变化仅一处：entity-first 方法异常的响应状态从「整组 → null」迁移为「失败字段 → null + errors、其余字段保留」（D4）。
