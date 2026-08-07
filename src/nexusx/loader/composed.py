"""ComposedErManager —— 同进程多 engine 组合（specs/019）。

ComposedErManager 是「按 entity 委托的查询代理 + 跨边界关系叠加层」：

- 多个自洽的子 ErManager（各自单 engine、loader 焊死各自 session）组合成一个总代理
- 满足 ``LoaderRegistry`` 协议，``create_resolver()`` 产出单一总代理 Resolver，
  跨 engine resolve 对用户透明
- 跨边界关系在组合体层集中声明（成员对跨边界关联无感，单独使用时纯粹，DD-02）

本质是「同进程版的 federation」——与 specs/012（跨进程 federation）对偶：

- 012：跨进程 service 组合，跨边界关系走 transport(HTTP)
- 019：同进程 engine 组合，跨边界关系走进程内 DataLoader（用户闭包）

federation 正交可叠加（FR-017）：federation 的 mutating 操作（federate/initialize）落子
ErManager，ComposedErManager 只查询委托 + ``_fed_registry`` 聚合。

不可变（FR-016）：成员 + 跨边界关系在 ``__init__`` 一次性确定。
不实现 ErManager 的管理接口（FR-013）：add_virtual_entities / federate / initialize
等在子 ErManager 上做，调用组合体的对应方法会明确报错。
"""

# 不用 ``from __future__ import annotations`` —— 保持 Protocol 在运行时可检查
# （@runtime_checkable），与 spike 一致。

from typing import Any, Protocol, runtime_checkable

from aiodataloader import DataLoader

from nexusx.loader.registry import (
    ErManager,
    RelationshipInfo,
    _build_custom_relationship_info,
)
from nexusx.relationship import Relationship


@runtime_checkable
class LoaderRegistry(Protocol):
    """Resolver / ER 图 依赖的「查询接口」契约。

    ``ErManager`` 天然满足（其查询方法是本 Protocol 的超集）；
    ``ComposedErManager`` 满足（按 entity 委托）。抽出本 Protocol 是为了：

    - 显式列出 Resolver / ER 图 的依赖面，组合体逐个实现不漏（spike 盘点 9 个访问点）
    - 让 ``create_resolver`` / ``GraphQLHandler`` 注入有正式类型，不绑死 ErManager 具体类
    - ``LoaderRegistry`` 原本是 ``= ErManager`` 的 internal 别名，此处升级为 Protocol
      （无 isinstance/实例化依赖，升级不 breaking）
    """

    # — 实体/关系查询（按 entity 路由）—
    def has_entity(self, entity: type) -> bool: ...
    def get_relationships(self, entity: type) -> dict[str, Any]: ...
    def get_relationship(self, entity: type, name: str) -> Any | None: ...
    def get_loader_for_entity(
        self, entity: type, rel_name: str, type_key: frozenset[str] | None = None
    ) -> DataLoader | None: ...

    # — 按 name / 按 class 兜底 —
    def get_loader_by_name(
        self, name: str, type_key: frozenset[str] | None = None
    ) -> DataLoader | None: ...
    def get_loader(
        self,
        loader_cls: type[DataLoader],
        *,
        type_key: frozenset[str] | None = None,
        force_split: bool = False,
        params_key: tuple | None = None,
    ) -> DataLoader: ...

    # — federation γ（组合体返回中性/聚合）—
    def get_dto_loader(
        self, owner_dto: Any, field_name: str | None = None
    ) -> Any | None: ...

    # — 生命周期 / 缓存 —
    def clear_cache(self) -> None: ...
    def create_resolver(self) -> type: ...

    # — Resolver / ER 图 读取的属性 —
    @property
    def _split_mode(self) -> bool: ...
    @property
    def _fed_registry(self) -> Any: ...

    # — ER 图额外用 —
    def get_all_entities(self) -> list[type]: ...
    def get_all_relationships(self) -> dict[type, dict[str, Any]]: ...


class _CompositeFedRegistryView:
    """只读聚合各子 member 的 ``_fed_registry``（federation 叠加，US5 / FR-017）。

    子 member 各自 federate 后，物化的 remote type 在各自 ``_fed_registry``。
    本视图遍历成员合并，使 ER 图 styling / remote type 判断正确。无 federation
    时各成员 ``_fed_registry`` 为 None，本视图方法返回空集 / None。
    """

    def __init__(self, members: list[ErManager]):
        self._members = members

    def _frs(self):
        for m in self._members:
            fr = getattr(m, "_fed_registry", None)
            if fr is not None:
                yield fr

    def qualified_of(self, cls):
        for fr in self._frs():
            qn = fr.qualified_of(cls)
            if qn:
                return qn
        return None

    def all_classes(self):
        classes: set = set()
        for fr in self._frs():
            classes.update(fr.all_classes())
        return classes

    def service_colors(self):
        colors: dict = {}
        for fr in self._frs():
            colors.update(fr.service_colors())
        return colors

    def has(self, qn):
        return any(fr.has(qn) for fr in self._frs())

    def get(self, qn):
        for fr in self._frs():
            cls = fr.get(qn)
            if cls:
                return cls
        return None


