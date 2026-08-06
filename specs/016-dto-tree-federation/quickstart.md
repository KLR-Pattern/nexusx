# Quickstart: DTO federation（UseCase 层）

> 验证场景，证明 γ 路径能组合 member public DTO。实现细节见 `tasks.md`（由 `/speckit-tasks` 生成）。

## 前置

- nexusx 5.1.0+（015 本地分页 order/direction）
- member 有 UseCase Resolver + DefineSubset 能力

## 场景 1: member public DTO 自包含 + mounter γ 组合（核心）

**member（reviews）**:

```python
class ReviewDTO(DefineSubset):
    __subset__ = SubsetConfig(
        source=Review,
        fields=("title", "rating", "product_id"),
        federation_public=True,
        federation_join_key="product_id",
    )
    total_after_discount: float | None = None
    def resolve_total_after_discount(self, loader=Loader("discount")):
        return loader.load(self.product_id)
```

**mounter（catalog）UseCaseService**:

```python
class ProductDTO(DefineSubset):
    __subset__ = (Product, ("id", "name"))
    reviews: list[reviews.ReviewDTO] = Field(default_factory=list)
    def resolve_reviews(self, loader=Loader("reviews")):
        return loader.load(self.id)
```

**查询**:

```bash
curl -X POST http://catalog:8022/api/catalog_service/composed_tree -d '{}'
```

**期望**: 返回 ProductDTO 树，reviews 是 reviews.ReviewDTO（含 member 算的 `total_after_discount`，不是裸实体字段）。

## 场景 2: mounter 二次 resolve（member 值只读）

mounter DefineSubset ReviewDTO + resolve_* 加 tax（基于 member 的 total）:

```python
class CatalogReviewDTO(DefineSubset):
    __subset__ = (reviews.ReviewDTO, ("title", "total_after_discount"))
    tax: float | None = None
    def resolve_tax(self):
        return self.total_after_discount * 0.1
```

**期望**: `tax` 是 catalog 算的，`total_after_discount` 是 reviews 算的（不覆盖）。

## 场景 3: member DTO 自包含（跨 service）

member ReviewDTO 含跨 service 出边（`.author → users.UserDTO`）。member 挂载 users，Resolver 加工时解析。mounter 拿到的 ReviewDTO 树 author 已解析（自包含）。

## 场景 4: β 路径不受影响（零回归）

β 路径（GraphQL 直查实体）行为不变——`{ Product { by_filter { reviews { title } } } }` 仍组合实体（Review），不碰 DTO。既有 federation 测试零回归。

## 验证命令

```bash
# 新增(本特性)
uv run pytest tests/test_dto_federation_e2e.py tests/test_dto_federation_introspect.py -v

# 回归(β 不受影响 + 012-014 + 5.0.1)
uv run pytest tests/test_federation_e2e.py tests/test_federation_pagination_e2e.py tests/test_federation_nested_local_pagination.py -q
```
