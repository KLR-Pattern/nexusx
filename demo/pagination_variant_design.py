"""分页判据理想设计的可运行 Demo（mindmap #16 / 节点 65 的落地演示）.

对比两套设计：

  现状    —— RelationshipInfo 平铺字段 + kind 字符串 + 各消费点手拼判定
  理想    —— 按 kind 拆成四个类型变体，判据内聚为多态属性

运行：

    uv run python demo/pagination_variant_design.py

对照表会逐场景并排打印两套设计的判定过程与结果，最后演示
"矛盾状态"在两套设计下的不同命运。文件末尾有几个可以动手改的
实验点。

对应脑图：map 37 节点 #16（分不分页 4 种编码）与子节点 65（理想设计）。
"""

from __future__ import annotations

from dataclasses import dataclass

# ══════════════════════════════════════════════════════════════════
# Part A  理想设计：kind 就是类型，四个变体各携己物
# ══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Relationship:
    """基类：只放所有变体共享的正交事实."""

    name: str
    fk_field: str
    target_entity: str  # demo 里用字符串代替真实实体类
    is_list: bool


@dataclass(frozen=True)
class LocalRelationship(Relationship):
    """本地 SQLModel 关系：分页能力恒在（SQL 随时可切片）.

    paged_view_loader 表达的是"装配了分页视图"（装配依据 order_by），
    不是"能力"——能力对本地恒 True，永远可以补装配.
    """

    loader: str
    paged_view_loader: str | None = None
    default_page_size: int = 20
    max_page_size: int = 100

    @property
    def can_paginate(self) -> bool:
        return True  # 数据源物理上支持任意切片

    @property
    def has_paged_view(self) -> bool:
        return self.paged_view_loader is not None


@dataclass(frozen=True)
class PlainRemoteRelationship(Relationship):
    """远程、不分页：member 没暴露 page_by 根，wire 上没有分页通道."""

    loader: str
    target_service: str
    join_remote: str

    @property
    def can_paginate(self) -> bool:
        return False


@dataclass(frozen=True)
class PagedRemoteRelationship(Relationship):
    """远程分页：member 声明了 __pagination_orders__，能力固有.

    page_loader / page_capability 必填无默认——构造即承诺，不存在
    "声明了分页却没有加载器"的中间态.
    """

    loader: str
    page_loader: str
    page_capability: dict  # demo 里用 dict 代替 BatchPageCapability
    target_service: str
    join_remote: str
    default_page_size: int = 20
    max_page_size: int = 50  # 从 member 声明带入（现状里是硬编码 100）

    @property
    def can_paginate(self) -> bool:
        return True


@dataclass(frozen=True)
class CoalescedRelationship(Relationship):
    """合并取回：member 声明的合并字段是否分页（唯一独立布尔）.

    注意：这个类型没有 loader / page_loader 字段——
    "COALESCED 却带分页加载器"的矛盾记录在本设计下无法构造.
    """

    paginated: bool
    target_service: str

    @property
    def can_paginate(self) -> bool:
        return self.paginated


# ══════════════════════════════════════════════════════════════════
# Part B  两个单义判定（不再共用一个混合函数）
# ══════════════════════════════════════════════════════════════════


def execute_paginated(rel: Relationship, enable_local: bool) -> bool:
    """本次是否以分页形态执行（动态：能力 × 装配 × 开关）."""
    if isinstance(rel, LocalRelationship):
        return rel.has_paged_view and enable_local  # 装配 × 开关
    return rel.can_paginate  # 远程：能力即形态


# ══════════════════════════════════════════════════════════════════
# Part C  模拟四个消费点：每个都是一两行，无人携带真值表
# ══════════════════════════════════════════════════════════════════


def resolver_dispatch(rel: Relationship, enable_local: bool) -> str:
    """执行层分派（现状里 resolver 手拼了 4 处的那种判定）."""
    if execute_paginated(rel, enable_local):
        loader = getattr(rel, "paged_view_loader", None) or getattr(
            rel, "page_loader", None
        )
        if loader is None:
            return "分页形态（由父取回解析，无独立加载器）"
        return f"分页加载 ← {loader}"
    return f"平铺加载 ← {getattr(rel, 'loader', '(合并取回，无独立加载)')}"