class ComposedErManager:
    """组合多个自洽 ErManager 的总代理 + 跨边界关系叠加层。

    满足 :class:`LoaderRegistry` 协议。``create_resolver()`` 产出单一总代理
    Resolver，跨 engine resolve 对用户透明。

    Args:
        members: 各自自洽的子 ErManager（单 engine，loader 焊死各自 session）。
            不可空，构造后不可变（FR-016）。成员实体集必须互斥（重名报错）。
        cross_relationships: 跨 engine 边界关系，形如 ``[(source_entity, Relationship), ...]``。
            关系在组合体层集中声明（DD-02/FR-008），成员对跨边界关联无感。
            Relationship.loader 是用户闭包，内部选用目标 engine 的 session。
        service_name: 组合体作为 federation member 被消费时的统一 service 名
            （可选；独立使用时不需）。

    不实现 ErManager 的管理接口（FR-013）：``add_virtual_entities`` / ``federate`` /
    ``initialize`` 等在子 ErManager 上做，调用组合体对应方法会抛 ``AttributeError``。
    """

    def __init__(
        self,
        members: list[ErManager],
        *,
        cross_relationships: list[tuple[type, Relationship]] | None = None,
        service_name: str | None = None,
    ):
        if not members:
            raise ValueError(
                "ComposedErManager requires at least one member ErManager"
            )

        self._members: list[ErManager] = list(members)
        self._service_name: str | None = service_name

        # entity → 所属 member（委托路由表）
        self._route: dict[type, ErManager] = {}
        # loader_cls → member（反向路由，避免 get_loader 缓存污染）
        self._loader_owner: dict[type, ErManager] = {}
        # 跨边界关系叠加层：source entity → {rel_name: RelationshipInfo}
        self._cross_rels: dict[type, dict[str, RelationshipInfo]] = {}
        # 跨边界 loader 实例缓存（组合体自持有，clear_cache 时清）
        self._cross_loader_cache: dict[type, DataLoader] = {}
        # _fed_registry 聚合视图（惰性创建）
        self._fed_registry_view: _CompositeFedRegistryView | None = None

        # 建立路由表 + loader 反向映射 + 实体互斥校验
        for m in self._members:
            for cls in m.get_all_entities():
                if cls in self._route:
                    raise ValueError(
                        f"实体 {cls!r} 被多个 member 注册"
                        f"（{self._route[cls]!r} 与 {m!r}），"
                        f"ComposedErManager 要求成员实体集互斥"
                    )
                self._route[cls] = m
            for _entity, rels in m.get_all_relationships().items():
                for rel_info in rels.values():
                    # loader 与 page_loader 都登记：分页路径经 page_loader 取实例
                    # （page_loader 是独立类，只登记 loader 会让分页查询 KeyError）
                    for _lk in (rel_info.loader, rel_info.page_loader):
                        if _lk is not None:
                            self._loader_owner[_lk] = m

        # 跨边界关系 → RelationshipInfo（复用 _build_custom_relationship_info）
        for source_entity, rel in cross_relationships or []:
            if source_entity not in self._route:
                raise ValueError(
                    f"跨边界关系 source {source_entity!r} 未在任一 member 注册"
                )
            if rel.target_entity not in self._route:
                raise ValueError(
                    f"跨边界关系 {source_entity.__name__}.{rel.name} 的 target "
                    f"{rel.target_entity!r} 未在任一 member 注册"
                )
            rel_info = _build_custom_relationship_info(rel)
            bucket = self._cross_rels.setdefault(source_entity, {})
            if rel.name in bucket:
                raise ValueError(
                    f"跨边界关系 {source_entity.__name__}.{rel.name} 重复声明"
                )
            bucket[rel.name] = rel_info

    # ── 内部辅助 ────────────────────────────────────────────────

    def _member_for(self, entity: type) -> ErManager | None:
        return self._route.get(entity)

    def _get_cross_loader(self, loader_cls: type[DataLoader]) -> DataLoader:
        """跨边界 loader 实例由组合体自持有缓存（不走 member.get_loader）。"""
        if loader_cls not in self._cross_loader_cache:
            self._cross_loader_cache[loader_cls] = loader_cls()
        return self._cross_loader_cache[loader_cls]

    def _cross_loader_classes(self) -> set[type]:
        cls_set: set[type] = set()
        for rels in self._cross_rels.values():
            for rel_info in rels.values():
                if rel_info.loader is not None:
                    cls_set.add(rel_info.loader)
        return cls_set

    # ── Resolver 依赖的查询接口（按 entity 路由 + 跨边界叠加）────────

    def has_entity(self, entity: type) -> bool:
        return entity in self._route

    def get_relationships(self, entity: type) -> dict[str, RelationshipInfo]:
        """委托 member 的本地关系 + 叠加跨边界关系。"""
        member = self._member_for(entity)
        local = dict(member.get_relationships(entity)) if member else {}
        cross = self._cross_rels.get(entity, {})
        if cross:
            local.update(cross)  # 跨边界关系声明优先（覆盖同名本地）
        return local

    def get_relationship(
        self, entity: type, name: str
    ) -> RelationshipInfo | None:
        return self.get_relationships(entity).get(name)

    def get_loader_for_entity(
        self,
        entity: type,
        rel_name: str,
        type_key: frozenset[str] | None = None,
    ) -> DataLoader | None:
        """跨边界关系 → 组合体自持有的 loader；本地 → 委托 member。"""
        cross = self._cross_rels.get(entity, {}).get(rel_name)
        if cross is not None and cross.loader is not None:
            return self._get_cross_loader(cross.loader)
        member = self._member_for(entity)
        if member is None:
            return None
        return member.get_loader_for_entity(entity, rel_name, type_key)

    def get_loader_by_name(
        self, name: str, type_key: frozenset[str] | None = None
    ) -> DataLoader | None:
        """按关系名取 loader。

        跨 member 同名关系抛 ambiguity —— 与 ``ErManager.get_loader_by_name``
        单体内同名抛 ``ValueError`` 的安全网对齐。若静默「首个获胜」，跨 engine
        同名关系（如 owner/tags）会用 A engine 的 session 取本该走 B engine 的
        关系，结果「看似对、其实错」。跨边界叠加层的关系名也参与歧义判定。
        """
        member_hits: list[ErManager] = []
        for m in self._members:
            if any(name in rels for rels in m.get_all_relationships().values()):
                member_hits.append(m)
        cross_hit = any(name in rels for rels in self._cross_rels.values())

        total = len(member_hits) + (1 if cross_hit else 0)
        if total == 0:
            return None
        if total > 1:
            raise ValueError(
                f"Ambiguous loader lookup: relationship '{name}' resolved to "
                f"{len(member_hits)} member(s)"
                f"{' plus the cross-boundary layer' if cross_hit else ''} in "
                f"ComposedErManager. Use get_loader_for_entity() for precision."
            )

        if member_hits:
            # 恰一个 member 命中：委托（member 内若多 entity 同名仍由其抛错）
            return member_hits[0].get_loader_by_name(name, type_key)
        # 恰跨边界层命中：取其 loader 类，组合体自持实例
        for rels in self._cross_rels.values():
            rel_info = rels.get(name)
            if rel_info is not None and rel_info.loader is not None:
                return self._get_cross_loader(rel_info.loader)
        return None

    def get_loader(
        self,
        loader_cls: type[DataLoader],
        *,
        type_key: frozenset[str] | None = None,
        force_split: bool = False,
        params_key: tuple | None = None,
    ) -> DataLoader:
        """反向路由 member loader；跨边界 loader 由组合体自持有。

        本地 loader 走构造时收集的 ``_loader_owner``；**federate 后 member 新增的
        loader（如 RemoteLoader）走动态查找**——它们在组合体构造时还不存在
       （federation 物化发生在子 member ``initialize()`` 之后），构造期收集不到。
        动态查找遍历 ``member.get_all_relationships()``（含物化关系）定位拥有者。
        跨边界 loader 由组合体自持有。
        """
        owner = self._loader_owner.get(loader_cls)
        if owner is None:
            # federate 后 member 新增的 loader —— 动态查找拥有它的 member
            for m in self._members:
                for _entity, rels in m.get_all_relationships().items():
                    for rel_info in rels.values():
                        if loader_cls in (rel_info.loader, rel_info.page_loader):
                            owner = m
                            break
                    if owner is not None:
                        break
                if owner is not None:
                    break
        if owner is not None:
            return owner.get_loader(
                loader_cls,
                type_key=type_key,
                force_split=force_split,
                params_key=params_key,
            )
        if loader_cls in self._cross_loader_classes():
            return self._get_cross_loader(loader_cls)
        raise KeyError(
            f"loader_cls {loader_cls!r} 不属于任何成员 ErManager 或跨边界关系"
        )

    def get_dto_loader(
        self, owner_dto: Any, field_name: str | None = None
    ) -> Any | None:
        """聚合 γ DTO loader：遍历成员查找。"""
        for m in self._members:
            loader = m.get_dto_loader(owner_dto, field_name)
            if loader is not None:
                return loader
        return None

    # ── 生命周期 / 缓存 ────────────────────────────────────────

    def clear_cache(self) -> None:
        """聚合所有成员的 clear_cache + 清跨边界 loader 缓存。"""
        for m in self._members:
            m.clear_cache()
        self._cross_loader_cache.clear()

    def create_resolver(self) -> type:
        """产出总代理 Resolver（照搬 ErManager.create_resolver，注入组合体自身）。

        Resolver 本体 0 改动——它的 ``__init__`` 已是 ``loader_registry: Any``，
        组合体作为 loader_registry 注入后，跨 engine resolve 透明。
        """
        from nexusx.resolver import Resolver as _Resolver

        composed = self

        class BoundResolver(_Resolver):
            def __init__(
                self,
                context: dict[str, Any] | None = None,
                loader_instances: dict[type, DataLoader] | None = None,
            ):
                super().__init__(
                    loader_registry=composed,
                    context=context,
                    loader_instances=loader_instances,
                )

        BoundResolver.__name__ = "Resolver"
        BoundResolver.__qualname__ = "Resolver"
        return BoundResolver

    # ── Resolver / ER 图 读取的属性 ────────────────────────────

    @property
    def _split_mode(self) -> bool:
        # 组合体不支持 split 模式（成员各自决定，组合体层面统一为 False）。
        # 现有 split_mode 用途（query_meta 列裁剪）在 member 内部各自生效。
        return False

    @property
    def _fed_registry(self) -> Any:
        """聚合各成员 _fed_registry 的只读视图（federation 叠加，US5）。"""
        if self._fed_registry_view is None:
            self._fed_registry_view = _CompositeFedRegistryView(self._members)
        return self._fed_registry_view

    # ── ER 图额外用 ────────────────────────────────────────────

    def get_all_entities(self) -> list[type]:
        return list(self._route.keys())

    def get_all_relationships(self) -> dict[type, dict[str, RelationshipInfo]]:
        merged: dict[type, dict[str, RelationshipInfo]] = {}
        for m in self._members:
            for entity, rels in m.get_all_relationships().items():
                merged.setdefault(entity, {}).update(rels)
        # 叠加跨边界关系
        for entity, rels in self._cross_rels.items():
            merged.setdefault(entity, {}).update(rels)
        return merged

    # ── federation member 暴露聚合（作 member 被消费时，US5-A2）─────

    @property
    def service_name(self) -> str | None:
        return self._service_name

    def get_dto_classes(self) -> list[type]:
        """聚合所有成员的 DTO 类（federation member introspection 用）。"""
        classes: list[type] = []
        for m in self._members:
            classes.extend(m.get_dto_classes())
        return classes

    def get_public_dtos(self) -> list[type]:
        """聚合所有成员的 federation-public DTO（γ-path composition source）。"""
        dtos: list[type] = []
        for m in self._members:
            dtos.extend(m.get_public_dtos())
        return dtos

    @property
    def _expose_mounted_endpoints(self) -> bool:
        """取成员的 expose 策略（任一为 True 则暴露，便于 transitively 发现）。"""
        return any(
            getattr(m, "_expose_mounted_endpoints", False) for m in self._members
        )

    # ── 版本（ER 图 / SDL 缓存用，组合体取成员最大版本）──────────

    @property
    def version(self) -> int:
        # 成员 version 单调递增（initialize / add_virtual_entities 各 +1）。
        # 不能用 max：当某 member 已是高版本主导时，另一低版本 member federate
        # （version+1）不会改变 max，导致 GraphQLHandler 的 SDL / introspection
        # 缓存（以 version 为 key）不刷新，schema 缺新物化的 remote type（review #4）。
        # sum 在「只增」语义下严格单调——任一 member 进入新一代 ⇒ 聚合变化——
        # 且保持 int，不破坏把 version 当 cache key / 计数的消费面。
        return sum(getattr(m, "version", 0) for m in self._members)
