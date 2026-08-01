# Phase 0 研究:nexusx 多服务联邦

**特性**:`specs/012-federation` | **日期**:2026-07-26 | **Spec**:[spec.md](./spec.md)

本文件记录把 spec 落到实现前需要核实/决策的技术点。每条以 **Decision / Rationale / Alternatives** 呈现。所有 NEEDS CLARIFICATION 已在 spec 阶段收敛(零待澄清);本文是**集成点核实 + 实现路径选型**。

---

## R1. IntrospectionGenerator 与 SDLGenerator 同病,FR-017 须覆盖两条路径

**核实**:`src/nexusx/introspection.py::IntrospectionGenerator._build_entity_type`(L221)对标量走 `entity.model_fields`、对关系字段走 `get_type_hints(entity)` + `_is_entity_relationship(hint)`(L238/272)。这与 `sdl_generator._generate_type` 完全同构——**都不读 `__relationships__`/注册表**。且两者构造期都接收固定的 `entities=` 列表(`handler.py` L91/L108 传入 `self.entities`),不迭代 `get_all_entities()`。

**Decision**:FR-017"schema 生成 registry 驱动"必须**同时改造 `SDLGenerator._generate_type` 与 `IntrospectionGenerator._build_entity_type`**:关系字段来源从 `get_type_hints` 改为 `loader_registry.get_relationships(entity)`(含 `RemoteRelationship`),并让两者覆盖 `get_all_entities()`(含 virtual/物化远程类型)。

**Rationale**:SDL 与 `__schema` 内省是两条独立代码路径,但同源同病。GraphiQL 客户端常用 `__schema` 内省而非裸 SDL,只改 SDL 会让 GraphiQL 看不到远程字段。spec US5/SC-007 已要求两者一致。

**Alternatives**:只改 SDL,内省暂不动——被否,GraphiQL 不可用,违反 US5。让物化远程类型"伪装"成带类型注解的类让 `get_type_hints` 拾取——被否,物化类型是 `create_model` 动态生成,强行注入注解比直接读注册表更脆。

---

## R2. 物化的远程类型必须进入 SDL/Introspection 的实体列表

**核实**:`GraphQLHandler.__init__` 用 `EntityDiscovery(base).discover(...)` 得到 `self.entities`,再把这同一个**固定列表**传给 `SDLGenerator`、`IntrospectionGenerator`、`QueryExecutor`。`ErManager` 内部虽按类对象建键、能容纳 virtual 实体(`add_virtual_entities`),但 SDL/Introspection 不会自动包含它们。

**Decision**:联邦物化的远程类型在物化后 MUST 被加入 SDL/Introspection 所依据的实体集合。落地方式:让 `SDLGenerator`/`IntrospectionGenerator` 在 `generate()` 时以 `loader_registry.get_all_entities()` 为实体来源(而非构造期 `entities=`),或在联邦 init 完成后把物化类型 append 进 `handler.entities` 并重建两个 generator。

**Rationale**:`get_all_entities()` 已统一返回 SQLModel + virtual 实体(`registry.py` L494),以此为单一来源最一致。优先选"generate 时读 get_all_entities()",改动局部、与 R1 同批。

**Alternatives**:要求用户手动把远程类型加进 `entities`——被否,联邦是框架自动物化,不应暴露给用户。

---

## R3. 引入 HTTP 客户端,放可选 extra `[federation]`

**核实**:`pyproject.toml` 无 `httpx`/`aiohttp`/`httpcore`/`requests`。RemoteLoader 需向被挂服务的 `/graphql` 发 async POST。

**Decision**:引入 `httpx`(async、FastAPI 生态标配),放入新的可选 extra `nexusx[federation]`。未启用联邦的用户不被迫安装。`er.federate(...)` 在未装 httpx 时给出明确 ImportError 提示。

**Rationale**:httpx 是 async、支持 HTTP/1.1&2、与 Starlette/FastAPI 同生态、API 稳定。可选 extra 符合 nexusx 现有做法(`[fastmcp]`、`[chat]`)。

**Alternatives**:`aiohttp`——被否,生态贴合度不如 httpx,且多一个依赖族。stdlib `urllib`——被否,无原生 async、用法笨重。把 HTTP 调用做成可注入的 transport 接口(用户自带 client)——作为后续可扩展点保留,但 MVP 用 httpx 兜底。

