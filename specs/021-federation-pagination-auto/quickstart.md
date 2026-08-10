# Quickstart: 联邦分页自动化验证

## 前置

- 020 已 merge（entity dunder 声明：`__federation_keys__` + `__pagination_orders__`）
- 动机证据：`tests/test_federation_pagination_transitive.py`（A→B→C 穿透，`pagination=True` 通过 / `False` 崩溃）

## 验证场景

1. **β 联邦分页（member 有 page_by_）**：A→B，B 有 `__pagination_orders__` → A 查 `bs(limit:N) { items }` → top-N Result。**去 RemoteRelationship.pagination 后自动 work**。
2. **β 联邦无分页（member 无 page_by_）**：B 无 `__pagination_orders__` → A 查 `bs { ... }` → list。
3. **多层穿透（核心：不传递问题消失）**：A→B→C，B/C 有 `__pagination_orders__`，**B/C 的 RemoteRelationship 不写 pagination** → A 查 `bs(limit) { cs(limit) }` → 双层 top-N，**不崩**（对比 020 前 B→C pagination=False 崩）。
4. **无 limit 全量**：A 查 `bs { items }`（无 limit）→ 全量 Result{items:全部}。
5. **to-one 不受影响**：`author`（to-one）→ by_id_in，不分页。
6. **γ DTO 分页**：member DTO `federation_public` → mounter `Paged` → Resolver top-N（member 能力驱动）。

## 运行

```bash
# 迁移后（去 RemoteRelationship.pagination）全绿
uv run pytest tests/test_federation_pagination_transitive.py tests/test_federation_pagination_e2e.py -q
# 全量回归
uv run pytest -q
```

## 预期

- 所有 `RemoteRelationship(pagination=...)` 删除。
- member 有 `__pagination_orders__` → 联邦关系自动 Result（limit 可选）。
- 多层穿透自动分页（不传递问题消失）—— 这是本 feature 的核心验证点。
- 全量 1517+ passed 零回归。
