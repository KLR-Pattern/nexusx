# 契约:by_<key>_in 批量 root + AutoQueryConfig 扩展

**特性**:`specs/012-federation` | 对应 FR-012/R6

这是**成员侧**契约:为支持 RemoteLoader 的 gql 嵌套取数,成员须按被用到的 join key 暴露批量查询 root。与既有 `by_id`/`by_filter` 同构、同模块,是单体 nexusx 也受益的通用能力(非联邦专属耦合)。

## 生成的 root 形状

对声明的每个 key 字段,生成一个 `@query` 方法挂在实体上:

```python
@query
async def by_<field>_in(cls, <field>_list: list[T]) -> list[Entity]:
    """Batch-fetch entities where <field> in <field>_list."""
    # 语义:select(cls).where(getattr(cls, <field>).in_(<field>_list))
    # 返回 list[Entity](顺序不保证;调用方按 <field> 分组对齐)
```

例(`Review` 实体,被挂载时按 `product_id` 批量取):

```python
@query
async def by_product_id_in(cls, product_id_list: list[int]) -> list[Review]:
    ...
```

该 root 出现在成员的 SDL/`__schema` 内省与 ER 片段的 `batch_roots` 字段中(见 [er-introspection.md](./er-introspection.md))。

## AutoQueryConfig 扩展

`AutoQueryConfig`(纯 policy)新增批量 key 策略:

```python
class AutoQueryConfig:
    def __init__(
        self,
        default_limit: int = 10,
        generate_by_id: bool = True,
        generate_by_filter: bool = True,
        enabled: bool = True,
        # 新增:
        batch_keys: dict[str, list[str]] | None = None,   # {typename: [field, ...]}
    ): ...
```

成员按自身被挂载时用到的 join key 配置:

```python
cfg = AutoQueryConfig(
    batch_keys={"Review": ["product_id", "author_id"]},   # 生成 by_product_id_in / by_author_id_in
)
handler = GraphQLHandler(base=Base, session_factory=session, auto_query_config=cfg)
```

## 不变量

- 与 `by_id`/`by_filter` 同:`session_factory` 由容器(`GraphQLHandler`/`Application`)注入,config 不持有连接(沿用近期重构 `a1a8aa4` 的"config 纯 policy"原则)。
- key 字段必须是实体的真实标量列(校验);否则生成阶段报错。
- 返回 `list[Entity]`,**顺序不保证**;调用方(RemoteLoader)负责按 key 分组对齐(见 [gql-fetch.md](./gql-fetch.md) 响应对齐)。
- 既有 `by_id`/`by_filter` 行为零变化(纯新增生成路径)。

## 相关
- [gql-fetch.md](./gql-fetch.md):RemoteLoader 以本 root 为 gql 查询入口。
- spec FR-012;plan `standard_queries.py` 改动;research.md R6。
