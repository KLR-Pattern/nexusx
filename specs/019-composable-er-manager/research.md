# Research: 可组合 ErManager（specs/019）

> Phase 0 产出。解决 spec clarify 阶段 Deferred 的实现决策 + 记录 spike 验证要点与已知坑。每条给出 Decision / Rationale / Alternatives。

## 概述：spike 验证基线

`spike_composed_er.py`（分支上）已实证「同进程多 engine 组合」成立：
- 两个 SQLite engine（blog/shop）+ 两个自洽 ErManager + 一条跨库 `Relationship`
- `ComposedErManager` 按 entity 委托，`create_resolver()` 产出总代理 Resolver
- 一次 `resolve()` 跨 engine + 二级钻取全通（4 断言绿）
- `ErDiagram.from_er_manager(composed)` 直接画出 4 实体 + 跨库边（ER 图层 0 改动）

spike 用「源实体 `__relationships__`」声明跨边界关系（A 方式）；产品化改为「组合体层集中声明」（B 方式，DD-02）——本 research 的 Unknown 1 即此改动的实现细节。

---

## Unknown 1：跨边界 loader 如何获得目标 engine 的 session

**背景**：B 方式下，跨边界关系在 `ComposedErManager` 构造时集中传入。其 loader 需要访问目标 engine 的 session_factory。

**Decision**：**用户闭包**。跨边界 `Relationship.loader` 是用户提供的 async batch 函数，在构造组合体时用户已持有目标子 member 的 session_factory，闭包捕获即可。组合体不注入 session、不扩展 `Relationship` 签名。

```python
shop_sf = async_sessionmaker(shop_engine, ...)
async def orders_by_user_id(user_ids):
    async with shop_sf() as s:
        ...  # 用 shop session

composed = ComposedErManager(
    members=[blog_er, shop_er],
    cross_relationships=[
        Relationship(fk="id", target=list[Order], name="orders", loader=orders_by_user_id),
    ],
)
```

**Rationale**：
- 最简单，复用现有 `Relationship.loader` 纯函数语义，零 API 改动（符合公共 API 不 breaking）
- spike 已用此方式验证
- 用户构造组合体时本就持有各子 member（及其 session_factory），闭包自然

**Alternatives**：
- *声明式注入*（扩展 `Relationship` 加 `session_factory=` 参数，组合体注入）：显式但扩大 API 面，且与「loader 是纯函数」语义冲突。**拒绝**。
- *路由式*（loader 只声明目标 member + join key，组合体自动查）：限制只能等值 join，不能自定义 loader 逻辑。**拒绝**。

---

## Unknown 2：ComposedErManager 的 engine 所有权 / dispose

**背景**：`Application` 有 `owns_engine` / `dispose()` 语义（`url=` 自造则拥有并 dispose，外部 engine 不拥有）。ComposedErManager 是否 own 子 member 的 engine？

**Decision**：**不 own**。ComposedErManager 不持有/释放 engine。engine 生命周期由各子 member（及其来源——Application 或用户）各自管理。组合体无 `dispose()`。

**Rationale**：
- 组合体是查询代理 + 叠加层，不拥有资源（与 FR-013「不实现管理接口」一致）
- 对齐 `Application` 的所有权判定：外部传入的 engine/session_factory 不拥有。组合体的子 member 都是外部传入的，组合体不追加所有权
- 避免双重 dispose（子 member 自己 dispose + 组合体 dispose）

**Alternatives**：
- *聚合 dispose*（组合体 dispose 调所有子 member 的 dispose/aclose_federation）： tempting 但越权——子 member 可能被别处共享，组合体不该替它们释放。**拒绝**。若用户希望统一释放，自己遍历子 member 调 dispose。

---

## Unknown 3：LoaderRegistry Protocol 抽象时机

**背景**：DD-03 决定把 Resolver 依赖的「查询接口」抽为正式 Protocol。落阶段 1 还是 2？