def sdl_render(rel: Relationship, enable_local: bool) -> str:
    """schema 形态：平 list 还是 {items, pagination}."""
    paginated = rel.can_paginate and (
        not isinstance(rel, LocalRelationship) or enable_local
    )
    return "{items, pagination}" if paginated else "[Target!]!"


def introspect_serialize(rel: Relationship) -> bool:
    """目录序列化：静态能力，不掺开关（现状里 9 行双推导的那段）."""
    return rel.can_paginate


def voyager_icon(rel: Relationship) -> str:
    """新人加的消费点：需要携带的领域知识为零."""
    return "📄分页" if rel.can_paginate else "📄平铺"


# ══════════════════════════════════════════════════════════════════
# Part D  现状对照：真实生产代码里的判定
# ══════════════════════════════════════════════════════════════════


def _legacy_relationship_infos() -> list[tuple[str, object, dict]]:
    """构造与 Part E 四个变体一一对应的真实 RelationshipInfo.

    返回 (名称, RelationshipInfo, 真值表快照)——快照就是现状消费者
    需要背的那张表：kind / pagination / page_loader.
    """
    from nexusx.loader.registry import RelationshipInfo, RelationshipKind

    class _L:  # 假 loader 类，只为了填字段
        pass

    rows: list[tuple[str, object, dict]] = []

    # 1. 本地 + 装配了分页视图
    local = RelationshipInfo(
        name="reviews", direction="ONETOMANY", fk_field="product_id",
        target_entity=object, is_list=True, loader=_L, page_loader=_L,
        kind=RelationshipKind.LOCAL,
    )
    rows.append(("本地(装配分页)", local,
                 {"kind": "LOCAL", "pagination": local.pagination,
                  "page_loader": "有"}))

    # 2. 远程分页（manager.py:406 的形态：pagination 与 kind 同源派生）
    paged = RelationshipInfo(
        name="reviews", direction="ONETOMANY", fk_field="product_id",
        target_entity=object, is_list=True, loader=_L, page_loader=_L,
        pagination=True, target_service="ReviewSvc",
        kind=RelationshipKind.REMOTE_PAGED,
    )
    rows.append(("远程分页", paged,
                 {"kind": "REMOTE_PAGED", "pagination": paged.pagination,
                  "page_loader": "有"}))

    # 3. 远程不分页
    plain = RelationshipInfo(
        name="author", direction="MANYTOONE", fk_field="author_id",
        target_entity=object, is_list=True, loader=_L,
        target_service="UserSvc", kind=RelationshipKind.REMOTE_PLAIN,
    )
    rows.append(("远程不分页", plain,
                 {"kind": "REMOTE_PLAIN", "pagination": plain.pagination,
                  "page_loader": "无"}))

    # 4. 合并取回（manager.py:267 的形态：pagination 是唯一真信息）
    coalesced = RelationshipInfo(
        name="stats", direction="ONETOMANY", fk_field="product_id",
        target_entity=object, is_list=True, loader=None,
        pagination=True, target_service="StatSvc",
        kind=RelationshipKind.REMOTE_COALESCED,
    )
    rows.append(("合并取回(分页)", coalesced,
                 {"kind": "REMOTE_COALESCED", "pagination": coalesced.pagination,
                  "page_loader": "无"}))
    return rows


def _legacy_truth_table(rel_info: object) -> bool:
    """现状消费者必须会背的真值表判定（is_active 的展开形态）."""
    from nexusx.utils.pagination_schema import is_active_paginated_relationship

    # 生产代码里真实存在的共享函数（SDL/introspection 已在用）
    return is_active_paginated_relationship(rel_info, enable_pagination=True)


# ══════════════════════════════════════════════════════════════════
# Part E  全景演示
# ══════════════════════════════════════════════════════════════════


