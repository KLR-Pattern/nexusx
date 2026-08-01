# 数据模型:nexusx 多服务联邦

**特性**:`specs/012-federation` | **日期**:2026-07-26 | **Spec**:[spec.md](./spec.md) | **Plan**:[plan.md](./plan.md)

本文描述联邦特性引入/扩展的核心数据结构(字段、关系、校验、状态流转)。实现细节(函数体)见后续 `tasks.md`;此处只钉**形状与契约**。

---

## 1. `RemoteRelationship`(新增,声明数据类)

表达一条跨服务关系(挂载方一侧的出边)。与既有 `Relationship` 并列于 `__relationships__`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `fk` | `str` | 源实体上用作 join key 的字段(如 `Product.id`),与 `Relationship.fk` 同名同义 |
| `target` | `RemoteRef \| list[RemoteRef]` | `RemoteService("srv").TypeName`;`list[...]` 表 to-many。内部归一为 `"<srv>.<typename>"` 标记字符串(FR-002),非 Python 类型 |
| `name` | `str` | 关系名,挂载方实体上的字段名,注册表 lookup key |
| `join_remote` | `str` | 被挂类型上对应的字段(如 `Review.product_id`),须有 `by_<join_remote>_in` root |
| `description` | `str \| None` | ER 图文档 |

`is_list` 不再是声明字段——由 `target` 是否包 `list[...]` 派生(`init=False`),与 `Relationship` 的 `target=list[X]` 约定一致。

**不变量**:不内联 loader(由框架组合时生成 RemoteLoader)。`target` 的 RemoteRef 必须可 parse 为恰好两段(`srv` + `typename`),否则 init 校验 fail-fast(FR-013a)。

**与既有 `Relationship` 的对齐与差异**:形状刻意贴近 `Relationship`——`fk`/`target`/`name` 同名同义,`list[...]` 表 to-many 约定一致;唯一结构性差异在加载槽——`Relationship` 内联 `loader`(本地 custom),`RemoteRelationship` 给 `join_remote` 字段名(远程,框架据此合成 RemoteLoader)。

---

## 2. `"<srv>.<typename>"` 规范名(概念,非类)

远程类型的**内部规范身份**,用于路由/校验/消歧/去环。

- 形式:`<service-name>.<bare-typename>`,如 `reviews.Review`。
- 仅存在于 `FederatedTypeRegistry` 与 `RelationshipInfo.target_service` + 物化类的逻辑身份中;**不进入** `__name__`、**不进入**对外 SDL(FR-014/FR-018)。
- 解析:`split(".")` → 校验恰两段 → `("srv","typename")`。

---

## 3. `RelationshipInfo`(扩展,既有数据类)

新增**可选**字段,使 executor 能区分本地/远程关系并路由。

| 新增字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `target_service` | `str | None` | `None` | 远程关系 = 归属服务前缀(如 `"reviews"`);本地关系 = `None`。executor 据此路由到 RemoteLoader(FR-009) |

其余字段(`name`/`direction`/`fk_field`/`target_entity`/`is_list`/`loader`/`page_loader`/...)不变。远程关系的 `loader` 字段在组合阶段被置为 `RemoteLoader` 实例,`target_entity` 被置为物化的远程类,`fk_field` = `fk`。

**向后兼容**:`target_service` 默认 `None`,既有本地关系构造路径不变。

---

## 4. `FederatedTypeRegistry`(新增模块)

维护"规范名 ↔ 物化类",负责两遍物化与跨远程引用解析。内部按**类对象**建键(不依赖 `__name__` 唯一性)。

**核心状态**:
- `qualified_to_class: dict[str, type]` —— `"srv.typename"` → 物化类
- `class_to_qualified: dict[type, str]` —— 反向
- `visited: set[str]` —— 传递式 ER 拉取的去环 visited-set(规范名)

**物化产物**:物化类由 `pydantic.create_model` 生成,`__name__` = 裸 `typename`;字段来自被挂服务的 ER 片段标量字段(FR-008)。

**状态流转(两遍物化,FR-007)**:
1. **pass1(拉取)**:从挂载方声明的所有 `RemoteRelationship.target` 出发,对每个未 visited 的规范名 → 拉取其 ER 片段 → 把片段中远程关系声明的目标规范名加入待拉取队列 → 标记 visited。遇自身或已 visited 即停(去环,R9)。
2. **pass2(物化)**:对全部已拉取规范名做拓扑排序(按片段内的跨远程引用)→ 逐个 `create_model` → 用"裸名→物化类" namespace 对每个类 `model_rebuild` 解开跨远程前向引用 → 注册进 `qualified_to_class`。
3. **注册**:对每个 `RemoteRelationship`,构造 `RelationshipInfo`(target_entity=物化类、target_service=srv、fk_field=fk、loader=RemoteLoader)注册进 `ErManager`;对物化类型自身的出边(片段内关系 + 在其上声明的远程出边)同样注册(FR-019)。

---

## 5. `RemoteLoader`(新增,DataLoader 工厂)

`aiodataloader.DataLoader` 子类工厂,把一组 join key + 嵌套选区转成**一条**对被挂服务 `/graphql` 的 gql 嵌套查询。

**输入(executor 经 side-channel 注入)**:
- `keys: list` —— 本层父实体的 `fk` 值集合
- `FieldSelection` —— 本关系的嵌套子树选区(由 executor 的 selection-aware 通道传入,FR-010)

