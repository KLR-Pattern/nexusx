# Quickstart 验证: Federation 配置正交化

验证新声明模型（entity `__federation_keys__` + `__pagination_orders__`）端到端跑通，行为与旧 `batch_keys`/`batch_pages` 等价。

## 前置

三层联邦 demo（`demo/federation/{catalog,reviews,users}_app.py`）已迁移到新声明模型：

- `reviews_app.py`：`Review` 用 `__federation_keys__ = ["product_id"]` + `__pagination_orders__`；删 `AutoQueryConfig(batch_keys=..., batch_pages=...)`。
- `catalog_app.py`：`ReviewDTO` 删 `federation_join_key`（自动推导）。
- `users_app.py`：同上（若有 batch 配置）。

## 验证场景（端到端）

1. 起 member + mounter（按序）：
   ```bash
   uv run uvicorn demo.federation.users_app:app --port 8020 &
   uv run uvicorn demo.federation.reviews_app:app --port 8021 &
   uv run uvicorn demo.federation.catalog_app:app --port 8022 &
   ```
2. catalog GraphiQL（http://localhost:8022/graphql）跑联邦查询：
   ```graphql
   { Product { by_filter {
     reviews(limit: 5) { items { title rating }
                         pagination { has_more total_count } }
   } } }
   ```
3. **期望**：reviews 按 `HIGHEST_RATING` 排序返回 top-5（order 来自 `Review.__pagination_orders__` 单一），分页 metadata 正确。行为与旧 `batch_pages` 配置**等价**。

## 回归锚点（SC-004）

- 三层联邦 demo 全部跑通（catalog→reviews→users 透明 fetch）
- member 用新声明（无 `batch_keys`/`batch_pages`）下，mounter 联邦行为零回归

## 自动化测试

```bash
# federation 分页 / DTO 联邦相关
uv run pytest tests/test_dto_paged_remote.py tests/test_dto_paged.py tests/test_paged_provider.py
# by_<key>_in / page_by_<key>_in 生成 + γ DTO join key 推导（新增测试）
uv run pytest tests/ -k "federation or paged or batch_root"
# 全量回归
uv run pytest -q
```

## 验证完成的标志

- [ ] demo 三层联邦在新声明模型下跑通，查询结果与旧模型一致
- [ ] `by_<key>_in` / `page_by_<key>_in` 从 entity `__federation_keys__` + `__pagination_orders__` 正确生成
- [ ] γ DTO join key 从源 entity 自动推导（单 key），`federation_join_key` 已删
- [ ] 全量测试零回归（基线 1517 passed）