**Decision**：**阶段 1 就抽**。`LoaderRegistry` Protocol 与 `ComposedErManager` 同文件（`loader/composed.py`），作为组合体实现的契约。`ErManager` 天然满足（它的查询方法是 Protocol 的超集）。

**Rationale**：
- 组合体阶段 1 就要实现这些方法，Protocol 正好把它们显式列出（不会漏，见 spike 小清单 9 个访问点）
- `LoaderRegistry = ErManager` 已是 internal 别名（未 public 导出），升级为 Protocol 属 internal 改动，对外不可见
- 让阶段 2 的 GraphQLHandler 注入有正式类型可用（`er_manager: LoaderRegistry`）

**Alternatives**：
- *阶段 2 才抽*：推迟会让阶段 1 的 ComposedErManager 缺少正式契约，靠鸭子类型易漏方法。**拒绝**。

**Protocol 方法集**（来自 resolver.py 访问面盘点）：
`has_entity` / `get_relationships` / `get_relationship` / `get_loader_for_entity` / `get_loader_by_name` / `get_loader` / `get_dto_loader` / `clear_cache` / `create_resolver`，外加属性 `_split_mode` / `_fed_registry`（resolver 读取）。ER 图额外用 `get_all_entities` / `get_all_relationships`。

---

## Unknown 4：ER 图跨 engine 分簇标注

**背景**：spec「中长期演进」提了跨 engine 实体按 engine/app 分框上色（复用 federation 的 `module_color`/`federated_modules`）。

**Decision**：**阶段 1 不做分簇，留作可选增强**。阶段 1 保证跨 engine 实体 + 跨库边正确出现在一张图（spike 已证）。分簇标注作为后续可选任务，复用 federation styling 机制。

**Rationale**：
- 分簇是可视化增强，不影响功能正确性
- 阶段 1 聚焦核心组合能力（resolve + 图合并），避免范围膨胀
- federation styling 机制（`_federation_styling` + `module_color`）现成，后续接入成本低

**Alternatives**：
- *阶段 1 就做*：扩大范围，且跨 engine 分簇的语义（按 member 名？按 engine 方言？）需额外设计。**推迟**。

---

## Unknown 5：Application ↔ ComposedErManager 集成（阶段 2）

**背景**：`Application` 是 entity-first 路径的用户入口（1 app = 1 base + 1 engine）。阶段 2 让 GraphQLHandler 能注入 ComposedErManager 后，Application 层怎么暴露？

**Decision**：**阶段 2 提供 `Application(er_manager=composed, entities=[合并集])` 注入路径**，与 `GraphQLHandler` 注入对齐。现有 `base=` + `url/engine/session_factory` 路径保留（非 breaking）。

**Rationale**：
- Application 是用户最常接触的 API，组合能力要到这一层才易用
- 与 GraphQLHandler 注入分支对称（Application 内部把 er_manager 透传给 handler）

**Alternatives**：
- *新写 ComposedApplication*：重复 Application 大量逻辑。**拒绝**，注入路径更轻。
- *阶段 1 就做*：Application 是 entity-first 入口，属阶段 2 范畴。**推迟到阶段 2**。

**注**：UseCase 路径（阶段 1）不经过 Application/GQLHandler，直接 `composed.create_resolver()` 即可，所以阶段 1 不需要 Application 集成。

---

## Unknown 6：federation 叠加的状态聚合（_fed_registry / member 暴露）

**背景**：spec FR-017 + US5 要求 federation 与 ComposedErManager 正交可叠加。子 member 各自 federate 后，组合体要正确转发/聚合 federation 状态，否则 ER 图 styling、remote type 判断、member 端 introspection 会缺失。

