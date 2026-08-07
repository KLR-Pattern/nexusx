# Data Model: 可组合 ErManager（specs/019）

> Phase 1 产出。定义 `LoaderRegistry` Protocol、`ComposedErManager` 结构与签名、跨边界关系叠加层数据流、`_fed_registry` 聚合视图。签名是产品化目标（spike 已验证可行性，产品化在它基础上补 cross_relationships 注入 + _fed_registry 聚合）。

## 1. LoaderRegistry Protocol（阶段 1 新增，`loader/composed.py`）

把 Resolver / ErDiagram 对 ErManager 的依赖面显式抽象为 Protocol。`ErManager` 天然满足（其查询方法是 Protocol 的超集）。`runtime_checkable` 便于断言。

```python
from typing import Protocol, runtime_checkable, Any
from aiodataloader import DataLoader

@runtime_checkable
class LoaderRegistry(Protocol):
    """Resolver / ER 图 所依赖的「查询接口」契约。
    ErManager 满足；ComposedErManager 满足（按 entity 委托）。"""

    # — 实体/关系查询（按 entity 路由）—
    def has_entity(self, entity: type) -> bool: ...
    def get_relationships(self, entity: type) -> dict[str, Any]: ...
    def get_relationship(self, entity: type, name: str) -> Any | None: ...
    def get_loader_for_entity(
        self, entity: type, rel_name: str, type_key: frozenset[str] | None = None,
    ) -> DataLoader | None: ...

    # — 按 name / 按 class 兜底 —
    def get_loader_by_name(
        self, name: str, type_key: frozenset[str] | None = None,
    ) -> DataLoader | None: ...
    def get_loader(
        self, loader_cls: type[DataLoader], *,
        type_key: frozenset[str] | None = None,
        force_split: bool = False, params_key: tuple | None = None,
    ) -> DataLoader: ...

    # — federation γ（组合体返回中性/聚合）—
    def get_dto_loader(self, owner_dto: Any, field_name: str | None = None) -> Any | None: ...

    # — 生命周期/缓存 —
    def clear_cache(self) -> None: ...
    def create_resolver(self) -> type: ...

    # — Resolver/ER 图 读取的属性 —
    @property
    def _split_mode(self) -> bool: ...
    @property
    def _fed_registry(self) -> Any: ...

    # — ER 图额外用 —
    def get_all_entities(self) -> list[type]: ...
    def get_all_relationships(self) -> dict[type, dict[str, Any]]: ...
```

> 注：`_split_mode` / `_fed_registry` 是带下划线的「内部」属性，但 resolver.py/er_diagram_dot.py 直接读它们（既有事实）。Protocol 把它们显式列出，避免组合体漏实现。

## 2. ComposedErManager（阶段 1 核心，`loader/composed.py`）

「按 entity 委托的查询代理 + 跨边界关系叠加层」。满足 `LoaderRegistry`。不可变（FR-016）。

### 2.1 构造签名

```python
class ComposedErManager:
    def __init__(
        self,
        members: list[ErManager],
        *,
        cross_relationships: list[Relationship] | None = None,
        service_name: str | None = None,   # 组合体作 federation member 时的统一名
    ): ...
```

- `members`：各自自洽的子 ErManager（单 engine，loader 焊死各自 session）。不可空。
- `cross_relationships`：跨边界关系（`Relationship`，loader 用户闭包，DD-02/FR-008）。组合体持有其 `RelationshipInfo`（叠加层）。
- `service_name`：组合体作为 federation member 被消费时的统一 service 名（Unknown 6）；独立使用时可选。

### 2.2 内部状态（构造时一次性建立，之后冻结）

```python
self._members: list[ErManager]                    # 成员（顺序保留）
self._route: dict[type, ErManager]               # entity → 所属 member（委托路由表）
self._loader_owner: dict[type[DataLoader], ErManager]  # loader_cls → member（反向路由，避免缓存污染）
self._cross_rels: dict[type, dict[str, RelationshipInfo]]  # 跨边界关系叠加层（按 source entity）
self._service_name: str | None
```

构造期校验（fail-fast，FR-014/FR-016）：
- 实体 `full_class_name` 冲突 → 报错
- 跨边界关系 source/target 必须在路由表内（target 可来自任一 member）
- loader_cls 反向映射从各 member 的 `get_all_relationships()` 收集

### 2.3 方法（按 entity 委托 + 叠加）

