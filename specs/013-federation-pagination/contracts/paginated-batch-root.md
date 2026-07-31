# 契约:by_<key>_in_page 分页批量 root

**特性**:`specs/013-federation-pagination` | 对应 FR-003/FR-004/FR-005/FR-008,研究 [research.md R3/R5/R6](../research.md)

这是**成员侧契约**:为支持分页取数,成员默认为每个 batch key 额外生成分页 root `by_<key>_in_page`。与 012 的全量 `by_<key>_in` 同构、同模块,**零配置**(member 不需声明分页能力)。

## 双 root 默认生成

对配置了 `batch_keys` 的每个 key 字段,成员**默认同时**生成两个 root:

- `by_<key>_in(<key>_list)` —— 全量,返回 `list[Entity]`(012 既有,不变)。
- `by_<key>_in_page(<key>_list, limit, offset, sort_field)` —— 分页,返回 per-key 分页包(本期新增)。

由挂载方的 field 声明(`RemoteRelationship.sort_field` 有无)决定调哪个。

## 分页 root 形状

```python
@query
async def by_<field>_in_page(
    cls,
    <field>_list: list[T],
    limit: int,
    offset: int,
    sort_field: str,
) -> list[dict]:
    """Per-key 分页:对 <field>_list 中每个 key,返回 {fk, items, pagination}。"""
    # 窗口函数:ROW_NUMBER() OVER (PARTITION BY <field> ORDER BY <sort_field> <dir>)
    #          BETWEEN offset+1 AND offset+limit
    # has_more : peek-by-1(取 limit+1 行,有第 limit+1 行 → True)
    # total_count: COUNT(*) OVER(PARTITION BY <field>) —— 仅客户端 selection 请求时算
    # 返回:[{<field>: <key>, items: [Entity...], pagination: {has_more, total_count?}}, ...]
```

例(`Review` 按 `product_id` 分页):

```python
@query
async def by_product_id_in_page(
    cls, product_id_list: list[int], limit: int, offset: int, sort_field: str,
) -> list[dict]:
    ...
```

- 参数 `limit`/`offset`/`sort_field` 为 **batch 级标量**(同一批所有 key 共享,R5)。
- 返回 per-key 分页包列表,每包含 join key 值(供挂载方对齐)、分页后的 `items`、`pagination`。
- `items` 是 `Entity` 列表,其子树由 member executor 递归解析(FR-007/R4)。

## wire 返回(per-key 分页包)

```json
[
  {"product_id": 1, "items": [ {"id": 10, "title": "..."}, {"id": 11} ],
   "pagination": {"has_more": true, "total_count": 42}},
  {"product_id": 2, "items": [ {"id": 20} ],
   "pagination": {"has_more": false, "total_count": 1}}
]
```

- `total_count` 仅客户端在 `pagination { total_count }` 里 select 时存在(R6);否则 member 不算 COUNT,包里只含 `has_more`。

## ER 内省暴露

该分页 root 出现在 ER 片段的 `batch_roots` 中,带分页标记(`BatchRoot` 扩展):

```python
class BatchRoot(BaseModel):
    name: str                        # "by_product_id_in_page"
    arg_name: str                    # "product_id_list"
    arg_type: str                    # "list[int]"
    paginated: bool                  # 新增:True 标记分页 root
    sort_field: str | None = None    # 新增:默认排序字段
```

挂载方据此识别 member 支持分页,并校验 `RemoteRelationship.sort_field` 合法性。

## 不变量

- 与 `by_<key>_in` 同:`session_factory` 由容器注入;key 字段须为真实标量列(校验)。
- 分页 root 默认生成,不需 member 额外配置(R3)。
- 排序方向默认 ASC;`sort_field` 携带方向时 member `ORDER BY` 据此。
- 既有 `by_<key>_in`(全量)行为零变化(纯新增生成路径)。

## 相关

- [paginated-remote-relationship.md](./paginated-remote-relationship.md):挂载方声明触发调用本 root。
- [paginated-gql-fetch.md](./paginated-gql-fetch.md):分页 RemoteLoader 的 gql 构造与对齐。
- spec FR-003/FR-004/FR-005/FR-008;research.md R3/R5/R6;[data-model.md §3](../data-model.md)。