**Decision**：
- **`_fed_registry` 聚合**：ComposedErManager 不返回 None（spike 临时做法），而是提供一个**只读聚合视图**——`qualified_of(cls)` / `all_classes()` / `service_colors()` 遍历子 member 的 `_fed_registry` 合并。实现为一个轻量 wrapper 委托各子 member 的 fed_registry。
- **member 端暴露聚合**：ComposedErManager 作 federation member 时，`service_name`（组合体级统一值）+ `get_all_entities` + `get_public_dtos` + `get_dto_classes`（后两者聚合所有子 member）+ `_expose_mounted_endpoints` 须正确反映组合体全貌。
- **federate/initialize 不在组合体上**（FR-013/FR-017）：在子 member 上触发。

**Rationale**：
- federation 物化的 remote type 进子 member 的 `_registry`/`_fed_registry`，组合体通过委托 + 聚合即可看到，无需自己物化
- member 端 introspection（`introspect.py`）只读上述字段，聚合后正确暴露

**Alternatives**：
- *组合体自己 federate*：违反 FR-013，且物化无处可写（组合体无 `_registry`）。**拒绝**。
- *_fed_registry 返回 None*：federation 感知缺失（ER 图 styling / remote type 判断错）。**拒绝**（spike 临时做法，产品化改正）。

**待验证**（US5 矩阵 C）：聚合视图在多 member 各自 federate 不同远程 service 时正确。

---

## spike 已知坑（实现注意）

### 坑 1：`from __future__ import annotations` + SQLModel Relationship 不兼容

spike 第一版顶部用 `from __future__ import annotations`，导致 `posts: list["Post"]` 注解被 SQLModel 当成 relationship 字符串参数解析失败（`InvalidRequestError: relationship("list['Post']")`）。

**实现注意**：`loader/composed.py` 若有 SQLModel entity 引用，避免延迟注解；`demo/composed_er/` 的 models.py 不用 `from __future__ import annotations`（与 `demo/multi_app/models.py` 一致）。

### 坑 2：root DTO 不能 `model_validate(orm_instance)`

spike 用 `UserDTO.model_validate(detached_user)` 触发 `DetachedInstanceError`——pydantic 碰 ORM relationship 字段（posts）触发 SQLAlchemy lazy load。

**实现注意**：root DTO 只填 subset 标量字段（`UserDTO(id=u.id, name=u.name)`），关系字段留给 resolver auto-load。resolver 内部 `_orm_to_dto` 已正确处理（只取 `__subset_fields__`），手动构造时勿用 `model_validate`。测试/demo 文档要写明。

### 坑 3：组合体 `_fed_registry` 不能返回 None

spike 为简化让 `_fed_registry` 返回 None。但 federation 叠加时（US5），ER 图 `_federation_styling` / remote type 判断依赖它。产品化必须做聚合视图（见 Unknown 6）。

### 坑 4：`initialize` 触发点

阶段 2 若 `GraphQLHandler(er_manager=composed)`，`handler.er.initialize()` 会失败（FR-013）。注入路径下 initialize 须在子 member 上触发——或 handler 注入路径分发（遍历子 member initialize），或文档说明用户手动调各子 member。

---

## 总结：阶段 1 实现清单（research 结论）

1. `src/nexusx/loader/composed.py`：`LoaderRegistry` Protocol + `ComposedErManager`（按 entity 委托 + 跨边界关系叠加层 + `_fed_registry` 聚合视图）
2. 跨边界关系：组合体构造时 `cross_relationships=[Relationship(...)]`，loader 用户闭包（Unknown 1）
3. 不 own engine、无 dispose（Unknown 2）
4. 从 `nexusx.loader` + 顶层 `nexusx` 导出 `ComposedErManager`（+ `LoaderRegistry`）
5. 测试：`test_composed_er_manager.py`（US1/US2/US4 + 协议 + 坑 1/2）+ `test_composed_federation.py`（US5 矩阵 A–E）
6. 现有套件零回归（含 federation 012/013/014/016 + benchmark）

阶段 2/3 见 Unknown 5 + spec FR-009~012。