**行为(FR-010/FR-011)**:
1. 构造 gql 文档:`{ <Typename> { by_<join_remote>_in(<keys>) { <选区标量> <嵌套远程子选区> } } }`,以被挂服务的 `by_<join_remote>_in` root 为入口。
2. 经 `httpx` POST 到被挂服务 `/graphql`(transport 可注入,便于测试)。
3. 解析 `{data, errors}`;按 `join_remote` 字段值分组对齐到 `keys` 位置契约(缺失→`None`(to-one)/`[]`(to-many))。
4. 反序列化进**物化远程类型**实例(`FederatedTypeRegistry` 提供),供上层 BFS/序列化。

**不变量**:每次 `batch_load_fn` 恰好发**一条** gql 查询(对被挂服务);被挂服务内部用自身 executor 解析整条嵌套子图(其 N+1-proof 保证)。

---

## 6. ER 片段(ER fragment,wire 数据)

成员经 ER 内省端点返回的结构化数据,是组合、校验与传递式发现的输入单位(FR-005)。序列化为 JSON(pydantic wire 类型,见 `contract.py`)。

**形状**:
```
ERIntrospectionResponse:
  service_name: str                       # 成员自声明 name(前缀)
  entities: list[EntityFragment]
    EntityFragment:
      typename: str                       # 裸类型名
      scalar_fields: list[FieldDescriptor]# 来自 model_fields(名 + 类型名)
      relationships: list[RelDescriptor]
        RelDescriptor:
          name: str
          direction: str                  # MANYTOONE|ONETOMANY|MANYTOMANY|CUSTOM|REMOTE
          fk_field: str
          target_typename: str            # 裸类型名(本服务内关系)或远程类型(见下)
          is_list: bool
          sort_field: str | None
          # 远程关系(REMOTE)额外:
          target_service: str | None      # 目标服务前缀
          target_endpoint: str | None     # 目标服务端点 URL(供挂载方传递式发现)
      batch_roots: list[str]              # 该类型暴露的 by_<key>_in root 字段名列表
```

**不变量**:`RelationshipInfo` 的 loader(代码对象)**不**序列化(非数据);远程关系必须携带 `target_service`+`target_endpoint` 以支持传递式发现(FR-005/R7)。wire 类型对齐既有 `RelationshipInfo` 字段语义,确保 round-trip 无损。

---

## 7. `by_<key>_in` root(生成,成员侧)

由 `AutoQueryConfig` 扩展策略生成的批量查询 root(FR-012/R6)。

**形状**(每个声明的 key 字段生成一个):
```
@query
async def by_<field>_in(cls, <field>_list: list[T]) -> list[Entity]:
    # select(cls).where(getattr(cls, <field>).in_(<field>_list))
```

**配置**:`AutoQueryConfig` 新增批量 key 策略(如 `batch_keys: dict[typename, list[fieldname]]` 或 `generate_by_keys`),成员按自身被挂载时用到的 join key 配置。

**与既有 `by_id`/`by_filter` 同构**:同模块、同 `session_factory` 注入模式;是单体 nexusx 也受益的通用批量取能力。

---

## 8. 校验规则(fail-fast,FR-013)

init 期对每条 `RemoteRelationship` 与挂载拓扑逐项校验,任一失败拒绝启动:

| 规则 | 校验对象 | 失败处置 |
|---|---|---|
| (a) 服务已注册 | `target` 的 `srv` ∈ 挂载 registry | 启动失败,指明未注册前缀 |
| (b) 类型存在 | `srv` 的 ER 片段含 `typename` | 启动失败,指明缺类型 |
| (c) join 字段存在且类型兼容 | 片段含 `join_remote` 字段,类型名与本地 `fk` 兼容 | 启动失败,指明缺字段或类型不匹配 |
| (d) 批量 root 存在 | 片段 `batch_roots` 含 `by_<join_remote>_in` | 启动失败,指明缺 root |
| (e) 前缀唯一 | 任意两个被挂服务 `service_name` 不重复 | 启动失败,列出冲突服务 |
| (f) 裸名不跨服务重复 | 任意两个不同服务不暴露同名 `typename` | 启动失败,指出跨服务裸名重复 |
| (g) 挂载图无不可终止环 | 传递式 ER 拉取的 visited-set 能终止 | 启动失败,指明成环路径 |

---

## 9. 关系图(数据流总览)

```
挂载方启动(lifespan):
  本地实体 + RemoteRelationship 声明
      │
      ▼  federate(services={srv→url})
  ER 内省端点 ←───── 被挂服务(每个 nexusx 服务)
      │  (传递式拉取,visited-set 去环)
      ▼
  校验 (a)–(g)  ──失败──▶ 启动失败(fail-fast)
      │  通过
      ▼
  FederatedTypeRegistry 两遍物化 → 物化远程类(裸名)+ RelationshipInfo(+target_service)
      │
      ▼  冻结 ErManager
  SDLGenerator/IntrospectionGenerator registry 化渲染 → 对外 schema(裸名,含远程字段)
      │
      ▼  客户端查询进入
  QueryExecutor BFS:遇 target_service≠None → RemoteLoader
      │
      ▼  一条 gql 嵌套查询
  被挂服务 /graphql → handler.execute → 自身 executor 解析组合子图 → {data}
      │
      ▼  按 join key 对齐 → 物化实例 → 上层 BFS 继续
  返回嵌套结果(对外无前缀)
```