---

## R4. 联邦 init 是 async,必须放在启动阶段(不能进 `GraphQLHandler.__init__`)

**核实**:`GraphQLHandler.__init__` 同步且急切:discovery → `add_standard_queries` → `ErManager(...)` → `SDLGenerator(...)` → `IntrospectionGenerator(...)` → `QueryExecutor(...)`,全在构造期完成。联邦需要 async HTTP 拉取 ER 片段 + 物化 + 校验,无法塞进同步 `__init__`。

**Decision**:联邦物化在 **async 启动阶段**完成。两种可行接法,推荐第一种:
1. **Application/lifespan 级编排**(推荐):在 FastAPI lifespan(或 Application 启动钩子)里——先发现本地实体 → `await er.federate(services=...)` 物化远程 → 再构造/重建 `GraphQLHandler` 的 SDL/Introspection/Executor,使其含物化类型。把 `GraphQLHandler` 的 schema-generator 构造做成可在 federate 后(重新)触发。
2. `GraphQLHandler` 增加 async `federate()` 方法,内部物化后重建 SDL/Introspection generator。

**Rationale**:联邦是部署期组合(启动时拉一次、冻结),天然属于 lifespan,而非每请求。方案 1 把组合知识集中在启动编排,handler 保持"给定实体集就构建 schema"的纯度。spec FR-006 要求物化在冻结前完成——lifespan 正好。

**Alternatives**:把 federate 做成 sync(用 `httpx.Client` 阻塞)——被否,阻塞 event loop、与 nexusx 全 async 矛盾。运行时懒加载——被否,spec FR-006 明确排除。

---

## R5. RemoteLoader 的取数契约 = 标准 GraphQL-over-HTTP

**核实**:`GraphQLHandler.execute(query: str, variables, operation_name) -> {data, errors}`(handler.py L169)是程序入口。`get_graphiql_html(endpoint="/graphql")` 表明存在 `/graphql` POST 端点的约定。

**Decision**:RemoteLoader 向被挂服务的 `/graphql`(或配置的端点)发 `POST {query, variables}`,body 是它从 `FieldSelection` 构造的 gql 嵌套文档(以 `by_<key>_in` 为入口、携带收集到的 join key),解析 `{data, errors}` 响应,按 join key 分组对齐到 DataLoader 位置契约。被挂服务侧只需把 `handler.execute` 暴露成 `/graphql` POST 路由(若 Application 尚未提供,作为本期小补充)。

**Rationale**:标准 GraphQL-over-HTTP,零自创协议;被挂服务用**自己的** `QueryExecutor` 解析整条嵌套子树(其 N+1-proof 批量身份),挂载方只在服务边界拼接。这是 spec 决定 6 的实现。

**Alternatives**:自定义批量 JSON 端点——被否,spec 已定 gql 嵌套取数。让 RemoteLoader 直接调用被挂服务的 Python API(进程内)——仅同进程场景可用,不通用,作为后续 in-process 优化保留。

---

## R6. `by_<key>_in` root 生成:扩展 AutoQueryConfig

**核实**:`src/nexusx/standard_queries.py` 现有 `_create_by_id_query`(单值 pk)、`_create_by_filter_query`(单值相等)。`AutoQueryConfig` 是纯 policy(`default_limit`/`generate_*`/`enabled`)。

**Decision**:为 `AutoQueryConfig` 增加"按指定字段生成批量 root"的策略(如 `generate_by_keys: dict[typename, list[fieldname]]` 或更通用的 `batch_keys`),生成 `_create_by_keys_in_query`——语义 `select(cls).where(getattr(cls, field).in_(values))`,返回 `list[entity]`。成员按自身被挂载时用到的 join key 配置生成。

**Rationale**:与现有 `by_id`/`by_filter` 同构、同模块、同 session_factory 注入模式;是单体 nexusx 也受益的通用能力(批量按字段取),非联邦专属耦合(spec FR-015)。

**Alternatives**:让成员作者手写 `@query by_product_id_in`——被否,重复劳动、易漏。生成通用 `_entities(representations)` 端点——被否,自创协议、偏离 gql root 复用。

---

