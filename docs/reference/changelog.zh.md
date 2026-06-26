# 变更记录

## Unreleased

### 新增

- **非 SQLModel 根对象（虚拟实体）**——普通 `pydantic.BaseModel` 子类现在可以作为 NexusX 解析和 ER 可视化的一等公民，不需要继承 SQLModel，也不需要底层表。三项能力同步落地：
  - `ErManager.add_virtual_entities([...])` 将普通 BaseModel 类注册到 ER 图。必须在 `create_resolver()` 之前调用；之后注册表冻结。SQLModel 类在此处会被拒绝，仍通过 `__init__` 的 `entities=` / `base=` 传入。
  - **`DefineSubset.__subset__` 源拓宽**——源现在可以是任意 `BaseModel`（SQLModel 或普通 BaseModel 均可）。适合对外部 schema（OAuth claims、SDK 响应类）做子集化，无需 ORM 表。
  - **ER / Voyager 虚拟节点渲染**——虚拟实体以黄底（`#FFF9C4`）、`«virtual»` UML 衍型、虚线 `cluster_virtual` 子图渲染，视觉上与真正的 DB 实体明确区分。使用 `ErDiagram.from_er_manager(er)`（数据 API）或 `ErDiagramDotBuilder(er).render_dot()`（DOT 路径）。

- **Resolver 统一源解析**——`_resolve_source()` 为 `_get_loader` 和 `_scan_auto_load_fields` 提供单一辅助函数。当类声明了 `__relationships__` 但未通过 `add_virtual_entities()` 注册时，会抛出明确的 `RuntimeError`，而不是静默跳过自动加载。

- **迁移路径**——使用 `_subset_registry[X] = Y` hack 的项目可以机械式迁移。详见 [迁移指南](./migration.zh.md) 和 [虚拟实体指南](../guide/virtual_entities.zh.md)。

## 1.4.0

!!! warning "Breaking Change: rpc → use_case 重构"

    `RpcService` → `UseCaseService`，`create_rpc_mcp_server` → `create_use_case_mcp_server`，`create_rpc_voyager` → `create_use_case_voyager`。

    新增四层 MCP 工具（`list_apps` → `list_services` → `describe_service` → `call_use_case`），支持多应用管理（`UseCaseAppConfig`）和上下文注入（`FromContext`）。

!!! warning "Breaking Change: 移除 `RpcServiceConfig`（历史）"

    `RpcServiceConfig` TypedDict 已移除。服务直接接受子类列表。

    - 服务名称从 `cls.__name__` 派生
    - 服务描述从 `cls.__doc__` 派生

## 1.3.3

!!! warning "Breaking Change: 移除 `Loader(str)` 支持"

    移除基于字符串的 `Loader('relationship_name')` 模式。仅支持 `Loader(DataLoaderClass)` 和 `Loader(async_callable)`。

!!! tip
    隐式自动加载（字段名匹配关系 + 兼容类型）已经覆盖了常见场景，无需 `resolve_*` 方法。

## 1.3.2

**Bug Fix**：修复 `IntrospectionGenerator` 默认值序列化，从 Python `repr()` 改为 JSON 格式（`json.dumps`）。

## 1.3.1

- 从 v1.3.0 起提供完整的 Core API、RPC + Voyager 模式文档
- 更新 `llms-full.txt` 以反映当前 API

---

完整变更记录请查看 [GitHub 上的 CHANGELOG.md](https://github.com/allmonday/nexusx/blob/master/CHANGELOG.md)。