def main() -> None:
    new_rels = [
        ("本地(装配分页)", LocalRelationship(
            name="reviews", fk_field="product_id", target_entity="Review",
            is_list=True, loader="OneToManyLoader", paged_view_loader="PagedO2M")),
        ("远程分页", PagedRemoteRelationship(
            name="reviews", fk_field="product_id", target_entity="Review",
            is_list=True, loader="RemoteLoader", page_loader="PaginatedRemote",
            page_capability={"default_order": "NEWEST"},
            target_service="ReviewSvc", join_remote="product_id")),
        ("远程不分页", PlainRemoteRelationship(
            name="author", fk_field="author_id", target_entity="User",
            is_list=True, loader="RemoteLoader",
            target_service="UserSvc", join_remote="id")),
        ("合并取回(分页)", CoalescedRelationship(
            name="stats", fk_field="product_id", target_entity="Stat",
            is_list=True, paginated=True, target_service="StatSvc")),
    ]

    print("═" * 72)
    print("场景 1  四种关系 × 五个消费点（理想设计：每个消费点一两行）")
    print("═" * 72)
    for name, rel in new_rels:
        print(f"\n● {name}  ({type(rel).__name__})")
        print(f"  resolver 分派   : {resolver_dispatch(rel, enable_local=True)}")
        print(f"  SDL 形态        : {sdl_render(rel, enable_local=True)}")
        print(f"  introspect 能力 : pagination={introspect_serialize(rel)}")
        print(f"  voyager 图标    : {voyager_icon(rel)}")

    print("\n" + "═" * 72)
    print("场景 2  同场景对照现状（消费者需背真值表才能判定）")
    print("═" * 72)
    from nexusx.loader.registry import RelationshipKind  # noqa: F401

    legacy = _legacy_relationship_infos()
    for (legacy_name, legacy_rel, snapshot), (new_name, new_rel) in zip(
        legacy, new_rels, strict=True
    ):
        legacy_verdict = _legacy_truth_table(legacy_rel)
        new_verdict = execute_paginated(new_rel, enable_local=True)
        agree = "✅一致" if legacy_verdict == new_verdict else "❌不一致"
        print(f"\n● {legacy_name}")
        print(f"  真值表快照      : {snapshot}")
        print(f"  现状判定        : {legacy_verdict}")
        print(f"  理想判定        : {new_verdict}   {agree}")

    print("\n" + "═" * 72)
    print("场景 3  矛盾状态的命运：'合并取回 + 分页加载器'")
    print("═" * 72)

    from nexusx.loader.registry import RelationshipInfo

    class _L2:
        pass

    bad = RelationshipInfo(
        name="stats", direction="ONETOMANY", fk_field="product_id",
        target_entity=object, is_list=True, loader=_L2, page_loader=_L2,
        pagination=True, target_service="StatSvc",
        kind=RelationshipKind.REMOTE_COALESCED,
    )
    print(f"\n  现状   ：构造成功，静默存在 —— {bad!r}"[:88], "...")
    print("          （kind=COALESCED 却带 page_loader，无任何报警）")

    print("\n  理想   ：构造失败 ——")
    try:
        # CoalescedRelationship 没有 loader/page_loader 字段
        CoalescedRelationship(
            name="stats", fk_field="product_id", target_entity="Stat",
            is_list=True, paginated=True, target_service="StatSvc",
            page_loader="PagedRemote",  # type: ignore[call-arg]
        )
    except TypeError as exc:
        print(f"          TypeError: {exc}")
        print("          矛盾状态在类型层面无法表示——校验都不需要")

    print("\n" + "═" * 72)
    print("场景 4  本地开关关闭时（能力恒在，但本次不以分页形态执行）")
    print("═" * 72)
    local = new_rels[0][1]
    print(f"\n  本地关系：can_paginate={local.can_paginate}（能力恒在）, "
          f"has_paged_view={local.has_paged_view}")
    print(f"  开关开  ：execute_paginated = {execute_paginated(local, True)}")
    print(f"  开关关  ：execute_paginated = {execute_paginated(local, False)}"
          "  ← 能力没变，只是本次不用分页形态")
    paged_remote = new_rels[1][1]
    print(f"  远程分页不受开关影响：execute_paginated = "
          f"{execute_paginated(paged_remote, False)}（能力即形态）")

    print(
        "\n═" * 8 + " 实验点（改完重跑） " + "═" * 34,
        """
    1. 给 LocalRelationship 去掉 paged_view_loader（设 None）——
       can_paginate 仍是 True：体会"能力"与"装配"是两个正交概念
    2. 把 CoalescedRelationship 的 paginated 改成 False——
       can_paginate 跟着变：它是这个类型上唯一的真信息
    3. 在文件里新增一个消费点（比如导出 Markdown 表格）——
       数一数需要写几行、需要背多少真值表（答案：一行、零）
    """,
    )


if __name__ == "__main__":
    main()
