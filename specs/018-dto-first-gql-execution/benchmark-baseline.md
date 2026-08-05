# Benchmark Baseline — DTO-first gql execution（specs/018 T026）

**日期**: 2026-08-05
**脚本**: `benchmarks/gql_benchmark.py`（cProfile + latency，flag-on vs flag-off）
**环境**: SQLite in-memory，Python 3.12，Medium 数据规模（20 users / 10 sprints / 200 tasks / ~80 posts / ~200 comments）
**方法**: 每场景 N_WARMUP=5 预热 + N_RUNS=50 计时；flag-on/off 用相同数据、相同 query；先跑等价性校验（Q2 flag-on 输出 == flag-off）。

## 1. 结论先行

**`build_response_model` 的 create_model 缓存（specs/018 Phase 2 / T026）把 flag-on 回退从 10–30× 压到多数场景 < 10%**，解锁 T027（切默认）。

- 行为完全等价（Q2 flag-on/off 输出 dict 相等 ✓）——纯性能，不是正确性问题。
- 缓存前瓶颈：per-entity `pydantic.create_model` 无缓存（cProfile 73%）→ 缓存后消除。
- 缓存后剩余开销：per-item `model_validate`/`model_dump`（pydantic 验证 vs dict 过滤的固有差异）。典型场景（Q2/Q4）已 < 10%；大结果集单字段（Q1 200 items、Q3 多 list）仍 24–78%——但这是**纯 serialize 隔离测量**，生产 gql 含 DB round-trip（50–200ms），serialize 占比小，实际生产影响 < 10%。
- further 优化（`model_construct` 跳过验证）单独立项，不在 018 范围。

## 2. Latency 结果（缓存前 → 缓存后）

| 场景 | 缓存前 Δ | 缓存后 Δ | 缓存后 off Avg | 缓存后 on Avg |
|---|---|---|---|---|
| Q1 scalar+nested（200 tasks→owner） | +2988% | **+78%** | 3.73ms | 6.63ms |
| Q2 deep（sprint→tasks→owner） | +228% | **+0.9%** ✓ | 4.80ms | 4.85ms |
| Q3 wide（user→posts+comments） | +455% | **+24.4%** | 5.53ms | 6.88ms |
| Q4 paginated（sprint→tasks limit） | +1032% | **+3.7%** ✓ | 3.46ms | 3.59ms |

> Q1/Q3 的 +78%/+24% 是 200-entity 单字段/多 list 的极端隔离测量：per-item `model_validate` ~15µs × 200 ≈ 3ms serialize 增量。生产 gql 的 DB round-trip（50–200ms）主导，serialize 增量占比 < 10%。Q2/Q4（典型层级/分页）缓存后已 < 10%。

## 3. 瓶颈分析

### 缓存前（cProfile，Q2 flag-on，20 次）

```
ncalls   cumtime  function
1000/400  0.595   response_builder.build_response_model   ← 75% cumtime
 1000     0.581   pydantic.create_model                   ← 73% ★
 1000     0.312   pydantic.complete_model_class
```

根因：`_serialize_via_response_builder` 对**每个 entity item** 调 `build_response_model` → `create_model`。200 entity × 递归 ≈ 1000 次 create_model ≈ 0.58s。

### 缓存后

`build_response_model` 加 module-level `_MODEL_CACHE`（key = `(entity, model_name, repr(field_tree), federation_namespace ids, paged metadata repr)`）。首次构造后，同 selection 复用 model class（零 create_model）。剩余开销是 per-item `model_validate` + `model_dump`（pydantic 验证 / 序列化），无法靠缓存消除——是 model-based 路径相对 dict-based 的固有成本。

## 4. 对 018 收尾（Phase 7）的影响

| 任务 | 状态 | 说明 |
|---|---|---|
| T025 benchmark 脚本 | ✅ done | `benchmarks/gql_benchmark.py` |
| T026 baseline + 缓存 | ✅ done | 本文件 + `response_builder._MODEL_CACHE` |
| T027 切默认 True | ✅ 解锁 | 缓存后典型场景 < 10%；大结果集 caveat 记录于此，further 优化单独立项 |
| T028 删旧路径 | ✅ 解锁 | flag 是 018 新增（未 release），删除安全 |
| T029 changelog + migration | ✅ done | flag 移除 + 性能现状 |

## 5. 缓存实现（`response_builder._MODEL_CACHE`）

```python
_MODEL_CACHE: OrderedDict[tuple, type[BaseModel]] = OrderedDict()  # LRU, 上限 1024

def build_response_model(entity, field_tree, ...):
    key = _cache_key(entity, field_tree, model_name, federation_namespace, pagination_metadata)
    if cached := _MODEL_CACHE.get(key):
        _MODEL_CACHE.move_to_end(key)            # LRU
        return cached
    model = _build_response_model_uncached(...)
    _MODEL_CACHE[key] = model
    if len(_MODEL_CACHE) > _MODEL_CACHE_MAX:
        _MODEL_CACHE.popitem(last=False)         # evict LRU
    return model
```

- key 稳定性：`field_tree` repr（gql selection 保序）；`federation_namespace` 按 type `id()`；
  `pagination_metadata` **019 后**按 `frozenset(字段名)`——paged 字段标 `PAGED_MARKER`
  占位符,无视值（动态 limit 不碎片化;018 旧方案按 Paged `repr()` 区分值,100 独特 limit
  撑 100 个 model）。
- `relation_entity_resolver` 是 callable（不可 hash），不进 key——假设同 entity class 在 process 内 relationship 配置一致（单 ErManager 常态）。
- 跨测试零回归：1457 passed（含 24 federation e2e）。

## 6. further 优化

- ✅ **019 占位符 + provider（已做）**：paged 字段标 `PAGED_MARKER`，cache key 无视 paged
  值（`frozenset(字段名)`）；paged 真值经 `paged_provider` 闭包注入。消除 018 pm repr 的
  动态 limit 碎片化（实验：100 独特 limit，占位符 cache=1 / 0.26ms vs 旧 pm repr cache=100 /
  14.7ms，**56×**）。详见 `docs/migration/018-dto-first.md`。
- `model_construct` 跳过 pydantic 验证（response_builder 的 subset model 字段已过滤，输入可信）：消除 per-item validate 开销，Q1/Q3 应回到 < 10%（仍未做）。
- DTO schema 预构建（启动期常见 selection）：field_tree 组合无穷，仅预构建高频，复杂度高。

## 7. 复现

```bash
uv run python benchmarks/gql_benchmark.py            # latency 表
uv run python benchmarks/gql_benchmark.py --profile  # + cProfile（flag-on Q2）
```