## R7. ER 内省端点:序列化 `get_all_entities()` + `get_all_relationships()`

**核实**:`ErManager.get_all_entities()`(L494)返回 SQLModel+virtual 实体;`get_all_relationships()`(L498)返回 `{entity: {rel_name: RelationshipInfo}}`。`RelationshipInfo` 含 `name/direction/fk_field/target_entity/is_list/sort_field/...`。Voyager 的 `ErDiagramDotBuilder.analysis()` 已消费这两者。

**Decision**:新增成员侧 ER 内省端点,序列化每个实体(标量字段来自 `model_fields`)+ 其 `RelationshipInfo` 列表;**远程关系**(target_service != None)额外携带 `target_service` 与该服务的端点,使挂载方能传递式发现(FR-005)。loader 类对象(callable)不序列化(它是代码、非数据)。复用 `RelationshipInfo` 的字段形状作为 wire schema。

**Rationale**:与 Voyager/executor 同源(spec 决定 1),不引入 SDL 第二套真相;`fk_field`/`direction`/`is_list` 直接可得,join key 确定可校验。

**Alternatives**:序列化 Voyager 的 `SchemaNode`/`Link`——被否,`Link` 把 `fk_field` 丢了(spec 已论证)。序列化 SDL——被否,有损投影。

---

## R8. RemoteLoader 的 gql 文档构造与响应解析

**核实**:`QueryExecutor._build_field_jobs` 按 `get_relationship` 取 `RelationshipInfo`,收集 `fk_values = [getattr(p, rel_info.fk_field) for p in parents]`,调 `loader.load_many(fk_values)`。现有 `create_one_to_many_loader` 做 `where(in_)` 后按 key 分组对齐。

**Decision**:`RemoteLoader` 是一个 `aiodataloader.DataLoader`,其 `batch_load_fn(keys)`:
1. 从 executor 注入的 `FieldSelection`(经 `_query_meta` 同款 side-channel 或新增 selection-aware 通道)构造 gql 文档:`{ <Typename> { by_<join_remote>_in(<Typename>_keys: [<keys>]) { <scalars...> <nested remote sub-selections> } } }`;
2. POST 到被挂服务 `/graphql`;
3. 解析 `data`,按 `join_remote` 字段值分组对齐到 `keys`(缺失→`None`/`[]`);
4. 把响应反序列化进**物化的远程类型**实例(`FederatedTypeRegistry` 提供),供上层 BFS/序列化使用。

**Rationale**:复用现有 DataLoader + BFS 编排;RemoteLoader 只替换"批量取的实现"(SQL→HTTP)。物化类型实例让后续 `_serialize_item`/`get_relationships` 走既有路径。

**Alternatives**:让挂载方 executor 直接持有被挂服务的子图解析(flat 逐层)——被否,spec 决定 6 已否定(网络层 N+1)。

---

## R9. 传递式 ER 拉取的去环

**核实**:相对组合下挂载图可能成环(A 挂 B、B 挂 A)。

**Decision**:挂载方传递式拉取 ER 片段时维护 visited-set(键为规范名 `srv.typename`),遇已访问或"自身"即停止;成员构建自身 ER 片段时也以自身 name 为界,不无限外扩。校验阶段若检出"挂载图成环且无可终止路径"则 fail-fast(spec FR-013g、US3 场景 6)。

**Rationale**:每个类型规范名含服务前缀,自身可识别;visited-set 是标准去环手段。

**Alternatives**:禁止任何环(A 挂 B 时 B 不得挂 A)——过严,合理的相互引用被误杀。本期允许环但要求可终止(visited-set 保证),仅对不可终止的 pathological 情况 fail-fast。

---

## 研究结论

九条核实全部落地为具体实现路径,无阻塞性未知。两项列为 plan 头号技术风险:
- **FR-017 schema 生成 registry 化**(R1+R2,触 SDL+Introspection 两条路径 + 实体来源)— 相对现有代码最大的非平凡改动。
- **R4 联邦 async init 与 `GraphQLHandler` 同步构造的 reconcile**— 决定 federate 的挂载时机与 handler 重建方式。

其余(R3 httpx、R5 取数契约、R6 by_<key>_in、R7 ER 端点、R8 RemoteLoader、R9 去环)为常规新增,路径明确。