```python
def has_entity(self, entity) -> bool:
    return entity in self._route

def get_relationships(self, entity) -> dict[str, RelationshipInfo]:
    # 委托 member 的本地关系 + 叠加跨边界关系
    member = self._route.get(entity)
    local = member.get_relationships(entity) if member else {}
    cross = self._cross_rels.get(entity, {})
    return {**local, **cross}   # 跨边界关系覆盖同名（声明优先）

def get_relationship(self, entity, name):
    return self.get_relationships(entity).get(name)

def get_loader_for_entity(self, entity, rel_name, type_key=None):
    # 跨边界关系 → 组合体自持有的 loader；本地 → 委托 member
    cross = self._cross_rels.get(entity, {}).get(rel_name)
    if cross is not None:
        return self.get_loader(cross.loader, type_key=type_key)
    member = self._route.get(entity)
    return member.get_loader_for_entity(entity, rel_name, type_key) if member else None

def get_loader(self, loader_cls, *, type_key=None, force_split=False, params_key=None):
    owner = self._loader_owner.get(loader_cls)
    if owner is None:
        raise KeyError(f"loader_cls {loader_cls!r} 不属于任何成员 ErManager")
    return owner.get_loader(loader_cls, type_key=type_key, force_split=force_split, params_key=params_key)

def get_loader_by_name(self, name, type_key=None):
    for m in self._members:
        loader = m.get_loader_by_name(name, type_key)
        if loader is not None:
            return loader
    return None

def clear_cache(self):
    for m in self._members:
        m.clear_cache()

def create_resolver(self) -> type:
    # 照搬 ErManager.create_resolver：把组合体自身作为 loader_registry 注入
    composed = self
    class BoundResolver(Resolver):
        def __init__(self, context=None, loader_instances=None):
            super().__init__(loader_registry=composed, context=context,
                             loader_instances=loader_instances)
    BoundResolver.__name__ = BoundResolver.__qualname__ = "Resolver"
    return BoundResolver

def get_all_entities(self):
    return list(self._route.keys())

def get_all_relationships(self):
    merged: dict = {}
    for m in self._members:
        merged.update(m.get_all_relationships())
    # 叠加跨边界关系
    for entity, rels in self._cross_rels.items():
        merged.setdefault(entity, {}).update(rels)
    return merged
```

### 2.4 不实现（FR-013/FR-017）

`add_virtual_entities` / `federate` / `initialize` / `register_dto_loader` / `aclose_federation` —— 均不实现。组合体是查询代理，federation mutating 操作在子 member 上做。调用应明确报错（非静默）。

## 3. 跨边界关系叠加层数据流

```
resolve UserDTO.orders（跨 engine）:

  Resolver → composed.get_loader_for_entity(User, 'orders')
               │
               ├─ cross = self._cross_rels[User].get('orders')   ← 叠加层命中
               │    → RelationshipInfo(loader=_CustomLoader_for_orders)
               │    → composed.get_loader(_CustomLoader_for_orders)
               │        → owner = _loader_owner[_CustomLoader_for_orders]
               │        → owner.get_loader(...) 返回实例
               │    → loader.load_many(user_ids)
               │        → orders_by_user_id 闭包 → shop session → [Order...]
               │
               └─ 返回 Order 列表（来自 shop engine）

  Resolver 继续遍历 Order → composed.get_relationships(Order)
               └─ 委托 shop_er.get_relationships(Order)   ← Order 归 shop_er
                    → shop_er.get_loader_for_entity(Order, 'items') → shop session
```

跨边界关系（叠加层）与本地关系（委托）混合，对 Resolver 透明。

## 4. _fed_registry 聚合视图（federation 叠加，US5/Unknown 6）

子 member 各自 federate 后，物化的 remote type 在各自 `_fed_registry`。组合体提供只读聚合视图，使 ER 图 styling / remote type 判断正确：

```python
@property
def _fed_registry(self):
    return _CompositeFedRegistryView(self._members)

class _CompositeFedRegistryView:
    """只读聚合各子 member 的 _fed_registry。无 federation 时各成员 _fed_registry 为 None。"""
    def qualified_of(self, cls):
        for m in self._members:
            fr = getattr(m, "_fed_registry", None)
            if fr is not None:
                qn = fr.qualified_of(cls)
                if qn:
                    return qn
        return None
    def all_classes(self): ...   # 并集
    def service_colors(self): ...  # 合并 dict
```

member 端暴露聚合（作 federation member 被消费时）：`service_name`（组合体级）+ `get_public_dtos`/`get_dto_classes`（聚合所有子 member）+ `get_all_entities` + `_expose_mounted_endpoints`。

## 5. 与既有组件的关系（0 改动）

```
ErManager           ──0 改动──  ComposedErManager 独立新类，组合它
Resolver            ──0 改动──  __init__ 已 loader_registry: Any，吃组合体
ErDiagram           ──0 改动──  from_er_manager 鸭子类型吃组合体
ErDiagramDotBuilder ──0 改动──  同上
GraphQLHandler      ──阶段2──   加 er_manager= 注入分支（非 breaking）
```
